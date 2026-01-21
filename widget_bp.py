# widget_bp.py — Embeddable chat widget API endpoints
# Production-grade with CORS, rate limiting, and tenant authentication

import json
import logging
import time
from functools import wraps
from typing import Optional, Dict, Any

from flask import Blueprint, request, jsonify, render_template, g

from core.db import (
    get_conn, get_business_by_id, create_session,
    log_message, get_session_messages, transaction
)
from core.ai import process_message
from core.booking import (
    extract_pending_booking,
    confirm_pending_booking,
    cancel_pending_booking,
    maybe_commit_booking,  # Keep for backward compatibility
)

logger = logging.getLogger(__name__)

bp = Blueprint("widget", __name__, url_prefix="/api/widget")

# Simple in-memory rate limiter (use Redis in production for multi-instance)
_RATE_LIMITS: Dict[str, list] = {}
RATE_LIMIT_REQUESTS = 30  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds


# ============================================================================
# Helpers
# ============================================================================

def _get_business_by_tenant_key(tenant_key: str) -> Optional[Dict[str, Any]]:
    """Look up a business by its tenant key."""
    if not tenant_key:
        return None
    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM businesses WHERE tenant_key = ? AND archived = 0",
            (tenant_key,)
        ).fetchone()
        return dict(row) if row else None


def _get_widget_settings(business_id: int) -> Dict[str, Any]:
    """Get widget settings for a business, with defaults."""
    defaults = {
        "enabled": 1,
        "position": "bottom-right",
        "primary_color": None,
        "welcome_message": "Hi! How can I help you today?",
        "placeholder_text": "Type a message...",
        "allowed_domains": None,
        "show_branding": 1,
        "auto_open_delay": None,
    }

    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM widget_settings WHERE business_id = ?",
            (business_id,)
        ).fetchone()

        if row:
            settings = dict(row)
            # Merge with defaults for any missing keys
            for key, value in defaults.items():
                if key not in settings or settings[key] is None:
                    settings[key] = value
            return settings

        return {**defaults, "business_id": business_id}


def _check_origin(settings: Dict, origin: str) -> bool:
    """Check if the request origin is allowed.

    SECURITY: Defaults to DENY if no allowed_domains configured.
    This prevents open CORS vulnerabilities.
    """
    allowed = settings.get("allowed_domains")

    # SECURITY: Default to DENY if not explicitly configured
    if not allowed:
        logger.warning(f"Widget CORS: No allowed_domains configured, denying origin: {origin}")
        return False

    try:
        domains = json.loads(allowed) if isinstance(allowed, str) else allowed

        # Empty list means deny all
        if not domains:
            logger.warning(f"Widget CORS: Empty allowed_domains list, denying origin: {origin}")
            return False

        # Wildcard explicitly allows all origins (must be intentional)
        if "*" in domains:
            return True

        # Extract hostname from origin
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        hostname = parsed.netloc.split(":")[0]  # Remove port

        is_allowed = hostname in domains or origin in domains
        if not is_allowed:
            logger.warning(f"Widget CORS: Origin {origin} not in allowed list: {domains}")
        return is_allowed

    except (json.JSONDecodeError, Exception) as e:
        # SECURITY: Deny on parsing errors
        logger.error(f"Widget CORS: Error parsing allowed_domains, denying: {e}")
        return False


def _rate_limit_check(key: str) -> bool:
    """Check if request should be rate limited. Returns True if allowed."""
    now = time.time()

    if key not in _RATE_LIMITS:
        _RATE_LIMITS[key] = []

    # Clean old entries
    _RATE_LIMITS[key] = [t for t in _RATE_LIMITS[key] if t > now - RATE_LIMIT_WINDOW]

    if len(_RATE_LIMITS[key]) >= RATE_LIMIT_REQUESTS:
        return False

    _RATE_LIMITS[key].append(now)
    return True


def _validate_cors_origin(origin: str, tenant_key: str) -> str:
    """Validate origin against widget settings. Returns origin if valid, None otherwise."""
    if not origin:
        return None

    if not tenant_key:
        return None

    business = _get_business_by_tenant_key(tenant_key)
    if not business:
        return None

    settings = _get_widget_settings(business["id"])
    if _check_origin(settings, origin):
        return origin

    return None


