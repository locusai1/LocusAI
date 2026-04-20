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
        "cost_cents", "customer_id",
        "call_intent", "call_outcome", "action_items", "caller_message", "containment",
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
# Expanded Intents: Appointments Status, Cancel, Reschedule
# ============================================================================

# Intent detection patterns
INTENT_STATUS_PATTERNS = [
    r'\b(when|what time).*(my|next|upcoming).*(appointment|booking|visit)\b',
    r'\b(do i have).*(appointment|booking|scheduled)\b',
    r'\b(check|look up|find).*(my|the|upcoming).*(appointment|booking)s?\b',
    r'\bmy.*(next|upcoming).*(appointment|booking)\b',
    r'\b(am i|what\'s).*(booked|scheduled)\b',
    r'\bupcoming.*(appointment|booking)s?\b',
]

INTENT_CANCEL_PATTERNS = [
    r'\b(cancel|canceling|cancellation).*(my|the).*(appointment|booking)\b',
    r'\b(need to|want to|like to).*(cancel)\b',
    r'\b(can\'t make|won\'t make|won\'t be able to make|unable to make).*(appointment|booking|it)\b',
    r'\b(remove|delete).*(my|the).*(appointment|booking)\b',
]

INTENT_RESCHEDULE_PATTERNS = [
    r'\b(reschedule|move|change|push|switch).*(my|the).*(appointment|booking)\b',
    r'\b(need to|want to|like to).*(reschedule|move|change)\b',
    r'\b(different|another).*(time|day|date).*(appointment|booking)\b',
    r'\b(change|move).*(the time|the date|when)\b',
]

# Compile patterns
_INTENT_STATUS_RE = re.compile('|'.join(INTENT_STATUS_PATTERNS), re.IGNORECASE)
_INTENT_CANCEL_RE = re.compile('|'.join(INTENT_CANCEL_PATTERNS), re.IGNORECASE)
_INTENT_RESCHEDULE_RE = re.compile('|'.join(INTENT_RESCHEDULE_PATTERNS), re.IGNORECASE)


def detect_appointment_intent(text: str) -> Optional[str]:
    """Detect appointment-related intent from user speech.

    Args:
        text: User's speech transcript

    Returns:
        'status', 'cancel', 'reschedule', or None
    """
    text = text.lower().strip()

    # Check in order of specificity
    if _INTENT_CANCEL_RE.search(text):
        return 'cancel'
    if _INTENT_RESCHEDULE_RE.search(text):
        return 'reschedule'
    if _INTENT_STATUS_RE.search(text):
        return 'status'

    return None


def get_caller_upcoming_appointments(
    business_id: int,
    phone: str,
    limit: int = 3
) -> List[Dict]:
    """Get caller's upcoming appointments by phone number.

    Args:
        business_id: Business ID
        phone: Caller's phone number
        limit: Max appointments to return

    Returns:
        List of upcoming appointments with id, service, start_at, status
    """
    if not phone or not business_id:
        return []

    from core.db import get_conn

    # Normalize phone for matching
    normalized = ''.join(c for c in phone if c.isdigit())
    if len(normalized) < 7:
        return []
    last_10 = normalized[-10:] if len(normalized) >= 10 else normalized

    with get_conn() as con:
        # Find upcoming appointments for this phone
        rows = con.execute("""
            SELECT id, service, start_at, status, customer_name
            FROM appointments
            WHERE business_id = ?
              AND phone LIKE ?
              AND status IN ('pending', 'confirmed')
              AND datetime(start_at) > datetime('now')
            ORDER BY start_at ASC
            LIMIT ?
        """, (business_id, f"%{last_10}%", limit)).fetchall()

        return [dict(row) for row in rows]


def format_appointments_for_voice(appointments: List[Dict]) -> str:
    """Format appointments for voice AI response.

    Args:
        appointments: List of appointment dicts

    Returns:
        Human-readable string for voice
    """
    if not appointments:
        return ""

    lines = []
    for i, appt in enumerate(appointments):
        service = appt.get("service", "appointment")
        start_at = appt.get("start_at", "")

        # Format datetime nicely
        try:
            dt = datetime.fromisoformat(start_at.replace("Z", "").replace(" ", "T"))
            # e.g., "Tuesday, January 28th at 2:30 PM"
            day_name = dt.strftime("%A")
            month_day = dt.strftime("%B %d").replace(" 0", " ")
            time_str = dt.strftime("%I:%M %p").lstrip("0")
            formatted = f"{day_name}, {month_day} at {time_str}"
        except:
            formatted = start_at

        lines.append(f"{service} on {formatted}")

    if len(lines) == 1:
        return lines[0]
    else:
        return "; ".join(lines)


