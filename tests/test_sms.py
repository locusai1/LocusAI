# tests/test_sms.py — Tests for core/sms.py (SMS via Telnyx)

import pytest
from unittest.mock import patch, MagicMock


# ============================================================================
# Configuration Tests
# ============================================================================

class TestTelnyxConfiguration:
    def test_telnyx_configured_flag(self):
        from core.sms import TELNYX_CONFIGURED
        assert isinstance(TELNYX_CONFIGURED, bool)

    def test_check_telnyx_config(self):
        from core.sms import check_telnyx_config
        result = check_telnyx_config()
        assert "api_key_set" in result
        assert "phone_number_set" in result
        assert "fully_configured" in result

    def test_check_telnyx_config_returns_bools(self):
        from core.sms import check_telnyx_config
        result = check_telnyx_config()
        for v in result.values():
            assert isinstance(v, bool)


# ============================================================================
# Phone Number Normalization Tests
# ============================================================================

class TestNormalizePhone:
    def test_normalize_us_10_digits(self):
        from core.sms import _normalize_phone
        assert _normalize_phone("5551234567") == "+15551234567"

    def test_normalize_us_11_digits(self):
        from core.sms import _normalize_phone
        assert _normalize_phone("15551234567") == "+15551234567"

    def test_normalize_e164(self):
        from core.sms import _normalize_phone
        assert _normalize_phone("+15551234567") == "+15551234567"

    def test_normalize_uk_number(self):
        from core.sms import _normalize_phone
        assert _normalize_phone("+442046203253") == "+442046203253"

    def test_normalize_with_dashes(self):
        from core.sms import _normalize_phone
        assert _normalize_phone("555-123-4567") == "+15551234567"

    def test_normalize_with_parens(self):
        from core.sms import _normalize_phone
        assert _normalize_phone("(555) 123-4567") == "+15551234567"

    def test_normalize_invalid(self):
        from core.sms import _normalize_phone
        assert _normalize_phone("123") is None

    def test_normalize_empty(self):
        from core.sms import _normalize_phone
        assert _normalize_phone("") is None


# ============================================================================
# Phone Masking Tests
# ============================================================================

class TestMaskPhone:
    def test_mask_standard(self):
        from core.sms import _mask_phone
        result = _mask_phone("+15551234567")
        assert "***" in result
        assert result.startswith("+15")
        assert result.endswith("4567")

    def test_mask_short(self):
        from core.sms import _mask_phone
        assert _mask_phone("123") == "***"

    def test_mask_empty(self):
        from core.sms import _mask_phone
        assert _mask_phone("") == ""


# ============================================================================
# Validate Phone Tests
# ============================================================================

class TestValidatePhone:
    def test_valid_phone(self):
        from core.sms import validate_phone
        valid, result = validate_phone("+15551234567")
        assert valid is True
        assert result == "+15551234567"

    def test_invalid_phone(self):
        from core.sms import validate_phone
        valid, result = validate_phone("abc")
        assert valid is False


# ============================================================================
# send_sms Tests
# ============================================================================

class TestSendSms:
    def test_send_sms_empty_message(self):
        from core.sms import send_sms
        result = send_sms("+15551234567", "")
        assert result["status"] == "error"
        assert "empty" in result["error"].lower()

    def test_send_sms_invalid_phone(self):
        from core.sms import send_sms
        result = send_sms("123", "Hello")
        assert result["status"] == "error"

    def test_send_sms_not_configured(self):
        from core.sms import send_sms
        with patch("core.sms.TELNYX_CONFIGURED", False):
            result = send_sms("+15551234567", "Hello")
        assert result["status"] == "error"
        assert "not configured" in result["error"].lower()

    @patch("httpx.post")
    def test_send_sms_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"id": "test-uuid-123", "to": [{"status": "queued"}]}
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with patch("core.sms.TELNYX_CONFIGURED", True), \
             patch("core.sms.TELNYX_API_KEY", "test-key"):
            from core.sms import send_sms
            result = send_sms("+15551234567", "Hello World")

        assert result["status"] == "sent"
        assert result["id"] == "test-uuid-123"
        assert result["error"] is None

    @patch("httpx.post")
    def test_send_sms_truncates_long_message(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"id": "x"}}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        long_message = "a" * 1700

        with patch("core.sms.TELNYX_CONFIGURED", True), \
             patch("core.sms.TELNYX_API_KEY", "test-key"):
            from core.sms import send_sms
            send_sms("+15551234567", long_message)

        called_json = mock_post.call_args.kwargs["json"]
        assert len(called_json["text"]) <= 1600

    @patch("httpx.post")
    def test_send_sms_handles_error(self, mock_post):
        mock_post.side_effect = Exception("connection error")

        with patch("core.sms.TELNYX_CONFIGURED", True), \
             patch("core.sms.TELNYX_API_KEY", "test-key"):
            from core.sms import send_sms
            result = send_sms("+15551234567", "Hello")

        assert result["status"] == "error"
        assert "connection error" in result["error"]


# ============================================================================
# send_bulk_sms Tests
# ============================================================================

class TestSendBulkSms:
    @patch("core.sms.send_sms")
    def test_send_bulk_sms_success(self, mock_send):
        mock_send.return_value = {"status": "sent", "id": "x", "error": None}
        recipients = ["+15551234567", "+15559876543"]

        from core.sms import send_bulk_sms
        result = send_bulk_sms(recipients, "Hello everyone")

        assert result["sent"] == 2
        assert result["failed"] == 0
        assert result["total"] == 2

    @patch("core.sms.send_sms")
    def test_send_bulk_sms_partial_failure(self, mock_send):
        mock_send.side_effect = [
            {"status": "sent", "id": "x", "error": None},
            {"status": "error", "id": None, "error": "fail"},
        ]
        recipients = ["+15551234567", "+15559876543"]

        from core.sms import send_bulk_sms
        result = send_bulk_sms(recipients, "Hello")

        assert result["sent"] == 1
        assert result["failed"] == 1


# ============================================================================
# Webhook Parsing Tests
# ============================================================================

class TestParseTelnyxWebhook:
    def test_parse_inbound_sms(self):
        from core.sms import parse_telnyx_webhook

        data = {
            "data": {
                "event_type": "message.received",
                "payload": {
                    "id": "msg-123",
                    "direction": "inbound",
                    "from": {"phone_number": "+15551234567"},
                    "to": [{"phone_number": "+442046203253"}],
                    "text": "Hello there",
                }
            }
        }

        result = parse_telnyx_webhook(data)
        assert result["from_number"] == "+15551234567"
        assert result["to_number"] == "+442046203253"
        assert result["body"] == "Hello there"
        assert result["event_type"] == "message.received"
        assert result["message_id"] == "msg-123"

    def test_parse_empty_webhook(self):
        from core.sms import parse_telnyx_webhook

        result = parse_telnyx_webhook({})
        assert result["from_number"] is None
        assert result["body"] == ""

    def test_parse_missing_to(self):
        from core.sms import parse_telnyx_webhook

        data = {
            "data": {
                "event_type": "message.received",
                "payload": {
                    "from": {"phone_number": "+15551234567"},
                    "to": [],
                    "text": "Hi",
                }
            }
        }

        result = parse_telnyx_webhook(data)
        assert result["to_number"] is None
        assert result["from_number"] == "+15551234567"
