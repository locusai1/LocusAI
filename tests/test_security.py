# tests/test_security.py — Tests for core/security.py (Security Utilities)
# Tests for audit logging, data masking, webhook verification, and security helpers

import pytest
import hashlib
import hmac
import time
import base64
from unittest.mock import patch, MagicMock
from datetime import datetime


# ============================================================================
# SecurityEvent Constants Tests
# ============================================================================

class TestSecurityEventConstants:
    """Tests for SecurityEvent constants class."""

    def test_authentication_events_defined(self):
        """Should have authentication event constants."""
        from core.security import SecurityEvent
        assert SecurityEvent.LOGIN_SUCCESS == "login_success"
        assert SecurityEvent.LOGIN_FAILED == "login_failed"
        assert SecurityEvent.LOGOUT == "logout"
        assert SecurityEvent.PASSWORD_CHANGE == "password_change"

    def test_authorization_events_defined(self):
        """Should have authorization event constants."""
        from core.security import SecurityEvent
        assert SecurityEvent.PERMISSION_DENIED == "permission_denied"
        assert SecurityEvent.TENANT_ACCESS_DENIED == "tenant_access_denied"
        assert SecurityEvent.ADMIN_ACTION == "admin_action"

    def test_data_events_defined(self):
        """Should have data event constants."""
        from core.security import SecurityEvent
        assert SecurityEvent.DATA_EXPORT == "data_export"
        assert SecurityEvent.DATA_DELETION == "data_deletion"
        assert SecurityEvent.PII_ACCESS == "pii_access"

    def test_api_events_defined(self):
        """Should have API event constants."""
        from core.security import SecurityEvent
        assert SecurityEvent.API_KEY_CREATED == "api_key_created"
        assert SecurityEvent.RATE_LIMIT_EXCEEDED == "rate_limit_exceeded"
        assert SecurityEvent.WEBHOOK_RECEIVED == "webhook_received"

    def test_security_events_defined(self):
        """Should have security event constants."""
        from core.security import SecurityEvent
        assert SecurityEvent.SUSPICIOUS_ACTIVITY == "suspicious_activity"
        assert SecurityEvent.LOCKOUT_TRIGGERED == "lockout_triggered"
        assert SecurityEvent.CSRF_VIOLATION == "csrf_violation"


# ============================================================================
# Data Masking Tests
# ============================================================================

class TestMaskPii:
    """Tests for mask_pii function."""

    def test_mask_basic_string(self):
        """Should mask string showing only first few characters."""
        from core.security import mask_pii
        result = mask_pii("johndoe")
        assert result == "joh***"

    def test_mask_empty_string(self):
        """Should return empty string for empty input."""
        from core.security import mask_pii
        assert mask_pii("") == ""
        assert mask_pii(None) == ""

    def test_mask_short_string(self):
        """Should mask entire short string."""
        from core.security import mask_pii
        assert mask_pii("ab", visible_chars=3) == "**"

    def test_mask_custom_visible_chars(self):
        """Should respect custom visible_chars parameter."""
        from core.security import mask_pii
        result = mask_pii("johndoe", visible_chars=5)
        assert result == "johnd***"

    def test_mask_phone_number(self):
        """Should mask phone number."""
        from core.security import mask_pii
        result = mask_pii("5551234567")
        assert result == "555***"


class TestMaskEmail:
    """Tests for mask_email function."""

    def test_mask_email_basic(self):
        """Should mask email keeping structure visible."""
        from core.security import mask_email
        result = mask_email("john.doe@example.com")
        assert result == "j***@e***.com"

    def test_mask_email_short_local(self):
        """Should handle short local part."""
        from core.security import mask_email
        result = mask_email("j@example.com")
        assert "@" in result
        assert "***" in result

    def test_mask_email_empty(self):
        """Should handle empty email."""
        from core.security import mask_email
        assert mask_email("") == ""
        assert mask_email(None) == ""

    def test_mask_email_no_at_sign(self):
        """Should handle string without @ symbol."""
        from core.security import mask_email
        result = mask_email("notanemail")
        assert "***" in result

    def test_mask_email_preserves_tld(self):
        """Should preserve top-level domain."""
        from core.security import mask_email
        result = mask_email("user@domain.org")
        assert result.endswith(".org")


