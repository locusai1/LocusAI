# core/security.py — Security utilities and audit logging for LocusAI
# Provides centralized security functions, audit logging, and data protection

import logging
import hashlib
import hmac
import re
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from functools import wraps

from flask import request, g, session

logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

# ============================================================================
# Security Event Types
# ============================================================================

class SecurityEvent:
    """Constants for security event types."""
    # Authentication events
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PASSWORD_CHANGE = "password_change"
    PASSWORD_RESET_REQUEST = "password_reset_request"
    MFA_ENABLED = "mfa_enabled"
    MFA_DISABLED = "mfa_disabled"

    # Authorization events
    PERMISSION_DENIED = "permission_denied"
    TENANT_ACCESS_DENIED = "tenant_access_denied"
    ADMIN_ACTION = "admin_action"

    # Data events
    DATA_EXPORT = "data_export"
    DATA_DELETION = "data_deletion"
    PII_ACCESS = "pii_access"
    BULK_OPERATION = "bulk_operation"

    # API events
    API_KEY_CREATED = "api_key_created"
    API_KEY_REVOKED = "api_key_revoked"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    WEBHOOK_RECEIVED = "webhook_received"
    WEBHOOK_VERIFICATION_FAILED = "webhook_verification_failed"

    # Security events
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    LOCKOUT_TRIGGERED = "lockout_triggered"
    LOCKOUT_CLEARED = "lockout_cleared"
    CSRF_VIOLATION = "csrf_violation"
    INVALID_INPUT = "invalid_input"


# ============================================================================
# Audit Logging
# ============================================================================

def log_security_event(
    event_type: str,
    user_id: Optional[int] = None,
    business_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    severity: str = "INFO"
) -> None:
    """Log a security-relevant event for audit trail.

    Args:
        event_type: Type of event (use SecurityEvent constants)
        user_id: ID of the user involved (or None for anonymous)
        business_id: ID of the business context (or None)
        details: Additional event-specific details
        severity: Log level (INFO, WARNING, ERROR, CRITICAL)
    """
    # Get request context if available
    ip_address = "unknown"
    user_agent = "unknown"
    request_id = "no-request"
    path = "unknown"

    try:
        if request:
            ip_address = request.remote_addr or "unknown"
            user_agent = request.user_agent.string if request.user_agent else "unknown"
            path = request.path
        if hasattr(g, 'request_id'):
            request_id = g.request_id
    except RuntimeError:
        # Outside of request context
        pass

    # Build log message
    log_data = {
        "event_type": event_type,
        "user_id": user_id,
        "business_id": business_id,
        "ip_address": ip_address,
        "user_agent": _truncate(user_agent, 200),
        "path": path,
        "request_id": request_id,
        "timestamp": datetime.now().isoformat(),
    }

    if details:
        # Mask sensitive data in details
        safe_details = _mask_sensitive_data(details)
        log_data["details"] = safe_details

    # Format message
    msg_parts = [
        f"[{event_type}]",
        f"user={user_id}",
        f"business={business_id}",
        f"ip={ip_address}",
    ]
    if details:
        detail_str = " ".join(f"{k}={v}" for k, v in safe_details.items())
        msg_parts.append(detail_str)

    message = " ".join(msg_parts)

    # Log at appropriate level
    level = getattr(logging, severity.upper(), logging.INFO)
    security_logger.log(level, message, extra=log_data)


def log_admin_action(action: str, target: str, details: Optional[Dict] = None) -> None:
    """Convenience function for logging admin actions."""
    user = session.get("user") if session else None
    user_id = user.get("id") if user else None

    log_security_event(
        SecurityEvent.ADMIN_ACTION,
        user_id=user_id,
        details={
            "action": action,
            "target": target,
            **(details or {})
        }
    )


def log_data_access(data_type: str, record_id: int, business_id: int) -> None:
    """Log access to sensitive data (for compliance)."""
    user = session.get("user") if session else None
    user_id = user.get("id") if user else None

    log_security_event(
        SecurityEvent.PII_ACCESS,
        user_id=user_id,
        business_id=business_id,
        details={
            "data_type": data_type,
            "record_id": record_id
        }
    )


