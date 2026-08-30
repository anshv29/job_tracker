from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from storage import init_db, has_seen, mark_seen
from emailer import send_email, EMAIL_ADDRESS
from filters import is_relevant_job, is_relevant_job_llm, get_job_tag, render_tag_badge

LISTINGS_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"


def fetch_simplify_listings():
    response = requests.get(LISTINGS_URL, timeout=30)
    response.raise_for_status()
    return response.json()


def to_eastern(unix_timestamp):
    if not unix_timestamp:
        return "Unknown"
    dt = datetime.fromtimestamp(unix_timestamp, tz=ZoneInfo("UTC"))
    eastern = dt.astimezone(ZoneInfo("America/New_York"))
    return eastern.strftime("%Y-%m-%d %I:%M %p %Z")


def normalize_job(raw_job):
    # Most active listings don't repeat the recruiting term (e.g. "Summer 2027")
    # in the title itself, so it's folded into description here - otherwise
    # filters.py's YEAR_TERMS check would reject almost everything.
    terms = raw_job.get("terms") or []
    description = (
        f"{raw_job.get('category', '')}. "
        f"Terms: {', '.join(terms)}. "
        f"Sponsorship: {raw_job.get('sponsorship', '')}."
    )
    return {
        "id": f"simplify-{raw_job['id']}",
        "title": raw_job["title"],
        "company": (raw_job.get("company_name") or "Unknown").strip(),
        "location": ", ".join(raw_job.get("locations") or []) or "Unknown",
        "url": raw_job["url"],
        "description": description,
        "posted": to_eastern(raw_job.get("date_posted")),
    }


def run_simplify_check():
    listings = fetch_simplify_listings()
    conn = init_db()
    new_jobs = []

    for raw_job in listings:
        if not raw_job.get("active"):
            continue
        normalized = normalize_job(raw_job)
        if not has_seen(conn, normalized["id"]):
            mark_seen(conn, normalized)
            if is_relevant_job(normalized) and is_relevant_job_llm(normalized):
                new_jobs.append(normalized)

    return new_jobs


def build_html_table(jobs):
    rows = ""
    for job in jobs:
        badge = render_tag_badge(get_job_tag(job))
        rows += f"""
        <tr>
            <td style="padding:12px; border-bottom:1px solid #e0e0e0;">
                <a href="{job['url']}" style="color:#1a73e8; text-decoration:none; font-weight:600;">{job['title']}</a><br>
                {badge}
            </td>
            <td style="padding:12px; border-bottom:1px solid #e0e0e0;">{job['company']}</td>
            <td style="padding:12px; border-bottom:1px solid #e0e0e0;">{job['location']}</td>
            <td style="padding:12px; border-bottom:1px solid #e0e0e0;">{job['posted']}</td>
        </tr>
        """

    html = f"""
    <html>
    <body style="font-family:Arial, sans-serif; max-width:800px; margin:0 auto;">
        <h2 style="color:#222;">{len(jobs)} new job(s) from SimplifyJobs internship list</h2>
        <table style="width:100%; border-collapse:collapse; font-size:14px;">
            <tr style="background-color:#f5f5f5; text-align:left;">
                <th style="padding:12px;">Title</th>
                <th style="padding:12px;">Company</th>
                <th style="padding:12px;">Location</th>
                <th style="padding:12px;">Posted</th>
            </tr>
            {rows}
        </table>
    </body>
    </html>
    """
    return html


def main():
    print("Checking SimplifyJobs internship list...")
    new_jobs = run_simplify_check()
    print(f"SimplifyJobs: {len(new_jobs)} new relevant job(s)")

    if new_jobs:
        html_body = build_html_table(new_jobs)
        send_email(
            to_address=EMAIL_ADDRESS,
            subject=f"{len(new_jobs)} new job(s) from SimplifyJobs",
            body=html_body,
            is_html=True,
        )
        print("Sent email for SimplifyJobs")
    else:
        print("No new jobs from SimplifyJobs, no email sent")


if __name__ == "__main__":
    main()
