# core/account.py — GDPR data rights: portability (export) + erasure (delete).
#
# The Privacy Policy promises data export and a right to erasure; these give
# owners a self-serve way to exercise both. Erasure deletes a business's data
# only when the requesting user is its sole member — a shared business is left
# intact and only the user's own membership + login are removed.
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from werkzeug.security import check_password_hash

from core.db import get_conn, transaction

logger = logging.getLogger(__name__)


def _rows(con, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def _user_business_ids(con, user_id: int) -> List[int]:
    return [
        r["business_id"]
        for r in con.execute(
            "SELECT business_id FROM business_users WHERE user_id = ?", (user_id,)
        ).fetchall()
    ]


def export_account_data(user_id: int) -> Dict[str, Any]:
    """Return a JSON-serialisable snapshot of the user's account and all data
    for the businesses they belong to. Never includes password hashes."""
    con = get_conn()
    try:
        urow = con.execute(
            "SELECT id, email, name, role, email_verified, trial_ends_at, "
            "signup_source, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not urow:
            return {}
        user = dict(urow)

        businesses = []
        for bid in _user_business_ids(con, user_id):
            brow = con.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
            if not brow:
                continue
            biz = dict(brow)
            biz.pop("tenant_key", None)  # secret — not part of a data export
            biz["services"] = _rows(
                con, "SELECT * FROM services WHERE business_id = ?", (bid,)
            )
            biz["customers"] = _rows(
                con, "SELECT * FROM customers WHERE business_id = ?", (bid,)
            )
            biz["appointments"] = _rows(
                con, "SELECT * FROM appointments WHERE business_id = ?", (bid,)
            )
            biz["knowledge_base"] = _rows(
                con,
                "SELECT id, question, answer, tags, active, created_at "
                "FROM kb_entries WHERE business_id = ?",
                (bid,),
            )
            biz["conversations"] = _rows(
                con,
                "SELECT id, channel, phone, escalated, created_at "
                "FROM sessions WHERE business_id = ?",
                (bid,),
            )
            biz["voice_calls"] = _rows(
                con,
                "SELECT id, direction, from_number, to_number, call_status, "
                "started_at, duration_seconds, call_summary, sentiment "
                "FROM voice_calls WHERE business_id = ?",
                (bid,),
            )
            businesses.append(biz)

        return {
            "export_type": "locusai_account_export",
            "account": user,
            "businesses": businesses,
        }
    finally:
        con.close()


def export_account_json(user_id: int) -> str:
    return json.dumps(export_account_data(user_id), indent=2, default=str)


def delete_account(user_id: int, password: str) -> Tuple[bool, str]:
    """Erase the user's account after verifying their password.

    For each business the user belongs to: if they are the *sole* member the
    whole business and its data are deleted; otherwise only the user's
    membership is removed (a shared business is preserved). Finally the user
    row is deleted (cascading their login tokens, sessions, push subs).
    Returns (ok, message).
    """
    con = get_conn()
    try:
        row = con.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        con.close()
    if not row:
        return False, "Account not found."
    if not password or not check_password_hash(row["password_hash"], password):
        return False, "Password is incorrect."

    with transaction() as con:
        con.execute("PRAGMA foreign_keys = ON;")
        for bid in _user_business_ids(con, user_id):
            members = con.execute(
                "SELECT COUNT(*) c FROM business_users WHERE business_id = ?", (bid,)
            ).fetchone()["c"]
            if members <= 1:
                # Sole owner — erase the business. FK ON DELETE CASCADE clears the
                # scoped children (sessions/messages, appointments/reminders,
                # customers, kb + embeddings, voice_calls, settings, webhooks…).
                # A couple of tables have a business_id without a cascade FK, so
                # purge those explicitly for a complete erasure.
                con.execute("DELETE FROM digest_log WHERE business_id = ?", (bid,))
                con.execute("DELETE FROM audit_log WHERE business_id = ?", (bid,))
                con.execute("DELETE FROM businesses WHERE id = ?", (bid,))
            else:
                con.execute(
                    "DELETE FROM business_users WHERE business_id = ? AND user_id = ?",
                    (bid, user_id),
                )
        con.execute("DELETE FROM users WHERE id = ?", (user_id,))

    logger.info("Account %s erased (GDPR right to erasure).", user_id)
    return True, "Your account and associated data have been permanently deleted."
