# core/voice.py — Voice call management with Retell AI integration
# Handles inbound/outbound calls, transcripts, and voice booking confirmation

import os
import re
import json
import hmac
import hashlib
import logging
import time
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from threading import Lock

from core.settings import (
    RETELL_API_KEY,
    RETELL_WEBHOOK_SECRET,
    RETELL_DEFAULT_AGENT_ID,
    VOICE_TRANSFER_TIMEOUT,
    VOICE_MAX_DURATION,
    VOICE_RECORDING_ENABLED,
)
from core.circuit_breaker import CircuitBreaker, CircuitState

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================

RETELL_BASE_URL = "https://api.retellai.com"
RETELL_API_VERSION = "v2"

# Voice booking confirmation patterns
VOICE_CONFIRM_PATTERNS = [
    r'\b(yes|yeah|yep|yup|sure|okay|ok|confirm|book it|go ahead|sounds good|perfect|great|please do|do it)\b',
    r'\b(that works|that\'s fine|absolutely|definitely|correct)\b',
]

VOICE_CANCEL_PATTERNS = [
    r'\b(no|nope|cancel|nevermind|never mind|forget it|wait|hold on|stop)\b',
    r'\b(different time|change|reschedule|not that|wrong)\b',
]

# Compile patterns for performance
_CONFIRM_RE = re.compile('|'.join(VOICE_CONFIRM_PATTERNS), re.IGNORECASE)
_CANCEL_RE = re.compile('|'.join(VOICE_CANCEL_PATTERNS), re.IGNORECASE)

# ============================================================================
# Circuit Breaker for Voice
# ============================================================================

_voice_circuit_breaker: Optional[CircuitBreaker] = None
_voice_breaker_lock = Lock()


def get_voice_circuit_breaker() -> CircuitBreaker:
    """Get the singleton circuit breaker for voice/Retell API calls.

    Uses slightly different settings than AI:
    - Lower threshold (3 failures) - voice is more critical
    - Longer recovery (120s) - give Retell more time to recover
    """
    global _voice_circuit_breaker
    with _voice_breaker_lock:
        if _voice_circuit_breaker is None:
            _voice_circuit_breaker = CircuitBreaker(
                failure_threshold=3,
                recovery_timeout=120,
                half_open_requests=1
            )
        return _voice_circuit_breaker


# ============================================================================
# Retell API Client
# ============================================================================

class RetellClientError(Exception):
    """Error from Retell API."""
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[Dict] = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(message)


