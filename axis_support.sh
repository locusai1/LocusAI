#!/usr/bin/env bash
set -euo pipefail
echo "==== SYSTEM ===="
uname -a || true
echo "Python:"; python -V || true
echo
echo "==== PROJECT ROOT ===="
pwd; ls -la
echo
echo "==== PY FILES ===="
find . -maxdepth 3 -name "*.py" | sort
echo
echo "==== CORE & ADAPTERS ===="
ls -la core || true
ls -la adapters || true
echo
echo "==== PIP PACKAGES (top 50) ===="
python - <<'PY'
try:
    import pkg_resources
    for i, d in enumerate(sorted([str(p) for p in pkg_resources.working_set])[:50],1):
        print(f"{i:02d}. {d}")
except Exception as e:
    print("pip list unavailable:", e)
PY
echo
echo "==== DB SCHEMA ===="
sqlite3 receptionist.db '.schema businesses'
sqlite3 receptionist.db '.schema messages'
sqlite3 receptionist.db 'SELECT COUNT(*) AS businesses FROM businesses;'
sqlite3 receptionist.db 'SELECT COUNT(*) AS messages FROM messages;'
echo
echo "==== SAMPLE BUSINESSES ===="
sqlite3 receptionist.db "SELECT id, '['||name||']' AS name, '['||slug||']' AS slug FROM businesses LIMIT 10;"
