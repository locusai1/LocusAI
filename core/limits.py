# core/limits.py — plan-based feature gating for LocusAI
#
# Design rule: a business is only gated once one of its owners holds an ACTIVE
# PAID subscription on a limited tier. Trial users and accounts with no
# subscription are treated as ungated (full access) — so activation isn't hurt
# and nothing breaks before billing goes live.

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from core import billing
from core.db import get_conn

logger = logging.getLogger(__name__)

_PLAN_RANK = {"starter": 1, "professional": 2, "business": 3}


def _owner_user_ids(business_id: int) -> List[int]:
    with get_conn() as con:
        rows = con.execute(
            "SELECT user_id FROM business_users WHERE business_id = ?", (business_id,)
        ).fetchall()
    return [r["user_id"] for r in rows]


def effective_plan_key(business_id: int) -> Optional[str]:
    """Highest active *paid* plan among the business's owners, or None when the
    business isn't on a paid plan (trial / no subscription = ungated)."""
    best = None
    best_rank = 0
    for uid in _owner_user_ids(business_id):
        try:
            pk = billing.current_plan_key(uid)
        except Exception:
            pk = None
        if pk and _PLAN_RANK.get(pk, 0) > best_rank:
            best, best_rank = pk, _PLAN_RANK[pk]
    return best


def _limits(business_id: int) -> Optional[Dict[str, Any]]:
    pk = effective_plan_key(business_id)
    if not pk:
        return None
    plan = billing.plan(pk)
    return plan["limits"] if plan else None


def conversations_this_month(business_id: int) -> int:
    """Count conversations (sessions) created for this business in the current
    UTC calendar month."""
    start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as con:
        row = con.execute(
            "SELECT COUNT(*) c FROM sessions WHERE business_id = ? AND created_at >= ?",
            (business_id, start),
        ).fetchone()
    return row["c"] if row else 0


def quota_status(business_id: int) -> Dict[str, Any]:
    """Conversation-quota snapshot. For ungated businesses, unlimited=True."""
    limits = _limits(business_id)
    if not limits:
        return {"gated": False, "limit": -1, "used": 0, "remaining": -1, "over": False}
    limit = limits.get("conversations", -1)
    used = conversations_this_month(business_id)
    if limit < 0:
        return {"gated": True, "limit": -1, "used": used, "remaining": -1, "over": False}
    remaining = max(0, limit - used)
    return {"gated": True, "limit": limit, "used": used,
            "remaining": remaining, "over": used >= limit}


def can_start_conversation(business_id: int) -> bool:
    """False only when a paid, limited tier has hit its monthly conversation cap."""
    return not quota_status(business_id)["over"]


def channel_allowed(business_id: int, channel: str) -> bool:
    """Whether the business's plan includes a channel (web/voice/sms).
    Ungated businesses allow all channels."""
    limits = _limits(business_id)
    if not limits:
        return True
    return channel in (limits.get("channels") or ["web", "voice", "sms"])


def users_count(business_id: int) -> int:
    return len(_owner_user_ids(business_id))


def can_add_user(business_id: int) -> bool:
    """Whether another team member can be added under the plan's user limit."""
    limits = _limits(business_id)
    if not limits:
        return True
    max_users = limits.get("users", -1)
    if max_users < 0:
        return True
    return users_count(business_id) < max_users


def upgrade_message(business_id: int, what: str = "conversations") -> str:
    """Friendly limit-reached copy for surfacing to end-users/owners."""
    pk = effective_plan_key(business_id)
    name = billing.plan(pk)["name"] if pk and billing.plan(pk) else "your"
    return (f"You've reached your {name} plan's monthly {what} limit. "
            "Please upgrade your plan to continue.")
