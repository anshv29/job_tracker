import re

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
