"""Turns a form question into an answer taken from private/answers.yaml.

Order: rules for work authorization, exact label match, phrase match, fuzzy
match, then Haiku. Haiku may only name an existing key. It never writes a value,
so nothing can end up in a form that did not come from answers.yaml.
"""
import re
from difflib import SequenceMatcher
from pathlib import Path

import yaml

ANSWERS_PATH = Path("private/answers.yaml")

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def load_answers(path=ANSWERS_PATH):
    with open(path) as f:
        raw = yaml.safe_load(f)

    # YAML turns yes/no into True/False, but forms want the words.
    answers = {}
    for key, value in raw.items():
        if value is True:
            value = "Yes"
        elif value is False:
            value = "No"
        answers[key] = str(value).strip()

    # Derived keys only reformat values that are already in the file.
    answers["full_name"] = f"{answers['first_name']} {answers['last_name']}"
    answers["location"] = f"{answers['city']}, {answers['province']}, {answers['country']}"
    grad_year, grad_month = answers["expected_grad"].split("-")
    answers["grad_year"] = grad_year
    answers["grad_month_name"] = MONTHS[int(grad_month) - 1]
    answers["grad_date_text"] = f"{answers['grad_month_name']} {grad_year}"
    start_year, start_month = answers["start_date"].split("-")
    answers["start_year"] = start_year
    answers["start_month_name"] = MONTHS[int(start_month) - 1]
    return answers


def norm(text):
    text = re.sub(r"\(.*?\)", " ", (text or "").lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text).split())


# The whole label must equal one of these. Short generic words live here only,
# because "location" or "name" inside a longer question means something else.
EXACT = {
    "first_name": ["first name", "given name", "legal first name", "first"],
    "last_name": ["last name", "surname", "family name", "legal last name", "last"],
    "preferred_name": ["preferred name", "preferred first name", "nickname", "preferred first name"],
    "full_name": ["full name", "name", "your name", "legal name", "full legal name"],
    "email": ["email", "email address", "e mail", "your email"],
    "phone": ["phone", "phone number", "mobile", "mobile phone", "mobile number", "telephone", "cell", "cell phone"],
    "location": ["current location", "location", "your location", "city and country", "where are you located",
                 "current city and country", "location city"],
    "city": ["city", "current city"],
    "province": ["province", "state", "state province", "state or province", "province state"],
    "country": ["country", "country of residence", "country region"],
    "school": ["school", "university", "college", "institution", "school name", "university name",
               "name of school", "name of your school", "what is the name of your school", "school university"],
    "degree": ["degree", "degree type", "level of education", "highest degree", "degree level"],
    "major": ["major", "discipline", "field of study", "area of study", "major field of study"],
    "grad_year": ["end date year", "graduation year", "year of graduation", "expected graduation year", "grad year"],
    "grad_date_text": ["when do you graduate", "expected graduation", "expected graduation date",
                       "graduation date", "anticipated graduation date", "expected graduation month and year"],
    "start_year": ["start date year", "start year"],
    "grad_month_name": ["end date month", "graduation month", "expected graduation month"],
    "start_month_name": ["start date month", "start month"],
    "gpa": ["gpa", "grade point average", "cumulative gpa"],
    "citizenship": ["citizenship", "country of citizenship", "nationality"],
    "linkedin": ["linkedin", "linkedin profile", "linkedin url", "linkedin profile url", "linkedin link"],
    "github": ["github", "github url", "github profile", "github link"],
    "website": ["website", "portfolio", "personal website", "other website", "personal site", "portfolio url",
                "portfolio website", "website url", "portfolio link"],
    "available_terms": ["availability", "internship term", "which term are you applying for",
                        "term", "which internship term are you interested in", "which term are you available"],
    "how_did_you_hear": ["source", "referral source", "how did you hear about us", "how did you hear about this job",
                         "how did you hear about this position", "how did you hear about this role"],
    "gender": ["gender", "gender identity"],
    "race_ethnicity": ["race", "ethnicity", "race ethnicity", "racial ethnic background"],
    "veteran_status": ["veteran status", "veteran", "protected veteran status"],
    "disability_status": ["disability status", "disability"],
    "hispanic_latino": ["are you hispanic latino", "hispanic latino", "hispanic or latino"],
}

