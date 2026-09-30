"""Retries jobs whose classification errored (not ones the LLM actually judged).

  python reclassify_failed.py            shows the count and estimated cost, does nothing
  python reclassify_failed.py --yes      re-fetches each posting's text and reclassifies it

Only rows with status_reason exactly 'LLM classification failed, needs a manual
look' are touched - that reason is set only when classify_job()'s error flag
was true (an API failure), never for a real YES/NO answer, so this can never
overwrite a genuine classification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor

import requests

import ashby
import db
import greenhouse
import lever
import rules
import workday
from ats import resolve_ats
from enrich import _ASHBY_URL, _GREENHOUSE_URL, _LEVER_URL
from filters import classify_job

FAILURE_REASON = "LLM classification failed, needs a manual look"
HAIKU_INPUT_PRICE_PER_M = 1.00
HAIKU_OUTPUT_PRICE_PER_M = 5.00
EST_INPUT_TOKENS_PER_CALL = 2200
EST_OUTPUT_TOKENS_PER_CALL = 80
EST_COST_PER_CALL = (EST_INPUT_TOKENS_PER_CALL / 1e6 * HAIKU_INPUT_PRICE_PER_M
                     + EST_OUTPUT_TOKENS_PER_CALL / 1e6 * HAIKU_OUTPUT_PRICE_PER_M)
CONFIRM_ABOVE = 50


def fetch_failed_rows(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT job_key, company, title, url, ats, location, source
                       FROM applications WHERE status_reason = %s ORDER BY found_at""",
                    (FAILURE_REASON,))
        cols = ["job_key", "company", "title", "url", "ats", "location", "source"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _workday_lookup(company_label):
    for c in workday.WORKDAY_COMPANIES:
        if c["label"] == company_label:
            return c
    return None


def refetch_description(row):
    """Best-effort full posting text for a stored row. May return "" (title-only)."""
    url = row["url"]

    match = _GREENHOUSE_URL.search(url)
    if match:
        try:
            data = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{match['slug']}/jobs/{match['id']}", timeout=10)
            data.raise_for_status()
            return greenhouse.strip_html(data.json().get("content", ""))
        except Exception as e:
            print(f"  could not refetch greenhouse text for {row['job_key']}: {e}")
            return ""

    match = _LEVER_URL.search(url)
    if match:
        try:
            data = requests.get(f"https://api.lever.co/v0/postings/{match['slug']}/{match['id']}", timeout=10)
            data.raise_for_status()
            return lever.normalize_job(data.json(), row["company"])["description"]
        except Exception as e:
            print(f"  could not refetch lever text for {row['job_key']}: {e}")
            return ""

    match = _ASHBY_URL.search(url)
    if match:
        try:
            for raw in ashby.fetch_ashby_jobs(match["slug"]):
                if raw["id"] == match["id"]:
                    return raw.get("descriptionPlain") or ""
        except Exception as e:
            print(f"  could not refetch ashby text for {row['job_key']}: {e}")
        return ""

    if row["ats"] == "workday":
        company = _workday_lookup(row["company"])
        if not company:
            return ""
        try:
            for raw in workday.fetch_workday_jobs(company["tenant"], company["host"], company["site"]):
                normalized = workday.normalize_job(raw, company["tenant"], company["host"], company["site"], row["company"])
                if normalized["id"] == row["job_key"]:
                    return normalized["description"]
        except Exception as e:
            print(f"  could not refetch workday text for {row['job_key']}: {e}")
        return ""

    # "other" ATS (a custom careers page Simplify found) - no generic fetch
    # exists, so this job is reclassified on its title alone.
    return ""


def reclassify_one(row):
    description = refetch_description(row)
    job = {"title": row["title"], "company": row["company"], "url": row["url"],
          "location": row["location"], "description": description,
          "has_full_text": bool(description)}
    classification = classify_job(job)
    ats = resolve_ats(row["url"], row["source"] or row["ats"])
    decision = rules.evaluate(job, classification, ats)
    return row, decision


def main(confirmed):
    conn = db.get_connection()
    if conn is None:
        raise SystemExit("Could not connect to the database")

    rows = fetch_failed_rows(conn)
    print(f"{len(rows)} row(s) with an errored classification.")
    if not rows:
        return

    if len(rows) > CONFIRM_ABOVE and not confirmed:
        est = len(rows) * EST_COST_PER_CALL
        print(f"Estimated cost ${est:.2f} (~${EST_COST_PER_CALL:.4f}/call). "
              f"Stopping without spending it - rerun with --yes to proceed.")
        return

    print(f"Reclassifying {len(rows)} jobs (estimated ${len(rows) * EST_COST_PER_CALL:.2f})...")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(reclassify_one, rows))

    counts = {}
    for row, decision in results:
        db.update_application(conn, row["job_key"], **decision)
        counts[decision["status"]] = counts.get(decision["status"], 0) + 1
        print(f"  {row['company']:25} {row['title'][:45]:45} -> {decision['status']}: {decision['status_reason']}")

    print(f"\nDone: {counts}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    main(args.yes)
