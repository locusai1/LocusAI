# tests/test_mailer.py — mailer headers + deliverability extras

from unittest.mock import MagicMock, patch

import pytest


def _sent_message(**kwargs):
    """Call send_email with SMTP mocked and return the EmailMessage sent."""
    import core.mailer as mailer

    captured = {}

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, *a, **k):
            pass

        def login(self, *a, **k):
            pass

        def send_message(self, msg):
            captured["msg"] = msg

    with patch.object(mailer, "SMTP_HOST", "smtp.example.com"), patch.object(
        mailer, "SMTP_FROM", "LocusAI <hello@locusai.co.uk>"
    ), patch.object(mailer, "SMTP_TLS", True), patch.object(
        mailer, "SMTP_USER", "u"
    ), patch.object(mailer, "SMTP_PASS", "p"), patch(
        "core.mailer.smtplib.SMTP", FakeSMTP
    ):
        ok = mailer.send_email("dest@example.com", "Subject", "Body", **kwargs)
    assert ok is True
    return captured["msg"]


class TestBaseHeaders:
    def test_sets_date_and_message_id(self):
        msg = _sent_message()
        assert msg["Date"]
        assert msg["Message-ID"] and msg["Message-ID"].endswith("@locusai.co.uk>")

    def test_plaintext_body(self):
        msg = _sent_message()
        assert msg.get_content_type() == "text/plain"
        assert "Body" in msg.get_content()

    def test_no_unsubscribe_by_default(self):
        msg = _sent_message()
        assert msg["List-Unsubscribe"] is None
        assert msg["Auto-Submitted"] is None


class TestAutomatedMail:
    def test_auto_generated_sets_headers(self):
        msg = _sent_message(auto_generated=True)
        assert msg["Auto-Submitted"] == "auto-generated"
        # Default mailto unsubscribe derived from From domain.
        assert "mailto:unsubscribe@locusai.co.uk" in msg["List-Unsubscribe"]

    def test_one_click_unsubscribe_url(self):
        msg = _sent_message(list_unsubscribe_url="https://locusai.co.uk/u/abc")
        assert "<https://locusai.co.uk/u/abc>" in msg["List-Unsubscribe"]
        assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"

    def test_reply_to(self):
        msg = _sent_message(reply_to="owner@shop.com")
        assert msg["Reply-To"] == "owner@shop.com"


class TestCompat:
    def test_to_alias_accepted(self):
        """core/reminders.py historically calls send_email(to=...)."""
        import core.mailer as mailer

        with patch.object(mailer, "SMTP_HOST", ""):
            # SMTP not configured -> log path, still returns True and accepts `to`.
            assert mailer.send_email(to_email=None, subject="s", body="b", to="x@y.com") is True

    def test_missing_recipient_raises(self):
        import core.mailer as mailer

        with patch.object(mailer, "SMTP_HOST", ""):
            with pytest.raises(ValueError):
                mailer.send_email(None, "s", "b")
