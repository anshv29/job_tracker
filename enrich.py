import csv
import re

import requests

import ashby
import greenhouse
import lever

# Matches boards.greenhouse.io, job-boards.greenhouse.io, and regional
# variants like job-boards.eu.greenhouse.io.
_GREENHOUSE_URL = re.compile(r"(?:boards|job-boards)(?:\.\w+)?\.greenhouse\.io/(?P<slug>[^/?#]+)/jobs/(?P<id>\d+)")
_LEVER_URL = re.compile(r"jobs\.lever\.co/(?P<slug>[^/?#]+)/(?P<id>[0-9a-f-]{36})")
_ASHBY_URL = re.compile(r"jobs\.ashbyhq\.com/(?P<slug>[^/?#]+)/(?P<id>[0-9a-f-]{36})")

# A company's own careers page (careers.acme.com, a "job board" SaaS product,
# Greenhouse's own /embed/job_app page) often still runs Greenhouse underneath
# and carries the job id as gh_jid or token, just with no board slug in the URL.
_GH_JOB_ID = re.compile(r"[?&](?:gh_jid|token)=(\d+)")
_GH_SLUG_IN_PAGE = re.compile(
    r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)|greenhouse\.io/embed/job_app\?for=([a-z0-9_-]+)", re.I)

_REGISTRY_SLUGS = None


def _greenhouse_slug_for_company(company):
    """registry.csv already maps every tracked company to its board slug."""
    global _REGISTRY_SLUGS
    if _REGISTRY_SLUGS is None:
        with open("registry.csv", newline="") as f:
            _REGISTRY_SLUGS = {row["company"]: row["slug"]
                               for row in csv.DictReader(f) if row["platform"] == "greenhouse"}
    return _REGISTRY_SLUGS.get(company)


def _fetch_greenhouse_by_slug(slug, job_id):
    api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
    data = requests.get(api, timeout=10)
    data.raise_for_status()
    return greenhouse.strip_html(data.json().get("content", ""))


def _fetch_greenhouse_unknown_slug(url, company):
    """A Greenhouse posting whose URL has no board slug, just a job id.

    Tries the slug already known for this company in registry.csv first (free),
    then looks for a Greenhouse API reference in the page's own HTML (the
    company's custom careers page usually calls the API client-side, and the
    slug it calls with is right there in the page source). If neither works,
    falls back to the visible text already fetched from the page - worse than
    the real posting, but still real content instead of nothing.
    """
    match = _GH_JOB_ID.search(url)
    if not match:
        return ""
    job_id = match.group(1)

    slug = _greenhouse_slug_for_company(company)
    if slug:
        try:
            return _fetch_greenhouse_by_slug(slug, job_id)
        except Exception as e:
            print(f"Registry slug '{slug}' didn't work for {url}: {e}")

    try:
        page = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        page.raise_for_status()
    except Exception as e:
        print(f"Could not fetch {url} to look for a board slug: {e}")
        return ""

    slug_match = _GH_SLUG_IN_PAGE.search(page.text)
    if slug_match:
        slug = slug_match.group(1) or slug_match.group(2)
        try:
            return _fetch_greenhouse_by_slug(slug, job_id)
        except Exception as e:
            print(f"Slug '{slug}' found on page but the API call failed for {url}: {e}")

    # No slug recoverable. Stripping the page's own HTML as a last resort was
    # tried and dropped: on the custom domains this actually hits, the page is
    # either a JS app with no real content server-side, or mostly nav/cookie
    # chrome - both look like real text without being it, which is worse than
    # just leaving this job's text unverified as before.
    return ""


def enrich_job(job):
    """Swaps in the real posting text for jobs that only have a thin summary.

    The Simplify feed gives a one line summary, not the posting. Without the
    real text, "no grad date mentioned" would just mean "nothing was checked",
    so we fetch it from the ATS's public API when the URL is Greenhouse, Lever
    or Ashby. On any failure the job is left alone and has_full_text stays False.
    """
    url = job.get("url") or ""
    try:
        match = _GREENHOUSE_URL.search(url)
        if match:
            text = _fetch_greenhouse_by_slug(match["slug"], match["id"])
        elif _LEVER_URL.search(url):
            match = _LEVER_URL.search(url)
            api = f"https://api.lever.co/v0/postings/{match['slug']}/{match['id']}"
            data = requests.get(api, timeout=10)
            data.raise_for_status()
            text = lever.normalize_job(data.json(), job["company"])["description"]
        elif _ASHBY_URL.search(url):
            # Ashby has no single-job endpoint, so read the board and pick the job.
            match = _ASHBY_URL.search(url)
            text = ""
            for raw in ashby.fetch_ashby_jobs(match["slug"]):
                if raw["id"] == match["id"]:
                    text = raw.get("descriptionPlain") or ""
                    break
        elif _GH_JOB_ID.search(url):
            # A gh_jid/token param with no other ATS match is still almost
            # certainly Greenhouse under a custom domain.
            text = _fetch_greenhouse_unknown_slug(url, job.get("company", ""))
        else:
            return job
    except Exception as e:
        print(f"Could not fetch full posting for {url}: {e}")
        return job

    if text.strip():
        job["description"] = f"{job.get('description', '')} {text}"
        job["has_full_text"] = True
    return job
