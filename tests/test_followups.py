# tests/test_followups.py — post-call lead follow-up (nurture SMS)

from unittest.mock import patch


def _voice_call(bid, **over):
    base = {
        "id": 101,
        "business_id": bid,
        "direction": "inbound",
        "from_number": "+14155551234",
        "duration_seconds": 60,
        "booking_confirmed": 0,
        "appointment_id": None,
        "booking_discussed": 1,
        "call_summary": "Caller asked about a haircut appointment next week.",
    }
    base.update(over)
    return base


class TestEligibility:
    def test_schedules_for_interested_non_booker(self, test_db, sample_business):
        from core import followups

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            fid = followups.maybe_schedule_lead_followup(_voice_call(bid))
            assert fid is not None
            from core.db import get_conn

            with get_conn() as con:
                row = con.execute("SELECT * FROM lead_followups WHERE id=?", (fid,)).fetchone()
        assert row["status"] == "pending"
        assert row["phone"] == "+14155551234"
        assert "/book/test-business" in row["booking_url"]
        assert "STOP" in row["message"]

    def test_skips_when_already_booked(self, test_db, sample_business):
        from core import followups

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            assert (
                followups.maybe_schedule_lead_followup(_voice_call(bid, booking_confirmed=1))
                is None
            )
            assert (
                followups.maybe_schedule_lead_followup(_voice_call(bid, appointment_id=7)) is None
            )

    def test_skips_short_or_missed_call(self, test_db, sample_business):
        from core import followups

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            assert (
                followups.maybe_schedule_lead_followup(_voice_call(bid, duration_seconds=5)) is None
            )

    def test_skips_outbound(self, test_db, sample_business):
        from core import followups

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            assert (
                followups.maybe_schedule_lead_followup(_voice_call(bid, direction="outbound"))
                is None
            )

    def test_skips_no_booking_interest(self, test_db, sample_business):
        from core import followups

        bid = sample_business["id"]
        vc = _voice_call(bid, booking_discussed=0, call_summary="Caller asked for opening hours.")
        with patch("core.db.DB_PATH", test_db):
            assert followups.maybe_schedule_lead_followup(vc) is None

    def test_keyword_fallback_detects_interest(self, test_db, sample_business):
        from core import followups

        bid = sample_business["id"]
        vc = _voice_call(
            bid, booking_discussed=0, call_summary="They wanted to know the price and availability."
        )
        with patch("core.db.DB_PATH", test_db):
            assert followups.maybe_schedule_lead_followup(vc) is not None

    def test_respects_opt_out(self, test_db, sample_business):
        from core import followups
        from core.sms import record_opt_out

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            record_opt_out("+14155551234")
            assert followups.maybe_schedule_lead_followup(_voice_call(bid)) is None

    def test_dedupes_per_call(self, test_db, sample_business):
        from core import followups

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            first = followups.maybe_schedule_lead_followup(_voice_call(bid))
            second = followups.maybe_schedule_lead_followup(_voice_call(bid))
        assert first is not None
        assert second is None

    def test_respects_business_disable(self, test_db, sample_business):
        from core import followups
        from core.db import get_conn

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            with get_conn() as con:
                con.execute(
                    "INSERT INTO voice_settings (business_id, lead_followup_enabled) VALUES (?, 0)",
                    (bid,),
                )
                con.commit()
            assert followups.maybe_schedule_lead_followup(_voice_call(bid)) is None


class TestDispatch:
    def test_sends_due_followups(self, test_db, sample_business):
        from core import followups
        from core.db import get_conn

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            # Schedule one in the past so it's due.
            with get_conn() as con:
                con.execute(
                    "INSERT INTO lead_followups (business_id, voice_call_id, phone, message, "
                    "scheduled_for) VALUES (?, 1, '+14155550000', 'book here', "
                    "datetime('now','-1 hour'))",
                    (bid,),
                )
                con.commit()
            with (
                patch("core.sms.TELNYX_CONFIGURED", True),
                patch(
                    "core.sms.send_sms", return_value={"id": "m1", "status": "sent"}
                ) as mock_send,
            ):
                sent = followups.dispatch_due_followups()
            assert sent == 1
            mock_send.assert_called_once()
            with get_conn() as con:
                row = con.execute("SELECT status FROM lead_followups LIMIT 1").fetchone()
        assert row["status"] == "sent"

    def test_does_not_send_future(self, test_db, sample_business):
        from core import followups
        from core.db import get_conn

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            with get_conn() as con:
                con.execute(
                    "INSERT INTO lead_followups (business_id, voice_call_id, phone, message, "
                    "scheduled_for) VALUES (?, 2, '+14155550000', 'book', "
                    "datetime('now','+5 hours'))",
                    (bid,),
                )
                con.commit()
            with (
                patch("core.sms.TELNYX_CONFIGURED", True),
                patch("core.sms.send_sms", return_value={"id": "m", "status": "sent"}) as mock_send,
            ):
                sent = followups.dispatch_due_followups()
            assert sent == 0
            mock_send.assert_not_called()

    def test_suppressed_marks_cancelled(self, test_db, sample_business):
        from core import followups
        from core.db import get_conn

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            with get_conn() as con:
                con.execute(
                    "INSERT INTO lead_followups (business_id, voice_call_id, phone, message, "
                    "scheduled_for) VALUES (?, 3, '+14155550000', 'book', datetime('now','-1 hour'))",
                    (bid,),
                )
                con.commit()
            with (
                patch("core.sms.TELNYX_CONFIGURED", True),
                patch("core.sms.send_sms", return_value={"id": None, "status": "suppressed"}),
            ):
                sent = followups.dispatch_due_followups()
            assert sent == 0
            with get_conn() as con:
                row = con.execute("SELECT status FROM lead_followups LIMIT 1").fetchone()
        assert row["status"] == "cancelled"
