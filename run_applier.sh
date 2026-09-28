#!/bin/zsh
# Called by launchd every 2 hours. Uses the repo's own virtualenv.
cd "$(dirname "$0")"
source venv/bin/activate
python applier.py >> applier.log 2>&1
