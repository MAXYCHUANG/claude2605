#!/usr/bin/env bash
# cc_auto_git_push.sh
# 
# Automatically commit and push the latest reports to GitHub so Render can pull them.
# Place this in your local cron after the OC reports are generated (e.g. 09:10 TPE time).

set -e

CLAUDE_DIR="/home/yc5/workspace/filefold/claude2605"
cd "${CLAUDE_DIR}"

# Check if there are changes in reports/
if ! git status --porcelain reports/ | grep -q "^"; then
    echo "[$(date)] No new reports to push."
    exit 0
fi

echo "[$(date)] Found new OC reports. Committing and pushing..."

git add reports/
git commit -m "Auto-update OC reports: $(date +'%Y-%m-%d')"
git push origin main

echo "[$(date)] Successfully pushed OC reports to GitHub. Render should auto-deploy shortly."
