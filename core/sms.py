# core/sms.py — SMS sending via Telnyx for LocusAI
# Provides SMS messaging for reminders, notifications, and 2-way conversations

import os
import logging
import re
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# Telnyx Configuration
# ============================================================================

TELNYX_API_KEY = os.getenv("TELNYX_API_KEY")
TELNYX_PHONE_NUMBER = os.getenv("TELNYX_PHONE_NUMBER", "+442046203253")

TELNYX_CONFIGURED = bool(TELNYX_API_KEY)

TELNYX_API_BASE = "https://api.telnyx.com/v2"


# ============================================================================
# SMS Sending
# ============================================================================

def send_sms(
    to: str,
    message: str,
    from_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Send an SMS message via Telnyx.

    Args:
        to: Recipient phone number (E.164 format preferred, e.g., +15551234567)
        message: Message content
        from_number: Override sender number (defaults to TELNYX_PHONE_NUMBER)

    Returns:
        Dict with 'id', 'status', 'error' keys
    """
    if not message:
        return {"id": None, "status": "error", "error": "Message is empty"}

    to = _normalize_phone(to)
    if not to:
        return {"id": None, "status": "error", "error": "Invalid phone number"}

    if not TELNYX_CONFIGURED:
        return {"id": None, "status": "error", "error": "Telnyx is not configured. Set TELNYX_API_KEY."}

    # Truncate to SMS limit
    if len(message) > 1600:
        logger.warning(f"SMS message truncated from {len(message)} to 1600 chars")
        message = message[:1597] + "..."

    try:
        import httpx

        payload = {
            "from": from_number or TELNYX_PHONE_NUMBER,
            "to": to,
            "text": message,
        }

        response = httpx.post(
            f"{TELNYX_API_BASE}/messages",
            headers={
                "Authorization": f"Bearer {TELNYX_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json().get("data", {})

        msg_id = data.get("id")
        logger.info(f"SMS sent to {_mask_phone(to)}, ID: {msg_id}")

        return {
            "id": msg_id,
            "status": "sent",
            "error": None,
            "to": to,
        }

    except Exception as e:
        logger.error(f"Failed to send SMS to {_mask_phone(to)}: {e}")
        return {
            "id": None,
            "status": "error",
            "error": str(e),
        }


def send_bulk_sms(
    recipients: list,
    message: str,
    from_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Send the same SMS to multiple recipients."""
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
    return {"sent": sent, "failed": failed, "total": len(recipients), "results": results}


# ============================================================================
# Phone Number Utilities
# ============================================================================

def validate_phone(phone: str) -> Tuple[bool, str]:
    normalized = _normalize_phone(phone)
    if not normalized:
        return False, "Invalid phone number format"
    return True, normalized


def _normalize_phone(phone: str) -> Optional[str]:
    """Normalize a phone number to E.164 format."""
    if not phone:
        return None

    digits = re.sub(r"[^\d+]", "", phone)

    if digits.startswith("+"):
        if len(digits) >= 11:
            return digits
        return None

    if digits.startswith("1") and len(digits) == 11:
        return f"+{digits}"

    if len(digits) == 10:
        return f"+1{digits}"

    if len(digits) >= 11:
        return f"+{digits}"

    return None


def _mask_phone(phone: str) -> str:
    if not phone:
        return ""
    if len(phone) < 7:
        return "***"
    return phone[:3] + "***" + phone[-4:]


# ============================================================================
# Incoming Webhook Parsing
# ============================================================================

def parse_telnyx_webhook(data: Dict) -> Dict[str, Any]:
    """Parse an incoming Telnyx SMS webhook (JSON body).

    Telnyx sends:
    {
      "data": {
        "event_type": "message.received",
        "payload": {
          "from": {"phone_number": "+1..."},
          "to": [{"phone_number": "+442046203253"}],
          "text": "Hello"
        }
      }
    }
    """
    payload = data.get("data", {}).get("payload", {})
    from_info = payload.get("from", {})
    to_list = payload.get("to", [{}])

    return {
        "message_id": payload.get("id"),
        "event_type": data.get("data", {}).get("event_type"),
        "from_number": from_info.get("phone_number"),
        "to_number": to_list[0].get("phone_number") if to_list else None,
        "body": payload.get("text", ""),
        "direction": payload.get("direction"),
    }


# ============================================================================
# Config Check
# ============================================================================

def check_telnyx_config() -> Dict[str, bool]:
    return {
        "api_key_set": bool(TELNYX_API_KEY),
        "phone_number_set": bool(TELNYX_PHONE_NUMBER),
        "fully_configured": TELNYX_CONFIGURED,
    }
