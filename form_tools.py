"""Browser helpers shared by every ATS module: find form fields, screenshot, bot checks."""
import re
from datetime import datetime
from pathlib import Path

SCREENSHOT_DIR = Path("private/screenshots")

# Runs inside the page. Every control gets a data-fid so Python can find it
# again, and each one is described by its question, type, options and required flag.
SCAN_JS = r"""
() => {
  const clean = (t) => (t || "").replace(/\s+/g, " ").trim();
  const textOf = (el) => (el ? clean(el.innerText || el.textContent) : "");
  // Labels like these say nothing about the question, the real one is nearby.
  const GENERIC = /^(type your response|select one|select ?\.\.\.|type here\.\.\.|attach|choose|cards\[)/i;

  const labelFor = (el) => {
    const parts = [];
    const ids = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
    for (const id of ids) parts.push(textOf(document.getElementById(id)));
    if (el.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) parts.push(textOf(lab));
    }
    const wrap = el.closest("label");
    if (wrap) parts.push(textOf(wrap));
    if (el.getAttribute("aria-label")) parts.push(clean(el.getAttribute("aria-label")));
    return parts.filter(Boolean)[0] || "";
  };

  const CONTAINER = "li.application-question, [data-field-path], [class*=fieldEntry], fieldset, [role=group], [class*=question], [class*=Question]";
  const HEADING = ".application-label, label[class*=heading], legend, [class*=heading], [class*=title], label";

  // The question a control belongs to, found from the box around it.
  const questionOf = (el) => {
    const box = el.closest(CONTAINER);
    if (!box) return { text: "", required: false };
    const head = box.querySelector(HEADING);
    if (!head || head.contains(el)) return { text: "", required: false };
    return { text: textOf(head), required: /required/i.test(head.className || "") };
  };

  const out = [];
  let n = 0;
  for (const el of document.querySelectorAll("input, textarea, select")) {
    const type = (el.getAttribute("type") || (el.tagName === "SELECT" ? "select" : el.tagName === "TEXTAREA" ? "textarea" : "text")).toLowerCase();
    if (["hidden", "submit", "button", "image", "reset"].includes(type)) continue;
    if (el.closest("[aria-hidden=true]") && type !== "file") continue;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const visible = style.display !== "none" && style.visibility !== "hidden" && (rect.width > 0 || rect.height > 0);
    if (!visible && !["file", "radio", "checkbox"].includes(type)) continue;

    el.setAttribute("data-fid", String(n));
    const own = labelFor(el);
    const q = questionOf(el);
    const isChoice = type === "radio" || type === "checkbox";
    let question;
    let fileLabel = "";
    if (type === "file") {
      // Upload buttons are just labelled "Attach"; the real name ("Cover Letter *")
      // is on a label in the nearest box around it.
      // Greenhouse wraps each upload in .file-upload, whose first line is the label.
      const box = el.closest(".file-upload");
      if (box) fileLabel = clean((box.innerText || "").split("\n")[0]);
      let node = el.parentElement;
      for (let i = 0; node && i < 5 && !fileLabel; i++, node = node.parentElement) {
        const lab = node.querySelector("label, legend");
        if (lab && !lab.contains(el) && textOf(lab) && textOf(lab).length < 120) fileLabel = textOf(lab);
      }
    }
    if (fileLabel) {
      question = fileLabel;
    } else if (isChoice) {
      const fs = el.closest("fieldset");
      question = (fs && fs.querySelector("legend") ? textOf(fs.querySelector("legend")) : "") || q.text || own;
    } else {
      question = own && !GENERIC.test(own) ? own : (q.text || own);
    }

    const info = {
      fid: n, tag: el.tagName.toLowerCase(), type, name: el.name || "", id: el.id || "",
      placeholder: el.getAttribute("placeholder") || "",
      role: el.getAttribute("role") || "",
      label: clean(question || el.getAttribute("placeholder") || el.name || ""),
      optionLabel: isChoice ? clean(own) : "",
      required: el.required || el.getAttribute("aria-required") === "true" || q.required
        || /\*\s*$/.test(question || "") || /\(required\)/i.test(question || ""),
      value: el.value || "",
      checked: !!el.checked,
    };
    if (type === "select") info.options = Array.from(el.options).map((o) => clean(o.textContent)).filter(Boolean);
    out.push(info);
    n++;
  }

  // Ashby answers Yes/No questions with two buttons, not radio inputs.
  for (const box of document.querySelectorAll("[data-field-path], [class*=fieldEntry]")) {
    if (box.querySelector("input[type=radio]")) continue;
    const buttons = Array.from(box.querySelectorAll("button")).filter((b) => /^(yes|no)$/i.test(clean(b.innerText)));
    if (buttons.length !== 2 || box.getAttribute("data-fid")) continue;
    box.setAttribute("data-fid", String(n));
    const head = box.querySelector(HEADING);
    out.push({
      fid: n, tag: "div", type: "yesno", name: "", id: "", placeholder: "", role: "",
      label: textOf(head), optionLabel: "", value: "", checked: false,
      required: /required/i.test((head && head.className) || "") || /\*\s*$/.test(textOf(head)),
      options: ["Yes", "No"],
    });
    n++;
  }
  return out;
}
"""

# A visible challenge the applier must never try to get past. An invisible
# reCAPTCHA badge is normal on these forms and does not stop anything.
CAPTCHA_JS = r"""
() => {
  const title = (document.title || "").toLowerCase();
  const bodyText = (document.body ? document.body.innerText : "").toLowerCase().slice(0, 4000);
  if (/just a moment|attention required|access denied|security check|verify you are human/.test(title)) return "bot check page: " + document.title;
  if (/verify (that )?you are (a )?human|are you a robot|complete the security check|checking your browser|press (and|&) hold/.test(bodyText)) return "bot check text on the page";
  for (const f of document.querySelectorAll("iframe")) {
    const src = (f.src || "").toLowerCase();
    if (!/recaptcha|hcaptcha|turnstile|captcha/.test(src)) continue;
    const r = f.getBoundingClientRect();
    const s = getComputedStyle(f);
    const shown = r.width > 200 && r.height > 100 && s.visibility !== "hidden" && s.display !== "none";
    if (shown) return "visible captcha challenge";
  }
  return "";
}
"""


def scan_fields(ctx):
    """ctx is a Playwright Page or Frame."""
    return ctx.evaluate(SCAN_JS)


def captcha_reason(page):
    """A short reason if a bot check is showing, else an empty string."""
    try:
        return page.evaluate(CAPTCHA_JS)
    except Exception:
        return ""


def locator_for(ctx, fid):
    return ctx.locator(f'[data-fid="{fid}"]').first


def find_form_context(page):
    """The Greenhouse iframe if one holds the form, else the main page.

    Companies embed the form in an iframe on their own site, and that page
    often has unrelated inputs of its own (search boxes), so the iframe has to
    be checked first.
    """
    fields = "input[type=text], input[type=email], textarea"
    for frame in page.frames:
        if frame != page.main_frame and "greenhouse.io" in frame.url and frame.locator(fields).count() > 0:
            return frame
    return page


def screenshot(page, job_key, tag):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", job_key)[:60]
    path = SCREENSHOT_DIR / f"{safe_key}-{tag}-{stamp}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)
