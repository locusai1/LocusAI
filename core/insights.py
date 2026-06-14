# core/insights.py — business intelligence the owner can't get anywhere else.
# Three reports that turn LocusAI's call/chat data into money decisions:
#   - missed_revenue:   what you're losing and roughly why
#   - demand_insights:  when demand hits + what callers want
#   - benchmarks:       how you compare to similar businesses (anonymised cohort)

from __future__ import annotations

import logging
import re
from typing import Dict, List

from core.db import get_conn
from core.value_report import _is_after_hours, _num, _period

logger = logging.getLogger(__name__)

MIN_COHORT = 3  # need at least this many businesses before showing a benchmark

_MISSED_SQL = (
    "duration_seconds IS NULL OR duration_seconds = 0 OR call_status IN ('error', 'registered')"
)


def _avg_service_value(con, business_id: int) -> float:
    rows = con.execute(
        "SELECT price FROM services WHERE business_id=? AND active=1", (business_id,)
    ).fetchall()
    vals = [_num(r["price"]) for r in rows if _num(r["price"]) > 0]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def compute_missed_revenue(business_id: int, days: int = 30) -> Dict:
    """Estimate revenue lost to missed/unconverted calls, with a transparent breakdown."""
    start_date, end_date = _period(days)
    with get_conn() as con:
        calls = con.execute(
            """
            SELECT started_at, duration_seconds, call_status, booking_discussed,
                   booking_confirmed, appointment_id
            FROM voice_calls
            WHERE business_id = ? AND date(started_at) BETWEEN ? AND ?
            """,
            (business_id, start_date, end_date),
        ).fetchall()
        avg_value = _avg_service_value(con, business_id)
        hours = {
            r["weekday"]: r
            for r in con.execute(
                "SELECT weekday, open_time, close_time, closed FROM business_hours "
                "WHERE business_id = ?",
                (business_id,),
            ).fetchall()
        }

    def _is_missed(c):
        return c["duration_seconds"] in (None, 0) or c["call_status"] in ("error", "registered")

    missed = [c for c in calls if _is_missed(c)]
    answered = [c for c in calls if not _is_missed(c)]
    unconverted = [
        c
        for c in answered
        if c["booking_discussed"] and not c["booking_confirmed"] and not c["appointment_id"]
    ]
    after_hours_missed = sum(1 for c in missed if _is_after_hours(c["started_at"], hours))

    lost_opportunities = len(missed) + len(unconverted)
    estimated_lost = round(lost_opportunities * avg_value, 2)

    return {
        "period_days": days,
        "missed_calls": len(missed),
        "after_hours_missed": after_hours_missed,
        "unconverted_booking_calls": len(unconverted),
        "lost_opportunities": lost_opportunities,
        "avg_booking_value": avg_value,
        "estimated_lost_revenue": estimated_lost,
    }


