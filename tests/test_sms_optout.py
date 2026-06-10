# tests/test_sms_optout.py — TCPA STOP/START opt-out handling

from unittest.mock import patch


class TestClassify:
    def test_stop_keywords(self):
        from core.sms import classify_sms_command
        for w in ["STOP", "stop", " Stop ", "UNSUBSCRIBE", "QUIT", "END", "OPTOUT"]:
            assert classify_sms_command(w) == "stop"

    def test_start_keywords(self):
        from core.sms import classify_sms_command
        for w in ["START", "start", "UNSTOP", "SUBSCRIBE", "OPTIN"]:
            assert classify_sms_command(w) == "start"

    def test_help(self):
        from core.sms import classify_sms_command
        assert classify_sms_command("HELP") == "help"
        assert classify_sms_command("info") == "help"

    def test_cancel_and_yes_are_not_optout(self):
        """CANCEL is appointment-cancel; YES is conversational — never opt-out."""
        from core.sms import classify_sms_command
        assert classify_sms_command("CANCEL") is None
        assert classify_sms_command("YES") is None
        assert classify_sms_command("I'd like to book") is None


class TestOptOutRegistry:
    def test_record_and_clear(self, test_db):
        from core import sms
        with patch("core.db.DB_PATH", test_db):
            phone = "+14155550100"
            assert sms.is_opted_out(phone) is False
            assert sms.record_opt_out(phone) is True
            assert sms.is_opted_out(phone) is True
            # idempotent re-record
            assert sms.record_opt_out(phone) is True
            assert sms.clear_opt_out(phone) is True
            assert sms.is_opted_out(phone) is False

    def test_send_sms_suppresses_opted_out(self, test_db):
        from core import sms
        with patch("core.db.DB_PATH", test_db):
            phone = "+14155550101"
            sms.record_opt_out(phone)
            result = sms.send_sms(phone, "hello there")
            assert result["status"] == "suppressed"

    def test_allow_opted_out_bypasses_suppression(self, test_db):
        from core import sms
        with patch("core.db.DB_PATH", test_db):
            phone = "+14155550102"
            sms.record_opt_out(phone)
            # Telnyx not configured in tests, so it won't actually send — but it
            # must get PAST the suppression check (status != 'suppressed').
            result = sms.send_sms(phone, "STOP confirmation", allow_opted_out=True)
            assert result["status"] != "suppressed"


class TestWebhookOptOut:
    def _inbound(self, body, to="+442046203253", frm="+14155550103"):
        return {
            "data": {
                "event_type": "message.received",
                "payload": {
                    "id": "msg_1",
                    "from": {"phone_number": frm},
                    "to": [{"phone_number": to}],
                    "text": body,
                },
            }
        }

    def test_stop_records_opt_out(self, client, sample_business, test_db):
        from core import sms
        with patch("core.db.DB_PATH", test_db):
            resp = client.post("/api/sms/webhook", json=self._inbound("STOP"))
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "opted_out"
            assert sms.is_opted_out("+14155550103") is True

    def test_start_clears_opt_out(self, client, sample_business, test_db):
        from core import sms
        with patch("core.db.DB_PATH", test_db):
            sms.record_opt_out("+14155550103")
            resp = client.post("/api/sms/webhook", json=self._inbound("START"))
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "opted_in"
            assert sms.is_opted_out("+14155550103") is False