class TestMaskPhone:
    """Tests for mask_phone function."""

    def test_mask_phone_basic(self):
        """Should mask phone showing last 4 digits."""
        from core.security import mask_phone
        result = mask_phone("555-123-4567")
        assert result == "***-***-4567"

    def test_mask_phone_digits_only(self):
        """Should handle digits-only phone."""
        from core.security import mask_phone
        result = mask_phone("5551234567")
        assert result == "***-***-4567"

    def test_mask_phone_empty(self):
        """Should handle empty phone."""
        from core.security import mask_phone
        assert mask_phone("") == ""
        assert mask_phone(None) == ""

    def test_mask_phone_short(self):
        """Should handle short phone numbers."""
        from core.security import mask_phone
        result = mask_phone("123")
        assert result == "***"

    def test_mask_phone_international(self):
        """Should handle international format."""
        from core.security import mask_phone
        result = mask_phone("+1-555-123-4567")
        assert "4567" in result


class TestMaskSensitiveData:
    """Tests for _mask_sensitive_data function."""

    def test_mask_password_key(self):
        """Should mask password fields."""
        from core.security import _mask_sensitive_data
        data = {"username": "john", "password": "secret123"}
        result = _mask_sensitive_data(data)
        assert result["password"] == "***REDACTED***"
        assert result["username"] == "john"

    def test_mask_token_key(self):
        """Should mask token fields."""
        from core.security import _mask_sensitive_data
        data = {"access_token": "abc123xyz", "name": "test"}
        result = _mask_sensitive_data(data)
        assert result["access_token"] == "***REDACTED***"

    def test_mask_nested_dict(self):
        """Should mask nested dictionaries."""
        from core.security import _mask_sensitive_data
        data = {"user": {"name": "John", "password": "secret"}}
        result = _mask_sensitive_data(data)
        assert result["user"]["password"] == "***REDACTED***"
        assert result["user"]["name"] == "John"

    def test_mask_email_pattern_in_value(self):
        """Should mask email patterns in values."""
        from core.security import _mask_sensitive_data
        data = {"info": "Contact john@example.com for help"}
        result = _mask_sensitive_data(data)
        assert "j***@e***.com" in result["info"]

    def test_mask_phone_pattern_in_value(self):
        """Should mask phone patterns in values."""
        from core.security import _mask_sensitive_data
        data = {"message": "Call me at 555-123-4567"}
        result = _mask_sensitive_data(data)
        assert "555-123-4567" not in result["message"]
        assert "4567" in result["message"]

    def test_mask_api_key_pattern(self):
        """Should mask API key patterns."""
        from core.security import _mask_sensitive_data
        data = {"key": "sk-abcdefghijklmnopqrstuvwxyz"}
        result = _mask_sensitive_data(data)
        assert "sk-abcdef" not in result["key"]

    def test_preserve_non_sensitive_data(self):
        """Should not modify non-sensitive data."""
        from core.security import _mask_sensitive_data
        data = {"name": "John", "age": 30, "active": True}
        result = _mask_sensitive_data(data)
        assert result == data


