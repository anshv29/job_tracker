import os
import re

import anthropic

YEAR_TERMS = [
    "2027",
    "summer 2027",
    "class of 2027",
]

INTERN_LEVEL_TERMS = [
    "intern",
    "internship",
    "co-op",
    "co op",
    "coop",
    "summer analyst",
    "summer associate",
]

ROLE_TERMS = [
    # Software engineering
    "software engineer",
    "software engineering",
    "software developer",
    "swe",
    "backend engineer",
    "back-end engineer",
    "frontend engineer",
    "front-end engineer",
    "full stack engineer",
    "full-stack engineer",
    "fullstack engineer",
    "mobile engineer",
    "ios engineer",
    "android engineer",
    "site reliability engineer",
    "sre",
    "devops engineer",
    "cloud engineer",
    "security engineer",
    "infrastructure engineer",
    "platform engineer",
    "systems engineer",
    "qa engineer",
    "test engineer",
    "application engineer",
    "web developer",
    # Trading
    "trading",
    "trader",
    "sales and trading",
    "flow trading",
    "algorithmic trading",
    "algo trading",
    # Quant
    "quant",
    "quantitative",
    "quantitative research",
    "quantitative trading",
    "quantitative developer",
    "quantitative analyst",
    "quantitative strategist",
    "quantitative researcher",
    # Capital markets / investment banking / buy-side
    "capital markets",
    "investment banking",
    "corporate finance",
    "leveraged finance",
    "equity capital markets",
    "debt capital markets",
    "ecm",
    "dcm",
    "m&a",
    "mergers and acquisitions",
    "private equity",
    "venture capital",
    "hedge fund",
    "asset management",
    "wealth management",
    "portfolio management",
    # Finance (general)
    "finance",
    "financial",
    "financial analyst",
    "treasury",
    "risk management",
    "credit risk",
    "market risk",
    "financial planning",
    "fp&a",
    "actuarial",
    "underwriting",
    "banking",
    # Data
    "data science",
    "data scientist",
    "data analyst",
    "data analytics",
    "data engineering",
    "data engineer",
    "machine learning",
    "ml engineer",
    "artificial intelligence",
    "business intelligence",
    "analytics",
    "research analyst",
]

EXCLUSION_TERMS = [
    "senior",
    "sr",
    "staff",
    "principal",
    "manager",
    "director",
    "vice president",
    "vp",
    "head of",
    "lead",
    "5+ years",
    "6+ years",
    "7+ years",
    "10+ years",
    "experienced",
    "full-time",
    "full time",
    "talent community",
    "talent network",
]


def _compile_terms(terms):
    # Word-boundary matching: a naive substring check would let "intern"
    # match inside "international", "coop" match inside "cooperation", "swe"
    # match inside random words, etc. \b anchors avoid those false positives.
    return [re.compile(r"\b" + re.escape(term) + r"\b") for term in terms]


_YEAR_PATTERNS = _compile_terms(YEAR_TERMS)
_INTERN_LEVEL_PATTERNS = _compile_terms(INTERN_LEVEL_TERMS)
_ROLE_PATTERNS = _compile_terms(ROLE_TERMS)
_EXCLUSION_PATTERNS = _compile_terms(EXCLUSION_TERMS)


def _matches_any(text, patterns):
    return any(pattern.search(text) for pattern in patterns)


def is_relevant(title, description=""):
    title_lower = (title or "").lower()
    text = f"{title_lower} {(description or '').lower()}"

    if not _matches_any(text, _YEAR_PATTERNS):
        return False

    if not _matches_any(text, _ROLE_PATTERNS):
        return False

    if not _matches_any(text, _INTERN_LEVEL_PATTERNS):
        return False

    # Exclusion terms are checked against the title only: descriptions often
    # contain boilerplate like "reports to the Director of Engineering" which
    # would otherwise wrongly reject a genuine internship posting.
    if _matches_any(title_lower, _EXCLUSION_PATTERNS):
        return False

    return True


def is_relevant_job(job):
    return is_relevant(job.get("title", ""), job.get("description", ""))


FRESHMAN_SOPHOMORE_TERMS = [
    "freshman",
    "freshmen",
    "sophomore",
    "sophomores",
    "rising freshman",
    "rising sophomore",
    "early insight",
    "early identification",
    "discovery day",
    "discovery program",
    "diversity program",
    "explore program",
    "spring insight",
    "winter insight",
    "underclassman",
    "underclassmen",
    "class of 2029",
    "class of 2030",
]

