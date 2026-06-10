# tests/test_digest.py — weekly AI performance digest

from unittest.mock import patch
import pytest


def _seed_activity(test_db, business_id):
    from core.db import get_conn, create_session, create_appointment
    with get_conn() as con:
        # sessions across channels
        for ch in ("voice", "voice", "web", "sms"):
            con.execute("INSERT INTO sessions (business_id, channel) VALUES (?, ?)", (business_id, ch))
        # voice calls with intents + containment
        con.execute("INSERT INTO voice_calls (business_id, retell_call_id, direction, call_intent, containment) "
                    "VALUES (?, 'c1', 'inbound', 'booking', 1)", (business_id,))
        con.execute("INSERT INTO voice_calls (business_id, retell_call_id, direction, call_intent, containment) "
                    "VALUES (?, 'c2', 'inbound', 'booking', 1)", (business_id,))
        con.execute("INSERT INTO voice_calls (business_id, retell_call_id, direction, call_intent, containment) "
                    "VALUES (?, 'c3', 'inbound', 'hours', 0)", (business_id,))
        con.execute("INSERT INTO escalations (business_id, reason, status) VALUES (?, 'angry', 'pending')", (business_id,))
        con.commit()
    create_appointment(business_id=business_id, customer_name="A", phone="+14150000001",
                       service="Haircut", start_at="2026-07-01 10:00", status="confirmed")


class TestBuildDigest:
    def test_aggregates(self, test_db, sample_business):
        from core import digest
        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            _seed_activity(test_db, bid)
            d = digest.build_digest(bid)
        assert d["calls"] == 2
        assert d["chats"] == 1
        assert d["sms"] == 1
        assert d["total_conversations"] == 4
        assert d["bookings"] == 1
        assert d["escalations"] == 1
        assert d["est_revenue"] == 25.0   # Haircut = £25
        assert d["top_intents"][0]["intent"] == "booking"
        assert d["containment_rate"] == 67  # 2/3

    def test_render_contains_numbers(self, test_db, sample_business):
        from core import digest
        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            _seed_activity(test_db, bid)
            d = digest.build_digest(bid)
            text = digest.render_digest_text(sample_business["name"], d)
        assert sample_business["name"] in text
        assert "4" in text and "booking" in text


class TestSendDigest:
    def _link(self, test_db, user_id, business_id):
        from core.db import get_conn
        with get_conn() as con:
            con.execute("INSERT OR IGNORE INTO business_users (user_id, business_id) VALUES (?, ?)",
                        (user_id, business_id))
            con.commit()

    def test_sends_when_activity(self, test_db, sample_business, sample_user):
        from core import digest
        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            self._link(test_db, sample_user["id"], bid)
            _seed_activity(test_db, bid)
            with patch("core.mailer.send_email", return_value=True) as mock_send:
                assert digest.send_digest(bid) is True
                mock_send.assert_called_once()
                # sent to the owner's email
                assert mock_send.call_args[0][0] == sample_user["email"]

    def test_skips_when_no_activity(self, test_db, sample_business, sample_user):
        from core import digest
        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            self._link(test_db, sample_user["id"], bid)
            with patch("core.mailer.send_email", return_value=True) as mock_send:
                assert digest.send_digest(bid) is False
                mock_send.assert_not_called()

    def test_respects_opt_out(self, test_db, sample_business, sample_user):
        from core import digest
        from core.db import get_conn
        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            self._link(test_db, sample_user["id"], bid)
            _seed_activity(test_db, bid)
            with get_conn() as con:
                con.execute("UPDATE businesses SET settings_json=? WHERE id=?",
                            ('{"weekly_digest_enabled": false}', bid))
                con.commit()
            with patch("core.mailer.send_email", return_value=True) as mock_send:
                assert digest.send_digest(bid) is False
                mock_send.assert_not_called()

    def test_weekly_dedupe(self, test_db, sample_business, sample_user):
        from core import digest
        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            self._link(test_db, sample_user["id"], bid)
            _seed_activity(test_db, bid)
            with patch("core.mailer.send_email", return_value=True) as mock_send:
                assert digest.send_weekly_digests() >= 1
                first = mock_send.call_count
                # second run same week -> no additional sends
                digest.send_weekly_digests()
                assert mock_send.call_count == first
