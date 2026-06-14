# core/followups.py — post-call lead nurture.
# When a caller asks about a service/appointment but doesn't book, schedule a
# follow-up SMS (24h later by default) with a link to the self-serve booking
# page. Recovers calls that would otherwise be lost leads.

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from core.db import get_business_by_id, get_conn
from core.settings import APP_BASE_URL

logger = logging.getLogger(__name__)

# A real conversation, not a hang-up / wrong number / missed call.
MIN_DURATION_SECONDS = 15

# Signals that the caller was interested in booking (used only as a fallback
# when the structured booking_discussed flag isn't set on the call record).
BOOKING_INTEREST_KEYWORDS = (
    "appointment",
    "book",
    "booking",
    "schedule",
    "availab",  # available / availability
    "slot",
    "reschedul",
    "openings",  # "any openings?" — note: NOT "opening hours" (a hours query)
    "price",
    "cost",
    "how much",
    "when can",
    "fit me in",
    "come in",
    "next week",
    "do you have",
)


def _showed_booking_interest(voice_call: dict) -> bool:
    """True if the caller looked like a booking lead.

    Prefers the structured booking_discussed flag; falls back to keyword
    matching on the AI summary / intent / transcript so it still works when the
    flag wasn't populated.
    """
    if voice_call.get("booking_discussed"):
        return True
    text = " ".join(
        str(voice_call.get(k) or "")
        for k in ("call_summary", "call_intent", "call_outcome", "transcript")
    ).lower()
    if not text.strip():
        return False
    return any(kw in text for kw in BOOKING_INTEREST_KEYWORDS)


def _booking_url(business: Optional[dict]) -> Optional[str]:
    if not business or not business.get("slug"):
        return None
    return f"{APP_BASE_URL.rstrip('/')}/book/{business['slug']}"


def compose_followup_message(business_name: str, booking_url: Optional[str]) -> str:
    """The nurture SMS. Includes STOP per TCPA."""
    name = business_name or "us"
    if booking_url:
        return (
            f"Hi! Thanks for calling {name}. Whenever you're ready, you can book "
            f"online here: {booking_url} — Reply STOP to opt out."
        )
    return (
        f"Hi! Thanks for calling {name}. Give us a call back whenever you'd like "
        f"to book. Reply STOP to opt out."
    )


def maybe_schedule_lead_followup(
    voice_call: dict, *, now: Optional[datetime] = None
) -> Optional[int]:
    """Schedule a follow-up SMS if this call was an unconverted booking lead.

    Returns the new lead_followups row id, or None if not eligible / already
    scheduled. Safe to call on every analyzed call.
    """
    if not voice_call:
        return None
    if voice_call.get("direction") != "inbound":
        return None
    # Already booked on this call — nothing to nurture.
    if voice_call.get("booking_confirmed") or voice_call.get("appointment_id"):
        return None
    # Must be a real conversation with a reachable caller.
    if (voice_call.get("duration_seconds") or 0) < MIN_DURATION_SECONDS:
        return None
    phone = (voice_call.get("from_number") or "").strip()
    if not phone:
        return None
    business_id = voice_call.get("business_id")
    if not business_id:
        return None

    # Per-business opt-out + delay.
    from core.voice import get_voice_settings

    settings = get_voice_settings(business_id) or {}
    if not settings.get("lead_followup_enabled", 1):
        return None

    if not _showed_booking_interest(voice_call):
        return None

    # Respect SMS opt-out (TCPA).
    from core.sms import is_opted_out

    if is_opted_out(phone):
        return None

    vc_id = voice_call.get("id")
    delay_hours = settings.get("lead_followup_delay_hours") or 24
    now = now or datetime.now()
    scheduled_for = (now + timedelta(hours=delay_hours)).strftime("%Y-%m-%d %H:%M:%S")

    business = get_business_by_id(business_id)
    booking_url = _booking_url(business)
    message = compose_followup_message((business or {}).get("name", "us"), booking_url)

    with get_conn() as con:
        # Dedupe: one follow-up per call.
        if (
            vc_id
            and con.execute(
                "SELECT 1 FROM lead_followups WHERE voice_call_id = ?", (vc_id,)
            ).fetchone()
        ):
            return None
        cur = con.execute(
            "INSERT INTO lead_followups "
            "(business_id, voice_call_id, phone, booking_url, message, scheduled_for) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (business_id, vc_id, phone, booking_url, message, scheduled_for),
        )
        con.commit()
        new_id = cur.lastrowid

    logger.info(
        "Scheduled lead follow-up %s for business %s at %s", new_id, business_id, scheduled_for
    )
    return new_id


def dispatch_due_followups(limit: int = 20) -> int:
    """Send any follow-ups whose scheduled time has passed. Returns count sent.

    Called from the background automation worker.
    """
    from core.sms import TELNYX_CONFIGURED, send_sms

    if not TELNYX_CONFIGURED:
        return 0

    sent = 0
    with get_conn() as con:
        rows = con.execute(
            "SELECT * FROM lead_followups "
            "WHERE status = 'pending' AND datetime(scheduled_for) <= datetime('now') "
            "ORDER BY scheduled_for LIMIT ?",
            (limit,),
        ).fetchall()

        for r in rows:
            try:
                result = send_sms(to=r["phone"], message=r["message"])
                status = result.get("status")
                if status == "error":
                    con.execute(
                        "UPDATE lead_followups SET status='failed', error_message=? WHERE id=?",
                        (result.get("error"), r["id"]),
                    )
                elif status == "suppressed":
                    con.execute(
                        "UPDATE lead_followups SET status='cancelled', error_message='opted out' "
                        "WHERE id=?",
                        (r["id"],),
                    )
                else:
                    con.execute(
                        "UPDATE lead_followups SET status='sent', sent_at=CURRENT_TIMESTAMP "
                        "WHERE id=?",
                        (r["id"],),
                    )
                    sent += 1
                con.commit()
            except Exception as e:
                logger.warning("Lead follow-up %s failed to send: %s", r["id"], e)

    return sent
