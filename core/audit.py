# core/audit.py — immutable audit trail for sensitive actions.
#
# Records who did what, when, from where. Used for compliance (GDPR
# accountability, "who cancelled this appointment", security review) and to
# unlock regulated verticals (medical/legal) that demand an access trail.
#
# Design notes:
#   - Append-only. Nothing in the app updates or deletes rows except the
#     retention purge (which keeps audit far longer than conversation data).
#   - Writes never raise into the caller: an audit failure must not break the
#     action being audited.

import json
import logging
from typing import Any, Dict, List, Optional

from core.db import get_conn, transaction

logger = logging.getLogger(__name__)


def log_audit(
    action: str,
    *,
    business_id: Optional[int] = None,
    user_id: Optional[int] = None,
    user_email: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[Any] = None,
    ip: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Record an audited action. Best-effort: never raises into the caller.

    `action` is a short verb.noun string, e.g. "appointment.cancelled",
    "user.created", "auth.login", "data.exported", "transcript.viewed".
    """
    try:
        detail_json = json.dumps(detail, default=str) if detail else None
        with transaction() as con:
            con.execute(
                """INSERT INTO audit_log
                   (business_id, user_id, user_email, action, entity_type, entity_id, ip, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    business_id,
                    user_id,
                    user_email,
                    action,
                    entity_type,
                    str(entity_id) if entity_id is not None else None,
                    ip,
                    detail_json,
                ),
            )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Audit log write failed for action %s: %s", action, e)


def log_audit_from_request(action: str, **kwargs) -> None:
    """Convenience wrapper that pulls user + IP from the Flask request/session."""
    try:
        from flask import request, session

        user = session.get("user") or {}
        kwargs.setdefault("user_id", user.get("id"))
        kwargs.setdefault("user_email", user.get("email"))
        kwargs.setdefault("business_id", session.get("business_id"))
        # Honour proxy headers (Railway/edge) but fall back to remote_addr
        fwd = request.headers.get("X-Forwarded-For", "")
        kwargs.setdefault("ip", (fwd.split(",")[0].strip() if fwd else request.remote_addr))
    except Exception:
        pass
    log_audit(action, **kwargs)


def list_audit(
    business_id: Optional[int] = None,
    *,
    limit: int = 200,
    action_prefix: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return recent audit rows (most recent first), optionally scoped/filtered."""
    clauses = []
    params: List[Any] = []
    if business_id is not None:
        clauses.append("(business_id = ? OR business_id IS NULL)")
        params.append(business_id)
    if action_prefix:
        clauses.append("action LIKE ?")
        params.append(action_prefix + "%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(int(limit))
    with get_conn() as con:
        rows = con.execute(
            f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("detail"):
            try:
                d["detail"] = json.loads(d["detail"])
            except (ValueError, TypeError):
                pass
        out.append(d)
    return out


def purge_old_audit(keep_days: int = 730) -> int:
    """Delete audit rows older than `keep_days` (default 2 years — kept far longer
    than conversation data). Returns number of rows removed."""
    with transaction() as con:
        cur = con.execute(
            "DELETE FROM audit_log WHERE datetime(created_at) < datetime('now', ? || ' days')",
            (-abs(int(keep_days)),),
        )
        return cur.rowcount
