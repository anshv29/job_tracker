import requests
import csv
import re
import time

def clean_slug(name):
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]", "", slug)
    return slug

def check_greenhouse(slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return len(data.get("jobs", []))
    return None

def check_lever(slug):
    url = f"https://api.lever.co/v0/postings/{slug}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return len(data)
    return None

companies = []
with open("company_list.csv", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        companies.append(row["company"])

print(f"Loaded {len(companies)} companies")

results = []
for i, name in enumerate(companies):
    slug = clean_slug(name)

    gh_count = check_greenhouse(slug)
    if gh_count is not None:
        results.append({"company": name, "slug": slug, "platform": "greenhouse", "job_count": gh_count})
        print(f"[{i+1}/{len(companies)}] {name} -> Greenhouse ({gh_count} jobs)")
    else:
        lever_count = check_lever(slug)
        if lever_count is not None:
            results.append({"company": name, "slug": slug, "platform": "lever", "job_count": lever_count})
            print(f"[{i+1}/{len(companies)}] {name} -> Lever ({lever_count} jobs)")
        else:
            print(f"[{i+1}/{len(companies)}] {name} -> not found")

    time.sleep(0.3)

with open("registry.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["company", "slug", "platform", "job_count"])
    writer.writeheader()
    writer.writerows(results)

print(f"\nDone. {len(results)} companies matched out of {len(companies)}.")