import re

from form_tools import find_form_context


def start_url(row):
    # The URL the alert email linked to. On a company's own careers site the
    # form is an iframe on that page, which find_context looks for.
    return row["url"]


def find_context(page):
    return find_form_context(page)


def submit_button(ctx):
    return ctx.get_by_role("button", name=re.compile(r"^\s*submit( application)?\s*$", re.I)).first


def confirmed_url(url):
    return "confirmation" in url or url.rstrip("/").endswith("/thanks")
