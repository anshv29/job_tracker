"""The application flow shared by Greenhouse, Lever and Ashby.

Each ATS module only says where the form lives, which button submits it and how
a success page looks. Everything else (finding fields, mapping them to
answers.yaml, filling, stopping on anything doubtful) happens here.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import field_mapping
import form_tools
from drafts import draft_answer

RESUME_PATH = Path("private/resume.pdf")
RESUME_UPLOAD_NAME = "Ansh_Vaishnav_Resume.pdf"

CONFIRM_TEXT = re.compile(
    r"thank you for (applying|your (application|interest))|thanks for applying|"
    r"application (has been |was |is )?(successfully )?(submitted|received)|"
    r"we('ve| have) received your application|successfully submitted", re.I)
CODE_TEXT = re.compile(r"security code|verification code|enter the code", re.I)
# Questions that need a written answer rather than a fact from answers.yaml.
ESSAY = re.compile(r"\bwhy\b|describe|tell us|explain|what (excites|interests|motivates|draws)|in your own words|"
                   r"cover letter|about yourself|passionate", re.I)
CONSENT = re.compile(r"privacy|terms|consent|acknowledge|i agree|data processing|i understand|i have read", re.I)


@dataclass
class Outcome:
    status: str                     # submitted, needs_review, failed, dry_ok
    reason: str = ""
    draft: str = None
    screenshot: str = None
    filled: list = field(default_factory=list)      # (question, value shown)
    blank_optional: list = field(default_factory=list)
    problems: list = field(default_factory=list)    # required questions we could not answer
    to_verify: list = field(default_factory=list)   # (sig, value) text fills worth double-checking stuck


def group_questions(fields):
    """Radio and checkbox options that share a name become one question."""
    questions, groups = [], {}
    for f in fields:
        if f["type"] in ("radio", "checkbox"):
            gkey = (f["type"], f["name"] or f["label"], f["label"])
            if gkey not in groups:
                groups[gkey] = {"kind": f["type"], "label": f["label"] or f["optionLabel"], "required": False,
                                "options": [], "fids": [], "name": f["name"], "placeholder": ""}
                questions.append(groups[gkey])
            g = groups[gkey]
            g["options"].append(f["optionLabel"] or f["value"])
            g["fids"].append(f["fid"])
            g["required"] = g["required"] or f["required"]
            continue
        if f["type"] == "file":
            kind = "file"
        elif f["type"] == "yesno":
            kind = "yesno"
        elif f["tag"] == "select":
            kind = "select"
        elif f["tag"] == "textarea":
            kind = "textarea"
        elif f["role"] == "combobox":
            kind = "combobox"
        else:
            kind = "text"
        questions.append({"kind": kind, "label": f["label"], "required": f["required"], "options": f.get("options", []),
                          "fids": [f["fid"]], "name": f["name"], "id": f["id"], "placeholder": f["placeholder"],
                          "type": f["type"], "value": f.get("value", ""),
                          "upload_trigger_fid": f.get("uploadTriggerFid")})
    return questions


def option_locator(ctx, combo):
    """The options of the dropdown this field controls, and only those.

    The page keeps other lists in the DOM too (a phone country list with 259
    entries), so a page-wide search would read the wrong one.
    """
    controls = combo.get_attribute("aria-controls")
    if controls:
        return ctx.locator(f'[id="{controls}"]').locator('[role="option"]')
    return ctx.locator('[role="option"]:visible')


def search_term(key, value):
    # Typing the whole value hides matches: "Bachelor of Mathematics" matches no
    # option, but "Bachelor" finds "Bachelor's Degree".
    if key == "degree":
        return value.split()[0]
    return value.split(",")[0][:30]


def fill_combobox(ctx, page, q, key, value):
    loc = form_tools.locator_for(ctx, q["fids"][0])
    loc.click(timeout=5000)
    page.wait_for_timeout(500)

    def read():
        return option_locator(ctx, loc).all_inner_texts()

    options = read()
    idx = field_mapping.pick_option(key, value, options) if options else None
    if idx is None:
        # Long lists (schools) only show matches once you type.
        loc.press_sequentially(search_term(key, value), delay=40)
        page.wait_for_timeout(1200)
        options = read()
        idx = field_mapping.pick_option(key, value, options) if options else None
    if idx is None:
        print(f"    no match for {value!r} among {options[:6]}")
        loc.press("Escape")
        return False
    option_locator(ctx, loc).nth(idx).click(timeout=5000)
    return True


def fill_native_select(ctx, q, key, value):
    idx = field_mapping.pick_option(key, value, q["options"])
    if idx is None:
        return False
    loc = form_tools.locator_for(ctx, q["fids"][0])
    return loc.evaluate(
        """(el, t) => { const o = [...el.options].find(o => o.textContent.replace(/\\s+/g, ' ').trim() === t);
                        if (!o) return false; el.value = o.value;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true})); return true; }""",
        q["options"][idx])


def fill_choice(ctx, q, key, value):
    """Radio group or checkbox group: tick the single best option."""
    idx = field_mapping.pick_option(key, value, q["options"])
    if idx is None:
        return False
    loc = form_tools.locator_for(ctx, q["fids"][idx])
    try:
        loc.check(force=True, timeout=4000)
    except Exception:
        loc.click(force=True, timeout=4000)
    return True


def fill_yesno(ctx, q, value):
    box = ctx.locator(f'[data-fid="{q["fids"][0]}"]')
    box.locator("button", has_text=re.compile(f"^{value}$", re.I)).first.click(timeout=4000)
    return True


def file_role(q, seen_resume):
    text = f"{q['label']} {q.get('name', '')} {q.get('id', '')}".lower()
    if re.search(r"resume|\bcv\b", text):
        return "resume"
    if "cover" in text:
        return "cover"
    return "other" if seen_resume else "resume?"


def upload_file(ctx, page, fid, trigger_fid, file_bytes, filename):
    """Attaches a file and confirms the page didn't reject it.

    Clicking the real trigger button (when one was found at scan time) and
    answering the native file-chooser dialog it opens matches what a person
    does, and avoids a Greenhouse bug where setting the hidden input's files
    directly skips setup the button's own click handler does first, leaving
    the upload to fail with a silent page-side JS error.
    """
    for attempt in range(2):
        try:
            if trigger_fid is not None:
                with page.expect_file_chooser(timeout=3000) as chooser_info:
                    form_tools.locator_for(ctx, trigger_fid).click()
                chooser_info.value.set_files(
                    files=[{"name": filename, "mimeType": "application/pdf", "buffer": file_bytes}])
            else:
                raise RuntimeError("no trigger button found, use the input directly")
        except Exception:
            form_tools.locator_for(ctx, fid).set_input_files(
                files=[{"name": filename, "mimeType": "application/pdf", "buffer": file_bytes}])
        # Some ATS (Lever confirmed) parse the resume after upload and briefly
        # overwrite fields like location with whatever they extracted, even
        # blanking them if they found nothing. Waiting this out here, before
        # any other field gets filled, avoids losing a value to that reset.
        page.wait_for_timeout(5000)
        if not visible_errors(ctx):
            return True
    return False


def verify_and_refill(ctx, out):
    """Re-checks text fields we filled are still holding their value.

    Confirmed on Lever: a resume upload can trigger the site's own resume-parse
    autofill, which overwrites a field like location shortly afterward - even
    blanking it if parsing found nothing there. upload_file() already waits
    this out before typing, but this is a second, independent check right
    before the screenshot, in case something else resets a field later.
    """
    if not out.to_verify:
        return
    current = {q["sig"]: q for q in scan_questions(ctx)}
    for sig, expected in out.to_verify:
        q = current.get(sig)
        if not q or not q["fids"]:
            continue
        loc = form_tools.locator_for(ctx, q["fids"][0])
        try:
            actual = loc.input_value(timeout=2000)
        except Exception:
            continue
        if actual != expected:
            try:
                loc.fill(expected, timeout=3000)
            except Exception as e:
                print(f"    could not re-fill '{q['label'][:50]}' after it reset: {str(e)[:90]}")


def scan_questions(ctx):
    """group_questions, plus a stable sig for each one.

    Field numbers are reassigned on every scan, so a question is identified by
    what it says instead. The counter keeps two identical labels apart.
    """
    questions = group_questions(form_tools.scan_fields(ctx))
    seen_count = {}
    for q in questions:
        base = (q["kind"], q["label"], tuple(q["options"]))
        seen_count[base] = seen_count.get(base, 0) + 1
        q["sig"] = base + (seen_count[base],)
    return questions


def fill_form(ctx, page, job, answers, resume_bytes, handled, out):
    """One pass over the form. Returns the number of controls it touched."""
    questions = scan_questions(ctx)
    touched = 0

    # Upload the resume first: some sites read it and prefill fields, and
    # anything we type afterwards then wins.
    has_labeled_resume = any(file_role(q, False) == "resume" for q in questions if q["kind"] == "file")
    for q in [q for q in questions if q["kind"] == "file"]:
        if q["sig"] in handled:
            continue
        handled.add(q["sig"])
        if q.get("value"):
            continue  # a file is already attached
        role = file_role(q, has_labeled_resume)
        if role in ("resume", "resume?"):
            if upload_file(ctx, page, q["fids"][0], q.get("upload_trigger_fid"), resume_bytes, RESUME_UPLOAD_NAME):
                out.filled.append(("Resume", RESUME_UPLOAD_NAME))
                has_labeled_resume = True
                touched += 1
            else:
                out.problems.append((q["label"] or "Resume", "the resume upload failed with a page error, needs a human to attach it", False))
        elif q["required"]:
            out.problems.append((q["label"] or "file upload", "a required file other than the resume is asked for", False))

    for q in questions:
        if q["kind"] == "file":
            continue
        label = q["label"] or "(unlabelled field)"
        if q["sig"] in handled:
            continue
        handled.add(q["sig"])

        # A lone checkbox is either "I have read the privacy notice" (check it) or
        # a yes/no eligibility question rendered as a single on/off box, in which
        # case checked means Yes and left unchecked means No - both answered
        # confidently, so "No" is not treated as skipped or left blank.
        if q["kind"] == "checkbox" and len(q["options"]) == 1:
            # Haiku is not trusted to pick the key for a binary checkbox: a wrong
            # guess here becomes a real submitted answer, and superficially
            # similar questions can mean opposite things (remote_ok answers
            # "are you okay working remotely", not "can you commit to 5 days
            # in-office", even though both mention "work" and "office").
            bool_key = field_mapping.resolve_key(q["label"], job.get("location", ""), answers, use_llm=False)
            bool_value = answers.get(bool_key, "") if bool_key else ""
            if bool_value in ("Yes", "No"):
                if bool_value == "Yes":
                    loc = form_tools.locator_for(ctx, q["fids"][0])
                    try:
                        loc.check(force=True, timeout=4000)
                    except Exception:
                        # Some sites style a visible toggle over a zero-size real
                        # input, which Playwright refuses to click even with
                        # force=true. A raw DOM click has no such restriction.
                        loc.evaluate("el => el.click()")
                out.filled.append((label[:60], bool_value))
                touched += 1
                continue

            text = f"{q['label']} {q['options'][0]}"
            if q["required"] and CONSENT.search(text):
                form_tools.locator_for(ctx, q["fids"][0]).check(force=True)
                out.filled.append((label[:60], "checked"))
                touched += 1
            elif q["required"]:
                out.problems.append((label, "a required checkbox that is not a plain consent", False))
            continue

        key = field_mapping.resolve_key(q["label"], job.get("location", ""), answers)
        if key is None and q["options"] and field_mapping.looks_like_source_question(q["options"]):
            key = "how_did_you_hear"
        value = answers.get(key, "") if key else ""

        if not key or not value:
            if not q["required"]:
                out.blank_optional.append(label[:70])
                continue
            why = f"no answer in answers.yaml for '{key}'" if key else "no matching answer in answers.yaml"
            out.problems.append((label, why, q["kind"] == "textarea" or bool(ESSAY.search(label))))
            continue

        try:
            ok = fill_one(ctx, page, q, key, value)
        except Exception as e:
            ok = False
            print(f"    could not fill '{label[:50]}': {str(e)[:90]}")
        if ok:
            out.filled.append((label[:60], value if key != "phone" else "(phone)"))
            touched += 1
            if q["kind"] in ("text", "textarea"):
                # Some ATS overwrite a text field shortly after a resume upload
                # (their own resume-parse autofill, even when it finds nothing
                # and just blanks the field) - worth confirming this stuck.
                out.to_verify.append((q["sig"], value))
        elif q["required"]:
            out.problems.append((label, f"could not pick an option for '{value}'", False))
        else:
            out.blank_optional.append(label[:70])
    return touched


def fill_one(ctx, page, q, key, value):
    kind = q["kind"]
    if kind in ("text", "textarea"):
        text = value
        if key == "phone" and "(" in (q.get("placeholder") or ""):
            text = value  # digits are accepted everywhere, the formatted copy only when asked for
        if q.get("type") == "number" and not re.fullmatch(r"\d+", text):
            return False
        form_tools.locator_for(ctx, q["fids"][0]).fill(text, timeout=5000)
        return True
    if kind == "select":
        return fill_native_select(ctx, q, key, value)
    if kind == "combobox":
        return fill_combobox(ctx, page, q, key, value)
    if kind in ("radio", "checkbox"):
        return fill_choice(ctx, q, key, value)
    if kind == "yesno":
        return value in ("Yes", "No") and fill_yesno(ctx, q, value)
    return False


def visible_errors(ctx):
    try:
        texts = ctx.locator('[role="alert"], [class*="error" i]:visible').all_inner_texts()
    except Exception:
        return []
    return [t.strip()[:120] for t in texts if t.strip()][:3]


def body_text(target):
    try:
        return target.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        return ""


def wait_for_result(page, ctx, spec, seconds=25):
    """Polls after clicking submit. Returns (kind, detail) with kind in confirmed, code, captcha, error, none."""
    for _ in range(seconds):
        page.wait_for_timeout(1000)
        text = body_text(page) + " " + (body_text(ctx) if ctx is not page else "")
        if CONFIRM_TEXT.search(text) or spec.confirmed_url(page.url):
            return "confirmed", ""
        if CODE_TEXT.search(text):
            return "code", "the site asks for an emailed security code"
        reason = form_tools.captcha_reason(page)
        if reason:
            return "captcha", reason
    errors = visible_errors(ctx)
    return ("error", "; ".join(errors)) if errors else ("none", "no confirmation appeared after submitting")


def wait_for_form(page, spec, seconds=30):
    """Heavy careers pages can take a while to draw the form, so poll for it."""
    for _ in range(seconds):
        ctx = spec.find_context(page)
        if ctx.locator("input[type=text], input[type=email], textarea").count() > 0:
            return ctx
        page.wait_for_timeout(1000)
    return None


def apply(page, row, spec, answers, resume_text, dry_run, before_submit=None):
    out = Outcome(status="needs_review")
    job = {"company": row["company"], "title": row["title"], "location": row.get("location") or ""}
    resume_bytes = RESUME_PATH.read_bytes()

    page.goto(spec.start_url(row), wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3500)

    reason = form_tools.captcha_reason(page)
    if reason:
        out.reason = f"Bot check before the form: {reason}. Stopped without trying to get past it."
        out.screenshot = form_tools.screenshot(page, row["job_key"], "botcheck")
        return out

    ctx = wait_for_form(page, spec)
    if ctx is None:
        out.status = "failed"
        out.reason = "No application form found, the posting may be closed"
        out.screenshot = form_tools.screenshot(page, row["job_key"], "noform")
        return out

    handled = set()
    for _ in range(3):  # extra passes pick up questions that only appear after earlier answers
        if fill_form(ctx, page, job, answers, resume_bytes, handled, out) == 0:
            break
        page.wait_for_timeout(600)

    verify_and_refill(ctx, out)

    reason = form_tools.captcha_reason(page)
    if reason:
        out.reason = f"Bot check appeared while filling: {reason}. Stopped without trying to get past it."
        out.screenshot = form_tools.screenshot(page, row["job_key"], "botcheck")
        return out

    if out.problems:
        drafts = []
        for label, why, is_essay in out.problems:
            if is_essay:
                text = draft_answer(label, job, answers, resume_text, body_text(page)[:1500])
                if text:
                    drafts.append(f"Q: {label}\nA: {text}")
        out.draft = "\n\n".join(drafts) or None
        shown = "; ".join(f"{label[:70]} ({why})" for label, why, _ in out.problems[:6])
        more = f" and {len(out.problems) - 6} more" if len(out.problems) > 6 else ""
        out.reason = f"Required questions I could not answer: {shown}{more}"
        out.screenshot = form_tools.screenshot(page, row["job_key"], "needs-review")
        return out

    # "Nothing required was left unanswered" is only meaningful if the real form
    # was found. Every application form takes an email and a resume, so if those
    # were not filled we are probably looking at the wrong part of the page.
    filled_labels = " ".join(label.lower() for label, _ in out.filled)
    if "resume" not in filled_labels or "email" not in filled_labels:
        out.status = "failed"
        out.reason = "Could not find the real application form (no email and resume fields were filled)"
        out.screenshot = form_tools.screenshot(page, row["job_key"], "wrong-form")
        return out

    out.screenshot = form_tools.screenshot(page, row["job_key"], "filled")
    if dry_run:
        out.status = "dry_ok"
        out.reason = "Filled every required field. Dry run, submit not clicked."
        return out

    button = spec.submit_button(ctx)
    if button.count() == 0:
        out.status = "failed"
        out.reason = "Could not find the submit button"
        return out

    if before_submit:
        before_submit()  # records "submit started" so a crash can never cause a second submission
    button.click(timeout=8000)
    kind, detail = wait_for_result(page, ctx, spec)
    out.screenshot = form_tools.screenshot(page, row["job_key"], f"after-{kind}")

    if kind == "confirmed":
        out.status, out.reason = "submitted", "Confirmation message detected"
    elif kind in ("code", "captcha"):
        out.status, out.reason = "needs_review", f"After submitting: {detail}. Finish this one by hand."
    else:
        out.status, out.reason = "failed", detail
    return out
