# voice_bp.py — Voice webhook handlers for LocusAI
# Handles incoming voice calls via Retell AI and routes to AI conversation flow

import logging
import os

from flask import Blueprint, Response, g, jsonify, request, session

from core.db import get_business_by_id, get_conn, log_message
from core.security import SecurityEvent, log_security_event
from core.voice import (
    RetellClientError,
    _get_business_by_phone,
    cancel_voice_booking,
    confirm_voice_booking,
    create_outbound_call,
    detect_booking_response,
    extract_voice_booking,
    get_caller_info,
    get_voice_call,
    get_voice_pending_booking,
    get_voice_settings,
    handle_call_analyzed,
    handle_call_ended,
    handle_call_started,
    is_retell_configured,
    update_voice_call,
    verify_retell_signature,
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
            details={"source": "retell", "path": request.path},
        )
        return False

    return True


# ============================================================================
# Inbound Dynamic Variables — Caller Recognition (fires before call is answered)
# ============================================================================


@bp.route("/call-setup", methods=["POST"])
def call_setup():
    """Called by Retell before an inbound call is answered.

    We return dynamic variables that get injected into the agent's prompt,
    enabling personalised greetings like "Hi Sarah, calling about your haircut?"

    Retell injects variables with {{var_name}} syntax in the LLM prompt.
    """
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({}), 200

    from_number = data.get("from_number") or data.get("caller_number", "")
    to_number = data.get("to_number") or data.get("called_number", "")

    # Look up the business by the called number. If we can't identify it (an
    # unknown/misconfigured number in a multi-tenant setup), return no dynamic
    # variables — the agent uses its generic greeting rather than us guessing a
    # business and leaking another tenant's caller recognition.
    business_id = _get_business_by_phone(to_number)
    if not business_id:
        logger.warning("call-setup: no business matched to_number=%s", to_number)
        return jsonify({"dynamic_variables": {}})

    # Build dynamic variables
    dynamic_vars = {}

    if from_number and business_id:
        customer = get_caller_info(business_id, from_number)
        if customer:
            dynamic_vars["caller_name"] = customer.get("name", "")
            dynamic_vars["caller_known"] = "true"
            dynamic_vars["caller_visit_count"] = str(customer.get("visit_count", 0))
            if customer.get("last_service"):
                dynamic_vars["caller_last_service"] = customer["last_service"]
            if customer.get("last_visit"):
                dynamic_vars["caller_last_visit"] = customer["last_visit"]
            logger.info(f"Caller recognised: {customer.get('name')} ({from_number})")
        else:
            dynamic_vars["caller_known"] = "false"
            dynamic_vars["caller_name"] = ""

    return jsonify({"dynamic_variables": dynamic_vars})


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
# Retell Custom Functions — real-time reschedule/cancel during native LLM calls
# ============================================================================
# The native Retell agent invokes these mid-call (registered as custom tools on
# the Retell LLM). Each returns a short JSON message the agent speaks back.


def _fn_context(data: dict):
    """Pull (business_id, caller_phone, args) from a Retell custom-function call.

    business_id is None when the called number can't be resolved to a business —
    callers MUST refuse rather than act on an arbitrary tenant's data (see
    _unresolved_business_response)."""
    call = data.get("call", {}) or {}
    from_number = call.get("from_number") or ""
    to_number = call.get("to_number") or ""
    business_id = _get_business_by_phone(to_number)
    args = data.get("args", {}) or data.get("arguments", {}) or {}
    return business_id, from_number, args


def _unresolved_business_response():
    """Spoken refusal when we can't tell which business a call is for. Better to
    take a message than to read back or modify the wrong tenant's appointments."""
    return jsonify(
        {
            "success": False,
            "message": (
                "I'm sorry, I'm having trouble accessing your details right now. "
                "Let me take a message and have someone call you straight back."
            ),
        }
    )


def _speak_dt(s: str) -> str:
    """Format '2026-06-15 14:30' as 'Monday 15 June at 2:30 PM' for the agent to read."""
    from datetime import datetime

    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return s
    return dt.strftime("%A %-d %B at %-I:%M %p")


