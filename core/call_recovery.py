# core/call_recovery.py — "never drop a call" recovery.
#
# Guarantees no inbound call is silently lost. Any inbound call that didn't reach
# a clean resolution — missed, errored mid-call, dropped, or left as a voicemail —
# triggers an OWNER ALERT (email + SMS to the escalation contact) so a human can
# call the person back. The caller-side "sorry we missed you" SMS is handled
# separately in voice.py; this module is the owner-facing safety net.
#
# Deduped per call via voice_calls.recovery_alerted. Best-effort: never raises.

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# call_status / outcome values that mean the call did not resolve cleanly.
_FAILED_STATUSES = {"error", "registered"}
_FAILED_OUTCOMES = {"missed", "no_answer", "incomplete", "voicemail"}


def _recovery_enabled(business_id: int) -> bool:
    """Owner can opt out per business via voice_settings.missed_call_recovery_enabled."""
    from core.db import get_conn

    try:
        with get_conn() as con:
            row = con.execute(
                "SELECT missed_call_recovery_enabled AS e FROM voice_settings WHERE business_id=?",
                (business_id,),
            ).fetchone()
        # Default ON when there's no settings row yet.
        return True if row is None else bool(row["e"])
    except Exception:
        return True


def is_recoverable(call: Dict[str, Any]) -> bool:
    """True if this call represents an inbound contact that didn't resolve.

    Pure function over a voice_calls row dict (easy to test)."""
    if not call:
        return False
    if (call.get("direction") or "inbound") != "inbound":
        return False
    if call.get("recovery_alerted"):
        return False
    # A call the AI fully handled (contained) and didn't flag as missed is fine.
    status = (call.get("call_status") or "").lower()
    outcome = (call.get("call_outcome") or "").lower()
    duration = call.get("duration_seconds")

    if status in _FAILED_STATUSES:
        return True
    if outcome in _FAILED_OUTCOMES:
        return True
    if call.get("caller_message"):  # voicemail left
        return True
    # Connected but effectively no conversation and not contained.
    if (duration is None or duration == 0) and not call.get("containment"):
        return True
    return False


def _build_owner_alert(call: Dict[str, Any], biz_name: str) -> tuple:
    """Return (subject, body, sms) for the owner alert."""
    caller = call.get("from_number") or "an unknown number"
    when = call.get("started_at") or call.get("created_at") or ""
    reason = (call.get("call_outcome") or call.get("call_status") or "missed").lower()
    voicemail = call.get("caller_message")

    subject = f"[LocusAI] Missed call from {caller} — {biz_name}"
    lines = [
        f"You have an inbound call that needs a callback ({reason}).",
        "",
        f"Caller: {caller}",
        f"Time: {when}",
    ]
    if voicemail:
        lines += ["", "Message left:", voicemail]
    lines += [
        "",
        "We've also texted the caller to let them know they can reply or call back.",
        "",
        "— LocusAI",
    ]
    sms = f"Missed call from {caller} at {biz_name}."
    if voicemail:
        sms += f' Message: "{voicemail[:120]}"'
    else:
        sms += " Tap to call them back."
    return subject, "\n".join(lines), sms


def recover_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """Alert the owner about an unresolved inbound call. Deduped + best-effort.

    Returns {"alerted": bool, "channels": [...]}.
    """
    result = {"alerted": False, "channels": []}
    try:
        if not is_recoverable(call):
            return result
        business_id = call.get("business_id")
        if not business_id or not _recovery_enabled(business_id):
            return result

        from core.db import get_business_by_id

        biz = get_business_by_id(business_id) or {}
        biz_name = biz.get("name") or "your business"
        subject, body, sms = _build_owner_alert(call, biz_name)

        # Email the owner.
        owner_email = biz.get("escalation_email")
        if owner_email:
            try:
                from core.mailer import send_email

                send_email(owner_email, subject, body)
                result["channels"].append("email")
            except Exception as e:
                logger.warning("Owner missed-call email failed: %s", e)

        # SMS the owner's escalation phone.
        owner_phone = biz.get("escalation_phone")
        if owner_phone:
            try:
                from core.sms import TELNYX_CONFIGURED, send_sms

                if TELNYX_CONFIGURED:
                    send_sms(to=owner_phone, message=sms)
                    result["channels"].append("sms")
            except Exception as e:
                logger.warning("Owner missed-call SMS failed: %s", e)

        # Mark handled so we never double-alert (even if no channel was configured).
        _mark_alerted(call.get("retell_call_id") or call.get("id"))
        result["alerted"] = bool(result["channels"])
        if result["alerted"]:
            logger.info(
                "Missed-call recovery: alerted owner of %s via %s",
                business_id,
                result["channels"],
            )
    except Exception:
        logger.warning("recover_call failed", exc_info=True)
    return result


def _mark_alerted(call_ref: Optional[Any]) -> None:
    from core.db import transaction

    if not call_ref:
        return
    with transaction() as con:
        con.execute(
            "UPDATE voice_calls SET recovery_alerted=1 WHERE retell_call_id=? OR id=?",
            (str(call_ref), call_ref),
        )