# The label only has to contain one of these phrases.
CONTAINS = {
    "linkedin": ["linkedin"],
    "github": ["github"],
    "how_did_you_hear": ["how did you hear", "how did you find out", "how did you learn about", "where did you hear"],
    "willing_to_relocate": ["willing to relocate", "willing to self relocate", "open to relocation",
                            "open to relocating", "willing to move", "able to relocate"],
    "remote_ok": ["work remotely", "open to remote", "remote work"],
    "previously_worked_here": ["previously worked", "worked here before", "former employee", "previously employed",
                               "have you ever worked for", "have you previously been employed"],
    "gender": ["gender identity", "your gender", "what gender"],
    "race_ethnicity": ["racial ethnic", "race ethnicity", "your race", "ethnicity"],
    "veteran_status": ["veteran"],
    "disability_status": ["disability"],
    "hispanic_latino": ["hispanic"],
    "full_name": ["full legal name", "your full name", "legal full name"],
    "degree": ["what degree are you", "degree are you currently pursuing", "degree are you pursuing"],
    "country": ["country are you applying from", "country you are applying from", "country do you live in",
                "country do you reside in", "country of residence"],
    "grad_date_text": ["when do you graduate", "expected graduation date", "anticipated graduation"],
    "available_terms": ["which term", "internship term", "co op term"],
}

KEY_HINTS = {
    "first_name": "given name", "last_name": "family name", "preferred_name": "preferred or nickname",
    "full_name": "full name", "email": "email address", "phone": "phone number",
    "location": "where the applicant lives", "city": "city", "province": "province or state",
    "country": "country of residence", "school": "university name", "degree": "degree type",
    "major": "field of study", "grad_year": "graduation year", "grad_date_text": "graduation month and year",
    "gpa": "grade point average", "citizenship": "citizenship", "linkedin": "LinkedIn URL", "github": "GitHub URL",
    "website": "personal website", "available_terms": "which internship term the applicant is available",
    "willing_to_relocate": "willing to relocate", "remote_ok": "open to remote work",
    "how_did_you_hear": "how the applicant heard about the job", "previously_worked_here": "worked at this company before",
    "gender": "gender", "race_ethnicity": "race or ethnicity", "veteran_status": "veteran status",
    "disability_status": "disability status",
}

_CANADA = re.compile(r"canad|toronto|vancouver|montreal|ottawa|waterloo|calgary|edmonton|mississauga|ontario|quebec|british columbia|alberta", re.I)
_CANADA_CODES = re.compile(r",\s*(ON|BC|QC|AB|MB|NS|SK|NB)\b")
_US = re.compile(r"united states|\busa\b|u\.s\.|new york|san francisco|boston|seattle|austin|chicago|washington|los angeles|denver|atlanta|miami|dallas|houston|palo alto|san jose|san diego", re.I)
_US_CODES = re.compile(r",\s*(?!ON\b|BC\b|QC\b|AB\b|MB\b|NS\b|SK\b|NB\b)[A-Z]{2}\b")
_US_SHORT = {"nyc", "sf", "la", "dc", "ny", "ca", "tx", "ma", "wa"}


def country_of(text):
    """'canada', 'us' or None when it is unclear or mentions both."""
    text = text or ""
    canada = bool(_CANADA.search(text) or _CANADA_CODES.search(text))
    us = bool(_US.search(text) or _US_CODES.search(text) or text.strip().lower() in _US_SHORT)
    if canada and not us:
        return "canada"
    if us and not canada:
        return "us"
    return None


def _label_country(label):
    text = label or ""
    canada = bool(re.search(r"canad", text, re.I))
    us = bool(re.search(r"united states|\bu\.s\.|\busa\b|\bthe us\b|in the us\b|\bus citizen|\bus work", text, re.I))
    if canada and not us:
        return "canada"
    if us and not canada:
        return "us"
    return None


def _authorization_key(label, job_location):
    """Work authorization and sponsorship depend on the country the job is in."""
    low = (label or "").lower()
    if "sponsor" in low:
        prefix = "needs_sponsorship_"
    elif ("authoriz" in low or "authoris" in low or "legally" in low or "eligible to work" in low
          or "right to work" in low or "work permit" in low) and "work" in low:
        prefix = "authorized_"
    else:
        return None
    country = _label_country(label) or country_of(job_location)
    return prefix + country if country else None


def _tokens_contain(label_tokens, phrase_tokens):
    n = len(phrase_tokens)
    return any(label_tokens[i:i + n] == phrase_tokens for i in range(len(label_tokens) - n + 1))


