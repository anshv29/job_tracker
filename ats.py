from urllib.parse import urlparse


def detect_ats(url):
    """Guesses the applicant tracking system from the apply URL's domain.

    Domain matching is deterministic and free, unlike asking the LLM, and the
    domain is what decides which form the applier would actually face.
    """
    host = urlparse(url or "").netloc.lower()

    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "myworkdayjobs.com" in host:
        return "workday"
    if "successfactors" in host:
        return "successfactors"
    return "other"


if __name__ == "__main__":
    samples = [
        "https://boards.greenhouse.io/janestreet/jobs/123",
        "https://job-boards.greenhouse.io/point72/jobs/456",
        "https://jobs.lever.co/wealthsimple/abc-def",
        "https://td.wd3.myworkdayjobs.com/en-US/TD_Bank_Careers/job/x",
        "https://career5.successfactors.com/career?company=abc",
        "https://www.example.com/careers/123",
    ]
    for url in samples:
        print(f"{detect_ats(url):15} {url}")
