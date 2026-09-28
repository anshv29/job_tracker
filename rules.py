import re

from config import BLOCKLISTED_COMPANIES
from filters import regex_flags_grad_restriction

AUTO_APPLY_ATS = {"greenhouse", "lever"}

_BLOCKLIST_PATTERNS = [
    re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
    for name in BLOCKLISTED_COMPANIES
]


def is_blocklisted(company):
    return any(p.search(company or "") for p in _BLOCKLIST_PATTERNS)


def combine_grad_restriction(regex_hit, llm_value):
    # The regex can only ever spot a restrictive phrase, it can't prove there
    # is none, so a regex hit always wins over whatever the LLM said.
    if regex_hit:
        return "specific"
    return llm_value


def evaluate(job, classification, ats):
    """Decides a job's status. Returns kwargs ready for db.insert_application.

    Checks run in a fixed order: hard rejections first, then "a human should
    look", and only jobs that clear everything become eligible.
    """
    reason = classification.get("reason")

    def result(status, status_reason, grad=None):
        return {"status": status, "status_reason": status_reason,
                "fit_reason": reason, "grad_restriction": grad}

    if classification.get("error"):
        return result("needs_review", "LLM classification failed, needs a manual look")

    grad = combine_grad_restriction(
        regex_flags_grad_restriction(job.get("title"), job.get("description")),
        classification.get("grad_restriction"),
    )
    # No real posting text means "no grad date found" proves nothing, so the
    # answer can never be better than unclear (a regex hit above still wins).
    no_text = not job.get("has_full_text", True)
    if no_text and grad != "specific":
        grad = "unclear"
    domain = classification.get("domain")

    if domain is None:
        return result("needs_review", "LLM did not return a usable domain", grad)
    if domain != "SWE":
        return result("filtered_out", f"Role domain is {domain.title()}, not SWE", grad)
    if is_blocklisted(job.get("company")):
        return result("filtered_out", f"{job.get('company')} is on the blocklist", grad)
    if grad == "specific":
        return result("filtered_out", "Posting states a grad date or year of study requirement", grad)
    if grad is None or grad == "unclear":
        why = ("Full posting text unavailable, could not check for a grad date or year of study"
               if no_text else "Could not tell whether a grad date or year of study is required")
        return result("needs_review", why, grad or "unclear")
    if ats not in AUTO_APPLY_ATS:
        return result("needs_review", f"ATS is '{ats}', the applier only handles Greenhouse and Lever", grad)

    return result("eligible", f"SWE role on {ats}, not blocklisted, no grad date or year requirement", grad)