@bp.route("/fn/find-appointments", methods=["POST"])
def fn_find_appointments():
    """Custom function: list the caller's upcoming appointments."""
    if not _verify_retell_request():
        return Response("Unauthorized", status=403)
    data = request.get_json(force=True, silent=True) or {}
    business_id, from_number, args = _fn_context(data)
    if business_id is None:
        return _unresolved_business_response()
    phone = (args.get("phone") or from_number or "").strip() or None

    from core.booking import voice_find_appointments

    appts = voice_find_appointments(business_id, phone)
    if not appts:
        return jsonify(
            {
                "success": True,
                "count": 0,
                "message": "I couldn't find any upcoming appointments under this number.",
            }
        )
    parts = [f"{a['service']} on {_speak_dt(a['start_at'])}" for a in appts[:3]]
    return jsonify(
        {
            "success": True,
            "count": len(appts),
            "appointments": [{"service": a["service"], "datetime": a["start_at"]} for a in appts],
            "message": "I found: " + "; ".join(parts) + ".",
        }
    )


@bp.route("/fn/cancel-appointment", methods=["POST"])
def fn_cancel_appointment():
    """Custom function: cancel the caller's appointment (after verbal confirmation)."""
    if not _verify_retell_request():
        return Response("Unauthorized", status=403)
    data = request.get_json(force=True, silent=True) or {}
    business_id, from_number, args = _fn_context(data)
    if business_id is None:
        return _unresolved_business_response()
    phone = (args.get("phone") or from_number or "").strip() or None

    from core.booking import voice_cancel_appointment

    ok, message = voice_cancel_appointment(
        business_id,
        phone=phone,
        service=args.get("service"),
        when=args.get("appointment_datetime") or args.get("datetime"),
    )
    logger.info(f"Voice cancel (business {business_id}, {phone}): ok={ok}")
    return jsonify({"success": ok, "message": message})


@bp.route("/fn/reschedule-appointment", methods=["POST"])
def fn_reschedule_appointment():
    """Custom function: move the caller's appointment to a new time."""
    if not _verify_retell_request():
        return Response("Unauthorized", status=403)
    data = request.get_json(force=True, silent=True) or {}
    business_id, from_number, args = _fn_context(data)
    if business_id is None:
        return _unresolved_business_response()
    phone = (args.get("phone") or from_number or "").strip() or None

    from core.booking import voice_reschedule_appointment

    ok, message = voice_reschedule_appointment(
        business_id,
        new_datetime=args.get("new_datetime") or args.get("new_appointment_datetime"),
        phone=phone,
        service=args.get("service"),
        old_when=args.get("current_datetime") or args.get("appointment_datetime"),
    )
    logger.info(f"Voice reschedule (business {business_id}, {phone}): ok={ok}")
    return jsonify({"success": ok, "message": message})


@bp.route("/fn/transfer", methods=["POST"])
def fn_transfer():
    """Custom function: warm-transfer the caller to a human.

    The agent calls this when the caller asks for a person or hits something the
    AI can't resolve. We record the transfer + reason, generate a short briefing
    for the human, and return the destination number for Retell to dial. If no
    transfer number is configured, we tell the agent to take a message instead.
    """
    if not _verify_retell_request():
        return Response("Unauthorized", status=403)
    data = request.get_json(force=True, silent=True) or {}
    call = data.get("call", {}) or {}
    call_id = call.get("call_id")
    business_id, from_number, args = _fn_context(data)
    if business_id is None:
        return _unresolved_business_response()
    reason = (args.get("reason") or "Caller requested a human").strip()

    settings = get_voice_settings(business_id) or {}
    transfer_number = settings.get("transfer_number")
    if not settings.get("transfer_enabled") or not transfer_number:
        return jsonify(
            {
                "success": False,
                "transfer": False,
                "message": (
                    "I'm not able to transfer you right now, but I can take a "
                    "detailed message and have someone call you straight back."
                ),
            }
        )

    # Build a spoken briefing for the human who picks up.
    briefing = ""
    try:
        from core.voice import generate_transfer_briefing

        vc = get_voice_call(call_id) if call_id else None
        transcript = (vc or {}).get("transcript") or ""
        caller_name = args.get("caller_name") or (vc or {}).get("customer_name")
        briefing = generate_transfer_briefing(transcript, caller_name)
    except Exception:
        logger.debug("transfer briefing skipped", exc_info=True)

    if call_id:
        try:
            update_voice_call(
                call_id,
                transferred=1,
                transfer_number=transfer_number,
                transfer_reason=reason,
                call_status="transferred",
                call_outcome="escalated",
            )
        except Exception:
            logger.warning("Could not mark call %s transferred", call_id)

    logger.info(f"Voice transfer (business {business_id}, {from_number}): {reason}")
    return jsonify(
        {
            "success": True,
            "transfer": True,
            "transfer_number": transfer_number,
            "briefing": briefing,
            "message": "Of course — connecting you to a member of the team now.",
        }
    )


