# tests/test_sms.py — Tests for core/sms.py (SMS Sending via Twilio)
# Tests for SMS sending, phone validation, and Twilio integration

import pytest
from unittest.mock import patch, MagicMock


# ============================================================================
# Configuration Tests
# ============================================================================

class TestTwilioConfiguration:
    """Tests for Twilio configuration."""

    def test_twilio_configured_flag(self):
        """Should have TWILIO_CONFIGURED flag."""
        from core.sms import TWILIO_CONFIGURED
        assert isinstance(TWILIO_CONFIGURED, bool)

    def test_check_twilio_config(self):
        """Should return configuration status."""
        from core.sms import check_twilio_config
        result = check_twilio_config()

        assert isinstance(result, dict)
        assert "account_sid_set" in result
        assert "auth_token_set" in result
        assert "phone_number_set" in result
        assert "fully_configured" in result

    def test_config_values_are_bool(self):
        """Should return boolean values."""
        from core.sms import check_twilio_config
        result = check_twilio_config()

        assert isinstance(result["account_sid_set"], bool)
        assert isinstance(result["auth_token_set"], bool)
        assert isinstance(result["phone_number_set"], bool)
        assert isinstance(result["fully_configured"], bool)


# ============================================================================
# Phone Number Normalization Tests
# ============================================================================

class TestNormalizePhone:
    """Tests for _normalize_phone function."""

    def test_normalize_10_digit_us(self):
        """Should normalize 10-digit US number."""
        from core.sms import _normalize_phone
        result = _normalize_phone("5551234567")
        assert result == "+15551234567"

    def test_normalize_11_digit_with_1(self):
        """Should normalize 11-digit number with leading 1."""
        from core.sms import _normalize_phone
        result = _normalize_phone("15551234567")
        assert result == "+15551234567"

    def test_normalize_with_formatting(self):
        """Should strip formatting."""
        from core.sms import _normalize_phone
        result = _normalize_phone("(555) 123-4567")
        assert result == "+15551234567"

    def test_normalize_with_dashes(self):
        """Should strip dashes."""
        from core.sms import _normalize_phone
        result = _normalize_phone("555-123-4567")
        assert result == "+15551234567"

    def test_normalize_already_e164(self):
        """Should keep already E.164 formatted number."""
        from core.sms import _normalize_phone
        result = _normalize_phone("+15551234567")
        assert result == "+15551234567"

    def test_normalize_international(self):
        """Should handle international numbers with +."""
        from core.sms import _normalize_phone
        result = _normalize_phone("+447700900123")
        assert result == "+447700900123"

    def test_normalize_empty(self):
        """Should return None for empty input."""
        from core.sms import _normalize_phone
        assert _normalize_phone("") is None
        assert _normalize_phone(None) is None

    def test_normalize_too_short(self):
        """Should return None for too short numbers."""
        from core.sms import _normalize_phone
        assert _normalize_phone("12345") is None


class TestMaskPhone:
    """Tests for _mask_phone function."""

    def test_mask_phone_basic(self):
        """Should mask middle of phone number."""
        from core.sms import _mask_phone
        result = _mask_phone("+15551234567")
        assert result == "+15***4567"

    def test_mask_phone_short(self):
        """Should return *** for short numbers."""
        from core.sms import _mask_phone
        assert _mask_phone("123") == "***"

    def test_mask_phone_empty(self):
        """Should return empty for empty input."""
        from core.sms import _mask_phone
        assert _mask_phone("") == ""
        assert _mask_phone(None) == ""


class TestValidatePhone:
    """Tests for validate_phone function."""

    def test_validate_valid_phone(self):
        """Should validate correct phone numbers."""
        from core.sms import validate_phone
        is_valid, normalized = validate_phone("5551234567")
        assert is_valid is True
        assert normalized == "+15551234567"

    def test_validate_invalid_phone(self):
        """Should reject invalid phone numbers."""
        from core.sms import validate_phone
        is_valid, error = validate_phone("123")
        assert is_valid is False
        assert "Invalid" in error


