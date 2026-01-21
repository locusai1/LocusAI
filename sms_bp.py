# sms_bp.py — SMS webhook handlers for AxisAI
# Handles incoming SMS via Twilio and routes to AI conversation flow

import os
import logging
from flask import Blueprint, request, Response, g

from core.db import get_conn, transaction, create_session, log_message
from core.sms import (
    parse_twilio_webhook, generate_twiml_response,
    TWILIO_AUTH_TOKEN, TWILIO_CONFIGURED
)
from core.security import (
    verify_twilio_signature, log_security_event, SecurityEvent
)

logger = logging.getLogger(__name__)

bp = Blueprint("sms", __name__, url_prefix="/api/sms")

# ============================================================================
# Webhook Signature Verification
# ============================================================================

def _verify_twilio_request() -> bool:
    """Verify that the request is actually from Twilio."""
    if not TWILIO_AUTH_TOKEN:
        logger.warning("Twilio auth token not configured, skipping signature verification")
        return True  # Allow in development, but log warning

    signature = request.headers.get("X-Twilio-Signature", "")
    url = request.url
    params = request.form.to_dict()

    if not verify_twilio_signature(url, params, signature, TWILIO_AUTH_TOKEN):
        log_security_event(
            SecurityEvent.WEBHOOK_VERIFICATION_FAILED,
            details={"source": "twilio", "path": request.path}
        )
        return False

    return True


# ============================================================================
# Business Routing
# ============================================================================

def _get_business_by_phone(phone_number: str):
    """Get business associated with a Twilio phone number.

    Each business can have a dedicated Twilio number, or there can be
    a default business for shared numbers.
    """
    with get_conn() as con:
        # First, try to find a business with this specific phone number
        row = con.execute(
            """SELECT id, name, tone FROM businesses
               WHERE escalation_phone = ? OR escalation_phone LIKE ?
               LIMIT 1""",
            (phone_number, f"%{phone_number[-10:]}%")  # Match last 10 digits
        ).fetchone()

        if row:
            return dict(row)

        # Fall back to the first active business (for single-tenant setups)
        row = con.execute(
            "SELECT id, name, tone FROM businesses WHERE archived = 0 ORDER BY id LIMIT 1"
        ).fetchone()

        return dict(row) if row else None


def _get_or_create_session(business_id: int, phone_number: str):
    """Get existing SMS session or create a new one."""
    with get_conn() as con:
        # Look for recent session from this phone number (within 24 hours)
        row = con.execute(
            """SELECT id FROM sessions
               WHERE business_id = ? AND phone = ? AND channel = 'sms'
                 AND datetime(created_at) > datetime('now', '-24 hours')
               ORDER BY created_at DESC LIMIT 1""",
            (business_id, phone_number)
        ).fetchone()

        if row:
            return row["id"]

    # Create new session
    with transaction() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO sessions(business_id, channel, phone) VALUES(?, 'sms', ?)",
            (business_id, phone_number)
        )
        return cur.lastrowid


# ============================================================================
# SMS Webhook Endpoint
# ============================================================================

