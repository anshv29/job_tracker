import csv
import html
import re
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from storage import init_db, has_seen, mark_seen
from emailer import send_email, EMAIL_ADDRESS
from filters import is_relevant_job, is_relevant_job_llm, get_job_tag, render_tag_badge

REGISTRY_PATH = "registry.csv"
RATE_LIMIT_SECONDS = 1.0


def fetch_greenhouse_jobs(company_slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    response = requests.get(url, params={"content": "true"}, timeout=15)
    response.raise_for_status()
    data = response.json()
    return data.get("jobs", [])


def strip_html(raw_html):
    unescaped = html.unescape(raw_html or "")
    return re.sub(r"<[^>]+>", " ", unescaped)


def to_eastern(iso_timestamp):
    dt = datetime.fromisoformat(iso_timestamp)
    eastern = dt.astimezone(ZoneInfo("America/New_York"))
    return eastern.strftime("%Y-%m-%d %I:%M %p %Z")


def normalize_job(raw_job, company_label):
    return {
        "id": f"greenhouse-{raw_job['id']}",
        "title": raw_job["title"],
        "company": company_label,
        "location": raw_job.get("location", {}).get("name", "Unknown"),
        "url": raw_job["absolute_url"],
        "description": strip_html(raw_job.get("content", "")),
        "posted": to_eastern(raw_job["updated_at"]) if raw_job.get("updated_at") else "Unknown",
    }


def run_greenhouse_check(company_slug, company_label):
    jobs = fetch_greenhouse_jobs(company_slug)
    conn = init_db()
    new_jobs = []

    for job in jobs:
        normalized = normalize_job(job, company_label)
        if not has_seen(conn, normalized["id"]):
            mark_seen(conn, normalized)
            if is_relevant_job(normalized) and is_relevant_job_llm(normalized):
                new_jobs.append(normalized)

    return new_jobs


def build_html_table(company_label, jobs):
    rows = ""
    for job in jobs:
        badge = render_tag_badge(get_job_tag(job))
        rows += f"""
        <tr>
            <td style="padding:12px; border-bottom:1px solid #e0e0e0;">
                <a href="{job['url']}" style="color:#1a73e8; text-decoration:none; font-weight:600;">{job['title']}</a><br>
                {badge}
            </td>
            <td style="padding:12px; border-bottom:1px solid #e0e0e0;">{job['location']}</td>
            <td style="padding:12px; border-bottom:1px solid #e0e0e0;">{job['posted']}</td>
        </tr>
        """

    html = f"""
    <html>
    <body style="font-family:Arial, sans-serif; max-width:700px; margin:0 auto;">
        <h2 style="color:#222;">{len(jobs)} new job(s) at {company_label}</h2>
        <table style="width:100%; border-collapse:collapse; font-size:14px;">
            <tr style="background-color:#f5f5f5; text-align:left;">
                <th style="padding:12px;">Title</th>
                <th style="padding:12px;">Location</th>
                <th style="padding:12px;">Posted</th>
            </tr>
            {rows}
        </table>
    </body>
    </html>
    """
    return html


def load_greenhouse_companies(registry_path=REGISTRY_PATH):
    companies = []
    with open(registry_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["platform"] == "greenhouse":
                companies.append({"slug": row["slug"], "label": row["company"]})
    return companies


def main():
    companies = load_greenhouse_companies()
    print(f"Checking {len(companies)} Greenhouse companies...")

    for i, company in enumerate(companies):
        label = company["label"]
        try:
            new_jobs = run_greenhouse_check(company["slug"], label)
            print(f"[{i + 1}/{len(companies)}] {label}: {len(new_jobs)} new relevant job(s)")

            if new_jobs:
                html_body = build_html_table(label, new_jobs)
                send_email(
                    to_address=EMAIL_ADDRESS,
                    subject=f"{len(new_jobs)} new job(s) at {label}",
                    body=html_body,
                    is_html=True,
                )
                print(f"Sent email for {label}")
        except Exception as e:
            print(f"[{i + 1}/{len(companies)}] {label}: ERROR - {e}")
            traceback.print_exc()

        time.sleep(RATE_LIMIT_SECONDS)


if __name__ == "__main__":
    main()