# ============================================================================
# Live Call Monitor — ongoing calls feed for the dashboard
# ============================================================================


@bp.route("/live", methods=["GET"])
def live_calls():
    """JSON feed of in-progress calls for the live monitor page (polled)."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401
    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        return jsonify({"calls": []})

    with get_conn() as con:
        rows = con.execute(
            """SELECT v.retell_call_id, v.from_number, c.name AS customer_name,
                      v.call_status, v.started_at, v.transcript, v.duration_seconds
               FROM voice_calls v
               LEFT JOIN customers c ON c.id = v.customer_id
               WHERE v.business_id = ?
                 AND v.call_status IN ('ongoing','registered','transferred')
               ORDER BY datetime(COALESCE(v.started_at, v.created_at)) DESC
               LIMIT 25""",
            (business_id,),
        ).fetchall()
    calls = []
    for r in rows:
        d = dict(r)
        # Send only the tail of the transcript to keep payloads light.
        t = d.get("transcript") or ""
        d["transcript_tail"] = t[-1200:]
        d.pop("transcript", None)
        calls.append(d)
    return jsonify({"calls": calls})


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
                response = (
                    "Your booking has been confirmed! You'll receive a confirmation text shortly."
                )
            else:
                response = (
                    f"I couldn't complete the booking: {message}. Would you like to try again?"
                )
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
            user_input=last_utterance, business_data=business_data, state=state
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
        business_id=business_id, to_number=to_number, purpose=purpose, metadata=metadata
    )

    if success:
        return jsonify({"success": True, "message": message, "call": call_data})
    else:
        return jsonify({"success": False, "error": message}), 400


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
            rows = con.execute(
                """
                SELECT * FROM voice_calls
                WHERE business_id = ? AND call_status = ?
                ORDER BY created_at DESC LIMIT ?
            """,
                (business_id, status, limit),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT * FROM voice_calls
                WHERE business_id = ?
                ORDER BY created_at DESC LIMIT ?
            """,
                (business_id, limit),
            ).fetchall()

    return jsonify({"calls": [dict(r) for r in rows], "count": len(rows)})


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
            messages = con.execute(
                """
                SELECT sender, text, timestamp FROM messages
                WHERE session_id = ?
                ORDER BY id
            """,
                (call["session_id"],),
            ).fetchall()
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
            call_id, transferred=1, transfer_number=transfer_number, transfer_reason=reason
        )

        logger.info(f"Call {call_id} transferred to {transfer_number}")

        return jsonify(
            {"success": True, "message": "Call transferred", "transfer_number": transfer_number}
        )

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
# Prompt Sync — push live KB/services/hours to Retell native LLM
# ============================================================================


@bp.route("/sync-calls", methods=["POST"])
def sync_calls():
    """Pull recent calls from Retell API and store them in the local DB.

    Quick fix for when webhooks can't reach the local server.
    Safe to call repeatedly — skips calls already stored.
    """
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    from core.voice import sync_calls_from_retell

    success, message = sync_calls_from_retell(business_id)

    if success:
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "error": message}), 500


@bp.route("/sync-prompt", methods=["POST"])
def sync_prompt():
    """Sync the business KB, services, and hours to the Retell voice agent prompt.

    This keeps the native Retell LLM (no added latency) while giving it
    up-to-date knowledge of services, hours, and FAQs from the database.
    """
    user = session.get("user")
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    from core.voice import sync_retell_prompt

    # Pass the current server URL so caller-recognition webhook can be auto-configured
    webhook_base_url = request.url_root.rstrip("/")
    success, message = sync_retell_prompt(business_id, webhook_base_url=webhook_base_url)

    if success:
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "error": message}), 500


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

    return jsonify(
        {
            "retell_configured": is_retell_configured(),
            "webhook_url": request.url_root.rstrip("/") + "/api/voice/webhook",
            "response_url": request.url_root.rstrip("/") + "/api/voice/webhook/response",
        }
    )