class RetellClient:
    """HTTP client for Retell AI API with circuit breaker protection.

    Usage:
        client = get_retell_client()
        call = client.create_phone_call(
            from_number="+14155551234",
            to_number="+14155555678",
            agent_id="agent_xyz",
            metadata={"business_id": 1}
        )
    """

    def __init__(self, api_key: str, base_url: str = RETELL_BASE_URL):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self._breaker = get_voice_circuit_breaker()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict:
        """Make an API request with circuit breaker protection."""
        import urllib.request
        import urllib.error

        # Check circuit breaker
        if self._breaker.is_open("retell:api"):
            raise RetellClientError("Retell API circuit breaker is open", status_code=503)

        url = f"{self.base_url}/{RETELL_API_VERSION}/{endpoint.lstrip('/')}"

        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body = json.dumps(data).encode('utf-8') if data else None

        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers=headers,
                method=method.upper()
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                self._breaker.record_success("retell:api")
                response_body = resp.read().decode('utf-8')
                return json.loads(response_body) if response_body else {}

        except urllib.error.HTTPError as e:
            self._breaker.record_failure("retell:api", str(e))
            error_body = e.read().decode('utf-8') if e.fp else ""
            try:
                error_data = json.loads(error_body)
            except json.JSONDecodeError:
                error_data = {"raw": error_body}
            raise RetellClientError(
                f"Retell API error: {e.code}",
                status_code=e.code,
                response=error_data
            )
        except urllib.error.URLError as e:
            self._breaker.record_failure("retell:api", str(e))
            raise RetellClientError(f"Network error: {e.reason}")
        except Exception as e:
            self._breaker.record_failure("retell:api", str(e))
            raise RetellClientError(f"Unexpected error: {e}")

    def create_phone_call(
        self,
        from_number: str,
        to_number: str,
        agent_id: str,
        metadata: Optional[Dict] = None,
        retell_llm_dynamic_variables: Optional[Dict] = None
    ) -> Dict:
        """Create an outbound phone call.

        Args:
            from_number: Caller ID (must be a Retell number)
            to_number: Number to call (E.164 format)
            agent_id: Retell agent ID
            metadata: Custom metadata (e.g., business_id)
            retell_llm_dynamic_variables: Variables to inject into prompts

        Returns:
            Call object with call_id, status, etc.
        """
        data = {
            "from_number": from_number,
            "to_number": to_number,
            "agent_id": agent_id,
        }
        if metadata:
            data["metadata"] = metadata
        if retell_llm_dynamic_variables:
            data["retell_llm_dynamic_variables"] = retell_llm_dynamic_variables

        return self._make_request("POST", "create-phone-call", data=data)

    def create_web_call(
        self,
        agent_id: str,
        metadata: Optional[Dict] = None,
        retell_llm_dynamic_variables: Optional[Dict] = None
    ) -> Dict:
        """Create a web call (browser-based).

        Returns:
            Call object with access_token for WebSocket connection
        """
        data = {"agent_id": agent_id}
        if metadata:
            data["metadata"] = metadata
        if retell_llm_dynamic_variables:
            data["retell_llm_dynamic_variables"] = retell_llm_dynamic_variables

        return self._make_request("POST", "create-web-call", data=data)

    def get_call(self, call_id: str) -> Dict:
        """Get call details by ID."""
        return self._make_request("GET", f"get-call/{call_id}")

    def list_calls(
        self,
        agent_id: Optional[str] = None,
        limit: int = 50,
        sort_order: str = "descending"
    ) -> List[Dict]:
        """List calls, optionally filtered by agent."""
        params = {"limit": limit, "sort_order": sort_order}
        if agent_id:
            params["agent_id"] = agent_id
        result = self._make_request("GET", "list-calls", params=params)
        return result.get("calls", [])

    def update_call(self, call_id: str, **updates) -> Dict:
        """Update a call (e.g., to transfer)."""
        return self._make_request("PATCH", f"update-call/{call_id}", data=updates)

    def end_call(self, call_id: str) -> Dict:
        """End an active call."""
        return self._make_request("POST", f"end-call/{call_id}")


# Singleton client
_retell_client: Optional[RetellClient] = None
_client_lock = Lock()


def get_retell_client() -> RetellClient:
    """Get the singleton Retell client."""
    global _retell_client
    with _client_lock:
        if _retell_client is None:
            if not RETELL_API_KEY:
                raise RetellClientError("RETELL_API_KEY not configured")
            _retell_client = RetellClient(RETELL_API_KEY)
        return _retell_client


def is_retell_configured() -> bool:
    """Check if Retell is properly configured."""
    return bool(RETELL_API_KEY)


# ============================================================================
# Webhook Signature Verification
# ============================================================================