_FRESHMAN_SOPHOMORE_PATTERNS = _compile_terms(FRESHMAN_SOPHOMORE_TERMS)

TAG_FRESHMAN_SOPHOMORE = "Freshman/Sophomore Program"
TAG_GENERAL_INTERNSHIP = "General Internship"

# Visual styling per tag, kept alongside the tag logic so every connector's
# HTML email renders badges identically without duplicating color choices.
_TAG_STYLES = {
    TAG_FRESHMAN_SOPHOMORE: {"bg": "#fef3c7", "fg": "#92400e"},
    TAG_GENERAL_INTERNSHIP: {"bg": "#e5e7eb", "fg": "#374151"},
}


def get_job_tag(job):
    title_lower = (job.get("title") or "").lower()
    text = f"{title_lower} {(job.get('description') or '').lower()}"

    if _matches_any(text, _FRESHMAN_SOPHOMORE_PATTERNS):
        return TAG_FRESHMAN_SOPHOMORE

    return TAG_GENERAL_INTERNSHIP


def render_tag_badge(tag):
    style = _TAG_STYLES.get(tag, _TAG_STYLES[TAG_GENERAL_INTERNSHIP])
    return (
        '<span style="display:inline-block; margin-top:4px; padding:2px 8px; '
        "border-radius:10px; font-size:11px; font-weight:600; "
        f'background-color:{style["bg"]}; color:{style["fg"]};">{tag}</span>'
    )


# --- LLM second-stage filter -------------------------------------------------
#
# Runs only on jobs that already passed is_relevant_job(). It's a precision
# gate on top of the keyword filter's recall, not a replacement for it - the
# keyword filter still decides what's even worth spending an API call on.

ANTHROPIC_MODEL = "claude-haiku-4-5"
_MAX_DESCRIPTION_CHARS = 3000  # keeps token spend predictable; the classification
                                # signal is almost always in the opening paragraphs

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


CLASSIFICATION_PROMPT = """You are screening a job posting for a college student targeting Summer 2027 internships in Software Engineering, Trading, Quant, Capital Markets, Finance, or Data.

Classify this posting against ALL of the following criteria. Answer YES only if every criterion is satisfied.

1. TIMING: The role must be for Summer 2027, or be an internship/co-op whose timing would clearly land in Summer 2027 - including postings that target "Class of 2027", "Class of 2028", or "Class of 2029" students (these are the typical graduating classes recruited for Summer 2027 internships).
2. LEVEL: The role must be an internship, co-op, or student/early-talent program. It must NOT be a full-time role, NOT a senior/experienced-level role, and must NOT require prior full-time work experience.
3. DOMAIN: The actual work described must be genuinely relevant to at least one of: Software Engineering (SWE), Trading, Quantitative roles (Quant), Capital Markets, Finance (broadly), or Data (including Data Analyst, Data Science, Data Engineering, Business Analytics, and Business Intelligence internships/co-ops). Judge by the substance of the work, not just whether the title literally contains one of these words - for example, a "Business Analytics Co-op" or "Strategy & Insights Intern" whose description is genuinely data-analysis-focused should count as YES for Data, even without an obvious keyword match.

Respond in EXACTLY this two-line format and nothing else:
ANSWER: YES or NO
REASON: <one short sentence>

Job title: {title}
Job description: {description}"""


def classify_job_with_llm(title, description):
    """Returns True/False, or None if the API call couldn't be completed."""
    prompt = CLASSIFICATION_PROMPT.format(
        title=title or "",
        description=(description or "")[:_MAX_DESCRIPTION_CHARS],
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        return "YES" in first_line.upper()
    except anthropic.RateLimitError as e:
        print(f"LLM classification rate-limited: {e}")
    except anthropic.APIConnectionError as e:
        print(f"LLM classification network error: {e}")
    except anthropic.APIStatusError as e:
        print(f"LLM classification API error ({e.status_code}): {e.message}")
    except Exception as e:
        print(f"LLM classification unexpected error: {e}")

    return None


def is_relevant_job_llm(job):
    result = classify_job_with_llm(job.get("title", ""), job.get("description", ""))
    if result is None:
        # Couldn't get an answer from the API for any reason - trust the
        # keyword filter's verdict (this is only called on jobs that already
        # passed it) rather than silently dropping a possibly-good job.
        return True
    return result