def compute_demand_insights(business_id: int, days: int = 30) -> Dict:
    """When demand hits (hour/day) and what callers want."""
    start_date, end_date = _period(days)
    hour_counts = [0] * 24
    day_counts = [0] * 7  # 0=Mon .. 6=Sun (Python weekday)

    with get_conn() as con:
        for table, col in (("voice_calls", "started_at"), ("sessions", "created_at")):
            rows = con.execute(
                f"SELECT {col} AS ts FROM {table} "
                f"WHERE business_id = ? AND date({col}) BETWEEN ? AND ?",
                (business_id, start_date, end_date),
            ).fetchall()
            for r in rows:
                from core.value_report import _parse_dt

                dt = _parse_dt(r["ts"])
                if dt:
                    hour_counts[dt.hour] += 1
                    day_counts[dt.weekday()] += 1

        top_services = con.execute(
            """
            SELECT service, COUNT(*) AS cnt FROM appointments
            WHERE business_id = ? AND date(created_at) BETWEEN ? AND ?
              AND service IS NOT NULL AND service != ''
            GROUP BY service ORDER BY cnt DESC LIMIT 5
            """,
            (business_id, start_date, end_date),
        ).fetchall()

        question_rows = con.execute(
            """
            SELECT m.text AS text FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE s.business_id = ? AND m.sender = 'user'
              AND date(m.timestamp) BETWEEN ? AND ?
            """,
            (business_id, start_date, end_date),
        ).fetchall()

    # Top recurring questions (normalised).
    q_buckets: Dict[str, Dict] = {}
    for r in question_rows:
        t = (r["text"] or "").strip()
        if len(t) < 6 or len(t) > 200 or "?" not in t:
            continue
        key = re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()
        if not key:
            continue
        b = q_buckets.setdefault(key, {"text": t, "n": 0})
        b["n"] += 1
    top_questions = sorted(q_buckets.values(), key=lambda x: x["n"], reverse=True)[:5]

    days_lbl = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    peak_hour = max(range(24), key=lambda h: hour_counts[h]) if any(hour_counts) else None
    peak_day = max(range(7), key=lambda d: day_counts[d]) if any(day_counts) else None

    return {
        "period_days": days,
        "hour_counts": hour_counts,
        "day_counts": day_counts,
        "day_labels": days_lbl,
        "peak_hour": peak_hour,
        "peak_day": days_lbl[peak_day] if peak_day is not None else None,
        "top_services": [{"name": r["service"], "count": r["cnt"]} for r in top_services],
        "top_questions": [{"text": q["text"], "count": q["n"]} for q in top_questions],
    }


def _business_call_stats(con, business_id: int, start_date: str, end_date: str):
    """(answered, total, ai_bookings) for one business in the window."""
    row = con.execute(
        f"""
        SELECT COUNT(*) AS total,
               COUNT(CASE WHEN NOT ({_MISSED_SQL}) THEN 1 END) AS answered
        FROM voice_calls
        WHERE business_id = ? AND date(started_at) BETWEEN ? AND ?
        """,
        (business_id, start_date, end_date),
    ).fetchone()
    ai = con.execute(
        "SELECT COUNT(*) AS c FROM appointments WHERE business_id = ? AND source = 'ai' "
        "AND date(created_at) BETWEEN ? AND ?",
        (business_id, start_date, end_date),
    ).fetchone()
    return row["answered"] or 0, row["total"] or 0, ai["c"] or 0


def compute_benchmarks(business_id: int, days: int = 30) -> Dict:
    """Compare this business to an anonymised cohort of similar (active) businesses."""
    start_date, end_date = _period(days)
    with get_conn() as con:
        businesses = con.execute("SELECT id FROM businesses WHERE archived = 0").fetchall()

        answer_rates: List[float] = []
        conv_rates: List[float] = []
        me = None
        for b in businesses:
            answered, total, ai_bookings = _business_call_stats(con, b["id"], start_date, end_date)
            if total == 0:
                continue  # no activity → not part of the cohort
            ar = answered / total * 100
            cr = (ai_bookings / answered * 100) if answered else 0.0
            answer_rates.append(ar)
            conv_rates.append(cr)
            if b["id"] == business_id:
                me = {"answer_rate": round(ar, 1), "conversion_rate": round(cr, 1)}

    if me is None or len(answer_rates) < MIN_COHORT:
        return {"available": False, "cohort_size": len(answer_rates), "min_cohort": MIN_COHORT}

    def _median(xs):
        xs = sorted(xs)
        n = len(xs)
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

    return {
        "available": True,
        "cohort_size": len(answer_rates),
        "your_answer_rate": me["answer_rate"],
        "cohort_answer_rate": round(_median(answer_rates), 1),
        "your_conversion_rate": me["conversion_rate"],
        "cohort_conversion_rate": round(_median(conv_rates), 1),
        "answer_rate_verdict": "above" if me["answer_rate"] >= _median(answer_rates) else "below",
        "conversion_verdict": "above" if me["conversion_rate"] >= _median(conv_rates) else "below",
    }
