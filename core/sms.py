# core/sms.py — SMS sending via Twilio for AxisAI
# Provides SMS messaging for reminders, notifications, and 2-way conversations

import os
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# Twilio Configuration
# ============================================================================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# Check if Twilio is configured
TWILIO_CONFIGURED = bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER)

# Lazy-load Twilio client
_twilio_client = None


def _get_twilio_client():
    """Get or create Twilio client (lazy initialization)."""
    global _twilio_client

    if _twilio_client is not None:
        return _twilio_client

    if not TWILIO_CONFIGURED:
        raise RuntimeError(
            "Twilio is not configured. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER environment variables."
        )

    try:
        from twilio.rest import Client
        _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        return _twilio_client
    except ImportError:
        raise ImportError(
            "Twilio library not installed. Run: pip install twilio"
        )


# ============================================================================
# SMS Sending
# ============================================================================

def send_sms(
    to: str,
    message: str,
    from_number: Optional[str] = None,
    media_url: Optional[str] = None,
    status_callback: Optional[str] = None
) -> Dict[str, Any]:
    """Send an SMS message via Twilio.

    Args:
        to: Recipient phone number (E.164 format preferred, e.g., +15551234567)
        message: Message content (max 1600 characters for SMS)
        from_number: Override sender number (defaults to TWILIO_PHONE_NUMBER)
        media_url: URL of media to attach (MMS)
        status_callback: URL for delivery status webhooks

    Returns:
        Dict with 'sid', 'status', 'error' keys

    Raises:
        RuntimeError: If Twilio is not configured
        Exception: On Twilio API errors
    """
    if not message:
        return {"sid": None, "status": "error", "error": "Message is empty"}

    # Normalize phone number
    to = _normalize_phone(to)
    if not to:
        return {"sid": None, "status": "error", "error": "Invalid phone number"}

    # Truncate message if too long (SMS limit is 1600 chars)
    if len(message) > 1600:
        logger.warning(f"SMS message truncated from {len(message)} to 1600 chars")
        message = message[:1597] + "..."

    try:
        client = _get_twilio_client()

        # Build message parameters
        params = {
            "to": to,
            "from_": from_number or TWILIO_PHONE_NUMBER,
            "body": message,
        }

        if media_url:
            params["media_url"] = [media_url]

        if status_callback:
            params["status_callback"] = status_callback

        # Send the message
        msg = client.messages.create(**params)

        logger.info(f"SMS sent to {_mask_phone(to)}, SID: {msg.sid}")

        return {
            "sid": msg.sid,
            "status": msg.status,
            "error": None,
            "to": to,
            "segments": getattr(msg, "num_segments", 1)
        }

    except Exception as e:
        logger.error(f"Failed to send SMS to {_mask_phone(to)}: {e}")
        return {
            "sid": None,
            "status": "error",
            "error": str(e)
        }


def send_bulk_sms(
    recipients: list,
    message: str,
    from_number: Optional[str] = None
) -> Dict[str, Any]:
    """Send the same SMS to multiple recipients.

    Args:
        recipients: List of phone numbers
        message: Message content
        from_number: Override sender number

    Returns:
        Dict with 'sent', 'failed', 'results' keys
    """
    results = []
    sent = 0
    failed = 0

    for to in recipients:
        result = send_sms(to, message, from_number)
        results.append({"to": to, **result})

        if result.get("status") != "error":
            sent += 1
        else:
            failed += 1

    logger.info(f"Bulk SMS: {sent} sent, {failed} failed out of {len(recipients)}")

    return {
        "sent": sent,
        "failed": failed,
        "total": len(recipients),
        "results": results
    }


# ============================================================================
# SMS Lookup & Validation
# ============================================================================

def lookup_phone(phone: str) -> Dict[str, Any]:
    """Look up phone number information via Twilio Lookup API.

    Args:
        phone: Phone number to look up

    Returns:
        Dict with carrier info, type, etc.
    """
    phone = _normalize_phone(phone)
    if not phone:
        return {"valid": False, "error": "Invalid phone format"}

    try:
        client = _get_twilio_client()
        lookup = client.lookups.v1.phone_numbers(phone).fetch(type=["carrier"])

        return {
            "valid": True,
            "phone_number": lookup.phone_number,
            "national_format": lookup.national_format,
            "country_code": lookup.country_code,
            "carrier": {
                "name": lookup.carrier.get("name") if lookup.carrier else None,
                "type": lookup.carrier.get("type") if lookup.carrier else None,
            }
        }
    except Exception as e:
        logger.warning(f"Phone lookup failed for {_mask_phone(phone)}: {e}")
        return {"valid": False, "error": str(e)}