def get_caller_appointments_context(
    business_id: int,
    phone: str
) -> Optional[str]:
    """Get a voice-friendly context string about caller's appointments.

    Used to inject into AI prompt for appointment management.

    Returns:
        Context string or None if no appointments
    """
    appointments = get_caller_upcoming_appointments(business_id, phone, limit=3)
    if not appointments:
        return None

    formatted = format_appointments_for_voice(appointments)
    return f"Upcoming appointments: {formatted}"


def cancel_caller_appointment(
    business_id: int,
    phone: str,
    appointment_id: Optional[int] = None
) -> Tuple[bool, str, Optional[Dict]]:
    """Cancel a caller's appointment.

    If appointment_id is not provided, cancels the next upcoming appointment.

    Args:
        business_id: Business ID
        phone: Caller's phone
        appointment_id: Specific appointment to cancel (optional)

    Returns:
        (success, message, cancelled_appointment or None)
    """
    from core.db import get_conn, update_appointment_status
    from core.reminders import cancel_reminders_for_appointment

    # Find the appointment
    if appointment_id:
        # Verify it belongs to this caller
        appointments = get_caller_upcoming_appointments(business_id, phone, limit=10)
        appt = next((a for a in appointments if a["id"] == appointment_id), None)
        if not appt:
            return False, "I couldn't find that appointment under your name.", None
    else:
        # Get next upcoming
        appointments = get_caller_upcoming_appointments(business_id, phone, limit=1)
        if not appointments:
            return False, "I don't see any upcoming appointments for you.", None
        appt = appointments[0]

    # Cancel it
    appt_id = appt["id"]
    success = update_appointment_status(appt_id, "cancelled")

    if not success:
        return False, "I had trouble cancelling that appointment. Could you try again?", None

    # Cancel reminders
    try:
        cancel_reminders_for_appointment(appt_id)
    except Exception as e:
        logger.warning(f"Could not cancel reminders for appointment {appt_id}: {e}")

    # Format the cancelled appointment info
    formatted = format_appointments_for_voice([appt])
    logger.info(f"Cancelled appointment {appt_id} for caller {phone}")

    return True, f"I've cancelled your {formatted}.", appt


def reschedule_caller_appointment(
    business_id: int,
    phone: str,
    new_datetime: str,
    appointment_id: Optional[int] = None,
    session_id: Optional[int] = None
) -> Tuple[bool, str, Optional[Dict]]:
    """Reschedule a caller's appointment to a new time.

    Args:
        business_id: Business ID
        phone: Caller's phone
        new_datetime: New datetime in YYYY-MM-DD HH:MM format
        appointment_id: Specific appointment to reschedule (optional)
        session_id: Session ID for logging

    Returns:
        (success, message, updated_appointment or None)
    """
    from core.db import get_conn, transaction, check_slot_available
    from core.reminders import reschedule_reminders_for_appointment

    # Find the appointment
    if appointment_id:
        appointments = get_caller_upcoming_appointments(business_id, phone, limit=10)
        appt = next((a for a in appointments if a["id"] == appointment_id), None)
        if not appt:
            return False, "I couldn't find that appointment under your name.", None
    else:
        appointments = get_caller_upcoming_appointments(business_id, phone, limit=1)
        if not appointments:
            return False, "I don't see any upcoming appointments to reschedule.", None
        appt = appointments[0]

    appt_id = appt["id"]
    service = appt.get("service")

    # Get service duration
    duration = 30  # default
    with get_conn() as con:
        row = con.execute(
            "SELECT duration_min FROM services WHERE business_id = ? AND name = ?",
            (business_id, service)
        ).fetchone()
        if row:
            duration = row["duration_min"]

    # Check if new slot is available
    if not check_slot_available(business_id, new_datetime, duration, exclude_appointment_id=appt_id):
        return False, "That time slot isn't available. Would you like to try another time?", None

    # Update the appointment
    try:
        with transaction() as con:
            con.execute(
                "UPDATE appointments SET start_at = ? WHERE id = ?",
                (new_datetime, appt_id)
            )

        # Reschedule reminders
        try:
            reschedule_reminders_for_appointment(
                appt_id,
                new_datetime,
                customer_email=None,  # Will use existing
                customer_phone=phone
            )
        except Exception as e:
            logger.warning(f"Could not reschedule reminders for appointment {appt_id}: {e}")

        # Format the new time
        try:
            dt = datetime.fromisoformat(new_datetime.replace("Z", "").replace(" ", "T"))
            day_name = dt.strftime("%A")
            month_day = dt.strftime("%B %d").replace(" 0", " ")
            time_str = dt.strftime("%I:%M %p").lstrip("0")
            formatted_time = f"{day_name}, {month_day} at {time_str}"
        except:
            formatted_time = new_datetime

        logger.info(f"Rescheduled appointment {appt_id} to {new_datetime} for caller {phone}")

        appt["start_at"] = new_datetime
        return True, f"I've moved your {service} to {formatted_time}.", appt

    except Exception as e:
        logger.error(f"Failed to reschedule appointment {appt_id}: {e}")
        return False, "I had trouble rescheduling that appointment. Could you try again?", None


