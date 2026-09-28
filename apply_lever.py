import re


def start_url(row):
    # The form lives at the posting URL plus /apply.
    base = row["url"].split("?")[0].rstrip("/")
    return base if base.endswith("/apply") else base + "/apply"


def find_context(page):
    return page


def submit_button(ctx):
    return ctx.get_by_role("button", name=re.compile(r"submit application", re.I)).first


def confirmed_url(url):
    return url.rstrip("/").endswith("/thanks")
