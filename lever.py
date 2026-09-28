import csv
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import db
from greenhouse import strip_html
from storage import init_db, has_seen, mark_seen
from emailer import send_email, EMAIL_ADDRESS
from filters import is_relevant_job, classify_job, passes_llm_gate, get_job_tag, render_tag_badge

REGISTRY_PATH = "registry.csv"
RATE_LIMIT_SECONDS = 1.0


def fetch_lever_jobs(company_slug):
    url = f"https://api.lever.co/v0/postings/{company_slug}"
    response = requests.get(url, params={"mode": "json"}, timeout=15)
    response.raise_for_status()
    return response.json()


def to_eastern(unix_millis):
    # Lever timestamps are in milliseconds, unlike the other connectors.
    if not unix_millis:
        return "Unknown"
    dt = datetime.fromtimestamp(unix_millis / 1000, tz=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M %p %Z")


def normalize_job(raw_job, company_label):
    categories = raw_job.get("categories") or {}

    # The job body is split across a plain-text intro and a list of sections
    # (responsibilities, requirements), so both go into the description that
    # the filters read.
    parts = [raw_job.get("descriptionPlain") or ""]
    for section in raw_job.get("lists") or []:
        parts.append(section.get("text") or "")
        parts.append(strip_html(section.get("content") or ""))
    parts.append(raw_job.get("additionalPlain") or "")

    return {
        "id": f"lever-{raw_job['id']}",
        "title": raw_job["text"],
        "company": company_label,
        "location": categories.get("location") or "Unknown",
        "url": raw_job["hostedUrl"],
        "description": " ".join(parts),
        "posted": to_eastern(raw_job.get("createdAt")),
    }


def run_lever_check(company_slug, company_label):
    jobs = fetch_lever_jobs(company_slug)
    conn = init_db()
    new_jobs = []

    for job in jobs:
        normalized = normalize_job(job, company_label)
        if not has_seen(conn, normalized["id"]):
            mark_seen(conn, normalized)
            if is_relevant_job(normalized):
                classification = classify_job(normalized)
                if passes_llm_gate(classification):
                    new_jobs.append(normalized)
                    db.save_job(normalized, source="lever", classification=classification)

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


def load_lever_companies(registry_path=REGISTRY_PATH):
    companies = []
    with open(registry_path, newline="") as f:
        for row in csv.DictReader(f):
            if row["platform"] == "lever":
                companies.append({"slug": row["slug"], "label": row["company"]})
    return companies


def main():
    companies = load_lever_companies()
    print(f"Checking {len(companies)} Lever companies...")

    for i, company in enumerate(companies):
        label = company["label"]
        try:
            new_jobs = run_lever_check(company["slug"], label)
            print(f"[{i + 1}/{len(companies)}] {label}: {len(new_jobs)} new relevant job(s)")

            if new_jobs:
                send_email(
                    to_address=EMAIL_ADDRESS,
                    subject=f"{len(new_jobs)} new job(s) at {label}",
                    body=build_html_table(label, new_jobs),
                    is_html=True,
                )
                print(f"Sent email for {label}")
        except Exception as e:
            print(f"[{i + 1}/{len(companies)}] {label}: ERROR - {e}")
            traceback.print_exc()

        time.sleep(RATE_LIMIT_SECONDS)


if __name__ == "__main__":
    main()
