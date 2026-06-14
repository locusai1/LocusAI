# core/onboarding.py — setup-progress checklist for new businesses
#
# Computes which setup steps a business has completed from real DB state, so the
# dashboard can show a "Get set up" checklist instead of a wall of zeros.

import logging
from typing import Any, Dict

from core.db import get_conn

logger = logging.getLogger(__name__)


def _count(con, sql: str, params) -> int:
    row = con.execute(sql, params).fetchone()
    return (row[0] if row else 0) or 0


def checklist_for_business(business_id: int) -> Dict[str, Any]:
    """Return the onboarding checklist + progress for a business.

    {
      "steps": [{key, label, desc, done, endpoint}],
      "done": int, "total": int, "complete": bool, "percent": int
    }
    """
    if not business_id:
        return {"steps": [], "done": 0, "total": 0, "complete": True, "percent": 100}

    with get_conn() as con:
        services = _count(
            con, "SELECT COUNT(*) FROM services WHERE business_id=? AND active=1", (business_id,)
        )
        hours = _count(
            con, "SELECT COUNT(*) FROM business_hours WHERE business_id=?", (business_id,)
        )
        kb = _count(
            con, "SELECT COUNT(*) FROM kb_entries WHERE business_id=? AND active=1", (business_id,)
        )
        web_sessions = _count(
            con,
            "SELECT COUNT(*) FROM sessions WHERE business_id=? AND channel='web'",
            (business_id,),
        )
        integrations = _count(
            con,
            "SELECT COUNT(*) FROM integrations WHERE business_id=? AND status='active'",
            (business_id,),
        )
        appts = _count(con, "SELECT COUNT(*) FROM appointments WHERE business_id=?", (business_id,))

    steps = [
        {
            "key": "services",
            "label": "Add your services",
            "desc": "Tell the AI what you offer so it can book the right appointments.",
            "done": services > 0,
            "endpoint": "services.services_index",
        },
        {
            "key": "hours",
            "label": "Set your business hours",
            "desc": "So the AI only books when you're open.",
            "done": hours > 0,
            "endpoint": "services.hours_index",
        },
        {
            "key": "kb",
            "label": "Add knowledge base answers",
            "desc": "Answer common questions once — the AI reuses them on every channel.",
            "done": kb > 0,
            "endpoint": "kb.kb_index",
        },
        {
            "key": "widget",
            "label": "Embed your chat widget",
            "desc": "Drop one line of code on your site to capture web enquiries.",
            "done": web_sessions > 0,
            "endpoint": "integrations.widget_settings",
        },
        {
            "key": "calendar",
            "label": "Connect a calendar",
            "desc": "Sync bookings with Google Calendar (optional but recommended).",
            "done": integrations > 0,
            "endpoint": "integrations.integrations_index",
        },
        {
            "key": "booking",
            "label": "Get your first booking",
            "desc": "Once set up, your AI starts booking appointments for you.",
            "done": appts > 0,
            "endpoint": "appointments.appointments_index",
        },
    ]

    done = sum(1 for s in steps if s["done"])
    total = len(steps)
    return {
        "steps": steps,
        "done": done,
        "total": total,
        "complete": done >= total,
        "percent": round(done * 100 / total) if total else 100,
    }
