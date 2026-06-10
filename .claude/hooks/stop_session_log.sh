#!/usr/bin/env bash
# Stop hook for LocusAI.
# Keeps the session log current: when Claude finishes a turn, this prompts it to
# create/refresh today's entry in session-log.md (what we did + future discussion
# points). Rate-limited to once per ~25 min of session via a per-session marker,
# so it never loops and isn't naggy. Fails open (allows stop) on any error.
MEMDIR="/Users/paulomartinez/.claude/projects/-Users-paulomartinez-LocusAI/memory"
/usr/bin/python3 - "$MEMDIR" <<'PY'
import json, sys, os, time
memdir = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
sid = str(data.get("session_id") or "unknown").replace("/", "_")
try:
    markdir = "/tmp/.locusai-claude-markers"
    os.makedirs(markdir, exist_ok=True)
    marker = os.path.join(markdir, sid)
    # Stay silent if we reminded within the last 25 minutes (1500s).
    if os.path.exists(marker) and (time.time() - os.path.getmtime(marker) < 1500):
        sys.exit(0)
    # Refresh the marker NOW so this can never loop even if Claude writes nothing.
    open(marker, "a").close()
    os.utime(marker, None)
except SystemExit:
    raise
except Exception:
    sys.exit(0)  # fail open: never trap the session
reason = (
    "Session-log checkpoint. Before finishing, create or update today's entry in "
    + os.path.join(memdir, "session-log.md")
    + " (keep the most-recent entry at the TOP, under a '## YYYY-MM-DD' heading). "
    "Capture two things concisely: (1) what we actually did this session, and "
    "(2) anything discussed for the future / open next steps. If nothing "
    "substantive has happened yet this session, just stop without writing. "
    "This reminder is rate-limited and won't fire again for ~25 minutes."
)
print(json.dumps({"decision": "block", "reason": reason}))
PY
