# voice_bp.py — Voice webhook handlers for LocusAI
# Handles incoming voice calls via Retell AI and routes to AI conversation flow

import os
import json
import logging
from flask import Blueprint, request, Response, jsonify, g, session

from core.db import get_conn, log_message, get_business_by_id
from core.security import log_security_event, SecurityEvent
from core.voice import (
    verify_retell_signature,
    handle_call_started,
    handle_call_ended,
    handle_call_analyzed,
    get_voice_call,
    update_voice_call,
    get_voice_settings,
    create_outbound_call,
    is_retell_configured,
    extract_voice_booking,
    detect_booking_response,
    confirm_voice_booking,
    cancel_voice_booking,
    get_voice_pending_booking,
    RetellClientError,
)

logger = logging.getLogger(__name__)

bp = Blueprint("voice", __name__, url_prefix="/api/voice")

# ============================================================================
# Webhook Signature Verification
# ============================================================================

def _verify_retell_request() -> bool:
    """Verify that the request is actually from Retell."""
    from core.settings import RETELL_WEBHOOK_SECRET

    if not RETELL_WEBHOOK_SECRET:
        logger.warning("RETELL_WEBHOOK_SECRET not configured, skipping signature verification")
        return True  # Allow in development, but log warning

    signature = request.headers.get("X-Retell-Signature", "")
    payload = request.get_data()

    if not verify_retell_signature(payload, signature):
        log_security_event(
            SecurityEvent.WEBHOOK_VERIFICATION_FAILED,
            details={"source": "retell", "path": request.path}
        )
        return False

    return True


# ============================================================================
# Main Webhook Endpoint
# ============================================================================

