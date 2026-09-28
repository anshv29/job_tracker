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
    "spring week",
    "spring weeks",
    "spring programme",
    "spring program",
    "discovery day",
    "discovery days",
    "insight day",
    "insight days",
    "insight programme",
    "insight program",
    "diversity program",
    "diversity programme",
    "freshman",
    "freshman program",
    "freshman programme",
    "sophomore",
    "sophomore program",
    "sophomore programme",
    "early insight",
    "early talent",
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
_MAX_DESCRIPTION_CHARS = 6000  # grad date requirements usually sit in the qualifications
                                # section near the end, so 3000 chars cut them off

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

The two extra fields below are separate from the YES/NO answer, so a posting can be YES (relevant) and still be restricted.

4. DOMAIN CATEGORY: Which single category best matches the actual work? Answer exactly one of: SWE, Trading, Quant, Finance, Data, None. Capital markets, investment banking, corporate finance, private equity and asset/wealth management all count as Finance. Machine learning, analytics and data engineering count as Data. Only genuine software engineering counts as SWE.
5. GRAD_RESTRICTION: The applicant is a first-year university student, so ANY explicit requirement about graduating class, graduation date, seniority or year of study is a possible disqualifier.
   - "specific": the posting names a class year, graduation date, seniority level or year of study (for example "Class of 2026", "graduating in December 2027", "rising senior", "third year students", "final year"). A required degree that must be completed or obtained by a date (for example "degree obtained by summer 2027") also counts as specific.
   - "unclear": it hints at such a requirement but you cannot tell.
   - "none": no such requirement is stated anywhere.

Respond in EXACTLY this four-line format and nothing else:
ANSWER: YES or NO
REASON: <one short sentence>
DOMAIN: SWE or Trading or Quant or Finance or Data or None
GRAD_RESTRICTION: none or specific or unclear

Job title: {title}
Job description: {description}"""

_VALID_DOMAINS = {"SWE", "TRADING", "QUANT", "FINANCE", "DATA", "NONE"}
_VALID_GRAD = {"none", "specific", "unclear"}


def _parse_field(text, name):
    # Matches "NAME: value" at the start of a line, tolerating case and spacing.
    match = re.search(rf"^\s*{name}\s*:\s*(.+?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    return match.group(1) if match else None


def classify_job(job):
    """One Haiku call that answers relevance, domain and grad restriction.

    Returns a dict and never raises. error=True means the API call or the
    parsing failed, in which case the other fields must not be trusted.
    """
    result = {"answer": None, "reason": None, "domain": None,
              "grad_restriction": None, "error": True}

    prompt = CLASSIFICATION_PROMPT.format(
        title=job.get("title") or "",
        description=(job.get("description") or "")[:_MAX_DESCRIPTION_CHARS],
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
    except anthropic.RateLimitError as e:
        print(f"LLM classification rate-limited: {e}")
        return result
    except anthropic.APIConnectionError as e:
        print(f"LLM classification network error: {e}")
        return result
    except anthropic.APIStatusError as e:
        print(f"LLM classification API error ({e.status_code}): {e.message}")
        return result
    except Exception as e:
        print(f"LLM classification unexpected error: {e}")
        return result

    answer = _parse_field(text, "ANSWER")
    if answer is None:
        print(f"LLM classification: could not parse response: {text[:80]!r}")
        return result

    result["error"] = False
    result["answer"] = "YES" in answer.upper()
    result["reason"] = _parse_field(text, "REASON")

    # A missing or unrecognised domain/grad value stays None rather than being
    # guessed, and rules.evaluate() sends those jobs to needs_review.
    domain = (_parse_field(text, "DOMAIN") or "").strip().upper()
    if domain in _VALID_DOMAINS:
        result["domain"] = domain
    grad = (_parse_field(text, "GRAD_RESTRICTION") or "").strip().lower()
    if grad in _VALID_GRAD:
        result["grad_restriction"] = grad

    return result


def passes_llm_gate(classification):
    if classification["error"]:
        # Couldn't get an answer from the API for any reason - trust the
        # keyword filter's verdict (this is only called on jobs that already
        # passed it) rather than silently dropping a possibly-good job.
        return True
    return classification["answer"]


# --- Grad restriction regex pass ----------------------------------------------
#
# Cheap first check before trusting the LLM. It can only say "I saw a
# restrictive phrase", never "there is none", so a hit always wins.

RESTRICTIVE_GRAD_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in [
        r"\bclass of 20\d{2}\b",
        r"\bgraduat(?:e|es|ing|ion)\s+(?:in|by|before|after|between|on)\b",
        r"\bexpected graduation\b",
        r"\bgraduation date\b",
        r"\bfinal[- ]year\b",
        r"\bpenultimate[- ]year\b",
        r"\brising (?:senior|junior)s?\b",
        r"\byear of study\b",
        r"\b(?:1st|2nd|3rd|4th|first|second|third|fourth)[- ]year\b",
        r"\b(?:senior|junior) year\b",
        r"\bgraduating (?:senior|class)\b",
        r"\b(?:final|last) (?:semester|term)\b",
        r"\b(?:fall|spring|winter|summer)(?: and (?:fall|spring|winter|summer))? graduates?\b",
        r"\b(?:recent|new) grad(?:uate)?s?\b",
        # "degree obtained by summer 2027", "completed by May 2027", etc.
        r"\b(?:degree|diploma|program)\b[^.]{0,80}\b(?:by|before|prior to|no later than)\b[^.]{0,30}\b(?:20\d{2}|summer|fall|winter|spring)\b",
        r"\b(?:obtained|completed|earned|conferred)\s+(?:by|before|in)\b[^.]{0,30}\b(?:20\d{2}|summer|fall|winter|spring)\b",
        r"\bgraduat\w*\b[^.]{0,40}\b20\d{2}\b",
        r"\b20\d{2}\b[^.]{0,40}\bgraduat\w*\b",
    ]
]


def regex_flags_grad_restriction(title, description):
    text = f"{title or ''} {description or ''}"
    return any(p.search(text) for p in RESTRICTIVE_GRAD_PATTERNS)
