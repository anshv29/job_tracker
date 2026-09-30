"""Applies to eligible jobs. Runs on the Mac, not in GitHub Actions.

  python applier.py                      apply to eligible jobs (dry run unless DRY_RUN=false)
  python applier.py --limit 3            only the first 3
  python applier.py --job-key KEY        one specific job (dry run only, any status)
  python applier.py --retry-failed       retry rows that failed, on purpose and by hand

DRY_RUN is on by default. A dry run fills the form and takes a screenshot but
never clicks submit and never writes to the database.
"""
import argparse
import random
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from playwright.sync_api import sync_playwright  # noqa: E402

import apply_ashby  # noqa: E402
import apply_greenhouse  # noqa: E402
import apply_lever  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
from apply_engine import apply  # noqa: E402
from field_mapping import load_answers  # noqa: E402
from resume_text import extract_resume_text  # noqa: E402

SPECS = {"greenhouse": apply_greenhouse, "lever": apply_lever, "ashby": apply_ashby}


def posting_id(row):
    """The ATS's own id for the posting, so one job found by two connectors is one job."""
    url = row["url"]
    match = re.search(r"gh_jid=(\d+)|greenhouse\.io/[^/]+/jobs/(\d+)", url)
    if match:
        return "greenhouse-" + (match.group(1) or match.group(2))
    if "greenhouse.io" in url:
        # boards.greenhouse.io/embed/job_app?token=<id> - no gh_jid, no /jobs/
        # path, but still the same job id scheme as the other two forms above.
        match = re.search(r"[?&]token=(\d+)", url)
        if match:
            return "greenhouse-" + match.group(1)
    match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", url)
    if match:
        return f"{row['ats']}-{match.group(0)}"
    return row["job_key"]


def submitted_today(conn):
    midnight = datetime.now(ZoneInfo("America/Toronto")).replace(hour=0, minute=0, second=0, microsecond=0)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM applications WHERE status = 'submitted' AND applied_at >= %s", (midnight,))
        return cur.fetchone()[0]


def already_applied(conn, row):
    wanted = posting_id(row)
    return any(posting_id(r) == wanted and r["job_key"] != row["job_key"]
               for r in db.fetch_by_status(conn, "submitted"))


def choose_rows(conn, args, dry_run, remaining):
    if args.job_key:
        rows = [db.get_by_job_key(conn, key) for key in args.job_key]
        rows = [r for r in rows if r]
        if not dry_run:
            wanted = "failed" if args.retry_failed else "eligible"
            rows = [r for r in rows if r["status"] == wanted]
        return rows
    rows = db.fetch_by_status(conn, "failed" if args.retry_failed else "eligible")
    rows = [r for r in rows if r["ats"] in SPECS]
    limit = min(remaining, args.limit) if args.limit else remaining
    return rows[:limit]


def save_result(conn, row, outcome):
    fields = {"status": outcome.status, "status_reason": outcome.reason, "screenshot_path": outcome.screenshot}
    if outcome.draft:
        fields["draft_answer"] = outcome.draft
    if outcome.status == "submitted":
        fields["applied_at"] = datetime.now(timezone.utc)
    db.update_application(conn, row["job_key"], **fields)


def print_outcome(row, outcome):
    print(f"  -> {outcome.status}: {outcome.reason}")
    if outcome.filled:
        print("     filled: " + "; ".join(f"{q} = {v}" for q, v in outcome.filled))
    if outcome.blank_optional:
        print(f"     left blank (optional): {len(outcome.blank_optional)}")
    if outcome.draft:
        print(f"     drafted answer saved ({len(outcome.draft)} chars)")
    if outcome.screenshot:
        print(f"     screenshot: {outcome.screenshot}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--job-key", action="append")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--test-url", action="append", help="dry run against any posting URL, even one not in the database")
    parser.add_argument("--max-submit", type=int, help="stop after this many real submissions, even if the daily cap allows more - for watching a supervised live run before trusting it unattended")
    args = parser.parse_args()

    if not config.auto_apply_enabled():
        print("Auto-apply is disabled (AUTO_APPLY_ENABLED=false in .env). "
              "The scraper and alert emails are unaffected. Exiting.")
        return

    dry_run = config.dry_run()
    print(f"{'DRY RUN (nothing is submitted or saved)' if dry_run else 'LIVE RUN'}")

    conn = db.get_connection()
    if conn is None:
        raise SystemExit("Database unreachable, nothing to do")

    # The cap is counted from the database, since each scheduled run is a new process.
    remaining = config.APPLIER_DAILY_CAP - submitted_today(conn)
    print(f"Daily cap {config.APPLIER_DAILY_CAP}, {max(remaining, 0)} left today")
    if args.max_submit is not None:
        remaining = min(remaining, args.max_submit)
        print(f"This run is capped at {args.max_submit} real submission(s)")
    if remaining <= 0 and not dry_run:
        return

    if args.test_url and not dry_run:
        raise SystemExit("--test-url only works as a dry run")
    if args.test_url:
        from ats import detect_ats
        rows = [{"job_key": f"adhoc-{i}", "company": "AdHoc", "title": "adhoc test", "url": u,
                 "ats": detect_ats(u), "location": "", "status": "eligible"} for i, u in enumerate(args.test_url)]
    else:
        rows = choose_rows(conn, args, dry_run, remaining)
    print(f"{len(rows)} job(s) to try")
    if not rows:
        return

    answers = load_answers()
    resume_text = extract_resume_text()
    delay = config.DRY_RUN_DELAY_SECONDS if dry_run else config.DELAY_SECONDS
    counts = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless())
        for i, row in enumerate(rows):
            print(f"\n[{i + 1}/{len(rows)}] {row['company']} | {row['title'][:60]} | {row['ats']}\n    {row['url'][:100]}")
            outcome = None
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            try:
                if not dry_run:
                    fresh = db.get_by_job_key(conn, row["job_key"])
                    wanted = "failed" if args.retry_failed else "eligible"
                    if fresh["status"] != wanted:
                        print(f"    skipped, status is now {fresh['status']}")
                        continue
                    if already_applied(conn, row):
                        print("    skipped, this posting was already submitted under another job key")
                        continue
                from apply_engine import Outcome
                spec = SPECS[row["ats"]]
                before = None if dry_run else (lambda r=row: db.update_application(
                    conn, r["job_key"], status="failed",
                    status_reason="Submit was clicked but the result is unknown, check by hand before retrying"))
                outcome = apply(page, row, spec, answers, resume_text, dry_run, before_submit=before)
            except Exception as e:
                outcome = Outcome(status="failed", reason=f"Unexpected error: {str(e)[:200]}")
            finally:
                context.close()

            print_outcome(row, outcome)
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            if not dry_run:
                save_result(conn, row, outcome)
                if outcome.status == "submitted":
                    remaining -= 1
                    if remaining <= 0:
                        print("Daily cap reached")
                        break
            if i < len(rows) - 1:
                time.sleep(random.uniform(*delay))
        browser.close()

    print(f"\nDone: {counts}")


if __name__ == "__main__":
    main()