class TestTruncate:
    """Tests for _truncate helper function."""

    def test_truncate_short_string(self):
        """Should not truncate short strings."""
        from core.security import _truncate
        assert _truncate("hello", 100) == "hello"

    def test_truncate_long_string(self):
        """Should truncate long strings with ellipsis."""
        from core.security import _truncate
        long_str = "a" * 200
        result = _truncate(long_str, 100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_truncate_empty_string(self):
        """Should handle empty string."""
        from core.security import _truncate
        assert _truncate("", 100) == ""
        assert _truncate(None, 100) == ""


# ============================================================================
# Webhook Signature Verification Tests
# ============================================================================

class TestVerifySignatureHmac:
    """Tests for verify_signature_hmac function."""

    def test_verify_valid_signature(self):
        """Should verify valid HMAC signature."""
        from core.security import verify_signature_hmac

        payload = b"test payload"
        secret = "my-secret-key"
        signature = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        assert verify_signature_hmac(payload, signature, secret) is True

    def test_verify_invalid_signature(self):
        """Should reject invalid signature."""
        from core.security import verify_signature_hmac

        payload = b"test payload"
        secret = "my-secret-key"
        wrong_signature = "abc123"

        assert verify_signature_hmac(payload, wrong_signature, secret) is False

    def test_verify_signature_with_prefix(self):
        """Should handle signatures with algorithm prefix."""
        from core.security import verify_signature_hmac

        payload = b"test payload"
        secret = "my-secret-key"
        signature = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        # Add prefix like GitHub uses
        assert verify_signature_hmac(payload, f"sha256={signature}", secret) is True

    def test_verify_empty_inputs(self):
        """Should return False for empty inputs."""
        from core.security import verify_signature_hmac

        assert verify_signature_hmac(b"", "sig", "secret") is False
        assert verify_signature_hmac(b"payload", "", "secret") is False
        assert verify_signature_hmac(b"payload", "sig", "") is False

    def test_verify_sha1_algorithm(self):
        """Should support SHA1 algorithm."""
        from core.security import verify_signature_hmac

        payload = b"test"
        secret = "secret"
        signature = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha1
        ).hexdigest()

        assert verify_signature_hmac(payload, signature, secret, algorithm="sha1") is True


class TestVerifyTwilioSignature:
    """Tests for verify_twilio_signature function."""

    def test_verify_twilio_valid(self):
        """Should verify valid Twilio signature."""
        from core.security import verify_twilio_signature

        url = "https://example.com/webhook"
        params = {"Body": "Hello", "From": "+15551234567"}
        auth_token = "test-auth-token"

        # Build Twilio signature manually
        s = url
        for key in sorted(params.keys()):
            s += key + params[key]

        expected = hmac.new(
            auth_token.encode(),
            s.encode(),
            hashlib.sha1
        ).digest()
        signature = base64.b64encode(expected).decode()

        assert verify_twilio_signature(url, params, signature, auth_token) is True

    def test_verify_twilio_invalid(self):
        """Should reject invalid Twilio signature."""
        from core.security import verify_twilio_signature

        url = "https://example.com/webhook"
        params = {"Body": "Hello"}
        auth_token = "test-auth-token"
        wrong_signature = "invalid-signature"

        assert verify_twilio_signature(url, params, wrong_signature, auth_token) is False

    def test_verify_twilio_empty_inputs(self):
        """Should return False for empty inputs."""
        from core.security import verify_twilio_signature

        assert verify_twilio_signature("", {}, "sig", "token") is False
        assert verify_twilio_signature("url", {}, "", "token") is False
        assert verify_twilio_signature("url", {}, "sig", "") is False


class TestVerifyStripeSignature:
    """Tests for verify_stripe_signature function."""

    def test_verify_stripe_valid(self):
        """Should verify valid Stripe signature."""
        from core.security import verify_stripe_signature

        payload = b'{"type": "test"}'
        webhook_secret = "whsec_test123"
        timestamp = int(datetime.now().timestamp())

        # Build Stripe signature
        signed_payload = f"{timestamp}.{payload.decode()}"
        v1_sig = hmac.new(
            webhook_secret.encode(),
            signed_payload.encode(),
            hashlib.sha256
        ).hexdigest()

        sig_header = f"t={timestamp},v1={v1_sig}"

        result = verify_stripe_signature(payload, sig_header, webhook_secret)
        assert result is not None
        assert result["t"] == str(timestamp)

    def test_verify_stripe_expired(self):
        """Should reject expired Stripe signature."""
        from core.security import verify_stripe_signature

        payload = b'{"type": "test"}'
        webhook_secret = "whsec_test123"
        # Timestamp from 10 minutes ago
        timestamp = int(datetime.now().timestamp()) - 600

        signed_payload = f"{timestamp}.{payload.decode()}"
        v1_sig = hmac.new(
            webhook_secret.encode(),
            signed_payload.encode(),
            hashlib.sha256
        ).hexdigest()

        sig_header = f"t={timestamp},v1={v1_sig}"

        result = verify_stripe_signature(payload, sig_header, webhook_secret, tolerance=300)
        assert result is None

    def test_verify_stripe_empty_inputs(self):
        """Should return None for empty inputs."""
        from core.security import verify_stripe_signature

        assert verify_stripe_signature(b"", "sig", "secret") is None
        assert verify_stripe_signature(b"payload", "", "secret") is None
        assert verify_stripe_signature(b"payload", "sig", "") is None

    def test_verify_stripe_malformed_header(self):
        """Should handle malformed signature header."""
        from core.security import verify_stripe_signature

        payload = b'{"type": "test"}'
        result = verify_stripe_signature(payload, "malformed", "secret")
        assert result is None