def resolve_key(label, job_location, answers, use_llm=True):
    """The answers.yaml key that answers this question, or None."""
    label_norm = norm(label)
    if not label_norm:
        return None

    key = _authorization_key(label, job_location)
    if key:
        return key if key in answers else None

    for k, phrases in EXACT.items():
        if k in answers and label_norm in phrases:
            return k

    tokens = label_norm.split()
    best = None
    for k, phrases in CONTAINS.items():
        if k not in answers:
            continue
        for phrase in phrases:
            if _tokens_contain(tokens, phrase.split()) and (best is None or len(phrase) > best[0]):
                best = (len(phrase), k)
    if best:
        return best[1]

    # Fuzzy: only on short labels, so long questions can't match by accident.
    if len(tokens) <= 5:
        scored = [(SequenceMatcher(None, label_norm, p).ratio(), k)
                  for k, phrases in EXACT.items() if k in answers for p in phrases]
        if scored:
            score, k = max(scored)
            if score >= 0.9:
                return k

    return _ask_haiku(label, answers) if use_llm else None


_llm_cache = {}
_llm_broken = False  # after one failure (no credit, network) stop asking for the rest of this run


def _ask_haiku(label, answers):
    """Haiku picks one existing key for a strangely worded label, or says NONE."""
    global _llm_broken
    if label in _llm_cache:
        return _llm_cache[label]
    if _llm_broken or len(label) > 160:
        return None  # long questions are essays, not a fact from answers.yaml

    keys = [k for k in KEY_HINTS if k in answers]
    listing = "\n".join(f"- {k}: {KEY_HINTS[k]}" for k in keys)
    prompt = (
        "A job application form has a field labelled:\n"
        f'"{label}"\n\n'
        "Which of these answer keys is the correct answer for that field? "
        "Reply with only the key, or NONE if no key clearly answers it.\n\n"
        f"{listing}\n"
    )
    result = None
    try:
        from filters import ANTHROPIC_MODEL, _get_client
        response = _get_client().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=20, messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in response.content if b.type == "text"), "").strip().strip("`\"' ")
        result = text if text in keys else None  # anything not on the list is thrown away
    except Exception as e:
        _llm_broken = True
        print(f"Haiku field mapping unavailable, using fuzzy matching only: {str(e)[:80]}")
    _llm_cache[label] = result
    return result


def pick_option(key, value, options):
    """Index of the option that best matches value, or None if none is convincing."""
    opts = [norm(o) for o in options]
    usable = [i for i, o in enumerate(opts)
              if o and not o.startswith("select") and o not in ("none", "please select", "choose")]
    v = norm(value)
    if not v or not usable:
        return None

    if v in ("yes", "no"):
        for i in usable:
            if opts[i].split()[0] == v:
                return i
        return None

    if key == "race_ethnicity":
        for wanted in ("south asian", "asian"):
            for i in usable:
                if wanted in opts[i]:
                    return i
        return None
    if key == "veteran_status":
        for i in usable:
            if "not a protected veteran" in opts[i] or "not a veteran" in opts[i] or opts[i].startswith("i am not"):
                return i
        return None
    if key == "how_did_you_hear":
        # "Company website" is how it is answered, but sites word it many ways.
        for i in usable:
            o = opts[i]
            if (("company" in o or "corporate" in o or "official" in o) and ("website" in o or "site" in o or "career" in o)) \
                    or "careers page" in o or "career page" in o or "career site" in o or "careers site" in o:
                return i
    if key == "degree":
        for level in ("bachelor", "undergraduate"):
            if level in v:
                for i in usable:
                    if level in opts[i]:
                        return i
        return None

    for i in usable:
        if opts[i] == v:
            return i
    matches = [i for i in usable if len(opts[i]) >= 3 and (v in opts[i].split() or opts[i] in v
                                                          or (len(v.split()) > 1 and v in opts[i]))]
    if matches:
        return min(matches, key=lambda i: len(opts[i]))
    best = max(usable, key=lambda i: SequenceMatcher(None, v, opts[i]).ratio())
    return best if SequenceMatcher(None, v, opts[best]).ratio() >= 0.8 else None


_SOURCE_WORDS = ("linkedin", "indeed", "glassdoor", "handshake", "referral", "company website", "twitter",
                 "facebook", "youtube", "career fair", "job board", "instagram")


def looks_like_source_question(options):
    """A question titled just "Select One" is 'how did you hear about us' if its options are sites."""
    joined = " ".join(norm(o) for o in options)
    return sum(word in joined for word in _SOURCE_WORDS) >= 3