# ============================================================================
# Data Masking
# ============================================================================

# Patterns for sensitive data
_SENSITIVE_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}[-]?\d{2}[-]?\d{4}\b"),
    "credit_card": re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
    "api_key": re.compile(r"(sk-[a-zA-Z0-9]{20,}|pk_[a-zA-Z0-9]{20,})"),
}

# Keys that should always be masked
_SENSITIVE_KEYS = frozenset({
    "password", "password_hash", "secret", "token", "api_key", "apikey",
    "access_token", "refresh_token", "authorization", "auth", "credential",
    "ssn", "social_security", "credit_card", "card_number", "cvv", "cvc"
})


def mask_pii(value: str, visible_chars: int = 3) -> str:
    """Mask a PII value, showing only first few characters.

    Examples:
        "john@example.com" -> "joh***"
        "555-123-4567" -> "555***"
    """
    if not value:
        return ""

    value = str(value)
    if len(value) <= visible_chars:
        return "*" * len(value)

    return value[:visible_chars] + "***"


def mask_email(email: str) -> str:
    """Mask an email address for logging.

    Example: "john.doe@example.com" -> "j***@e***.com"
    """
    if not email or "@" not in email:
        return mask_pii(email)

    local, domain = email.rsplit("@", 1)
    parts = domain.rsplit(".", 1)

    masked_local = local[0] + "***" if local else "***"
    if len(parts) == 2:
        masked_domain = parts[0][0] + "***." + parts[1] if parts[0] else "***." + parts[1]
    else:
        masked_domain = "***"

    return f"{masked_local}@{masked_domain}"


def mask_phone(phone: str) -> str:
    """Mask a phone number for logging.

    Example: "555-123-4567" -> "***-***-4567"
    """
    if not phone:
        return ""

    # Extract only digits
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 4:
        return "***"

    return "***-***-" + digits[-4:]