# ============================================================================
# Input Sanitization Tests
# ============================================================================

class TestSanitizeHtml:
    """Tests for sanitize_html function."""

    def test_remove_basic_tags(self):
        """Should remove HTML tags."""
        from core.security import sanitize_html
        result = sanitize_html("<p>Hello <b>World</b></p>")
        assert result == "Hello World"

    def test_remove_script_tags(self):
        """Should remove script tags (note: removes tags, not content)."""
        from core.security import sanitize_html
        result = sanitize_html("<script>alert('xss')</script>Hello")
        assert "<script>" not in result
        assert "</script>" not in result
        assert "Hello" in result

    def test_empty_string(self):
        """Should handle empty string."""
        from core.security import sanitize_html
        assert sanitize_html("") == ""
        assert sanitize_html(None) == ""

    def test_no_tags(self):
        """Should leave text without tags unchanged."""
        from core.security import sanitize_html
        assert sanitize_html("Hello World") == "Hello World"


class TestSanitizeForLog:
    """Tests for sanitize_for_log function."""

    def test_remove_control_chars(self):
        """Should remove control characters."""
        from core.security import sanitize_for_log
        result = sanitize_for_log("Hello\x00World\x1f")
        assert "\x00" not in result
        assert "\x1f" not in result

    def test_preserve_newlines_tabs(self):
        """Should preserve newlines and tabs."""
        from core.security import sanitize_for_log
        result = sanitize_for_log("Hello\nWorld\tTest")
        assert "\n" in result
        assert "\t" in result

    def test_truncate_long_text(self):
        """Should truncate long text."""
        from core.security import sanitize_for_log
        long_text = "a" * 1000
        result = sanitize_for_log(long_text, max_length=100)
        assert len(result) == 100


# ============================================================================
# Rate Limiting Tests
# ============================================================================

class TestCheckRateLimit:
    """Tests for check_rate_limit function."""

    def test_first_request_allowed(self):
        """Should allow first request."""
        from core.security import check_rate_limit, reset_rate_limit

        key = f"test_rate_limit_{time.time()}"
        reset_rate_limit(key)

        allowed, remaining = check_rate_limit(key, limit=10, window_seconds=60)
        assert allowed is True
        assert remaining == 9

    def test_rate_limit_tracking(self):
        """Should track request count."""
        from core.security import check_rate_limit, reset_rate_limit

        key = f"test_tracking_{time.time()}"
        reset_rate_limit(key)

        for i in range(5):
            allowed, remaining = check_rate_limit(key, limit=10, window_seconds=60)
            assert allowed is True
            assert remaining == 9 - i

    def test_rate_limit_exceeded(self):
        """Should block after limit exceeded."""
        from core.security import check_rate_limit, reset_rate_limit

        key = f"test_exceeded_{time.time()}"
        reset_rate_limit(key)

        # Use up the limit
        for _ in range(5):
            check_rate_limit(key, limit=5, window_seconds=60)

        # Next request should be blocked
        allowed, remaining = check_rate_limit(key, limit=5, window_seconds=60)
        assert allowed is False
        assert remaining == 0

    def test_reset_rate_limit(self):
        """Should reset rate limit counter."""
        from core.security import check_rate_limit, reset_rate_limit

        key = f"test_reset_{time.time()}"

        # Use up some requests
        for _ in range(3):
            check_rate_limit(key, limit=5, window_seconds=60)

        # Reset
        reset_rate_limit(key)

        # Should be back to full limit
        allowed, remaining = check_rate_limit(key, limit=5, window_seconds=60)
        assert allowed is True
        assert remaining == 4


