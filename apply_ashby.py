import re


def start_url(row):
    base = row["url"].split("?")[0].rstrip("/")
    return base if base.endswith("/application") else base + "/application"


def find_context(page):
    return page


def submit_button(ctx):
    return ctx.get_by_role("button", name=re.compile(r"submit application", re.I)).first


def confirmed_url(url):
    return False