def _mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively mask sensitive data in a dictionary."""
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        key_lower = key.lower()

        # Check if key indicates sensitive data
        if key_lower in _SENSITIVE_KEYS:
            result[key] = "***REDACTED***"
        elif isinstance(value, dict):
            result[key] = _mask_sensitive_data(value)
        elif isinstance(value, str):
            # Check for patterns in string values
            masked = value
            for pattern_name, pattern in _SENSITIVE_PATTERNS.items():
                if pattern.search(masked):
                    if pattern_name == "email":
                        masked = pattern.sub(lambda m: mask_email(m.group()), masked)
                    elif pattern_name == "phone":
                        masked = pattern.sub(lambda m: mask_phone(m.group()), masked)
                    else:
                        masked = pattern.sub("***REDACTED***", masked)
            result[key] = masked
        else:
            result[key] = value

    return result


def _truncate(value: str, max_length: int = 100) -> str:
    """Truncate a string to max length."""
    if not value:
        return ""
    if len(value) <= max_length:
        return value
    return value[:max_length - 3] + "..."


# ============================================================================
# Webhook Signature Verification
# ============================================================================

def verify_signature_hmac(
    payload: bytes,
    signature: str,
    secret: str,
    algorithm: str = "sha256"
) -> bool:
    """Verify an HMAC signature.

    Args:
        payload: The raw request body
        signature: The signature from the header
        secret: The shared secret
        algorithm: Hash algorithm (sha256, sha1, etc.)

    Returns:
        True if signature is valid
    """
    if not payload or not signature or not secret:
        return False

    hash_func = getattr(hashlib, algorithm, None)
    if not hash_func:
        logger.error(f"Unknown hash algorithm: {algorithm}")
        return False

    expected = hmac.new(
        secret.encode('utf-8'),
        payload,
        hash_func
    ).hexdigest()

    # Handle signatures with algorithm prefix (e.g., "sha256=abc123")
    if "=" in signature:
        _, signature = signature.split("=", 1)

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected.lower(), signature.lower())



def verify_stripe_signature(
    payload: bytes,
    sig_header: str,
    webhook_secret: str,
    tolerance: int = 300
) -> Optional[Dict]:
    """Verify a Stripe webhook signature.

    Args:
        payload: Raw request body
        sig_header: The Stripe-Signature header value
        webhook_secret: The webhook signing secret
        tolerance: Maximum age of the event in seconds

    Returns:
        Parsed signature parts if valid, None if invalid
    """
    if not payload or not sig_header or not webhook_secret:
        return None

    try:
        # Parse signature header
        parts = {}
        for item in sig_header.split(","):
            key, value = item.split("=", 1)
            parts[key.strip()] = value.strip()

        timestamp = int(parts.get("t", 0))
        v1_signature = parts.get("v1", "")

        if not timestamp or not v1_signature:
            return None

        # Check timestamp tolerance
        now = int(datetime.now().timestamp())
        if abs(now - timestamp) > tolerance:
            logger.warning(f"Stripe webhook timestamp too old: {now - timestamp}s")
            return None

        # Compute expected signature
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        expected = hmac.new(
            webhook_secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(expected, v1_signature):
            return parts

        return None

    except Exception as e:
        logger.error(f"Stripe signature verification failed: {e}")
        return None


# ============================================================================
# Security Decorators
# ============================================================================

def audit_action(event_type: str, get_business_id=None):
    """Decorator to automatically log security events for actions.

    Args:
        event_type: The type of security event
        get_business_id: Optional callable to extract business_id from request
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            user = session.get("user") if session else None
            user_id = user.get("id") if user else None

            business_id = None
            if get_business_id:
                try:
                    business_id = get_business_id()
                except Exception:
                    pass
            elif hasattr(g, 'active_business_id'):
                business_id = g.active_business_id

            # Log before action
            log_security_event(
                event_type,
                user_id=user_id,
                business_id=business_id,
                details={"endpoint": request.endpoint if request else None}
            )

            return f(*args, **kwargs)
        return wrapped
    return decorator


# ============================================================================
# Input Sanitization Helpers
# ============================================================================

def sanitize_html(text: str) -> str:
    """Remove all HTML tags from text for safe display.

    Note: For full HTML sanitization, use bleach library instead.
    """
    if not text:
        return ""

    # Remove HTML tags
    return re.sub(r"<[^>]+>", "", text)


def sanitize_for_log(text: str, max_length: int = 500) -> str:
    """Sanitize text for safe logging (remove control chars, truncate)."""
    if not text:
        return ""

    # Remove control characters except newline and tab
    cleaned = "".join(
        c if c in ('\n', '\t') or (ord(c) >= 32 and ord(c) < 127)
        else ' '
        for c in text
    )

    # Truncate
    return _truncate(cleaned, max_length)


# ============================================================================
# Rate Limiting Helpers
# ============================================================================

# Simple in-memory rate limiter (use Redis for production multi-instance)
_rate_limits: Dict[str, Dict] = {}


def check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int = 60
) -> Tuple[bool, int]:
    """Check if a rate limit has been exceeded.

    Args:
        key: Unique identifier (e.g., "api:tenant_key" or "login:ip")
        limit: Maximum requests allowed in window
        window_seconds: Time window in seconds

    Returns:
        (is_allowed, remaining_requests)
    """
    from datetime import timedelta

    now = datetime.now()
    data = _rate_limits.get(key)

    if not data or now > data.get("window_end", now):
        # Start new window
        _rate_limits[key] = {
            "count": 1,
            "window_end": now + timedelta(seconds=window_seconds)
        }
        return True, limit - 1

    # Increment counter
    data["count"] = data.get("count", 0) + 1

    remaining = limit - data["count"]
    if remaining < 0:
        remaining = 0

    return data["count"] <= limit, remaining


def reset_rate_limit(key: str) -> None:
    """Reset a rate limit counter."""
    if key in _rate_limits:
        del _rate_limits[key]
