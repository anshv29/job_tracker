"""Builds registry.csv: which companies host their jobs on Greenhouse, Lever or Ashby.

  python slugcheck.py --tracker "/path/to/Career_Tracker.xlsx"

Reads company names from the tracker's "Job Tracker" sheet (column B), tries a
few spellings of each name as a board slug on all three job board APIs, and
keeps only matches that are verified to belong to that company. Companies that
are already in registry.csv are re-checked too, so dead boards get dropped.
"""
import argparse
import csv
import re
import time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

import openpyxl
import requests

REGISTRY_PATH = "registry.csv"
PLATFORMS = ["greenhouse", "lever", "ashby"]

# Slugs that exist but belong to a different company with a similar name,
# checked by hand against the postings. Skipped so a rerun can't bring them back.
NOT_A_MATCH = {
    "Lincoln Financial Group", "Apex Investment", "Access Holdings", "Tailwind Capital",
    "Antares Capital", "Multiply Group", "Waterfall Asset Management",
    "Anchorage Capital Group", "Greenlight Capital", "Crescent Capital Group",
}

# Words that companies add to their legal or marketing name but that rarely
# appear in a board slug ("Point72 Asset Management" is just "point72").
SUFFIX_WORDS = {
    "capital", "partners", "group", "management", "investments", "investment",
    "asset", "holdings", "securities", "financial", "technologies", "technology",
    "inc", "llc", "lp", "co", "company", "corp", "corporation", "ltd", "and",
}


def alnum(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def slug_variants(name):
    name = re.sub(r"\(.*?\)", " ", name.replace("&amp;", "&"))
    words = re.findall(r"[a-z0-9]+", name.lower())
    core = [w for w in words if w not in SUFFIX_WORDS] or words

    variants = [
        "".join(words),        # janestreet
        "-".join(words),       # jane-street
        "".join(core),         # point72 (suffix words dropped)
        "-".join(core),
        core[0] if core else "",
    ]
    seen = []
    for v in variants:
        if len(v) >= 3 and v not in seen:
            seen.append(v)
    return seen


def get_json(url):
    try:
        response = requests.get(url, timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception:
        return None


def probe(platform, slug):
    """Returns (job_count, board_name_or_None, sample_text) or None if no such board."""
    if platform == "greenhouse":
        board = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
        if board is None:
            return None
        jobs = (get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs") or {}).get("jobs", [])
        return len(jobs), board.get("name"), " ".join(j.get("title", "") for j in jobs[:20])

    if platform == "lever":
        jobs = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if jobs is None:
            return None
        text = " ".join((j.get("text") or "") + " " + (j.get("descriptionPlain") or "")[:800] for j in jobs[:8])
        return len(jobs), None, text

    jobs = (get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}") or {}).get("jobs")
    if jobs is None:
        return None
    text = " ".join((j.get("title") or "") + " " + (j.get("descriptionPlain") or "")[:800] for j in jobs[:8])
    return len(jobs), None, text


def verified(company, slug, board_name, sample_text, job_count, trusted):
    """Guards against a slug that exists but belongs to a different company."""
    if trusted:
        return True  # already in the registry, only needs to still exist
    target = alnum(company)
    core = alnum(" ".join(w for w in re.findall(r"[a-z0-9]+", company.lower()) if w not in SUFFIX_WORDS))

    if board_name:  # Greenhouse tells us the board's real name
        found = alnum(board_name)
        return SequenceMatcher(None, found, target).ratio() >= 0.8 or (len(core) >= 4 and core in found)

    if job_count > 0:  # Lever and Ashby: the company should name itself in its postings
        return len(core) >= 4 and core in alnum(sample_text)

    # An empty board can't confirm anything, so only accept an exact name match.
    return slug == target and len(target) >= 6


def find_board(company, known_slug=None, known_platform=None):
    """Tries every slug spelling on every platform. Returns the best verified match."""
    trusted = known_slug is not None
    slugs = ([known_slug] if trusted else []) + slug_variants(company)
    matches = []

    for slug in dict.fromkeys(slugs):
        for platform in PLATFORMS:
            result = probe(platform, slug)
            if result is None:
                continue
            job_count, board_name, text = result
            is_trusted = trusted and slug == known_slug
            if verified(company, slug, board_name, text, job_count, is_trusted):
                matches.append({"company": company, "slug": slug, "platform": platform, "job_count": job_count})
        if matches:
            break  # first spelling that works wins, later ones are guesses

    if not matches:
        return None
    # A company can appear on two platforms after switching ATS; the live one has jobs.
    return max(matches, key=lambda m: (m["job_count"], m["platform"] == known_platform))


def load_tracker_companies(path):
    sheet = openpyxl.load_workbook(path, read_only=True)["Job Tracker"]
    names = []
    for row in sheet.iter_rows(min_row=4, values_only=True):
        if row[1] and str(row[1]).strip():
            names.append(str(row[1]).strip())
    return list(dict.fromkeys(names))


def load_registry():
    with open(REGISTRY_PATH, newline="") as f:
        return list(csv.DictReader(f))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracker", required=True)
    args = parser.parse_args()

    existing = load_registry()
    existing_by_name = {r["company"].lower(): r for r in existing}
    tracker = load_tracker_companies(args.tracker)
    print(f"{len(tracker)} tracker companies, {len(existing)} already in the registry")

    jobs = []
    for row in existing:
        jobs.append((row["company"], row["slug"], row["platform"]))
    for name in tracker:
        if name.lower() not in existing_by_name and name not in NOT_A_MATCH:
            jobs.append((name, None, None))

    def work(job):
        result = find_board(*job)
        time.sleep(0.2)
        return job, result

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(work, jobs))

    kept, added, moved, dropped, duplicates = [], [], [], [], []
    boards_seen = set()
    for (company, known_slug, known_platform), match in results:
        if match is None:
            if known_slug:
                dropped.append(f"{company} ({known_platform}/{known_slug})")
            continue
        # Two tracker names can point at one board ("William Blair" and
        # "William Blair Investment Management"), which would email every job twice.
        board = (match["platform"], match["slug"])
        if board in boards_seen:
            duplicates.append(f"{company} (same board as an earlier entry: {match['platform']}/{match['slug']})")
            continue
        boards_seen.add(board)
        kept.append(match)
        if known_slug is None:
            added.append(match)
        elif match["platform"] != known_platform:
            moved.append(f"{company}: {known_platform} -> {match['platform']}")

    with open(REGISTRY_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company", "slug", "platform", "job_count"])
        writer.writeheader()
        writer.writerows(kept)

    by_platform = {p: sum(1 for m in kept if m["platform"] == p) for p in PLATFORMS}
    print(f"\nRegistry now has {len(kept)} companies: {by_platform}")
    print(f"Added {len(added)} new: {sorted({m['platform'] for m in added})}")
    for m in added:
        print(f"  + {m['company']} -> {m['platform']}/{m['slug']} ({m['job_count']} jobs)")
    print(f"Platform changed for {len(moved)}:")
    for line in moved:
        print(f"  ~ {line}")
    print(f"Skipped {len(duplicates)} duplicate boards:")
    for line in duplicates:
        print(f"  = {line}")
    print(f"Dropped {len(dropped)} dead boards:")
    for line in dropped:
        print(f"  - {line}")