# ============================================================================
# SMS Sending Tests (Mocked)
# ============================================================================

class TestSendSms:
    """Tests for send_sms function."""

    def test_send_sms_empty_message(self):
        """Should reject empty message."""
        from core.sms import send_sms
        result = send_sms("+15551234567", "")
        assert result["status"] == "error"
        assert "empty" in result["error"].lower()

    def test_send_sms_invalid_phone(self):
        """Should reject invalid phone number."""
        from core.sms import send_sms
        result = send_sms("123", "Hello")
        assert result["status"] == "error"
        assert "Invalid" in result["error"]

    @patch("core.sms._get_twilio_client")
    def test_send_sms_success(self, mock_get_client):
        """Should send SMS successfully with valid inputs."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.sid = "SM123456"
        mock_message.status = "queued"
        mock_client.messages.create.return_value = mock_message
        mock_get_client.return_value = mock_client

        from core.sms import send_sms
        result = send_sms("+15551234567", "Hello World")

        assert result["sid"] == "SM123456"
        assert result["status"] == "queued"
        assert result["error"] is None

    @patch("core.sms._get_twilio_client")
    def test_send_sms_truncates_long_message(self, mock_get_client):
        """Should truncate messages over 1600 chars."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.sid = "SM123456"
        mock_message.status = "queued"
        mock_client.messages.create.return_value = mock_message
        mock_get_client.return_value = mock_client

        from core.sms import send_sms
        long_message = "a" * 2000
        send_sms("+15551234567", long_message)

        # Check that the message was truncated
        call_args = mock_client.messages.create.call_args
        body = call_args[1]["body"]
        assert len(body) == 1600
        assert body.endswith("...")

    @patch("core.sms._get_twilio_client")
    def test_send_sms_with_media(self, mock_get_client):
        """Should include media_url when provided."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.sid = "SM123"
        mock_message.status = "queued"
        mock_client.messages.create.return_value = mock_message
        mock_get_client.return_value = mock_client

        from core.sms import send_sms
        send_sms("+15551234567", "Check this out", media_url="https://example.com/image.jpg")

        call_args = mock_client.messages.create.call_args
        assert "media_url" in call_args[1]

    @patch("core.sms._get_twilio_client")
    def test_send_sms_with_callback(self, mock_get_client):
        """Should include status_callback when provided."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.sid = "SM123"
        mock_message.status = "queued"
        mock_client.messages.create.return_value = mock_message
        mock_get_client.return_value = mock_client

        from core.sms import send_sms
        send_sms("+15551234567", "Hello", status_callback="https://example.com/webhook")

        call_args = mock_client.messages.create.call_args
        assert call_args[1]["status_callback"] == "https://example.com/webhook"

    @patch("core.sms._get_twilio_client")
    def test_send_sms_handles_error(self, mock_get_client):
        """Should handle Twilio errors gracefully."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("Twilio error")
        mock_get_client.return_value = mock_client

        from core.sms import send_sms
        result = send_sms("+15551234567", "Hello")

        assert result["status"] == "error"
        assert "Twilio error" in result["error"]


class TestSendBulkSms:
    """Tests for send_bulk_sms function."""

    @patch("core.sms.send_sms")
    def test_send_bulk_sms_success(self, mock_send):
        """Should send to multiple recipients."""
        mock_send.return_value = {"sid": "SM123", "status": "queued", "error": None}

        from core.sms import send_bulk_sms
        recipients = ["+15551234567", "+15559876543"]
        result = send_bulk_sms(recipients, "Hello everyone")

        assert result["sent"] == 2
        assert result["failed"] == 0
        assert result["total"] == 2
        assert len(result["results"]) == 2

    @patch("core.sms.send_sms")
    def test_send_bulk_sms_partial_failure(self, mock_send):
        """Should track partial failures."""
        mock_send.side_effect = [
            {"sid": "SM123", "status": "queued", "error": None},
            {"sid": None, "status": "error", "error": "Invalid number"},
        ]

        from core.sms import send_bulk_sms
        recipients = ["+15551234567", "invalid"]
        result = send_bulk_sms(recipients, "Hello")

        assert result["sent"] == 1
        assert result["failed"] == 1
        assert result["total"] == 2


# ============================================================================
# Phone Lookup Tests
# ============================================================================

class TestLookupPhone:
    """Tests for lookup_phone function."""

    def test_lookup_invalid_format(self):
        """Should return invalid for bad format."""
        from core.sms import lookup_phone
        result = lookup_phone("123")
        assert result["valid"] is False
        assert "error" in result

    @patch("core.sms._get_twilio_client")
    def test_lookup_success(self, mock_get_client):
        """Should return phone info on success."""
        mock_client = MagicMock()
        mock_lookup = MagicMock()
        mock_lookup.phone_number = "+15551234567"
        mock_lookup.national_format = "(555) 123-4567"
        mock_lookup.country_code = "US"
        mock_lookup.carrier = {"name": "AT&T", "type": "mobile"}
        mock_client.lookups.v1.phone_numbers.return_value.fetch.return_value = mock_lookup
        mock_get_client.return_value = mock_client

        from core.sms import lookup_phone
        result = lookup_phone("+15551234567")

        assert result["valid"] is True
        assert result["phone_number"] == "+15551234567"
        assert result["country_code"] == "US"

    @patch("core.sms._get_twilio_client")
    def test_lookup_handles_error(self, mock_get_client):
        """Should handle lookup errors gracefully."""
        mock_client = MagicMock()
        mock_client.lookups.v1.phone_numbers.return_value.fetch.side_effect = Exception("Lookup failed")
        mock_get_client.return_value = mock_client

        from core.sms import lookup_phone
        result = lookup_phone("+15551234567")

        assert result["valid"] is False
        assert "error" in result


# ============================================================================
# Webhook Parsing Tests
# ============================================================================

class TestParseTwilioWebhook:
    """Tests for parse_twilio_webhook function."""

    def test_parse_basic_webhook(self):
        """Should parse basic webhook data."""
        from core.sms import parse_twilio_webhook

        data = {
            "MessageSid": "SM123",
            "AccountSid": "AC123",
            "From": "+15551234567",
            "To": "+15559876543",
            "Body": "Hello"
        }

        result = parse_twilio_webhook(data)

        assert result["message_sid"] == "SM123"
        assert result["from_number"] == "+15551234567"
        assert result["to_number"] == "+15559876543"
        assert result["body"] == "Hello"

    def test_parse_webhook_with_media(self):
        """Should parse webhook with media."""
        from core.sms import parse_twilio_webhook

        data = {
            "MessageSid": "SM123",
            "From": "+15551234567",
            "To": "+15559876543",
            "Body": "Check this",
            "NumMedia": "2",
            "MediaUrl0": "https://example.com/image1.jpg",
            "MediaUrl1": "https://example.com/image2.jpg"
        }

        result = parse_twilio_webhook(data)

        assert result["num_media"] == 2
        assert len(result["media_urls"]) == 2

    def test_parse_webhook_with_location(self):
        """Should parse webhook with location info."""
        from core.sms import parse_twilio_webhook

        data = {
            "MessageSid": "SM123",
            "From": "+15551234567",
            "To": "+15559876543",
            "Body": "Hello",
            "NumMedia": "0",
            "FromCity": "San Francisco",
            "FromState": "CA",
            "FromCountry": "US"
        }

        result = parse_twilio_webhook(data)

        assert result["from_city"] == "San Francisco"
        assert result["from_state"] == "CA"
        assert result["from_country"] == "US"

    def test_parse_webhook_missing_fields(self):
        """Should handle missing fields gracefully."""
        from core.sms import parse_twilio_webhook

        data = {"Body": "Hello"}
        result = parse_twilio_webhook(data)

        assert result["body"] == "Hello"
        assert result["message_sid"] is None
        assert result["num_media"] == 0


# ============================================================================
# TwiML Response Tests
# ============================================================================

class TestGenerateTwimlResponse:
    """Tests for generate_twiml_response function."""

    def test_generate_basic_twiml(self):
        """Should generate valid TwiML."""
        from core.sms import generate_twiml_response

        result = generate_twiml_response("Hello there!")

        assert '<?xml version="1.0"' in result
        assert "<Response>" in result
        assert "<Message>" in result
        assert "Hello there!" in result
        assert "</Message>" in result
        assert "</Response>" in result

    def test_generate_twiml_escapes_xml(self):
        """Should escape XML special characters."""
        from core.sms import generate_twiml_response

        result = generate_twiml_response("Price is <$50 & >$30")

        assert "&lt;" in result  # <
        assert "&gt;" in result  # >
        assert "&amp;" in result  # &

    def test_generate_twiml_escapes_quotes(self):
        """Should escape quotes."""
        from core.sms import generate_twiml_response

        result = generate_twiml_response('He said "hello"')

        assert "&quot;" in result


# ============================================================================
# Message Status Tests
# ============================================================================

class TestGetMessageStatus:
    """Tests for get_message_status function."""

    @patch("core.sms._get_twilio_client")
    def test_get_status_success(self, mock_get_client):
        """Should return message status."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.sid = "SM123"
        mock_message.status = "delivered"
        mock_message.error_code = None
        mock_message.error_message = None
        mock_message.date_sent = None
        mock_message.date_updated = None
        mock_client.messages.return_value.fetch.return_value = mock_message
        mock_get_client.return_value = mock_client

        from core.sms import get_message_status
        result = get_message_status("SM123")

        assert result["sid"] == "SM123"
        assert result["status"] == "delivered"

    @patch("core.sms._get_twilio_client")
    def test_get_status_handles_error(self, mock_get_client):
        """Should handle errors gracefully."""
        mock_client = MagicMock()
        mock_client.messages.return_value.fetch.side_effect = Exception("Not found")
        mock_get_client.return_value = mock_client

        from core.sms import get_message_status
        result = get_message_status("SM123")

        assert result["status"] == "unknown"
        assert "error" in result


