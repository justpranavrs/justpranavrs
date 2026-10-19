#!/usr/bin/env bash
set -euo pipefail

# Configure Bot
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Switch to orphan "activity" branch and push svg.
if [ -f "activity.svg" ]; then
  git checkout --orphan activity
  git reset
  git add activity.svg
  TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")
  git commit -m "chore: update activity ($TIMESTAMP)"
  git push origin activity --force
fi
