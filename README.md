# Job Tracker

A Python job-posting scraper and alert system that watches ~840 companies for new internship/co-op postings and emails a curated, personalized shortlist.

Runs on a schedule via GitHub Actions, so it's live 24/7 independent of any local machine.

## What it does

1. Pulls fresh job postings from every monitored company's ATS.
2. Runs a keyword filter to knock out obviously irrelevant postings.
3. Sends survivors through an LLM classification pass to catch relevant roles the keyword filter misses (and drop false positives it lets through).
4. Tags each posting as **Freshman/Sophomore Program** or **General Internship**.
5. Generates a short "why this fits you" line per posting, based on your resume.
6. Emails you the results from a dedicated bot account, separate from your personal inbox.

## Sources monitored (~840 companies)

- **Greenhouse** — 82 companies
- **Workday** — TD, RBC, CIBC
- **SAP SuccessFactors** — Scotiabank
- **SimplifyJobs internship list** (GitHub-hosted) — ~755 companies, for broad coverage beyond the curated list

LinkedIn/Indeed were deliberately left out — no public API and real ToS risk for scraping either.

## Filtering pipeline

**Stage 1 — keyword filter.** Matches on internship/co-op language, plus early-program signals that don't always say "intern" outright: Spring Week, Discovery Day, Insight Day/Programme, Diversity Program, Freshman, Sophomore.

**Stage 2 — LLM classification.** Claude Haiku 4.5 via the Anthropic API re-checks what passes stage 1, filtered specifically for SWE, trading, quant, capital markets, finance, and data roles, scoped to Summer 2027 (adjust the target term as needed). General finance/analyst roles and senior/full-time postings are excluded here.

**Stage 3 — resume-aware reasoning.** The classification step also reads your resume and writes a one-line "why this fits you" note per posting, included in the email.

Full LLM classification on every posting was intentionally skipped early on for cost/complexity — it was added later as a second-stage filter once the source list scaled up.

## Scheduling

Runs hourly via GitHub Actions (`.github/workflows/`), not on a local machine — this used to run on local `launchd` but was migrated so it doesn't depend on a laptop being on.

Known gotcha already fixed: a request with no timeout (`workday.py`) could hang, and combined with `cancel-in-progress: false` this caused runs to queue for hours instead of firing hourly. Fixed with a request timeout, a 10-minute job-level kill switch, and shifting the cron trigger off the top-of-hour peak (everyone's workflow fires at :00, so GitHub's queue backs up right then).

## Cost controls

- LLM classification uses Claude Haiku 4.5, the cheap end of the lineup.
- Anthropic auto-reload is off, so max exposure is capped at the prepaid balance on the API account.
- GitHub Actions schedule is hourly (not every 30 min) to stay comfortably within the free tier.

## Setup

> Fill in / adjust to match your actual repo layout — this is the general shape.

1. Clone the repo and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set the following as GitHub Actions secrets (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY` — for the classification + resume-matching step
   - `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` (or equivalent) — dedicated sender account, kept separate from your personal Gmail
   - `ALERT_RECIPIENT_EMAIL` — where alerts get sent
3. Company/source list lives in [wherever your config file is — e.g. `companies.json` / `sources.yaml`].
4. Resume used for the "why this fits you" reasoning lives at [path] — update it when your resume changes.
5. The workflow file under `.github/workflows/` controls the cron schedule; edit the cron expression there to change frequency.

## Not doing (for now)

- Full resume-matching product (users upload a resume, get personalized recommendations across all postings) — considered, deliberately shelved as a separate future project, not part of this scraper.
- Scraping LinkedIn/Indeed.

## Ideas / possible next steps

- More GitHub-hosted internship-list repos as additional sources beyond SimplifyJobs.
- Expand bank coverage beyond TD/RBC/Scotiabank/CIBC to all Canadian banks.
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
- At most 25 applications per day, with a random pause between them.

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

- `classification_report.py` never re-sends a job to Haiku once it already has a real classification in the database. Rerunning it on more than 50 jobs prints the estimated cost and stops, unless you pass `--yes`.
- `AUTO_APPLY_ENABLED=false` in `.env` turns the applier off entirely without touching the scraper or alert emails.
- The daily submission cap is `APPLIER_DAILY_CAP` in `config.py`.

### Board list

`slugcheck.py --tracker <your tracker xlsx>` looks for each company on Greenhouse, Lever and Ashby, checks that the board really belongs to that company, and rewrites `registry.csv`. Boards that turned out to belong to a different company with a similar name are listed in `NOT_A_MATCH`.

`classification_report.py --sample` shows how live postings would be classified without sending email.