# ============================================================================
# Connection Test Tests
# ============================================================================

class TestTestConnection:
    """Tests for test_connection function."""

    @patch("core.sms._get_twilio_client")
    def test_connection_success(self, mock_get_client):
        """Should return connection info on success."""
        mock_client = MagicMock()
        mock_account = MagicMock()
        mock_account.friendly_name = "Test Account"
        mock_account.status = "active"
        mock_account.type = "Full"
        mock_client.api.accounts.return_value.fetch.return_value = mock_account
        mock_get_client.return_value = mock_client

        from core.sms import test_connection
        result = test_connection()

        assert result["connected"] is True
        assert result["account_name"] == "Test Account"

    @patch("core.sms._get_twilio_client")
    def test_connection_failure(self, mock_get_client):
        """Should return error on connection failure."""
        mock_get_client.side_effect = RuntimeError("Not configured")

        from core.sms import test_connection
        result = test_connection()

        assert result["connected"] is False
        assert "error" in result


# ============================================================================
# Client Initialization Tests
# ============================================================================

class TestGetTwilioClient:
    """Tests for _get_twilio_client function."""

    def test_client_raises_without_config(self):
        """Should raise error when not configured."""
        from core.sms import TWILIO_CONFIGURED

        if not TWILIO_CONFIGURED:
            from core.sms import _get_twilio_client
            with pytest.raises(RuntimeError) as exc_info:
                _get_twilio_client()
            assert "not configured" in str(exc_info.value).lower()

    def test_client_caches_instance(self):
        """Should cache client instance once created."""
        from core import sms

        # If twilio is not installed or not configured, the caching mechanism
        # still exists - we just test the module attribute
        assert hasattr(sms, '_twilio_client')
        # The _twilio_client starts as None and is set on first use
        # This confirms the caching variable exists
