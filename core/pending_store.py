# core/pending_store.py — durable, cross-worker store for short-lived tokens
#
# Booking confirmations and reschedule/cancel tokens used to live in per-process
# dicts. Under `gunicorn --workers 2` a token created while serving one request
# was invisible to the worker that served the follow-up confirm request, so
# roughly half of all confirmations failed with "booking expired". This store
# keeps the same data in SQLite, so every worker sees the same tokens and they
# survive a worker restart within their TTL.
#
# Values must be JSON-serialisable. `pop()` deletes-and-returns atomically
# (BEGIN IMMEDIATE), so a double-submitted confirm can only succeed once.
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from core.db import get_conn

logger = logging.getLogger(__name__)


def put(
    token: str,
    kind: str,
    data: Dict[str, Any],
    ttl_seconds: float,
    business_id: Optional[int] = None,
) -> None:
    """Store `data` under `token` for `ttl_seconds`. Overwrites any existing
    row with the same token. A negative ttl stores an already-expired row
    (useful in tests)."""
    now = time.time()
    payload = json.dumps(data, default=str)
    con = get_conn()
    try:
        con.execute(
            """INSERT OR REPLACE INTO pending_actions
                   (token, kind, business_id, data_json, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token, kind, business_id, payload, now, now + ttl_seconds),
        )
        con.commit()
    finally:
        con.close()


def _decode(row, kind: Optional[str], now: float) -> Optional[Dict[str, Any]]:
    """Validate kind + expiry and decode the JSON payload."""
    if row is None:
        return None
    if kind is not None and row["kind"] != kind:
        return None
    if now > row["expires_at"]:
        return None
    try:
        return json.loads(row["data_json"])
    except json.JSONDecodeError:
        logger.warning("Corrupt pending_actions payload for a %s token", row["kind"])
        return None


def get(token: str, kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the data for `token` without consuming it, or None if it is
    missing, expired, or of a different `kind`."""
    now = time.time()
    con = get_conn()
    try:
        row = con.execute(
            "SELECT kind, data_json, expires_at FROM pending_actions WHERE token = ?",
            (token,),
        ).fetchone()
    finally:
        con.close()
    return _decode(row, kind, now)


def pop(token: str, kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Atomically fetch-and-delete `token`. Returns its data, or None if the
    token is missing, expired, or of a different `kind`. The row is always
    deleted when found (single-use), so a replayed request can't reuse it."""
    now = time.time()
    con = get_conn()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT kind, data_json, expires_at FROM pending_actions WHERE token = ?",
            (token,),
        ).fetchone()
        if row is not None:
            con.execute("DELETE FROM pending_actions WHERE token = ?", (token,))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return _decode(row, kind, now)


def cleanup(now: Optional[float] = None) -> int:
    """Delete all expired rows. Returns the number removed. Safe to call
    often; used opportunistically and by the daily data-purge worker."""
    now = now if now is not None else time.time()
    con = get_conn()
    try:
        cur = con.execute("DELETE FROM pending_actions WHERE expires_at < ?", (now,))
        con.commit()
        return cur.rowcount
    finally:
        con.close()