def verify_retell_signature(payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
    """Verify Retell webhook signature using HMAC-SHA256.

    Args:
        payload: Raw request body bytes
        signature: X-Retell-Signature header value
        secret: Webhook secret (defaults to RETELL_WEBHOOK_SECRET)

    Returns:
        True if signature is valid
    """
    secret = secret or RETELL_WEBHOOK_SECRET

    if not secret:
        logger.warning("RETELL_WEBHOOK_SECRET not configured, skipping verification")
        return True  # Allow in dev, but log warning

    if not signature:
        return False

    try:
        expected = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False


# ============================================================================
# Voice Session Management
# ============================================================================

def get_or_create_voice_session(
    business_id: int,
    phone_number: str,
    call_id: str
) -> int:
    """Get existing voice session or create new one.

    Reuses sessions from same phone number within 24 hours.

    Args:
        business_id: Business receiving the call
        phone_number: Caller's phone number
        call_id: Retell call ID

    Returns:
        Session ID
    """
    from core.db import get_conn, transaction

    # Look for recent session from same number
    with get_conn() as con:
        row = con.execute("""
            SELECT id FROM sessions
            WHERE business_id = ? AND phone = ? AND channel = 'voice'
              AND datetime(created_at) > datetime('now', '-24 hours')
            ORDER BY created_at DESC LIMIT 1
        """, (business_id, phone_number)).fetchone()

        if row:
            logger.debug(f"Reusing voice session {row['id']} for {phone_number}")
            return row["id"]

    # Create new session
    with transaction() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO sessions(business_id, channel, phone) VALUES(?, 'voice', ?)",
            (business_id, phone_number)
        )
        session_id = cur.lastrowid
        logger.info(f"Created new voice session {session_id} for business {business_id}")
        return session_id


