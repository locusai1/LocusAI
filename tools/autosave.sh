#!/bin/bash
# Autosave script for AxisAI project
# Automatically commits changes if there are any

PROJECT_DIR="/Users/paulomartinez/AI Business Utility Agent R&D"
cd "$PROJECT_DIR" || exit 1

# Check if there are any changes to commit
if [[ -n $(git status --porcelain) ]]; then
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

    # Stage all changes
    git add -A

    # Commit with timestamp
    git commit -m "Auto-save: $TIMESTAMP

Changes auto-committed by autosave script.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

    echo "[$TIMESTAMP] Auto-saved changes"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No changes to save"
fi