@bp.route("/webhook", methods=["POST"])
def voice_webhook():
    """Handle voice call events from Retell AI.

    Retell sends webhooks for various call lifecycle events:
    - call_started: Call has connected
    - call_ended: Call has ended
    - call_analyzed: Post-call analysis complete

    The actual conversation is handled by Retell's LLM integration,
    so we mainly track state and handle bookings here.
    """
    # Verify request is from Retell
    if not _verify_retell_request():
        return Response("Unauthorized", status=403)

    try:
        data = request.get_json(force=True)
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        return jsonify({"error": "Invalid JSON"}), 400

    event_type = data.get("event")
    call_data = data.get("call", {})
    call_id = call_data.get("call_id")

    logger.info(f"Voice webhook received: event={event_type}, call_id={call_id}")

    try:
        if event_type == "call_started":
            result = handle_call_started(data)
            return jsonify(result)

        elif event_type == "call_ended":
            result = handle_call_ended(data)
            return jsonify(result)

        elif event_type == "call_analyzed":
            result = handle_call_analyzed(data)
            return jsonify(result)

        else:
            logger.warning(f"Unknown voice webhook event: {event_type}")
            return jsonify({"status": "ignored", "event": event_type})

    except Exception as e:
        logger.error(f"Error handling voice webhook: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================================
# LLM Response Webhook (Real-time conversation)
# ============================================================================

@bp.route("/webhook/response", methods=["POST"])
def voice_response_webhook():
    """Handle LLM response requests from Retell.

    This endpoint is called by Retell when it needs an LLM response.
    We process the transcript through our AI and return the response.

    Note: This is only used if you configure Retell to use a custom LLM endpoint.
    Otherwise, Retell handles the conversation using its built-in LLM.
    """
    if not _verify_retell_request():
        return Response("Unauthorized", status=403)

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    call_id = data.get("call_id")
    transcript = data.get("transcript", [])

    if not call_id:
        return jsonify({"error": "Missing call_id"}), 400

    # Get call record
    voice_call = get_voice_call(call_id)
    if not voice_call:
        logger.error(f"Voice call not found: {call_id}")
        return jsonify({"error": "Call not found"}), 404

    business_id = voice_call["business_id"]
    session_id = voice_call["session_id"]

    # Get the last user utterance
    last_utterance = None
    for item in reversed(transcript):
        if item.get("role") == "user":
            last_utterance = item.get("content", "")
            break

    if not last_utterance:
        # No user input yet, return empty response
        return jsonify({"response": ""})

    # Log user message
    log_message(session_id, "user", last_utterance)

    # Check for pending booking confirmation
    pending = get_voice_pending_booking(call_id)
    if pending:
        response_type = detect_booking_response(last_utterance)
        if response_type == "confirm":
            success, message, appt_id = confirm_voice_booking(call_id, business_id, session_id)
            if success:
                response = "Your booking has been confirmed! You'll receive a confirmation text shortly."
            else:
                response = f"I couldn't complete the booking: {message}. Would you like to try again?"
            log_message(session_id, "bot", response)
            return jsonify({"response": response})
        elif response_type == "cancel":
            cancel_voice_booking(call_id)
            response = "No problem, I've cancelled that booking. Is there anything else I can help you with?"
            log_message(session_id, "bot", response)
            return jsonify({"response": response})

    # Process through AI
    try:
        from core.ai import process_message_for_voice

        business_data = get_business_by_id(business_id)
        if not business_data:
            return jsonify({"error": "Business not found"}), 404

        state = {
            "session_id": session_id,
            "channel": "voice",
            "call_id": call_id,
        }

        # Get AI response with voice-optimized prompt
        ai_response = process_message_for_voice(
            user_input=last_utterance,
            business_data=business_data,
            state=state
        )

        # Check for booking in response
        cleaned_response, booking_data = extract_voice_booking(ai_response, call_id)

        if booking_data:
            update_voice_call(call_id, booking_discussed=1)

        # Log the response
        log_message(session_id, "bot", cleaned_response)

        return jsonify({"response": cleaned_response})

    except Exception as e:
        logger.error(f"Error processing voice response: {e}", exc_info=True)
        fallback = "I'm having a little trouble. Could you repeat that?"
        log_message(session_id, "bot", fallback)
        return jsonify({"response": fallback})


# ============================================================================
# Outbound Call Endpoint
# ============================================================================

@bp.route("/outbound", methods=["POST"])
def create_outbound():
    """Create an outbound voice call.

    Requires authentication and business access.

    Request body:
        {
            "to_number": "+14155551234",
            "purpose": "reminder",  // optional
            "metadata": {}  // optional
        }
    """
    # Check authentication
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    # Get active business
    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    to_number = data.get("to_number")
    if not to_number:
        return jsonify({"error": "to_number is required"}), 400

    purpose = data.get("purpose", "outreach")
    metadata = data.get("metadata", {})

    success, message, call_data = create_outbound_call(
        business_id=business_id,
        to_number=to_number,
        purpose=purpose,
        metadata=metadata
    )

    if success:
        return jsonify({
            "success": True,
            "message": message,
            "call": call_data
        })
    else:
        return jsonify({
            "success": False,
            "error": message
        }), 400


# ============================================================================
# Call Management Endpoints
# ============================================================================

@bp.route("/calls", methods=["GET"])
def list_calls():
    """List voice calls for the current business.

    Query params:
        limit: Max calls to return (default 50)
        status: Filter by status (optional)
    """
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    limit = request.args.get("limit", 50, type=int)
    status = request.args.get("status")

    with get_conn() as con:
        if status:
            rows = con.execute("""
                SELECT * FROM voice_calls
                WHERE business_id = ? AND call_status = ?
                ORDER BY created_at DESC LIMIT ?
            """, (business_id, status, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT * FROM voice_calls
                WHERE business_id = ?
                ORDER BY created_at DESC LIMIT ?
            """, (business_id, limit)).fetchall()

    return jsonify({
        "calls": [dict(r) for r in rows],
        "count": len(rows)
    })


@bp.route("/calls/<call_id>", methods=["GET"])
def get_call_details(call_id: str):
    """Get details of a specific voice call."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    business_id = g.get("active_business_id") or session.get("active_business_id")

    call = get_voice_call(call_id)
    if not call:
        return jsonify({"error": "Call not found"}), 404

    # Check business access
    if business_id and call["business_id"] != business_id:
        # Admin can access any call
        if user.get("role") != "admin":
            return jsonify({"error": "Access denied"}), 403

    # Get associated messages
    if call["session_id"]:
        with get_conn() as con:
            messages = con.execute("""
                SELECT sender, text, timestamp FROM messages
                WHERE session_id = ?
                ORDER BY id
            """, (call["session_id"],)).fetchall()
            call["messages"] = [dict(m) for m in messages]
    else:
        call["messages"] = []

    return jsonify(call)


@bp.route("/calls/<call_id>/transfer", methods=["POST"])
def transfer_call(call_id: str):
    """Transfer an active call to a human.

    Request body:
        {
            "transfer_number": "+14155559999",  // optional, uses default
            "reason": "customer requested"  // optional
        }
    """
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    call = get_voice_call(call_id)
    if not call:
        return jsonify({"error": "Call not found"}), 404

    if call["call_status"] != "ongoing":
        return jsonify({"error": "Call is not active"}), 400

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    # Get transfer number
    transfer_number = data.get("transfer_number")
    if not transfer_number:
        settings = get_voice_settings(call["business_id"])
        transfer_number = settings.get("transfer_number")

    if not transfer_number:
        return jsonify({"error": "No transfer number configured"}), 400

    reason = data.get("reason", "manual transfer")

    try:
        from core.voice import get_retell_client
        client = get_retell_client()

        # Request transfer via Retell API
        client.update_call(call_id, transfer_number=transfer_number)

        # Update call record
        update_voice_call(
            call_id,
            transferred=1,
            transfer_number=transfer_number,
            transfer_reason=reason
        )

        logger.info(f"Call {call_id} transferred to {transfer_number}")

        return jsonify({
            "success": True,
            "message": "Call transferred",
            "transfer_number": transfer_number
        })

    except RetellClientError as e:
        logger.error(f"Failed to transfer call: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Voice Settings Endpoints
# ============================================================================

@bp.route("/settings", methods=["GET"])
def get_settings():
    """Get voice settings for the current business."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    settings = get_voice_settings(business_id)
    return jsonify(settings)


@bp.route("/settings", methods=["POST"])
def update_settings():
    """Update voice settings for the current business."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    from core.voice import update_voice_settings

    if update_voice_settings(business_id, **data):
        return jsonify({"success": True, "message": "Settings updated"})
    else:
        return jsonify({"error": "Failed to update settings"}), 400


# ============================================================================
# Health & Configuration Check
# ============================================================================

@bp.route("/status", methods=["GET"])
def voice_status():
    """Check voice configuration status.

    Only accessible to authenticated users.
    """
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    business_id = g.get("active_business_id") or session.get("active_business_id")

    retell_configured = is_retell_configured()

    result = {
        "retell_configured": retell_configured,
        "webhook_url": request.url_root.rstrip("/") + "/api/voice/webhook",
    }

    if business_id:
        settings = get_voice_settings(business_id)
        result["business_configured"] = bool(
            settings.get("retell_agent_id") and settings.get("retell_phone_number")
        )
        result["has_agent"] = bool(settings.get("retell_agent_id"))
        result["has_phone"] = bool(settings.get("retell_phone_number"))

    return jsonify(result)


# ============================================================================
# Test Endpoint (Development Only)
# ============================================================================

@bp.route("/test", methods=["GET"])
def voice_test():
    """Test endpoint to verify voice configuration.

    Only accessible in development.
    """
    if os.getenv("APP_ENV", "dev").lower() in ("prod", "production"):
        return Response("Not available in production", status=404)

    return jsonify({
        "retell_configured": is_retell_configured(),
        "webhook_url": request.url_root.rstrip("/") + "/api/voice/webhook",
        "response_url": request.url_root.rstrip("/") + "/api/voice/webhook/response",
    })
