# Job Tracker

A Python job-posting scraper and alert system that watches Greenhouse, Lever, Ashby and Workday company boards plus the SimplifyJobs internship feed, filters for Summer 2027 SWE/Trading/Quant/Finance/Data internships, and emails new matches. A second half, described under Auto-apply below, tracks eligibility in a database and fills in application forms for you.

Runs on a schedule via GitHub Actions, so it's live 24/7 independent of any local machine.

## What it does

1. Pulls fresh job postings from Greenhouse (93 companies), Lever (16), Ashby (8), a hardcoded list of 13 Workday companies, and the SimplifyJobs GitHub feed (thousands of postings across many companies and ATS platforms).
2. Runs a keyword filter (`filters.py`) to knock out postings that don't mention Summer 2027, an internship/co-op-level role, and a relevant role term (SWE, Trading, Quant, Finance, Data), or that look senior/full-time from the title.
3. Sends survivors through a Claude Haiku classification pass that double-checks timing, level and domain, and drops anything the keyword filter let through by mistake.
4. Tags each posting as **Freshman/Sophomore Program** or **General Internship** for the email.
5. Emails the results from a dedicated bot Gmail account, separate from your personal inbox.

LinkedIn/Indeed were deliberately left out: no public API and real ToS risk for scraping either.

## Filtering pipeline

**Stage 1, keyword filter.** A posting must mention a Summer 2027 signal, an intern/co-op-level term (including early-program language like Spring Week, Discovery Day, Insight Day/Programme, Diversity Program, Freshman, Sophomore), and a relevant role term, and must not have a senior/full-time term in the title.

**Stage 2, LLM classification.** Claude Haiku 4.5 re-checks what passes stage 1 against the same Summer 2027 SWE/Trading/Quant/Capital Markets/Finance/Data target, and also returns the specific role domain and whether the posting states a grad-year or seniority requirement. Both are used by the Auto-apply eligibility rules below, so this one call serves both the email decision and the database status, with no extra API spend.

Full LLM classification on every posting was intentionally skipped early on for cost/complexity. It was added later as a second-stage filter once the source list scaled up.

## Scheduling

The scraper runs hourly via GitHub Actions (`.github/workflows/scheduler.yml`), not on a local machine. The dashboard (below) runs once a day on its own workflow.

Known gotcha already fixed: a request with no timeout (`workday.py`) could hang, and combined with `cancel-in-progress: false` this caused runs to queue for hours instead of firing hourly. Fixed with a request timeout, a 10-minute job-level kill switch, and shifting the cron trigger off the top-of-hour peak (everyone's workflow fires at :00, so GitHub's queue backs up right then).

A second gotcha: the workflow's last step commits `jobs.db` back to the repo, and a manual push from a laptop landing at the same moment used to make that push fail outright. It now syncs with origin and retries a few times before giving up.

## Cost controls

- LLM classification uses Claude Haiku 4.5, the cheap end of the lineup, and is only called on postings that already passed the free keyword filter.
- Anthropic auto-reload is off, so max exposure is capped at the prepaid balance on the API account.
- GitHub Actions schedule is hourly (not every 30 min) to stay comfortably within the free tier.
- See "Cost and safety controls" under Auto-apply for the backfill/reclassification spending guards.

## Setup