# In-memory storage for pending appointment changes (cancel/reschedule)
_VOICE_PENDING_CHANGES: Dict[str, Dict] = {}
_changes_lock = Lock()


def store_voice_pending_change(call_id: str, change_type: str, change_data: Dict) -> None:
    """Store a pending appointment change for voice confirmation.

    Args:
        call_id: Retell call ID
        change_type: 'cancel' or 'reschedule'
        change_data: Details of the change
    """
    with _changes_lock:
        _VOICE_PENDING_CHANGES[call_id] = {
            "type": change_type,
            "data": change_data,
            "created_at": time.time(),
            "call_id": call_id,
        }
    logger.info(f"Stored pending {change_type} for call {call_id}")


def get_voice_pending_change(call_id: str) -> Optional[Dict]:
    """Get pending appointment change for a call."""
    with _changes_lock:
        return _VOICE_PENDING_CHANGES.get(call_id)


def clear_voice_pending_change(call_id: str) -> Optional[Dict]:
    """Clear and return pending change for a call."""
    with _changes_lock:
        return _VOICE_PENDING_CHANGES.pop(call_id, None)


def confirm_voice_change(call_id: str, business_id: int, phone: str, session_id: Optional[int] = None) -> Tuple[bool, str]:
    """Confirm a pending appointment change (cancel or reschedule).

    Args:
        call_id: Retell call ID
        business_id: Business ID
        phone: Caller's phone
        session_id: Optional session ID

    Returns:
        (success, response_message)
    """
    pending = clear_voice_pending_change(call_id)
    if not pending:
        return False, "I don't have any pending changes to confirm."

    change_type = pending.get("type")
    change_data = pending.get("data", {})

    if change_type == "cancel":
        appointment_id = change_data.get("appointment_id")
        success, message, _ = cancel_caller_appointment(business_id, phone, appointment_id)
        return success, message

    elif change_type == "reschedule":
        appointment_id = change_data.get("appointment_id")
        new_datetime = change_data.get("new_datetime")
        success, message, _ = reschedule_caller_appointment(
            business_id, phone, new_datetime, appointment_id, session_id
        )
        return success, message

    return False, "I'm not sure what to confirm. Could you tell me what you'd like to do?"


def cancel_voice_change(call_id: str) -> Tuple[bool, str]:
    """Cancel a pending appointment change.

    Returns:
        (success, message)
    """
    pending = clear_voice_pending_change(call_id)
    if pending:
        change_type = pending.get("type", "change")
        logger.info(f"Voice {change_type} cancelled for call {call_id}")
        return True, f"No problem, I won't {change_type} anything. Is there something else I can help with?"
    return False, "No pending changes to cancel."


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
    transcript = call.get("transcript") or ""
    transcript_json = json.dumps(call.get("transcript_object")) if call.get("transcript_object") else None

    # Get recording URL
    recording_url = call.get("recording_url")

    # Get cost
    cost_data = call.get("call_cost", {})
    cost_cents = cost_data.get("total_cost_cents") if cost_data else None

    # Detect missed calls (< 8s with no real transcript)
    is_missed = (duration_seconds is not None and duration_seconds < 8 and len(transcript.strip()) < 20)

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
        call_outcome="missed" if is_missed else None,
        call_intent="missed" if is_missed else None,
        containment=0 if is_missed else 1,
    )

    # Clear any pending bookings
    clear_voice_pending_booking(call_id)

    logger.info(f"Call ended: {call_id}, duration={duration_seconds}s, missed={is_missed}")

    # Fetch voice call record once (for business_id, from_number)
    voice_call = get_voice_call(call_id)
    business_id = voice_call.get("business_id", 1) if voice_call else 1

    # Send missed-call auto-SMS
    if is_missed and voice_call:
        from_number = voice_call.get("from_number", "")
        if from_number:
            _trigger_missed_call_sms(from_number, business_id)

    # Trigger post-call AI analysis in background (non-blocking)
    if transcript and not is_missed:
        trigger_post_call_analysis(call_id, transcript, business_id)

    return {"call_id": call_id, "duration_seconds": duration_seconds, "missed": is_missed}


