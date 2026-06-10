#!/usr/bin/env bash
# SessionStart hook for LocusAI.
# Surfaces the most recent session-log entries so a new session automatically
# knows what was done and discussed previously. Fails open (silent) if anything
# goes wrong — it must never block a session from starting.
LOG="/Users/paulomartinez/.claude/projects/-Users-paulomartinez-LocusAI/memory/session-log.md"
/usr/bin/python3 - "$LOG" <<'PY'
import json, sys, os
log = sys.argv[1]
try:
    if not os.path.exists(log):
        sys.exit(0)
    with open(log, encoding="utf-8", errors="replace") as f:
        text = f.read().strip()
    if not text:
        sys.exit(0)
    # Newest entries live at the top of the file; surface the first ~4000 chars.
    snippet = text[:4000]
    ctx = ("Recent LocusAI session log (most-recent entry first). "
           "Use this to recall what was previously done and what was discussed for the future:\n\n"
           + snippet)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": ctx,
    }}))
except Exception:
    sys.exit(0)
PY