def validate_phone(phone: str) -> Tuple[bool, str]:
    """Validate a phone number format.

    Args:
        phone: Phone number to validate

    Returns:
        Tuple of (is_valid, normalized_number_or_error)
    """
    normalized = _normalize_phone(phone)
    if not normalized:
        return False, "Invalid phone number format"
    return True, normalized


# ============================================================================
# Phone Number Utilities
# ============================================================================

def _normalize_phone(phone: str) -> Optional[str]:
    """Normalize a phone number to E.164 format.

    Handles common US formats:
    - 5551234567 -> +15551234567
    - 15551234567 -> +15551234567
    - +15551234567 -> +15551234567
    - (555) 123-4567 -> +15551234567
    """
    if not phone:
        return None

    # Remove all non-digit characters except +
    import re
    digits = re.sub(r"[^\d+]", "", phone)

    # Handle + prefix
    if digits.startswith("+"):
        # Already has country code
        if len(digits) >= 11:  # +1 + 10 digits minimum for US
            return digits
        return None

    # Remove leading 1 if present (US country code)
    if digits.startswith("1") and len(digits) == 11:
        return f"+{digits}"

    # Assume US number if 10 digits
    if len(digits) == 10:
        return f"+1{digits}"

    # If 11+ digits, assume it includes country code
    if len(digits) >= 11:
        return f"+{digits}"

    return None


def _mask_phone(phone: str) -> str:
    """Mask a phone number for logging."""
    if not phone:
        return ""
    if len(phone) < 7:
        return "***"
    return phone[:3] + "***" + phone[-4:]


# ============================================================================
# Incoming SMS Handling
# ============================================================================

def parse_twilio_webhook(request_data: Dict[str, str]) -> Dict[str, Any]:
    """Parse an incoming Twilio SMS webhook.

    Args:
        request_data: Request form data from Twilio

    Returns:
        Parsed message data
    """
    return {
        "message_sid": request_data.get("MessageSid"),
        "account_sid": request_data.get("AccountSid"),
        "from_number": request_data.get("From"),
        "to_number": request_data.get("To"),
        "body": request_data.get("Body", ""),
        "num_media": int(request_data.get("NumMedia", 0)),
        "media_urls": [
            request_data.get(f"MediaUrl{i}")
            for i in range(int(request_data.get("NumMedia", 0)))
            if request_data.get(f"MediaUrl{i}")
        ],
        "from_city": request_data.get("FromCity"),
        "from_state": request_data.get("FromState"),
        "from_country": request_data.get("FromCountry"),
    }


def generate_twiml_response(message: str) -> str:
    """Generate TwiML response for replying to SMS.

    Args:
        message: Reply message content

    Returns:
        TwiML XML string
    """
    # Escape XML special characters
    escaped = (message
               .replace("&", "&amp;")
               .replace("<", "&lt;")
               .replace(">", "&gt;")
               .replace('"', "&quot;"))

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{escaped}</Message>
</Response>'''


# ============================================================================
# Status Checking
# ============================================================================

def get_message_status(message_sid: str) -> Dict[str, Any]:
    """Get the delivery status of a sent message.

    Args:
        message_sid: Twilio message SID

    Returns:
        Dict with status information
    """
    try:
        client = _get_twilio_client()
        msg = client.messages(message_sid).fetch()

        return {
            "sid": msg.sid,
            "status": msg.status,  # queued, sending, sent, delivered, undelivered, failed
            "error_code": msg.error_code,
            "error_message": msg.error_message,
            "date_sent": str(msg.date_sent) if msg.date_sent else None,
            "date_updated": str(msg.date_updated) if msg.date_updated else None,
        }
    except Exception as e:
        logger.error(f"Failed to get message status for {message_sid}: {e}")
        return {"sid": message_sid, "status": "unknown", "error": str(e)}


# ============================================================================
# Testing Utilities
# ============================================================================

def check_twilio_config() -> Dict[str, bool]:
    """Check if Twilio is properly configured.

    Returns:
        Dict indicating configuration status
    """
    return {
        "account_sid_set": bool(TWILIO_ACCOUNT_SID),
        "auth_token_set": bool(TWILIO_AUTH_TOKEN),
        "phone_number_set": bool(TWILIO_PHONE_NUMBER),
        "fully_configured": TWILIO_CONFIGURED,
    }


def test_connection() -> Dict[str, Any]:
    """Test Twilio connection by fetching account info.

    Returns:
        Dict with account info or error
    """
    try:
        client = _get_twilio_client()
        account = client.api.accounts(TWILIO_ACCOUNT_SID).fetch()

        return {
            "connected": True,
            "account_name": account.friendly_name,
            "account_status": account.status,
            "account_type": account.type,
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e)
        }
