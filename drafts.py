"""Drafts an answer to a required essay question so you can edit it by hand.

A draft is only ever saved to the database for review. Nothing here submits it.
"""
from filters import ANTHROPIC_MODEL, _get_client

DRAFT_PROMPT = """You are helping a university student answer a required question on a job application. They will read and edit the draft before anyone sends it.

Rules:
- Write in first person, 80 to 130 words, plain and specific, no buzzwords.
- Use only facts that appear in the resume or the details below. Do not invent projects, numbers, employers or skills.
- If the question needs a fact you do not have (a salary, a date, a name), write [NEEDS YOUR INPUT: what is missing] in its place.

Company: {company}
Role: {title}
About the role: {description}

Student details: {details}

Resume:
{resume}

Question: {question}

Draft answer:"""


_broken = False


def draft_answer(question, job, answers, resume_text, description=""):
    """Returns draft text, or None if Haiku could not be reached."""
    global _broken
    if _broken:
        return None
    details = "; ".join(f"{k}: {answers[k]}" for k in
                        ("school", "degree", "major", "expected_grad", "available_terms", "city", "province") if answers.get(k))
    prompt = DRAFT_PROMPT.format(
        company=job["company"], title=job["title"], description=(description or "")[:1500],
        details=details, resume=resume_text[:4000], question=question,
    )
    try:
        response = _get_client().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=400, messages=[{"role": "user", "content": prompt}])
        return next((b.text for b in response.content if b.type == "text"), "").strip() or None
    except Exception as e:
        _broken = True
        print(f"Could not draft answers (skipping the rest of this run): {str(e)[:100]}")
        return None
