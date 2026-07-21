# sms_bp.py — SMS webhook handlers for LocusAI
# Handles incoming SMS via Telnyx and routes to AI conversation flow

import logging

from flask import Blueprint, jsonify, request

from core.db import get_conn, log_message, transaction
from core.sms import parse_telnyx_webhook

logger = logging.getLogger(__name__)

bp = Blueprint("sms", __name__, url_prefix="/api/sms")


# ============================================================================
# Business Routing
# ============================================================================


def _get_business_by_phone(phone_number: str):
    """Get business associated with a Telnyx phone number."""
    with get_conn() as con:
        row = con.execute(
            """SELECT id, name, tone FROM businesses
               WHERE escalation_phone = ? OR escalation_phone LIKE ?
               LIMIT 1""",
            (phone_number, f"%{phone_number[-10:]}%"),
        ).fetchone()

        if row:
            return dict(row)

        # Only fall back to "the business" when there is exactly one active — with
        # multiple tenants, guessing would route an SMS on an unknown number to the
        # wrong business (and reply to the sender as that business). Return None so
        # the webhook records "no_business" instead.
        rows = con.execute(
            "SELECT id, name, tone FROM businesses WHERE archived = 0 ORDER BY id LIMIT 2"
        ).fetchall()
        if len(rows) == 1:
            return dict(rows[0])
        return None


def _get_or_create_session(business_id: int, phone_number: str):
    """Get existing SMS session or create a new one."""
    with get_conn() as con:
        row = con.execute(
            """SELECT id FROM sessions
               WHERE business_id = ? AND phone = ? AND channel = 'sms'
                 AND datetime(created_at) > datetime('now', '-24 hours')
               ORDER BY created_at DESC LIMIT 1""",
            (business_id, phone_number),
        ).fetchone()

        if row:
            return row["id"]

    with transaction() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO sessions(business_id, channel, phone) VALUES(?, 'sms', ?)",
            (business_id, phone_number),
        )
        return cur.lastrowid


# ============================================================================
# SMS Webhook Endpoint
# ============================================================================