# ============================================================================
# Audit Logging Tests
# ============================================================================

class TestLogSecurityEvent:
    """Tests for log_security_event function."""

    @patch("core.security.security_logger")
    def test_log_basic_event(self, mock_logger):
        """Should log basic security event."""
        from core.security import log_security_event, SecurityEvent

        log_security_event(SecurityEvent.LOGIN_SUCCESS, user_id=1)
        assert mock_logger.log.called

    @patch("core.security.security_logger")
    def test_log_event_with_details(self, mock_logger):
        """Should log event with details."""
        from core.security import log_security_event, SecurityEvent

        log_security_event(
            SecurityEvent.ADMIN_ACTION,
            user_id=1,
            business_id=2,
            details={"action": "delete_user", "target_id": 5}
        )
        assert mock_logger.log.called

    @patch("core.security.security_logger")
    def test_log_event_masks_sensitive_data(self, mock_logger):
        """Should mask sensitive data in details."""
        from core.security import log_security_event, SecurityEvent

        log_security_event(
            SecurityEvent.LOGIN_FAILED,
            details={"email": "user@example.com", "password": "secret123"}
        )
        # Password should be masked
        call_args = str(mock_logger.log.call_args)
        assert "secret123" not in call_args


class TestLogAdminAction:
    """Tests for log_admin_action convenience function."""

    @patch("core.security.log_security_event")
    def test_log_admin_action(self, mock_log):
        """Should log admin action."""
        from core.security import log_admin_action

        with patch("core.security.session", {"user": {"id": 1}}):
            log_admin_action("delete", "user:5")

        assert mock_log.called


class TestLogDataAccess:
    """Tests for log_data_access convenience function."""

    @patch("core.security.log_security_event")
    def test_log_data_access(self, mock_log):
        """Should log data access."""
        from core.security import log_data_access

        with patch("core.security.session", {"user": {"id": 1}}):
            log_data_access("customer", record_id=123, business_id=1)

        assert mock_log.called


# ============================================================================
# Decorator Tests
# ============================================================================

class TestAuditActionDecorator:
    """Tests for @audit_action decorator."""

    @patch("core.security.log_security_event")
    def test_audit_action_decorator(self, mock_log):
        """Should log action when decorated function is called."""
        from core.security import audit_action, SecurityEvent
        from flask import Flask

        app = Flask(__name__)

        @audit_action(SecurityEvent.ADMIN_ACTION)
        def admin_function():
            return "done"

        with app.test_request_context():
            with patch("core.security.session", {"user": {"id": 1}}):
                result = admin_function()

        assert result == "done"
        assert mock_log.called


# ============================================================================
# Sensitive Keys Detection Tests
# ============================================================================

class TestSensitiveKeysDetection:
    """Tests for sensitive key patterns."""

    def test_sensitive_keys_constant(self):
        """Should have _SENSITIVE_KEYS frozenset."""
        from core.security import _SENSITIVE_KEYS

        assert "password" in _SENSITIVE_KEYS
        assert "api_key" in _SENSITIVE_KEYS
        assert "token" in _SENSITIVE_KEYS
        assert "secret" in _SENSITIVE_KEYS
        assert "credit_card" in _SENSITIVE_KEYS

    def test_sensitive_patterns_constant(self):
        """Should have _SENSITIVE_PATTERNS dict."""
        from core.security import _SENSITIVE_PATTERNS

        assert "email" in _SENSITIVE_PATTERNS
        assert "phone" in _SENSITIVE_PATTERNS
        assert "api_key" in _SENSITIVE_PATTERNS
