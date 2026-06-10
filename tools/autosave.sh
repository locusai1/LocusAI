#!/bin/bash
# Autosave script for LocusAI project
# Automatically commits changes if there are any, then pushes to origin so the
# remote never falls behind (runs every 15 min via com.locusai.autosave launchd agent).

PROJECT_DIR="/Users/paulomartinez/LocusAI"
cd "$PROJECT_DIR" || exit 1

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# 1. Commit any working-tree changes.
if [[ -n $(git status --porcelain) ]]; then
    git add -A
    git commit -m "Auto-save: $TIMESTAMP

Changes auto-committed by autosave script.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
    echo "[$TIMESTAMP] Auto-saved changes"
else
    echo "[$TIMESTAMP] No changes to save"
fi

# 2. Push to origin if the local branch is ahead (covers both the new commit
#    above and any backlog of unpushed commits). Fails quietly when offline.
if git rev-parse @{u} >/dev/null 2>&1; then
    if [[ -n $(git rev-list @{u}..HEAD 2>/dev/null) ]]; then
        if git push --quiet origin HEAD; then
            echo "[$TIMESTAMP] Pushed to origin"
        else
            echo "[$TIMESTAMP] Push failed (offline or rejected) — will retry next run"
        fi
    fi
else
    echo "[$TIMESTAMP] No upstream configured for $(git branch --show-current); skipping push"
fi
