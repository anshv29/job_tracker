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
