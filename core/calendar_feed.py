# core/calendar_feed.py — per-business iCal subscription feed.
#
# A universal calendar integration that needs ZERO external accounts: each
# business gets a secret feed URL (/calendar/<token>.ics) that Google Calendar,
# Outlook and Apple Calendar can subscribe to. Confirmed/pending appointments
# show up automatically and stay in sync as the calendar app re-polls.

import logging
import secrets
from datetime import datetime
from typing import Optional

from core.db import get_conn, transaction
from core.ics import make_feed_ics

logger = logging.getLogger(__name__)

# How far back/forward to publish.
_PAST_DAYS = 7


def ensure_feed_token(business_id: int) -> Optional[str]:
    """Return the business's feed token, generating + persisting one if absent."""
    with transaction() as con:
        row = con.execute(
            "SELECT calendar_feed_token FROM businesses WHERE id=?", (business_id,)
        ).fetchone()
        if not row:
            return None
        token = row["calendar_feed_token"]
        if not token:
            token = secrets.token_urlsafe(24)
            con.execute(
                "UPDATE businesses SET calendar_feed_token=? WHERE id=?", (token, business_id)
            )
        return token


def regenerate_feed_token(business_id: int) -> Optional[str]:
    """Rotate the token (invalidates the old subscription URL)."""
    token = secrets.token_urlsafe(24)
    with transaction() as con:
        cur = con.execute(
            "UPDATE businesses SET calendar_feed_token=? WHERE id=?", (token, business_id)
        )
        if cur.rowcount == 0:
            return None
    return token


def business_by_feed_token(token: str) -> Optional[dict]:
    if not token:
        return None
    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM businesses WHERE calendar_feed_token=?", (token,)
        ).fetchone()
    return dict(row) if row else None


def feed_path(token: str) -> str:
    return f"/calendar/{token}.ics"


def build_feed(business_id: int, business_name: str = "") -> bytes:
    """Build the VCALENDAR bytes for a business's appointments."""
    with get_conn() as con:
        rows = con.execute(
            """
            SELECT a.id, a.customer_name, a.phone, a.service, a.start_at, a.status,
                   a.notes, s.duration_min
            FROM appointments a
            LEFT JOIN services s ON s.business_id = a.business_id AND s.name = a.service
            WHERE a.business_id = ?
              AND a.status IN ('pending', 'confirmed', 'completed')
              AND datetime(a.start_at) >= datetime('now', ? || ' days')
            ORDER BY a.start_at
            """,
            (business_id, -_PAST_DAYS),
        ).fetchall()

    events = []
    for r in rows:
        start = _parse_dt(r["start_at"])
        if not start:
            continue
        who = r["customer_name"] or "Customer"
        service = r["service"] or "Appointment"
        desc_parts = [f"Booked via LocusAI ({r['status']})"]
        if r["phone"]:
            desc_parts.append(f"Phone: {r['phone']}")
        if r["notes"]:
            desc_parts.append(str(r["notes"]))
        events.append(
            {
                "uid": f"appt-{r['id']}",
                "summary": f"{service} — {who}",
                "description": "\n".join(desc_parts),
                "location": "",
                "start": start,
                "duration_min": r["duration_min"] or 30,
            }
        )

    return make_feed_ics(f"{business_name or 'LocusAI'} appointments", events)


def _parse_dt(s) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(str(s)[: len(fmt) + 2], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(s))
    except ValueError:
        return None
