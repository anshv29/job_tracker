# Companies the auto-applier must never apply to. Matched as whole words,
# case-insensitive, against the company name, so "Meta Platforms" matches
# "Meta" but "Metamask" does not. Edit this list freely.
BLOCKLISTED_COMPANIES = [
    "Google",
    "Alphabet",
    "Meta",
    "Facebook",
    "Amazon",
    "Apple",
    "Microsoft",
    "Netflix",
    "LinkedIn",
]


# --- Applier safety settings -------------------------------------------------
import os

# At most this many applications are submitted per day (Toronto time).
APPLIER_DAILY_CAP = 25

# Random pause between applications so they don't all land back to back.
DELAY_SECONDS = (45, 150)
DRY_RUN_DELAY_SECONDS = (2, 5)


def dry_run():
    # Anything except an explicit DRY_RUN=false stays a dry run, so a typo in
    # .env can never turn on real submissions.
    return os.getenv("DRY_RUN", "true").strip().lower() != "false"


def headless():
    return os.getenv("HEADLESS", "false").strip().lower() == "true"
