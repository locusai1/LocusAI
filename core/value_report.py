# core/value_report.py — "what LocusAI did for you" value report.
# Turns existing data (AI bookings, calls answered after hours, leads recovered)
# into a concrete value story for the owner. Retention/upsell lever: SMBs keep
# tools whose ROI they can see.

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict

from core.db import get_conn

logger = logging.getLogger(__name__)


def _period(days: int):
    end = datetime.now()
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _parse_dt(s):
    if not s:
        return None
    s = str(s).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[: len(fmt) + 2] if len(s) > len(fmt) else s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.split(".")[0])
    except ValueError:
        return None


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_after_hours(started_at, hours: Dict) -> bool:
    """True if the call landed outside the business's open hours for that day."""
    dt = _parse_dt(started_at)
    if not dt or not hours:
        return False
    row = hours.get(dt.weekday())  # business_hours.weekday: 0=Mon .. 6=Sun
    if row is None:
        return False
    if row["closed"]:
        return True
    ot, ct = row["open_time"], row["close_time"]
    if not ot or not ct:
        return False
    return not (ot <= dt.strftime("%H:%M") <= ct)


def compute_value_report(business_id: int, days: int = 30) -> Dict:
    """Compute the value LocusAI delivered for a business over the last `days`."""
    start_date, end_date = _period(days)
    with get_conn() as con:
        # AI-booked appointments + the revenue they represent (price from services).
        ai = con.execute(
            """
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(CASE WHEN a.status != 'cancelled'
                                     THEN COALESCE(s.price, 0) ELSE 0 END), 0) AS revenue
            FROM appointments a
            LEFT JOIN services s ON a.service = s.name AND s.business_id = a.business_id
            WHERE a.business_id = ? AND a.source = 'ai'
              AND date(a.created_at) BETWEEN ? AND ?
            """,
            (business_id, start_date, end_date),
        ).fetchone()

        conv = con.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE business_id = ? "
            "AND date(created_at) BETWEEN ? AND ?",
            (business_id, start_date, end_date),
        ).fetchone()

        calls = con.execute(
            """
            SELECT started_at FROM voice_calls
            WHERE business_id = ? AND date(started_at) BETWEEN ? AND ?
              AND duration_seconds > 0 AND call_status NOT IN ('error', 'registered')
            """,
            (business_id, start_date, end_date),
        ).fetchall()

        # lead_followups may not exist on very old DBs — guard.
        try:
            leads = con.execute(
                "SELECT COUNT(*) AS c FROM lead_followups WHERE business_id = ? "
                "AND status = 'sent' AND date(created_at) BETWEEN ? AND ?",
                (business_id, start_date, end_date),
            ).fetchone()
            leads_recovered = leads["c"] or 0
        except Exception:
            leads_recovered = 0

        hours = {
            r["weekday"]: r
            for r in con.execute(
                "SELECT weekday, open_time, close_time, closed FROM business_hours "
                "WHERE business_id = ?",
                (business_id,),
            ).fetchall()
        }

    after_hours = sum(1 for c in calls if _is_after_hours(c["started_at"], hours))
    revenue = round(_num(ai["revenue"]), 2)

    return {
        "period_days": days,
        "start_date": start_date,
        "end_date": end_date,
        "ai_bookings": ai["cnt"] or 0,
        "revenue_captured": revenue,
        "conversations_handled": conv["c"] or 0,
        "calls_answered": len(calls),
        "after_hours_calls": after_hours,
        "leads_recovered": leads_recovered,
        # Headline number for the report card.
        "headline_value": revenue,
    }