def create_voice_call_record(
    business_id: int,
    session_id: int,
    retell_call_id: str,
    direction: str,
    from_number: str,
    to_number: str,
    retell_agent_id: Optional[str] = None
) -> int:
    """Create a voice_calls record for tracking.

    Returns:
        voice_calls.id
    """
    from core.db import transaction

    with transaction() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO voice_calls(
                business_id, session_id, retell_call_id, retell_agent_id,
                direction, from_number, to_number, call_status, started_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 'ongoing', datetime('now'))
        """, (
            business_id, session_id, retell_call_id, retell_agent_id,
            direction, from_number, to_number
        ))
        return cur.lastrowid


def update_voice_call(retell_call_id: str, **fields) -> bool:
    """Update a voice call record."""
    from core.db import transaction

    allowed = {
        "call_status", "ended_at", "duration_seconds", "transcript",
        "transcript_json", "call_summary", "sentiment", "recording_url",
        "recording_duration_seconds", "booking_discussed", "booking_confirmed",
        "appointment_id", "transferred", "transfer_number", "transfer_reason",
        "cost_cents", "customer_id"
    }

    safe_fields = {k: v for k, v in fields.items() if k in allowed}
    if not safe_fields:
        return False

    safe_fields["updated_at"] = datetime.now().isoformat()

    cols = [f"{k}=?" for k in safe_fields.keys()]
    vals = list(safe_fields.values())
    vals.append(retell_call_id)

    try:
        with transaction() as con:
            con.execute(
                f"UPDATE voice_calls SET {', '.join(cols)} WHERE retell_call_id=?",
                tuple(vals)
            )
        return True
    except Exception as e:
        logger.error(f"Failed to update voice call {retell_call_id}: {e}")
        return False


def get_voice_call(retell_call_id: str) -> Optional[Dict]:
    """Get voice call record by Retell call ID."""
    from core.db import get_conn

    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM voice_calls WHERE retell_call_id = ?",
            (retell_call_id,)
        ).fetchone()
        return dict(row) if row else None


# ============================================================================
# Voice Settings
# ============================================================================

def get_voice_settings(business_id: int) -> Dict:
    """Get voice settings for a business, with defaults."""
    from core.db import get_conn

    defaults = {
        "business_id": business_id,
        "retell_agent_id": RETELL_DEFAULT_AGENT_ID,
        "retell_phone_number": None,
        "voice_id": "default",
        "voice_speed": 1.0,
        "voice_pitch": 1.0,
        "greeting_message": "Hello! Thank you for calling. How can I help you today?",
        "transfer_message": "Let me connect you with a team member.",
        "voicemail_message": None,
        "transfer_enabled": True,
        "transfer_number": None,
        "transfer_after_seconds": VOICE_TRANSFER_TIMEOUT,
        "after_hours_enabled": True,
        "after_hours_message": None,
        "after_hours_voicemail": True,
        "recording_enabled": VOICE_RECORDING_ENABLED,
        "transcript_enabled": True,
        "booking_enabled": True,
        "booking_confirmation_required": True,
    }

    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM voice_settings WHERE business_id = ?",
            (business_id,)
        ).fetchone()

        if row:
            settings = dict(row)
            # Apply defaults for missing values
            for key, value in defaults.items():
                if key not in settings or settings[key] is None:
                    settings[key] = value
            # Convert integers to bools
            for bool_key in ["transfer_enabled", "after_hours_enabled", "after_hours_voicemail",
                           "recording_enabled", "transcript_enabled", "booking_enabled",
                           "booking_confirmation_required"]:
                if bool_key in settings:
                    settings[bool_key] = bool(settings[bool_key])
            return settings

        return defaults


def update_voice_settings(business_id: int, **fields) -> bool:
    """Update voice settings for a business (upsert)."""
    from core.db import transaction

    allowed = {
        "retell_agent_id", "retell_phone_number", "voice_id",
        "voice_speed", "voice_pitch", "greeting_message",
        "transfer_message", "voicemail_message", "transfer_enabled",
        "transfer_number", "transfer_after_seconds",
        "after_hours_enabled", "after_hours_message", "after_hours_voicemail",
        "recording_enabled", "transcript_enabled",
        "booking_enabled", "booking_confirmation_required"
    }

    safe_fields = {k: v for k, v in fields.items() if k in allowed}
    if not safe_fields:
        return False

    try:
        with transaction() as con:
            # Check if exists
            exists = con.execute(
                "SELECT 1 FROM voice_settings WHERE business_id = ?",
                (business_id,)
            ).fetchone()

            if exists:
                # Update
                cols = [f"{k}=?" for k in safe_fields.keys()]
                cols.append("updated_at=datetime('now')")
                vals = list(safe_fields.values()) + [business_id]
                con.execute(
                    f"UPDATE voice_settings SET {', '.join(cols)} WHERE business_id=?",
                    tuple(vals)
                )
            else:
                # Insert
                safe_fields["business_id"] = business_id
                cols = list(safe_fields.keys())
                placeholders = ["?" for _ in cols]
                vals = list(safe_fields.values())
                con.execute(
                    f"INSERT INTO voice_settings({', '.join(cols)}) VALUES({', '.join(placeholders)})",
                    tuple(vals)
                )
        return True
    except Exception as e:
        logger.error(f"Failed to update voice settings for business {business_id}: {e}")
        return False


# ============================================================================
# Voice Booking Confirmation
# ============================================================================

# In-memory storage for pending voice bookings (per call)
_VOICE_PENDING_BOOKINGS: Dict[str, Dict] = {}
_booking_lock = Lock()


def store_voice_pending_booking(call_id: str, booking_data: Dict) -> None:
    """Store a pending booking for voice confirmation.

    Args:
        call_id: Retell call ID
        booking_data: Booking details (name, phone, service, datetime, etc.)
    """
    with _booking_lock:
        _VOICE_PENDING_BOOKINGS[call_id] = {
            **booking_data,
            "created_at": time.time(),
            "call_id": call_id,
        }
    logger.info(f"Stored pending voice booking for call {call_id}")


def get_voice_pending_booking(call_id: str) -> Optional[Dict]:
    """Get pending booking for a call."""
    with _booking_lock:
        return _VOICE_PENDING_BOOKINGS.get(call_id)


def clear_voice_pending_booking(call_id: str) -> Optional[Dict]:
    """Clear and return pending booking for a call."""
    with _booking_lock:
        return _VOICE_PENDING_BOOKINGS.pop(call_id, None)


def extract_voice_booking(ai_response: str, call_id: str) -> Tuple[str, Optional[Dict]]:
    """Extract booking details from AI response with VOICE_BOOKING tag.

    Args:
        ai_response: AI response text
        call_id: Retell call ID

    Returns:
        (cleaned_text, booking_data or None)
    """
    import re

    pattern = r'<VOICE_BOOKING>(.*?)</VOICE_BOOKING>'
    match = re.search(pattern, ai_response, re.DOTALL)

    if not match:
        return ai_response, None

    # Remove the tag from response
    cleaned = re.sub(pattern, '', ai_response).strip()

    try:
        booking_json = match.group(1).strip()
        booking_data = json.loads(booking_json)

        # Store for later confirmation
        store_voice_pending_booking(call_id, booking_data)

        return cleaned, booking_data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse voice booking JSON: {e}")
        return ai_response, None


def detect_booking_response(transcript: str) -> Optional[str]:
    """Detect if user confirmed or cancelled booking from transcript.

    Args:
        transcript: User's speech transcript

    Returns:
        'confirm', 'cancel', or None if unclear
    """
    text = transcript.lower().strip()

    # Check cancel first (more specific patterns)
    if _CANCEL_RE.search(text):
        return 'cancel'

    # Then check confirm
    if _CONFIRM_RE.search(text):
        return 'confirm'

    return None


def confirm_voice_booking(call_id: str, business_id: int, session_id: int) -> Tuple[bool, str, Optional[int]]:
    """Confirm a pending voice booking.

    Args:
        call_id: Retell call ID
        business_id: Business ID
        session_id: Session ID

    Returns:
        (success, message, appointment_id or None)
    """
    from core.db import create_appointment_atomic, get_conn
    from core.booking import get_service_duration

    pending = clear_voice_pending_booking(call_id)
    if not pending:
        return False, "No pending booking found for this call", None

    # Get service duration
    service_name = pending.get("service") or pending.get("service_name")
    duration = get_service_duration(business_id, service_name) if service_name else 30

    # Create appointment atomically
    appt_id, error = create_appointment_atomic(
        business_id=business_id,
        start_at=pending.get("datetime") or pending.get("slot"),
        duration_min=duration,
        customer_name=pending.get("name") or pending.get("customer_name"),
        phone=pending.get("phone"),
        service=service_name,
        status="confirmed",
        session_id=session_id,
        source="ai",
        customer_email=pending.get("email"),
    )

    if error:
        logger.error(f"Voice booking failed: {error}")
        return False, f"Booking failed: {error}", None

    # Update voice call record
    update_voice_call(call_id, booking_confirmed=1, appointment_id=appt_id)

    logger.info(f"Voice booking confirmed: appointment {appt_id} for call {call_id}")
    return True, "Booking confirmed successfully", appt_id


def cancel_voice_booking(call_id: str) -> Tuple[bool, str]:
    """Cancel a pending voice booking.

    Returns:
        (success, message)
    """
    pending = clear_voice_pending_booking(call_id)
    if pending:
        logger.info(f"Voice booking cancelled for call {call_id}")
        return True, "Booking cancelled"
    return False, "No pending booking found"


# ============================================================================
# Caller Recognition
# ============================================================================

def get_caller_info(business_id: int, phone: str) -> Optional[Dict]:
    """Look up caller by phone number and return enriched customer info.

    This is the core of caller recognition - when a call comes in,
    we look up the customer and provide context to the AI.

    Args:
        business_id: Business receiving the call
        phone: Caller's phone number

    Returns:
        Dict with customer info including:
        - id, name, email, phone
        - total_appointments, visit_count
        - last_service, last_visit
        - preferred_staff
        - notes, tags
        Or None if customer not found
    """
    if not phone or not business_id:
        return None

    from core.db import get_conn

    # Normalize phone for matching
    normalized = ''.join(c for c in phone if c.isdigit())
    if len(normalized) < 7:
        return None

    # Last 10 digits for matching (handles country codes)
    last_10 = normalized[-10:] if len(normalized) >= 10 else normalized

    with get_conn() as con:
        # Find customer by phone
        rows = con.execute(
            "SELECT * FROM customers WHERE business_id = ? AND phone IS NOT NULL",
            (business_id,)
        ).fetchall()

        customer = None
        for row in rows:
            row_phone = ''.join(c for c in (row["phone"] or "") if c.isdigit())
            row_last_10 = row_phone[-10:] if len(row_phone) >= 10 else row_phone
            if row_last_10 and last_10 == row_last_10:
                customer = dict(row)
                break

        if not customer:
            return None

        customer_id = customer["id"]

        # Get last appointment info
        last_appt = con.execute(
            """SELECT service, start_at, status
               FROM appointments
               WHERE business_id = ? AND customer_name IS NOT NULL
               AND (phone LIKE ? OR customer_email = ?)
               AND status IN ('completed', 'confirmed')
               ORDER BY start_at DESC
               LIMIT 1""",
            (business_id, f"%{last_10}%", customer.get("email"))
        ).fetchone()

        if last_appt:
            customer["last_service"] = last_appt["service"]
            # Format date nicely
            try:
                dt = datetime.fromisoformat(last_appt["start_at"].replace("Z", ""))
                customer["last_visit"] = dt.strftime("%B %d")  # e.g., "January 15"
            except:
                customer["last_visit"] = last_appt["start_at"][:10] if last_appt["start_at"] else None

        # Count total completed appointments
        count_row = con.execute(
            """SELECT COUNT(*) as cnt FROM appointments
               WHERE business_id = ?
               AND (phone LIKE ? OR customer_email = ?)
               AND status IN ('completed', 'confirmed')""",
            (business_id, f"%{last_10}%", customer.get("email"))
        ).fetchone()
        customer["visit_count"] = count_row["cnt"] if count_row else customer.get("total_appointments", 0)

        # Get preferred staff if we track it (future enhancement)
        customer["preferred_staff"] = None  # TODO: Add staff preference tracking

        logger.info(f"Caller recognized: {customer.get('name')} (ID: {customer_id}) for business {business_id}")
        return customer


def get_caller_info_by_call_id(call_id: str) -> Optional[Dict]:
    """Get caller info for a voice call by looking up the call record.

    Args:
        call_id: Retell call ID

    Returns:
        Customer info dict or None
    """
    voice_call = get_voice_call(call_id)
    if not voice_call:
        return None

    business_id = voice_call.get("business_id")
    # For inbound calls, from_number is the caller
    # For outbound calls, to_number is the customer
    direction = voice_call.get("direction", "inbound")
    phone = voice_call.get("from_number") if direction == "inbound" else voice_call.get("to_number")

    if not business_id or not phone:
        return None

    return get_caller_info(business_id, phone)


# ============================================================================
# Voice Call Lifecycle
# ============================================================================

def handle_call_started(data: Dict) -> Dict:
    """Handle call_started webhook event.

    Args:
        data: Webhook payload

    Returns:
        Created voice call record
    """
    call = data.get("call", {})
    call_id = call.get("call_id")
    agent_id = call.get("agent_id")
    direction = call.get("direction", "inbound")
    from_number = call.get("from_number")
    to_number = call.get("to_number")
    metadata = call.get("metadata", {})

    # Get business_id from metadata or lookup by phone
    business_id = metadata.get("business_id")
    if not business_id:
        business_id = _get_business_by_phone(to_number if direction == "inbound" else from_number)

    if not business_id:
        logger.error(f"Could not find business for call {call_id}")
        return {"error": "Business not found"}

    # Create or get session
    phone = from_number if direction == "inbound" else to_number
    session_id = get_or_create_voice_session(business_id, phone, call_id)

    # Create voice call record
    record_id = create_voice_call_record(
        business_id=business_id,
        session_id=session_id,
        retell_call_id=call_id,
        direction=direction,
        from_number=from_number,
        to_number=to_number,
        retell_agent_id=agent_id
    )

    logger.info(f"Call started: {call_id}, direction={direction}, business={business_id}")

    return {
        "id": record_id,
        "call_id": call_id,
        "session_id": session_id,
        "business_id": business_id,
    }


def handle_call_ended(data: Dict) -> Dict:
    """Handle call_ended webhook event."""
    call = data.get("call", {})
    call_id = call.get("call_id")

    # Calculate duration
    duration_ms = call.get("duration_ms") or call.get("call_duration_ms")
    duration_seconds = int(duration_ms / 1000) if duration_ms else None

    # Get transcript
    transcript = call.get("transcript")
    transcript_json = json.dumps(call.get("transcript_object")) if call.get("transcript_object") else None

    # Get recording URL
    recording_url = call.get("recording_url")

    # Get cost
    cost_data = call.get("call_cost", {})
    cost_cents = cost_data.get("total_cost_cents") if cost_data else None

    # Update call record
    update_voice_call(
        call_id,
        call_status="ended",
        ended_at=datetime.now().isoformat(),
        duration_seconds=duration_seconds,
        transcript=transcript,
        transcript_json=transcript_json,
        recording_url=recording_url,
        cost_cents=cost_cents,
    )

    # Clear any pending bookings
    clear_voice_pending_booking(call_id)

    logger.info(f"Call ended: {call_id}, duration={duration_seconds}s")

    return {"call_id": call_id, "duration_seconds": duration_seconds}


def handle_call_analyzed(data: Dict) -> Dict:
    """Handle call_analyzed webhook event."""
    call = data.get("call", {})
    call_id = call.get("call_id")
    analysis = call.get("call_analysis", {})

    sentiment = analysis.get("sentiment")
    summary = analysis.get("summary")

    update_voice_call(
        call_id,
        sentiment=sentiment,
        call_summary=summary,
    )

    logger.info(f"Call analyzed: {call_id}, sentiment={sentiment}")

    return {"call_id": call_id, "sentiment": sentiment}


def _get_business_by_phone(phone: str) -> Optional[int]:
    """Get business ID by phone number."""
    from core.db import get_conn

    if not phone:
        return None

    # Normalize phone (last 10 digits)
    digits = re.sub(r'\D', '', phone)
    last_10 = digits[-10:] if len(digits) >= 10 else digits

    with get_conn() as con:
        # Try voice settings first
        row = con.execute("""
            SELECT business_id FROM voice_settings
            WHERE retell_phone_number LIKE ?
            LIMIT 1
        """, (f"%{last_10}%",)).fetchone()

        if row:
            return row["business_id"]

        # Try escalation_phone
        row = con.execute("""
            SELECT id FROM businesses
            WHERE escalation_phone LIKE ? AND archived = 0
            LIMIT 1
        """, (f"%{last_10}%",)).fetchone()

        if row:
            return row["id"]

        # Fallback to first active business
        row = con.execute(
            "SELECT id FROM businesses WHERE archived = 0 LIMIT 1"
        ).fetchone()

        return row["id"] if row else None


# ============================================================================
# Outbound Call Support
# ============================================================================

def create_outbound_call(
    business_id: int,
    to_number: str,
    purpose: str = "outreach",
    metadata: Optional[Dict] = None
) -> Tuple[bool, str, Optional[Dict]]:
    """Create an outbound voice call.

    Args:
        business_id: Business initiating the call
        to_number: Number to call (E.164 format)
        purpose: Call purpose (for tracking)
        metadata: Additional metadata

    Returns:
        (success, message, call_data or None)
    """
    settings = get_voice_settings(business_id)

    if not settings.get("retell_phone_number"):
        return False, "No Retell phone number configured for this business", None

    if not settings.get("retell_agent_id"):
        return False, "No Retell agent configured for this business", None

    try:
        client = get_retell_client()

        call_metadata = {
            "business_id": business_id,
            "purpose": purpose,
            **(metadata or {})
        }

        result = client.create_phone_call(
            from_number=settings["retell_phone_number"],
            to_number=to_number,
            agent_id=settings["retell_agent_id"],
            metadata=call_metadata,
        )

        logger.info(f"Outbound call created: {result.get('call_id')} to {to_number}")
        return True, "Call initiated", result

    except RetellClientError as e:
        logger.error(f"Failed to create outbound call: {e}")
        return False, str(e), None