@bp.route("/webhook", methods=["POST"])
def sms_webhook():
    """Handle incoming SMS from Twilio.

    Twilio sends a POST request for each incoming SMS.
    We process it through the AI and respond with TwiML.
    """
    # Verify request is from Twilio
    if not _verify_twilio_request():
        return Response("Unauthorized", status=403)

    # Parse the incoming message
    data = parse_twilio_webhook(request.form.to_dict())

    from_number = data.get("from_number")
    to_number = data.get("to_number")
    message_body = data.get("body", "").strip()

    if not from_number or not message_body:
        logger.warning("SMS webhook received with missing data")
        return generate_twiml_response("Sorry, I couldn't understand your message.")

    logger.info(f"SMS received from {from_number[-4:] if from_number else '???'}")

    # Find the business for this number
    business = _get_business_by_phone(to_number)
    if not business:
        logger.warning(f"No business found for SMS to {to_number}")
        return generate_twiml_response(
            "Sorry, this number is not currently active. Please try again later."
        )

    business_id = business["id"]

    # Get or create SMS session
    session_id = _get_or_create_session(business_id, from_number)

    # Log the incoming message
    log_message(session_id, "user", message_body)

    # Check for special commands
    response = _handle_special_commands(message_body, session_id, business_id)
    if response:
        log_message(session_id, "bot", response)
        return Response(generate_twiml_response(response), mimetype="text/xml")

    # Process through AI
    try:
        from core.ai import process_message
        from core.db import get_business_by_id

        # Get full business data
        business_data = get_business_by_id(business_id) or business

        # State for the conversation
        state = {
            "session_id": session_id,
            "channel": "sms"
        }

        # Get AI response
        ai_response = process_message(
            user_input=message_body,
            business_data=business_data,
            state=state
        )

        # Log the response
        log_message(session_id, "bot", ai_response)

        # SMS responses should be concise
        if len(ai_response) > 480:
            ai_response = ai_response[:477] + "..."

        return Response(generate_twiml_response(ai_response), mimetype="text/xml")

    except Exception as e:
        logger.error(f"Error processing SMS: {e}", exc_info=True)
        fallback = "Sorry, I'm having trouble right now. Please try again or call us directly."
        log_message(session_id, "bot", fallback)
        return Response(generate_twiml_response(fallback), mimetype="text/xml")


def _handle_special_commands(message: str, session_id: int, business_id: int):
    """Handle special SMS commands like STOP, CANCEL, HELP.

    Returns:
        Response string if command handled, None otherwise
    """
    message_upper = message.upper().strip()

    if message_upper in ("STOP", "UNSUBSCRIBE", "QUIT"):
        # TODO: Mark customer as opted out
        return "You've been unsubscribed. Reply START to opt back in."

    if message_upper in ("START", "SUBSCRIBE"):
        # TODO: Mark customer as opted in
        return "Welcome back! You're now subscribed to messages from us."

    if message_upper == "HELP":
        return (
            "Commands: STOP to unsubscribe, CANCEL to cancel appointment. "
            "Or just type your question and I'll help you."
        )

    if message_upper == "CANCEL":
        # Check for pending appointments
        with get_conn() as con:
            # Find the most recent upcoming appointment for this session
            row = con.execute(
                """SELECT a.id, a.service, a.start_at, s.phone
                   FROM appointments a
                   JOIN sessions s ON a.session_id = s.id
                   WHERE s.id = ?
                     AND a.status IN ('pending', 'confirmed')
                     AND datetime(a.start_at) > datetime('now')
                   ORDER BY a.start_at LIMIT 1""",
                (session_id,)
            ).fetchone()

        if row:
            # TODO: Actually cancel the appointment
            return (
                f"To cancel your {row['service']} appointment, "
                f"please call us directly to confirm. Reply YES to proceed."
            )
        else:
            return "I don't see any upcoming appointments. How can I help you?"

    return None


# ============================================================================
# Status Webhook (Optional)
# ============================================================================

@bp.route("/status", methods=["POST"])
def sms_status_webhook():
    """Handle SMS delivery status updates from Twilio.

    This is called when message status changes (sent, delivered, failed, etc.)
    """
    if not _verify_twilio_request():
        return Response("Unauthorized", status=403)

    message_sid = request.form.get("MessageSid")
    message_status = request.form.get("MessageStatus")
    error_code = request.form.get("ErrorCode")

    logger.info(f"SMS status update: {message_sid} -> {message_status}")

    if error_code:
        logger.warning(f"SMS delivery error: {message_sid}, code: {error_code}")

    # TODO: Update reminder status if this was a reminder message

    return Response("OK", status=200)


# ============================================================================
# Test Endpoint (Development Only)
# ============================================================================

@bp.route("/test", methods=["GET"])
def sms_test():
    """Test endpoint to verify SMS configuration.

    Only accessible in development.
    """
    if os.getenv("APP_ENV", "dev").lower() in ("prod", "production"):
        return Response("Not available in production", status=404)

    from core.sms import check_twilio_config, test_connection

    config = check_twilio_config()
    connection = test_connection() if config["fully_configured"] else {"connected": False}

    return {
        "configuration": config,
        "connection": connection,
        "webhook_url": request.url_root.rstrip("/") + "/api/sms/webhook"
    }