1. Clone the repo and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set these as GitHub Actions secrets (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY`: for classification
   - `EMAIL_ADDRESS` / `EMAIL_APP_PASSWORD`: the dedicated bot Gmail account (both the sender and the recipient of alert emails)
   - `DATABASE_URL`: Supabase Postgres, Session pooler connection string
3. Greenhouse/Lever/Ashby companies live in `registry.csv`, rebuilt by `slugcheck.py --tracker <xlsx>` (see Board list under Auto-apply). Workday companies are the `WORKDAY_COMPANIES` list in `workday.py`.
4. The cron schedule is set in `.github/workflows/scheduler.yml` and `.github/workflows/dashboard.yml`.

## Not doing (for now)

- Scraping LinkedIn/Indeed.
- Applying through Workday or SuccessFactors postings. The applier only handles Greenhouse, Lever and Ashby; those land in `needs_review` instead.
- Solving or working around CAPTCHAs. The applier always stops and asks for a human.

## Ideas / possible next steps

- More GitHub-hosted internship-list repos as additional sources beyond SimplifyJobs.
- A Workday or SuccessFactors applier, if enough eligible jobs end up needing one.
- Revisit whether keyword filtering alone could be dropped now that LLM classification is in place.

## Auto-apply

Every job that goes into an alert email is also saved to a Postgres table (Supabase) called `applications`. A second program, `applier.py`, runs on the Mac and fills in application forms for the jobs marked `eligible`.

### How a job gets a status

The classifier call that already decides "is this relevant" now also returns the role type and whether the posting has a grad date requirement, so there is no extra API call. `rules.py` then picks a status in this order:

1. Not software, data or ML: `filtered_out`
2. Company is in the blocklist (`config.py`): `filtered_out`
3. Grad date or year of study that rules out a first year graduating May 2031, like "class of 2027", "final year" or "degree obtained by summer 2027": `filtered_out`
4. Grad requirement unclear, or the full posting text could not be read: `needs_review`
5. Not on Greenhouse, Lever or Ashby: `needs_review`
6. Everything else: `eligible`

Saying "currently enrolled" or "pursuing a bachelor's" does not count as a restriction. Every row has a `status_reason` that says why.

### The applier

- Works on Greenhouse, Lever and Ashby forms using Playwright.
- Form fields are matched to keys in `private/answers.yaml`. Haiku is only allowed to pick one of those existing keys, never to write a value.
- Optional questions are left blank. A required question it cannot answer, or a required essay, stops the application and marks the row `needs_review`, with a drafted answer saved in `draft_answer` when it is an essay.
- A CAPTCHA or bot check stops that job. The applier never tries to get past one.
- A job is only marked `submitted` after a confirmation message shows up. A screenshot is saved either way.
- `DRY_RUN` is on unless `.env` says `DRY_RUN=false`. A dry run fills the form and takes a screenshot but never clicks submit and never writes to the database.
- At most `APPLIER_DAILY_CAP` applications per day (currently 10), with a random pause between them. `AUTO_APPLY_ENABLED=false` in `.env` turns the whole applier off without touching the scraper or alert emails.

Try it: `python applier.py --limit 3` for eligible jobs, or `python applier.py --test-url <posting url>` for any posting.

To run it every 2 hours on the Mac (9:05am to 9:05pm), once you are happy with the dry runs:

```bash
cp com.anshvaishnav.trcker.applier.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.anshvaishnav.trcker.applier.plist
```

### Private files

`private/` is git ignored. It holds `answers.yaml` (what goes into forms), `resume.pdf` and the screenshots. Mac only packages are in `requirements-mac.txt`, and browsers come from `playwright install chromium`.

### Dashboard

A GitHub Actions workflow (`.github/workflows/dashboard.yml`) emails a dashboard at 11pm Toronto time: applied today/this week/all time, a breakdown by ATS, today's submissions, the `needs_review` queue with draft answers, today's failures, and a 14 day chart of submissions. It also appends today's submitted jobs to `career_tracker.xlsx` if that file exists in the repo, otherwise it skips that step.

Try it: `python dashboard.py --force`.

### Cost and safety controls

- `classification_report.py` never re-sends a job to Haiku once it already has a real classification in the database. A job that only errored (an API outage, not a real YES/NO answer) is retried.
- Rerunning `classification_report.py` or `reclassify_failed.py` on more than 50 jobs prints the estimated cost and stops, unless you pass `--yes`.
- See "The applier" above for `APPLIER_DAILY_CAP` and `AUTO_APPLY_ENABLED`.

### Board list

`slugcheck.py --tracker <your tracker xlsx>` looks for each company on Greenhouse, Lever and Ashby, checks that the board really belongs to that company, and rewrites `registry.csv`. Boards that turned out to belong to a different company with a similar name are listed in `NOT_A_MATCH`.

`classification_report.py --sample` shows how live postings would be classified without sending email. `reclassify_failed.py` retries jobs stuck with an errored classification (for example from an Anthropic account running out of credit) by re-fetching each posting's text and trying again.