@bp.route("/webhook", methods=["POST"])
def sms_webhook():
    """Handle incoming SMS from Telnyx.

    Telnyx sends a JSON POST for each incoming message.
    We process it through the AI and respond with 200 OK.
    (Unlike Twilio, Telnyx does not use the response body for replies —
    outbound replies are sent via a separate API call.)
    """
    data = request.get_json(silent=True) or {}
    event_type = data.get("data", {}).get("event_type")

    # Only handle inbound messages
    if event_type != "message.received":
        return jsonify({"status": "ignored"}), 200

    parsed = parse_telnyx_webhook(data)
    from_number = parsed.get("from_number")
    to_number = parsed.get("to_number")
    message_body = parsed.get("body", "").strip()

    if not from_number or not message_body:
        logger.warning("SMS webhook received with missing data")
        return jsonify({"status": "ok"}), 200

    logger.info(f"SMS received from ...{from_number[-4:] if from_number else '???'}")

    business = _get_business_by_phone(to_number)
    if not business:
        logger.warning(f"No business found for SMS to {to_number}")
        return jsonify({"status": "no_business"}), 200

    business_id = business["id"]
    session_id = _get_or_create_session(business_id, from_number)
    log_message(session_id, "user", message_body)

    from core.sms import (
        TELNYX_PHONE_NUMBER,
        classify_sms_command,
        clear_opt_out,
        record_opt_out,
        send_sms,
    )

    # ---- TCPA opt-out / opt-in (must run before any AI reply) ----
    cmd = classify_sms_command(message_body)
    if cmd == "stop":
        record_opt_out(from_number, source="sms")
        reply = (
            "You've been unsubscribed and won't receive further messages. "
            "Reply START to opt back in."
        )
        log_message(session_id, "bot", reply)
        try:  # confirmation is permitted even after opt-out
            send_sms(
                to=from_number,
                message=reply,
                from_number=to_number or TELNYX_PHONE_NUMBER,
                allow_opted_out=True,
            )
        except Exception as e:
            logger.error(f"Failed to send STOP confirmation: {e}")
        return jsonify({"status": "opted_out"}), 200

    if cmd == "start":
        clear_opt_out(from_number)
        reply = (
            "You're re-subscribed and will receive messages again. "
            "Reply STOP to opt out at any time."
        )
        log_message(session_id, "bot", reply)
        try:
            send_sms(
                to=from_number,
                message=reply,
                from_number=to_number or TELNYX_PHONE_NUMBER,
                allow_opted_out=True,
            )
        except Exception as e:
            logger.error(f"Failed to send START confirmation: {e}")
        return jsonify({"status": "opted_in"}), 200

    # Check for special commands (HELP, CANCEL)
    response_text = _handle_special_commands(message_body, session_id, business_id)
    if not response_text:
        try:
            from core.ai import process_message
            from core.db import get_business_by_id

            business_data = get_business_by_id(business_id) or business
            state = {"session_id": session_id, "channel": "sms"}

            response_text = process_message(
                user_input=message_body,
                business_data=business_data,
                state=state,
            )

            # Reschedule/cancel: SMS has no confirm UI, so when the AI emits a
            # <CANCEL>/<RESCHEDULE> tag (after confirming verbally per its prompt),
            # apply it immediately and reply with the outcome.
            try:
                from core.booking import confirm_pending_change, extract_pending_change

                cleaned, change = extract_pending_change(response_text, business_data, session_id)
                if change:
                    ok, outcome = confirm_pending_change(change["token"])
                    response_text = (cleaned + " " + outcome).strip() if cleaned else outcome
                else:
                    response_text = cleaned
            except Exception as e:
                logger.warning(f"SMS reschedule/cancel handling failed: {e}")

            if len(response_text) > 480:
                response_text = response_text[:477] + "..."

        except Exception as e:
            logger.error(f"Error processing SMS: {e}", exc_info=True)
            response_text = (
                "Sorry, I'm having trouble right now. Please try again or call us directly."
            )

    log_message(session_id, "bot", response_text)

    # Send reply via Telnyx API
    try:
        from core.sms import TELNYX_PHONE_NUMBER, send_sms

        send_sms(
            to=from_number, message=response_text, from_number=to_number or TELNYX_PHONE_NUMBER
        )
    except Exception as e:
        logger.error(f"Failed to send SMS reply: {e}")

    return jsonify({"status": "ok"}), 200


def _handle_special_commands(message: str, session_id: int, business_id: int):
    """Handle special SMS commands HELP and CANCEL.

    Opt-out keywords (STOP/START) are handled earlier in the webhook so they can
    record the opt-out and bypass send suppression for the confirmation."""
    message_upper = message.upper().strip()

    if message_upper in ("HELP", "INFO"):
        return (
            "Commands: STOP to unsubscribe, CANCEL to cancel an appointment. "
            "Or just type your question and I'll help you."
        )

    if message_upper == "CANCEL":
        with get_conn() as con:
            row = con.execute(
                """SELECT a.id, a.service, a.start_at
                   FROM appointments a
                   JOIN sessions s ON a.session_id = s.id
                   WHERE s.id = ?
                     AND a.status IN ('pending', 'confirmed')
                     AND datetime(a.start_at) > datetime('now')
                   ORDER BY a.start_at LIMIT 1""",
                (session_id,),
            ).fetchone()

        if row:
            return (
                f"To cancel your {row['service']} appointment, please call us directly to confirm."
            )
        return "I don't see any upcoming appointments. How can I help you?"

    return None


# ============================================================================
# Status Webhook
# ============================================================================


@bp.route("/status", methods=["POST"])
def sms_status_webhook():
    """Handle SMS delivery status updates from Telnyx."""
    data = request.get_json(silent=True) or {}
    event_type = data.get("data", {}).get("event_type", "")
    payload = data.get("data", {}).get("payload", {})
    msg_id = payload.get("id")

    logger.info(f"SMS status update: {msg_id} -> {event_type}")
    return jsonify({"status": "ok"}), 200
