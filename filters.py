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
    "ai engineer",
    "ai/ml",
    "applied scientist",
    "research engineer",
    "computer vision",
    "nlp",
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
3. DOMAIN: The actual work described must be genuinely relevant to at least one of: Software Engineering (SWE), Trading, Quantitative roles (Quant), Capital Markets, Finance (broadly), or Data (real data science, data engineering, or ML/AI work - see the technical-substance test in DOMAIN CATEGORY below). Judge by the substance of the work, not just whether the title contains a word like "Analytics", "Data", or "Insights" - a reporting or dashboards role for an HR/People/operations/business function does not qualify just because its title says "Analytics".

The two extra fields below are separate from the YES/NO answer, so a posting can be YES (relevant) and still be restricted.

4. DOMAIN CATEGORY: Which single category best matches the actual work? Answer exactly one of: SWE, Trading, Quant, Finance, Data, None. Capital markets, investment banking, corporate finance, private equity and asset/wealth management all count as Finance. Software engineering counts as SWE.
   Data means real data science, data engineering, analytics engineering, business intelligence, machine learning, or AI work - the day-to-day must involve technical substance: writing SQL or Python, building or maintaining data pipelines, statistical or ML modeling, or working directly with production data systems. Using Excel/Google Sheets and BI dashboards to report on a non-technical function does NOT count as Data, no matter what the title says.
   People Analytics, HR Analytics, Workforce Analytics, Talent Analytics, and any similar "Analytics"-titled role that is actually an HR/People-function reporting job (spreadsheets, dashboards, presenting insights to non-technical stakeholders, "SQL is a plus" as an optional nice-to-have rather than a core skill) are Finance or None, never Data - this is a common mislabeling to watch for specifically.
   General business, operations, economics, consulting, audit, or risk analyst roles are also Finance or None, even if they involve some reporting.
5. GRAD_RESTRICTION: The applicant is in their FIRST year of university, graduating May 2031, and would do this internship in Summer 2027 (after first year). Only a requirement the applicant clearly fails is a restriction.
   - "specific": the posting states a graduation date or class year earlier than 2031 (for example "Class of 2027", "graduating in 2028"), a required year of study that is not first year ("rising junior", "rising senior", "penultimate year", "final year", "third year"), or a degree that must be completed or obtained by a date on or before 2030 (for example "degree obtained by summer 2027").
   - "none": there is no such requirement. Wording like "currently enrolled", "pursuing a bachelor's degree", "returning to school after the internship", "open to all years", "freshman or sophomore", or a class year of 2031 or later does NOT exclude the applicant, so answer none.
   - "unclear": only when the posting hints at a requirement but you genuinely cannot tell whether it excludes the applicant.

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
# Cheap first check before trusting the LLM. It only fires on phrasing that
# clearly excludes a first-year student graduating May 2031, and it can only
# say "found one", never "there is none", so a hit always wins. Merely
# mentioning a grad date is fine ("class of 2031", "currently enrolled").

APPLICANT_GRAD_YEAR = 2031

# Phrases that exclude a first-year no matter what year they mention.
_ALWAYS_EXCLUDING = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(?:final|last|penultimate)[- ](?:year|semester|term)\b",
        r"\brising (?:senior|junior)s?\b",
        r"\b(?:third|3rd|fourth|4th)[- ]year\b",
        r"\b(?:senior|junior) year\b",
        # Plural "juniors"/"seniors" means students in those years ("Juniors working
        # towards a bachelor's"). Singular "senior engineer" is a job level, so not matched.
        r"\b(?:juniors|seniors)\b",
        r"\bgraduating seniors?\b",
        r"\b(?:recent|new) grad(?:uate)?s?\b",
        r"\b(?:fall|spring|winter|summer)(?: and (?:fall|spring|winter|summer))? graduates?\b",
    ]
]

# Phrases where a year decides it: "class of 2027", "graduating in May 2028",
# "degree obtained by summer 2027", "2027 graduates".
_YEAR_CONTEXTS = [
    re.compile(r"class of[^.;\n]{0,30}", re.IGNORECASE),
    re.compile(r"\bgraduat(?:e|es|ing|ion)\b[^.;\n]{0,40}", re.IGNORECASE),
    re.compile(r"\b20\d{2}\b[^.;\n]{0,25}\bgraduat\w*", re.IGNORECASE),
    re.compile(r"\b(?:obtained|obtain|completed|complete|earned|finished|conferred)\b[^.;\n]{0,30}\b(?:by|before|prior to)\b[^.;\n]{0,25}", re.IGNORECASE),
]
# "graduate students", "graduate degree" are about level of study, not a date.
_NOT_A_DATE = re.compile(r"\bgraduat\w*\s+(?:students?|school|degrees?|programs?|studies|level|courses|candidates?)\b", re.IGNORECASE)
# "graduating after 2027" is a lower bound, which a 2031 graduate satisfies.
_LOWER_BOUND = re.compile(r"\b(?:after|later|beyond|newer|at least|no earlier)\b", re.IGNORECASE)


def regex_flags_grad_restriction(title, description):
    text = f"{title or ''} {description or ''}"

    if any(p.search(text) for p in _ALWAYS_EXCLUDING):
        return True

    for pattern in _YEAR_CONTEXTS:
        for match in pattern.finditer(text):
            span = match.group(0)
            if _NOT_A_DATE.search(span) or _LOWER_BOUND.search(span):
                continue
            years = [int(y) for y in re.findall(r"\b(20\d{2})\b", span)]
            # Only excluding if every year named is before the applicant's grad
            # year: "class of 2029, 2030 or 2031" still includes them.
            if years and max(years) < APPLICANT_GRAD_YEAR:
                return True
    return False