def _trigger_missed_call_sms(caller_phone: str, business_id: int) -> None:
    """Fire a missed-call auto-SMS in a background thread so the webhook returns instantly."""
    import threading

    def _send():
        try:
            from core.db import get_business_by_id
            from core.sms import send_sms, TWILIO_CONFIGURED
            if not TWILIO_CONFIGURED:
                return
            biz = get_business_by_id(business_id)
            biz_name = dict(biz).get("name", "us") if biz else "us"
            msg = (
                f"Hi! You just called {biz_name} but we couldn't pick up. "
                f"Reply here to chat with our AI assistant, or call back when convenient. "
                f"We're happy to help!"
            )
            send_sms(to=caller_phone, message=msg)
            logger.info(f"Missed-call SMS sent to {caller_phone}")
        except Exception as e:
            logger.warning(f"Could not send missed-call SMS to {caller_phone}: {e}")

    threading.Thread(target=_send, daemon=True).start()


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


# ============================================================================
# Retell Call Sync — pull recent calls from Retell API into local DB
# ============================================================================

def sync_calls_from_retell(business_id: int, limit: int = 50) -> Tuple[bool, str]:
    """Fetch recent calls from Retell API and store any missing ones in the DB.

    This is the quick fix for when webhooks can't reach the local server.
    Safe to run repeatedly — skips calls already in the DB.

    Args:
        business_id: Business to associate calls with.
        limit: Max calls to fetch from Retell.

    Returns:
        (success, message)
    """
    import urllib.request
    import urllib.error
    from core.settings import RETELL_API_KEY
    from core.db import get_conn, transaction

    if not RETELL_API_KEY:
        return False, "RETELL_API_KEY is not configured."

    # ── 1. Fetch calls from Retell ────────────────────────────────────────────
    url = f"{RETELL_BASE_URL}/{RETELL_API_VERSION}/list-calls"
    payload = json.dumps({"limit": limit}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {RETELL_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            calls = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return False, f"Retell API error {e.code}: {body[:200]}"
    except Exception as e:
        return False, f"Failed to fetch calls: {e}"

    if not isinstance(calls, list):
        return False, f"Unexpected response format from Retell."

    # ── 2. Get existing call IDs so we don't duplicate ────────────────────────
    with get_conn() as con:
        existing = {
            r["retell_call_id"]
            for r in con.execute("SELECT retell_call_id FROM voice_calls").fetchall()
            if r["retell_call_id"]
        }

    # ── 3. Insert missing calls ───────────────────────────────────────────────
    inserted = 0
    for call in calls:
        call_id = call.get("call_id")
        if not call_id or call_id in existing:
            continue

        direction = call.get("direction", "inbound")
        from_number = call.get("from_number", "")
        to_number = call.get("to_number", "")
        agent_id = call.get("agent_id", "")
        status = call.get("call_status", "ended")
        duration_ms = call.get("duration_ms") or call.get("call_duration_ms")
        duration_seconds = int(duration_ms / 1000) if duration_ms else None
        transcript = call.get("transcript", "")
        transcript_json = json.dumps(call.get("transcript_object")) if call.get("transcript_object") else None
        recording_url = call.get("recording_url")
        cost_data = call.get("call_cost", {})
        cost_cents = cost_data.get("total_cost_cents") if cost_data else None

        # Convert timestamps (ms → ISO string)
        start_ts = call.get("start_timestamp")
        end_ts = call.get("end_timestamp")
        started_at = datetime.fromtimestamp(start_ts / 1000).isoformat() if start_ts else None
        ended_at = datetime.fromtimestamp(end_ts / 1000).isoformat() if end_ts else None
        created_at = started_at or datetime.now().isoformat()

        # Create a session for the call
        phone = from_number if direction == "inbound" else to_number
        try:
            session_id = get_or_create_voice_session(business_id, phone, call_id)
        except Exception:
            session_id = None

        try:
            with transaction() as con:
                con.execute("""
                    INSERT INTO voice_calls(
                        business_id, session_id, retell_call_id, retell_agent_id,
                        direction, from_number, to_number, call_status,
                        started_at, ended_at, duration_seconds,
                        transcript, transcript_json, recording_url, cost_cents, created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    business_id, session_id, call_id, agent_id,
                    direction, from_number, to_number, status,
                    started_at, ended_at, duration_seconds,
                    transcript, transcript_json, recording_url, cost_cents, created_at
                ))
            inserted += 1
        except Exception as e:
            logger.warning(f"Could not insert call {call_id}: {e}")

    logger.info(f"Synced {inserted} new calls from Retell for business {business_id}")
    return True, f"Synced {inserted} new call(s) from Retell ({len(calls) - inserted} already up to date)."


# ============================================================================
# Retell Prompt Sync — push live KB/services/hours to the native Retell LLM
# ============================================================================

def sync_retell_prompt(business_id: int, webhook_base_url: Optional[str] = None) -> Tuple[bool, str]:
    """Build a context-rich system prompt from the DB and push it to the Retell LLM.

    This keeps the native Retell LLM (zero-latency) while giving it real
    knowledge of the business: services, hours, KB Q&A, address, and tone.

    Args:
        business_id: The business whose data should be synced.

    Returns:
        (success, message)
    """
    import urllib.request
    import urllib.error
    from core.settings import RETELL_API_KEY, RETELL_LLM_ID, RETELL_DEFAULT_AGENT_ID
    from core.db import get_conn, get_business_by_id

    if not RETELL_API_KEY:
        return False, "RETELL_API_KEY is not configured."

    if not RETELL_LLM_ID:
        return False, "RETELL_LLM_ID is not configured."

    # ── 1. Fetch business record ──────────────────────────────────────────────
    business = get_business_by_id(business_id)
    if not business:
        return False, f"Business {business_id} not found."

    try:
        business = dict(business)
    except Exception:
        pass

    biz_name = business.get("name", "this business")
    biz_hours = business.get("hours", "")
    biz_address = business.get("address", "")
    biz_tone = business.get("tone", "friendly and professional")

    # ── 2. Fetch active services ──────────────────────────────────────────────
    services_lines = []
    try:
        with get_conn() as con:
            rows = con.execute("""
                SELECT name, duration_min, price FROM services
                WHERE business_id = ? AND active = 1
                ORDER BY name
            """, (business_id,)).fetchall()
            for r in rows:
                line = f"- {r['name']}"
                if r["duration_min"]:
                    line += f" ({r['duration_min']} min)"
                if r["price"]:
                    line += f" — {r['price']}"
                services_lines.append(line)
    except Exception as e:
        logger.warning(f"Could not fetch services for prompt sync: {e}")

    # ── 3. Fetch KB entries ───────────────────────────────────────────────────
    kb_lines = []
    try:
        with get_conn() as con:
            rows = con.execute("""
                SELECT question, answer FROM kb_entries
                WHERE business_id = ? AND active = 1
                ORDER BY id DESC LIMIT 30
            """, (business_id,)).fetchall()
            for r in rows:
                if r["question"] and r["answer"]:
                    kb_lines.append(f"Q: {r['question']}\nA: {r['answer']}")
    except Exception as e:
        logger.warning(f"Could not fetch KB entries for prompt sync: {e}")

    # ── 4. Fetch upcoming availability (next 7 days) ──────────────────────────
    availability_lines = []
    try:
        today = datetime.now()
        with get_conn() as con:
            # Get booked slots for next 7 days
            rows = con.execute("""
                SELECT start_at, service FROM appointments
                WHERE business_id = ?
                  AND status IN ('pending','confirmed')
                  AND date(start_at) BETWEEN date('now') AND date('now', '+7 days')
                ORDER BY start_at
            """, (business_id,)).fetchall()
            if rows:
                availability_lines.append("The following slots are already booked in the next 7 days:")
                for r in rows:
                    try:
                        dt = datetime.fromisoformat(r["start_at"].replace("Z",""))
                        availability_lines.append(
                            f"- {dt.strftime('%A %d %b at %I:%M %p')} ({r['service']})"
                        )
                    except Exception:
                        pass
            else:
                availability_lines.append("No appointments are currently booked in the next 7 days.")
    except Exception as e:
        logger.warning(f"Could not fetch availability for prompt sync: {e}")

    # ── 5. Build prompt ───────────────────────────────────────────────────────
    now_str = datetime.now().strftime("%A, %d %B %Y")

    prompt_parts = [
        f"You are the AI phone receptionist for {biz_name}.",
        f"If anyone asks what company this is, always say \"{biz_name}\" — never say anything else.",
        f"Today is {now_str}. Use this when discussing dates and availability.",
        f"Be {biz_tone} — warm, natural, and genuinely helpful.",
        "You are speaking on the phone so keep every response to 1-2 sentences.",
        "Never use bullet points, lists, or markdown — just natural speech.",
        "Use contractions naturally (I'll, you're, we've). Sound human, not robotic.",
        "",
        "## Call Opening (MANDATORY)",
        "Every call MUST begin with this exact opening — no exceptions:",
        f"\"Hello, thanks for calling {biz_name}. Just to let you know, this call may be recorded for quality purposes. How can I help you today?\"",
        "If caller_known is 'true', personalise after the recording notice: 'Hi {{caller_name}}! Just to let you know this call may be recorded — how can I help you today?'",
        "Never skip the recording notice. It must always be the first thing said.",
        "",
        "## Caller Recognition",
        "When a call connects, you are given context about the caller:",
        "- {{caller_name}} — the caller's name if they're a known customer, or empty if unknown",
        "- {{caller_known}} — 'true' if they're a returning customer, 'false' if new",
        "- {{caller_visit_count}} — how many times they've visited",
        "- {{caller_last_service}} — their last service (if any)",
        "- {{caller_last_visit}} — when they last visited (if any)",
        "If caller_known is 'true', greet them by name: 'Hi {{caller_name}}, great to hear from you!'",
        "If they've been before, you can personalise: 'Last time you had a {{caller_last_service}} — shall we book the same again?'",
        "If caller_known is 'false', give a warm standard greeting.",
        "",
        "## Your job",
        "- Answer questions about the business",
        "- Help callers book appointments (collect: service, preferred date/time, name, phone)",
        "- Manage existing appointments (cancel or reschedule)",
        "- Transfer to a human if the caller asks for one",
        "",
    ]

    if biz_hours:
        prompt_parts += ["## Business Hours", biz_hours, ""]

    if biz_address:
        prompt_parts += ["## Address", biz_address, ""]

    if services_lines:
        prompt_parts += ["## Services Offered"] + services_lines + [""]

    if availability_lines:
        prompt_parts += ["## Current Availability"] + availability_lines + [""]

    if kb_lines:
        prompt_parts += ["## Frequently Asked Questions"] + kb_lines + [""]

    # ── After-hours status ────────────────────────────────────────────────────
    try:
        is_open, hours_msg = is_business_open(business_id)
    except Exception:
        is_open, hours_msg = True, ""

    if not is_open:
        prompt_parts += [
            "## IMPORTANT — Currently Outside Business Hours",
            f"{hours_msg}",
            "Tell the caller we're currently closed and when we'll next be open.",
            "Offer to: (1) take a message so we can call them back, or (2) help them book in advance.",
            "If they want to leave a message, ask for their name, number, and what it's about.",
            "Then say exactly: <VOICE_MESSAGE>{{\"name\":\"NAME\",\"phone\":\"PHONE\",\"message\":\"MESSAGE\"}}</VOICE_MESSAGE>",
            "",
        ]
    else:
        prompt_parts += [
            f"## Current Status",
            f"{hours_msg}",
            "",
        ]

    prompt_parts += [
        "## Booking Instructions",
        "When a caller wants to book, ask for: (1) which service, (2) preferred date and time, (3) their name and phone number.",
        "Once you have all details, read them back clearly: \"So that's a [service] on [day] at [time] for [name] — shall I book that in?\"",
        "Wait for the caller to confirm before finalising.",
        "When booking is confirmed by the caller, say: \"Perfect, I've got that booked for you!\"",
        "",
        "## If a Caller Wants to Speak to a Human",
        "Say: \"Of course, let me get someone for you — just a moment.\"",
        "Then transfer the call.",
        "",
        "## Taking Messages",
        "If a caller wants to leave a message or have someone call them back:",
        "Ask: their name, their number, and what it's about.",
        "Then say exactly (hidden from caller): <VOICE_MESSAGE>{\"name\":\"NAME\",\"phone\":\"PHONE\",\"message\":\"MESSAGE\"}</VOICE_MESSAGE>",
        "Then say: \"Got it, I'll pass that on and someone will be in touch shortly.\"",
        "",
        "## What NEVER to do",
        "- Never say 'as an AI' or mention you're artificial",
        "- Never give long responses — one or two sentences maximum",
        "- Never make up information — if unsure, say 'I'm not sure about that, let me have someone call you back'",
        "- Never say 'I don't have access to' — just say 'I'm not sure about that'",
        "- Never read out a long list — summarise naturally",
    ]

    prompt = "\n".join(prompt_parts).strip()

    # ── 5. Push to Retell LLM ─────────────────────────────────────────────────
    url = f"https://api.retellai.com/update-retell-llm/{RETELL_LLM_ID}"
    payload = json.dumps({"general_prompt": prompt}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {RETELL_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="PATCH")
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()

        logger.info(
            f"Retell LLM prompt synced for business {business_id} "
            f"({len(services_lines)} services, {len(kb_lines)} KB entries)"
        )

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        logger.error(f"Retell LLM update failed ({e.code}): {body}")
        return False, f"Retell API error {e.code}: {body[:200]}"
    except Exception as e:
        logger.error(f"Failed to sync Retell prompt: {e}")
        return False, f"Sync failed: {e}"

    # ── 6. Update agent's inbound_dynamic_variables_webhook_url (caller recognition) ──
    agent_id = RETELL_DEFAULT_AGENT_ID
    if webhook_base_url and agent_id:
        call_setup_url = webhook_base_url.rstrip("/") + "/api/voice/call-setup"
        agent_url = f"https://api.retellai.com/update-agent/{agent_id}"
        agent_payload = json.dumps({"inbound_dynamic_variables_webhook_url": call_setup_url}).encode("utf-8")
        try:
            req2 = urllib.request.Request(agent_url, data=agent_payload, headers=headers, method="PATCH")
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                resp2.read()
            logger.info(f"Retell agent caller-recognition webhook set to {call_setup_url}")
        except Exception as e:
            # Non-fatal — prompt already synced, just log
            logger.warning(f"Could not set inbound_dynamic_variables_webhook_url: {e}")

    return True, (
        f"Prompt synced: {len(services_lines)} services and "
        f"{len(kb_lines)} KB entries pushed to voice agent."
        + (" Caller recognition activated." if webhook_base_url and agent_id else "")
    )


# ============================================================================
# Post-Call AI Intelligence — intent, outcome, action items, voicemail
# ============================================================================

def analyse_call_transcript(retell_call_id: str, transcript: str, business_id: int) -> None:
    """Use OpenAI to classify a call's intent, outcome, and extract action items.

    Runs in a background thread so it never blocks the webhook response.
    Updates the voice_calls record with the results.
    """
    from core.settings import OPENAI_API_KEY, OPENAI_MODEL
    if not OPENAI_API_KEY or not transcript or len(transcript.strip()) < 30:
        return

    try:
        import urllib.request as _req

        prompt = f"""Analyse this voice call transcript and return a JSON object with these fields:

call_intent: one of: booking | reschedule | cancel | faq | complaint | transfer_request | missed | general
call_outcome: one of: booked | resolved | escalated | voicemail | missed | no_answer | incomplete
action_items: array of strings — any follow-up actions needed (e.g. ["Call back John about Friday slot", "Check availability for cut & colour"])
caller_message: if the caller left a voicemail or message, include the full message text here, else null
summary: 1-2 sentence plain English summary of the call
containment: 1 if the AI fully handled the call without human escalation, 0 if a human was needed

Transcript:
{transcript[:3000]}

Respond with valid JSON only, no commentary."""

        payload = json.dumps({
            "model": OPENAI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "max_tokens": 400,
            "temperature": 0,
        }).encode("utf-8")

        request = _req.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with _req.urlopen(request, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        content = result["choices"][0]["message"]["content"]
        data = json.loads(content)

        update_voice_call(
            retell_call_id,
            call_intent=data.get("call_intent"),
            call_outcome=data.get("call_outcome"),
            action_items=json.dumps(data.get("action_items", [])),
            caller_message=data.get("caller_message"),
            containment=int(data.get("containment", 1)),
            call_summary=data.get("summary") or data.get("call_summary"),
        )

        # Update customer record with latest voice interaction data
        voice_call = get_voice_call(retell_call_id)
        if voice_call:
            caller_phone = voice_call.get("from_number")
            if caller_phone and business_id:
                try:
                    from core.db import transaction
                    normalized = ''.join(c for c in caller_phone if c.isdigit())
                    last_10 = normalized[-10:] if len(normalized) >= 10 else normalized
                    with transaction() as con:
                        con.execute(
                            """UPDATE customers
                               SET total_sessions = total_sessions + 1
                               WHERE business_id = ? AND phone LIKE ?""",
                            (business_id, f"%{last_10}%")
                        )
                except Exception as e:
                    logger.warning(f"Could not update customer record after call: {e}")

        logger.info(f"Post-call analysis complete for {retell_call_id}: "
                    f"intent={data.get('call_intent')} outcome={data.get('call_outcome')}")

    except Exception as e:
        logger.warning(f"Post-call analysis failed for {retell_call_id}: {e}")


def trigger_post_call_analysis(retell_call_id: str, transcript: str, business_id: int) -> None:
    """Fire post-call analysis in a background thread."""
    import threading
    t = threading.Thread(
        target=analyse_call_transcript,
        args=(retell_call_id, transcript, business_id),
        daemon=True,
    )
    t.start()


# ============================================================================
# After-Hours Detection
# ============================================================================

def is_business_open(business_id: int) -> Tuple[bool, str]:
    """Check if the business is currently open based on DB hours.

    Returns:
        (is_open, message) — message is human-friendly hours info
    """
    from core.db import get_conn

    now = datetime.now()
    weekday = now.weekday()  # 0=Monday … 6=Sunday
    current_time = now.strftime("%H:%M")

    with get_conn() as con:
        # Check closures first
        closure = con.execute(
            "SELECT reason FROM closures WHERE business_id = ? AND date = date('now')",
            (business_id,)
        ).fetchone()
        if closure:
            reason = closure["reason"] or "closed today"
            return False, f"We're {reason}."

        # Check business hours
        row = con.execute(
            "SELECT open_time, close_time, closed FROM business_hours WHERE business_id = ? AND weekday = ?",
            (business_id, weekday)
        ).fetchone()

        if not row or row["closed"]:
            # Find next open day
            for offset in range(1, 8):
                next_day = (weekday + offset) % 7
                next_row = con.execute(
                    "SELECT open_time, close_time, closed FROM business_hours WHERE business_id = ? AND weekday = ?",
                    (business_id, next_day)
                ).fetchone()
                if next_row and not next_row["closed"]:
                    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                    return False, f"We're closed today. We're next open on {day_names[next_day]} from {next_row['open_time']}."
            return False, "We're currently closed."

        open_t = row["open_time"] or "09:00"
        close_t = row["close_time"] or "17:00"

        if current_time < open_t:
            return False, f"We're not open yet today — we open at {open_t}."
        if current_time >= close_t:
            # Find next open slot
            for offset in range(1, 8):
                next_day = (weekday + offset) % 7
                next_row = con.execute(
                    "SELECT open_time, close_time, closed FROM business_hours WHERE business_id = ? AND weekday = ?",
                    (business_id, next_day)
                ).fetchone()
                if next_row and not next_row["closed"]:
                    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                    label = "tomorrow" if offset == 1 else day_names[next_day]
                    return False, f"We've closed for today. We're back open {label} at {next_row['open_time']}."
            return False, "We're currently closed."

        return True, f"We're open until {close_t} today."


# ============================================================================
# Warm Transfer Briefing
# ============================================================================

def generate_transfer_briefing(transcript: str, caller_name: Optional[str] = None) -> str:
    """Generate a brief for the human agent receiving a warm transfer.

    This text is read aloud to the agent before the caller is connected.

    Returns:
        Short briefing string (2-3 sentences max)
    """
    from core.settings import OPENAI_API_KEY, OPENAI_MODEL
    if not OPENAI_API_KEY or not transcript:
        name = caller_name or "a caller"
        return f"Transferring {name}. Please assist them."

    try:
        import urllib.request as _req

        prompt = f"""Based on this call transcript, write a 2-sentence briefing for the human agent
who is about to take over. Be concise and factual. Include caller name if mentioned,
what they need, and any relevant context.

Transcript:
{transcript[:2000]}

Write only the briefing, nothing else."""

        payload = json.dumps({
            "model": OPENAI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 100,
            "temperature": 0,
        }).encode("utf-8")

        request = _req.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with _req.urlopen(request, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        return result["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logger.warning(f"Transfer briefing generation failed: {e}")
        name = caller_name or "a caller"
        return f"Transferring {name}. Please assist them."
