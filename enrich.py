import re

import requests

import ashby
import greenhouse
import lever

_GREENHOUSE_URL = re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?P<slug>[^/?#]+)/jobs/(?P<id>\d+)")
_LEVER_URL = re.compile(r"jobs\.lever\.co/(?P<slug>[^/?#]+)/(?P<id>[0-9a-f-]{36})")
_ASHBY_URL = re.compile(r"jobs\.ashbyhq\.com/(?P<slug>[^/?#]+)/(?P<id>[0-9a-f-]{36})")


def enrich_job(job):
    """Swaps in the real posting text for jobs that only have a thin summary.

    The Simplify feed gives a one line summary, not the posting. Without the
    real text, "no grad date mentioned" would just mean "nothing was checked",
    so we fetch it from the ATS's public API when the URL is Greenhouse or
    Lever. On any failure the job is left alone and has_full_text stays False.
    """
    url = job.get("url") or ""
    try:
        match = _GREENHOUSE_URL.search(url)
        if match:
            api = f"https://boards-api.greenhouse.io/v1/boards/{match['slug']}/jobs/{match['id']}"
            data = requests.get(api, timeout=10)
            data.raise_for_status()
            text = greenhouse.strip_html(data.json().get("content", ""))
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
        else:
            return job
    except Exception as e:
        print(f"Could not fetch full posting for {url}: {e}")
        return job

    if text.strip():
        job["description"] = f"{job.get('description', '')} {text}"
        job["has_full_text"] = True
    return job
