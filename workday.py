import requests
from storage import init_db, has_seen, mark_seen
from emailer import send_email, EMAIL_ADDRESS
from filters import is_relevant_job, is_relevant_job_llm, get_job_tag, render_tag_badge

def fetch_workday_jobs(tenant, host, site):
    url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    payload = {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": ""
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        return []
    data = response.json()
    return data.get("jobPostings", [])

def normalize_job(raw_job, tenant, host, site, company_label):
    base_url = f"https://{tenant}.{host}.myworkdayjobs.com/en-US/{site}"
    req_id = raw_job["bulletFields"][0] if raw_job.get("bulletFields") else raw_job["externalPath"]
    bullet_text = " ".join(raw_job.get("bulletFields", []))
    return {
        "id": req_id,
        "title": raw_job["title"],
        "company": company_label,
        "location": raw_job.get("locationsText", "Unknown"),
        "url": base_url + raw_job["externalPath"],
        "posted": raw_job.get("postedOn", "Unknown"),
        "description": bullet_text,
    }

def run_workday_check(tenant, host, site, company_label):
    jobs = fetch_workday_jobs(tenant, host, site)
    conn = init_db()
    new_jobs = []

    for job in jobs:
        normalized = normalize_job(job, tenant, host, site, company_label)
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

def main():
    banks = [
        {"tenant": "td", "host": "wd3", "site": "TD_Bank_Careers", "label": "TD"},
        {"tenant": "rbc", "host": "wd3", "site": "RBCEARLYTALENT1", "label": "RBC (Early Talent)"},
        {"tenant": "cibc", "host": "wd3", "site": "campus", "label": "CIBC (Campus)"},
    ]

    for bank in banks:
        new_jobs = run_workday_check(bank["tenant"], bank["host"], bank["site"], bank["label"])
        print(f"{bank['label']}: {len(new_jobs)} new relevant jobs")

        if new_jobs:
            html_body = build_html_table(bank["label"], new_jobs)
            send_email(
                to_address=EMAIL_ADDRESS,
                subject=f"{len(new_jobs)} new job(s) at {bank['label']}",
                body=html_body,
                is_html=True
            )
            print(f"Sent email for {bank['label']}")
        else:
            print(f"No new jobs at {bank['label']}, no email sent")

if __name__ == "__main__":
    main()