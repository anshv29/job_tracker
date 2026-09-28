from urllib.parse import urlparse


def detect_ats(url):
    """Guesses the applicant tracking system from the apply URL's domain.

    Domain matching is deterministic and free, unlike asking the LLM, and the
    domain is what decides which form the applier would actually face.
    """
    host = urlparse(url or "").netloc.lower()

    # Many companies show Greenhouse jobs on their own careers site and only
    # leave a gh_jid parameter behind, so the domain alone would say "other".
    if "greenhouse.io" in host or "gh_jid=" in (url or ""):
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "myworkdayjobs.com" in host:
        return "workday"
    if "successfactors" in host:
        return "successfactors"
    return "other"


def resolve_ats(url, source):
    """detect_ats, plus what we know from which connector found the job.

    Greenhouse and Lever are known from the connector even when the URL is a
    custom careers page that hides the ATS.
    """
    ats = detect_ats(url)
    if ats == "other" and source in ("greenhouse", "lever"):
        return source
    return ats


if __name__ == "__main__":
    samples = [
        "https://boards.greenhouse.io/janestreet/jobs/123",
        "https://job-boards.greenhouse.io/point72/jobs/456",
        "https://jobs.lever.co/wealthsimple/abc-def",
        "https://td.wd3.myworkdayjobs.com/en-US/TD_Bank_Careers/job/x",
        "https://career5.successfactors.com/career?company=abc",
        "https://www.example.com/careers/123",
        "https://www.coinbase.com/careers/positions/123?gh_jid=123",
    ]
    for url in samples:
        print(f"{detect_ats(url):15} {url}")
