"""Shows how jobs get classified, without waiting for new postings to appear.

  python classification_report.py --from-db
      Status counts and 5 examples per status from the live applications table.

  python classification_report.py --sample
      Pulls real postings, runs the real pipeline (Haiku calls included) and
      prints the same breakdown. Writes nothing and sends no email.

  python classification_report.py --sample --write-db
      Same, but also saves the jobs that pass the LLM gate into the
      applications table. Used to backfill jobs that were already emailed.
"""
import argparse
import random
import re
from concurrent.futures import ThreadPoolExecutor

import ashby
import db
import greenhouse
import lever
import rules
import simplify
from ats import resolve_ats
from enrich import enrich_job
from filters import is_relevant_job, classify_job, passes_llm_gate

STATUS_ORDER = ["eligible", "needs_review", "filtered_out", "found", "submitted", "failed"]


def print_examples(rows):
    by_status = {}
    for row in rows:
        by_status.setdefault(row["status"], []).append(row)

    print("\n=== Counts ===")
    for status in STATUS_ORDER:
        if status in by_status:
            print(f"{status:14} {len(by_status[status])}")

    print("\n=== Reasons ===")
    reasons = {}
    for row in rows:
        # Company names in the blocklist message would make every row unique.
        reason = re.sub(r"^.* is on the blocklist$", "Company is on the blocklist", row["status_reason"] or "")
        reasons[(row["status"], reason)] = reasons.get((row["status"], reason), 0) + 1
    for (status, reason), count in sorted(reasons.items(), key=lambda kv: (STATUS_ORDER.index(kv[0][0]), -kv[1])):
        print(f"{count:4}  {status:13} {reason}")

    for status in STATUS_ORDER:
        if status not in by_status:
            continue
        print(f"\n=== {status}: 5 examples ===")
        for row in by_status[status][:5]:
            print(f"- {row['company']} | {row['title']} | {row['ats']}")
            print(f"    why: {row['status_reason']}")


def report_from_db():
    conn = db.get_connection()
    if conn is None:
        raise SystemExit("Could not connect to the database")
    rows = []
    with conn.cursor() as cur:
        for status in STATUS_ORDER:
            cur.execute(
                """SELECT company, title, ats, status, status_reason FROM applications
                   WHERE status = %s ORDER BY found_at DESC""",
                (status,),
            )
            rows += [dict(zip(["company", "title", "ats", "status", "status_reason"], r))
                     for r in cur.fetchall()]
    print_examples(rows)


def collect_candidates(per_source, sources, all_companies):
    """Fetches real postings from each source and keeps a random keyword-passing slice."""
    pools = {source: [] for source in sources}

    companies = greenhouse.load_greenhouse_companies() if "greenhouse" in pools else []
    if not all_companies:
        companies = random.sample(companies, min(len(companies), 40))
    for company in companies:
        try:
            for raw in greenhouse.fetch_greenhouse_jobs(company["slug"]):
                pools["greenhouse"].append(greenhouse.normalize_job(raw, company["label"]))
        except Exception as e:
            print(f"skipping greenhouse/{company['label']}: {e}")

    for company in (lever.load_lever_companies() if "lever" in pools else []):
        try:
            for raw in lever.fetch_lever_jobs(company["slug"]):
                pools["lever"].append(lever.normalize_job(raw, company["label"]))
        except Exception as e:
            print(f"skipping lever/{company['label']}: {e}")

    for company in (ashby.load_ashby_companies() if "ashby" in pools else []):
        try:
            for raw in ashby.fetch_ashby_jobs(company["slug"]):
                if raw.get("isListed", True):
                    pools["ashby"].append(ashby.normalize_job(raw, company["label"]))
        except Exception as e:
            print(f"skipping ashby/{company['label']}: {e}")

    if "simplify" in pools:
        for raw in simplify.fetch_simplify_listings():
            if raw.get("active"):
                pools["simplify"].append(simplify.normalize_job(raw))

    picked = []
    for source, jobs in pools.items():
        relevant = [j for j in jobs if is_relevant_job(j)]
        print(f"{source}: {len(jobs)} postings, {len(relevant)} pass the keyword filter")
        random.shuffle(relevant)
        picked += [(source, j) for j in relevant[:per_source]]
    return picked


def classify_one(item):
    source, job = item
    if source == "simplify":
        enrich_job(job)
    return source, job, classify_job(job)


def report_sample(max_llm, write_db, sources, all_companies):
    candidates = collect_candidates(max_llm // len(sources), sources, all_companies)
    print(f"\nClassifying {len(candidates)} jobs with Haiku...")

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(classify_one, candidates))

    rows = []
    rejected = 0
    for source, job, classification in results:
        if not passes_llm_gate(classification):
            rejected += 1
            continue
        ats = resolve_ats(job["url"], source)
        decision = rules.evaluate(job, classification, ats)
        rows.append({"company": job["company"], "title": job["title"], "ats": ats,
                     "status": decision["status"], "status_reason": decision["status_reason"]})
        if write_db:
            db.save_job(job, source=source, classification=classification)

    print(f"Haiku said NO to {rejected}, kept {len(rows)}")
    print_examples(rows)
    if write_db:
        print("\nSaved the kept jobs to the applications table.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-db", action="store_true")
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--max-llm", type=int, default=90,
                        help="cap on Haiku calls, split evenly across the three sources")
    parser.add_argument("--sources", default="greenhouse,lever,ashby,simplify",
                        help="comma separated: greenhouse,lever,ashby,simplify")
    parser.add_argument("--all-companies", action="store_true",
                        help="use every Greenhouse company instead of a random 40")
    args = parser.parse_args()

    if args.from_db:
        report_from_db()
    elif args.sample:
        report_sample(args.max_llm, args.write_db, args.sources.split(","), args.all_companies)
    else:
        parser.print_help()