def cors_headers(f):
    """Decorator to add CORS headers to responses.

    Only reflects Origin if it passes validation against allowed_domains.
    Falls back to not setting CORS headers if origin is invalid.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Get origin and tenant key from request
        origin = request.headers.get("Origin", "")
        tenant_key = request.headers.get("X-Tenant-Key") or request.args.get("tenant_key")

        # Validate origin against widget settings
        validated_origin = _validate_cors_origin(origin, tenant_key)

        # Handle preflight
        if request.method == "OPTIONS":
            response = jsonify({"status": "ok"})
            if validated_origin:
                response.headers["Access-Control-Allow-Origin"] = validated_origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Tenant-Key, X-Session-ID"
            response.headers["Access-Control-Max-Age"] = "86400"
            return response

        # Call the actual function
        result = f(*args, **kwargs)

        # Add CORS headers to response only if origin is validated
        if hasattr(result, "headers") and validated_origin:
            result.headers["Access-Control-Allow-Origin"] = validated_origin
            result.headers["Access-Control-Allow-Credentials"] = "true"

        return result

    return decorated


def require_tenant(f):
    """Decorator to require and validate tenant key."""
    @wraps(f)
    def decorated(*args, **kwargs):
        tenant_key = request.headers.get("X-Tenant-Key") or request.args.get("tenant_key")

        if not tenant_key:
            return jsonify({"error": "Missing tenant key"}), 401

        business = _get_business_by_tenant_key(tenant_key)
        if not business:
            return jsonify({"error": "Invalid tenant key"}), 401

        settings = _get_widget_settings(business["id"])
        if not settings.get("enabled"):
            return jsonify({"error": "Widget is disabled"}), 403

        # Check origin
        origin = request.headers.get("Origin", "")
        if not _check_origin(settings, origin):
            return jsonify({"error": "Origin not allowed"}), 403

        # Rate limiting by tenant + IP
        rate_key = f"{tenant_key}:{request.remote_addr}"
        if not _rate_limit_check(rate_key):
            return jsonify({"error": "Rate limit exceeded"}), 429

        # Store in g for route access
        g.business = business
        g.widget_settings = settings

        return f(*args, **kwargs)

    return decorated


# ============================================================================
# Widget Configuration Endpoint
# ============================================================================

@bp.route("/config", methods=["GET", "OPTIONS"])
@cors_headers
@require_tenant
def widget_config():
    """Get widget configuration for initialization."""
    business = g.business
    settings = g.widget_settings

    return jsonify({
        "business": {
            "name": business.get("name"),
            "accent_color": business.get("accent_color") or settings.get("primary_color") or "#2f6fec",
        },
        "widget": {
            "position": settings.get("position", "bottom-right"),
            "welcome_message": settings.get("welcome_message"),
            "placeholder_text": settings.get("placeholder_text"),
            "show_branding": bool(settings.get("show_branding", 1)),
            "auto_open_delay": settings.get("auto_open_delay"),
        }
    })


# ============================================================================
# Chat Session Endpoints
# ============================================================================

@bp.route("/session", methods=["POST", "OPTIONS"])
@cors_headers
@require_tenant
def create_widget_session():
    """Create a new chat session for the widget."""
    business = g.business

    session_id = create_session(business["id"])

    # Get welcome message
    settings = g.widget_settings
    welcome = settings.get("welcome_message", "Hi! How can I help you today?")

    # Log the welcome message as first bot message
    if welcome:
        log_message(session_id, "bot", welcome)

    return jsonify({
        "session_id": session_id,
        "welcome_message": welcome
    })


@bp.route("/chat", methods=["POST", "OPTIONS"])
@cors_headers
@require_tenant
def widget_chat():
    """Send a message and get AI response.

    Response includes:
    - reply: The AI's text response
    - pending_booking: If AI suggested a booking, contains details for user to confirm
      - token: Unique token to confirm/cancel this booking
      - customer_name, phone, email, service, datetime: Booking details
      - expires_in: Seconds until this pending booking expires
    """
    business = g.business

    # Get session ID
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "Missing session ID"}), 400

    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid session ID"}), 400

    # Verify session belongs to this business
    with get_conn() as con:
        row = con.execute(
            "SELECT business_id FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()

        if not row or row["business_id"] != business["id"]:
            return jsonify({"error": "Invalid session"}), 403

    # Get message from request
    data = request.get_json(silent=True) or {}
    user_text = (data.get("message") or "").strip()

    if not user_text:
        return jsonify({"error": "Message required"}), 400

    if len(user_text) > 2000:
        return jsonify({"error": "Message too long"}), 400

    # Log user message
    log_message(session_id, "user", user_text)

    # Get AI response
    pending_booking = None
    try:
        state = {"session_id": session_id}
        reply = process_message(user_text, business, state)
        reply = (reply or "").strip()

        # Extract booking data WITHOUT auto-committing
        # User must explicitly confirm before booking is saved
        reply, pending_booking = extract_pending_booking(reply, business, session_id)

    except Exception as e:
        logger.error(f"Widget chat error: {e}")
        reply = "I'm having a little trouble right now. Could I take your name and number so we can call you back?"

    # Log bot response
    log_message(session_id, "bot", reply)

    response = {"reply": reply}

    # Include pending booking data if AI suggested a booking
    if pending_booking:
        response["pending_booking"] = pending_booking
        logger.info(f"Pending booking returned to widget for session {session_id}")

    return jsonify(response)


# ============================================================================
# Booking Confirmation Endpoints
# ============================================================================

@bp.route("/booking/confirm", methods=["POST", "OPTIONS"])
@cors_headers
@require_tenant
def confirm_booking():
    """Confirm a pending booking.

    Request body:
        - token: The pending booking token from the chat response

    Response:
        - success: Boolean indicating if booking was confirmed
        - message: Confirmation message or error description
        - appointment_id: ID of the created appointment (if successful)
    """
    business = g.business

    # Get session ID for logging
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")

    # Get token from request
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()

    if not token:
        return jsonify({
            "success": False,
            "message": "Missing booking token"
        }), 400

    # Confirm the booking
    success, message, appointment_id = confirm_pending_booking(token)

    if success:
        # Log the confirmation message
        if session_id:
            try:
                log_message(int(session_id), "bot", f"✅ {message}")
            except (ValueError, TypeError):
                pass

        logger.info(f"Booking confirmed via widget: appointment {appointment_id}")
        return jsonify({
            "success": True,
            "message": message,
            "appointment_id": appointment_id
        })
    else:
        logger.warning(f"Booking confirmation failed: {message}")
        return jsonify({
            "success": False,
            "message": message
        }), 400


@bp.route("/booking/cancel", methods=["POST", "OPTIONS"])
@cors_headers
@require_tenant
def cancel_booking():
    """Cancel a pending booking (before confirmation).

    Request body:
        - token: The pending booking token from the chat response

    Response:
        - success: Boolean indicating if cancellation was processed
        - message: Status message
    """
    business = g.business

    # Get session ID for logging
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")

    # Get token from request
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()

    if not token:
        return jsonify({
            "success": False,
            "message": "Missing booking token"
        }), 400

    # Cancel the pending booking
    success, message = cancel_pending_booking(token)

    if success:
        # Log the cancellation
        if session_id:
            try:
                log_message(int(session_id), "bot", message)
            except (ValueError, TypeError):
                pass

        logger.info(f"Pending booking cancelled via widget")

    return jsonify({
        "success": success,
        "message": message
    })


@bp.route("/history", methods=["GET", "OPTIONS"])
@cors_headers
@require_tenant
def widget_history():
    """Get chat history for a session."""
    business = g.business

    session_id = request.headers.get("X-Session-ID") or request.args.get("session_id")

    if not session_id:
        return jsonify({"error": "Missing session ID"}), 400

    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid session ID"}), 400

    # Verify session
    with get_conn() as con:
        row = con.execute(
            "SELECT business_id FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()

        if not row or row["business_id"] != business["id"]:
            return jsonify({"error": "Invalid session"}), 403

    # Get messages
    rows = get_session_messages(session_id, limit=50)
    messages = [
        {
            "role": "assistant" if r["sender"] == "bot" else "user",
            "text": r["text"],
            "timestamp": r["timestamp"]
        }
        for r in reversed(rows)  # Oldest first
    ]

    return jsonify({"messages": messages})


# ============================================================================
# Widget Frame (for iframe embedding)
# ============================================================================

@bp.route("/frame")
def widget_frame():
    """Serve the widget iframe content."""
    tenant_key = request.args.get("tenant_key")

    if not tenant_key:
        return "Missing tenant key", 400

    business = _get_business_by_tenant_key(tenant_key)
    if not business:
        return "Invalid tenant key", 401

    settings = _get_widget_settings(business["id"])
    if not settings.get("enabled"):
        return "Widget disabled", 403

    return render_template(
        "widget_frame.html",
        business=business,
        settings=settings,
        tenant_key=tenant_key
    )


# ============================================================================
# Widget Settings Management (Dashboard)
# ============================================================================

def get_or_create_widget_settings(business_id: int) -> Dict[str, Any]:
    """Get or create widget settings for a business."""
    settings = _get_widget_settings(business_id)

    # Ensure record exists in DB
    with transaction() as con:
        existing = con.execute(
            "SELECT 1 FROM widget_settings WHERE business_id = ?",
            (business_id,)
        ).fetchone()

        if not existing:
            con.execute("""
                INSERT INTO widget_settings (business_id, enabled, position, welcome_message, placeholder_text, show_branding)
                VALUES (?, 1, 'bottom-right', 'Hi! How can I help you today?', 'Type a message...', 1)
            """, (business_id,))

    return settings


def update_widget_settings(business_id: int, **fields) -> bool:
    """Update widget settings for a business."""
    allowed = {"enabled", "position", "primary_color", "welcome_message",
               "placeholder_text", "allowed_domains", "show_branding", "auto_open_delay"}

    safe_fields = {k: v for k, v in fields.items() if k in allowed}
    if not safe_fields:
        return False

    # Ensure record exists
    get_or_create_widget_settings(business_id)

    cols = [f"{k} = ?" for k in safe_fields.keys()]
    vals = list(safe_fields.values()) + [business_id]

    try:
        with transaction() as con:
            con.execute(
                f"UPDATE widget_settings SET {', '.join(cols)}, updated_at = datetime('now') WHERE business_id = ?",
                tuple(vals)
            )
        return True
    except Exception as e:
        logger.error(f"Failed to update widget settings: {e}")
        return False
