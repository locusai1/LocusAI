# tests/test_reschedule_cancel.py — AI reschedule/cancel of existing appointments

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


def _future(days=3, hour=14, minute=0):
    d = datetime.now() + timedelta(days=days)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")


def _make_appt(test_db, business_id, phone="+14155551234", service="Haircut", when=None):
    from core.db import create_appointment

    with patch("core.db.DB_PATH", test_db):
        return create_appointment(
            business_id=business_id,
            customer_name="Jane Doe",
            phone=phone,
            service=service,
            start_at=when or _future(),
            status="confirmed",
            source="ai",
        )


class TestFindUpcoming:
    def test_finds_by_phone(self, test_db, sample_business):
        from core import booking

        bid = sample_business["id"]
        _make_appt(test_db, bid)
        with patch("core.db.DB_PATH", test_db):
            appts = booking.find_upcoming_appointments(bid, phone="+14155551234")
        assert len(appts) == 1
        assert appts[0]["service"] == "Haircut"

    def test_ignores_past_and_cancelled(self, test_db, sample_business):
        from core import booking
        from core.db import create_appointment, update_appointment_status

        bid = sample_business["id"]
        past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        with patch("core.db.DB_PATH", test_db):
            create_appointment(
                business_id=bid,
                customer_name="P",
                phone="+14155550000",
                service="X",
                start_at=past,
                status="confirmed",
            )
            aid = create_appointment(
                business_id=bid,
                customer_name="C",
                phone="+14155550001",
                service="Y",
                start_at=_future(),
                status="confirmed",
            )
            update_appointment_status(aid, "cancelled")
            appts = booking.find_upcoming_appointments(bid)
        assert appts == []


class TestCancelFlow:
    def test_cancel_tag_stages_then_confirms(self, test_db, sample_business):
        from core import booking

        bid = sample_business["id"]
        aid = _make_appt(test_db, bid)
        reply = (
            'Sure, I can cancel that. <CANCEL>{"phone":"+14155551234","service":"Haircut"}</CANCEL>'
        )
        with patch("core.db.DB_PATH", test_db):
            clean, change = booking.extract_pending_change(reply, sample_business, session_id=None)
            assert "<CANCEL>" not in clean
            assert change and change["action"] == "cancel"
            assert change["service"] == "Haircut"
            ok, msg = booking.confirm_pending_change(change["token"])
            assert ok is True
            from core.db import get_conn

            with get_conn() as con:
                status = con.execute(
                    "SELECT status FROM appointments WHERE id=?", (aid,)
                ).fetchone()["status"]
        assert status == "cancelled"

    def test_cancel_no_match_returns_message(self, test_db, sample_business):
        from core import booking

        reply = '<CANCEL>{"phone":"+19998887777"}</CANCEL>'
        with patch("core.db.DB_PATH", test_db):
            clean, change = booking.extract_pending_change(reply, sample_business, session_id=None)
        assert change is None
        assert "couldn't find" in clean.lower()

    def test_dismiss_pending_change(self, test_db, sample_business):
        from core import booking

        bid = sample_business["id"]
        _make_appt(test_db, bid)
        with patch("core.db.DB_PATH", test_db):
            _, change = booking.extract_pending_change(
                '<CANCEL>{"phone":"+14155551234"}</CANCEL>', sample_business, None
            )
            ok, _ = booking.cancel_pending_change(change["token"])
            assert ok is True
            # token now gone
            assert booking.get_pending_change(change["token"]) is None


class TestRescheduleFlow:
    def test_reschedule_tag_moves_appointment(self, test_db, sample_business):
        from core import booking

        bid = sample_business["id"]
        aid = _make_appt(test_db, bid, when=_future(days=3, hour=14))
        new_dt = _future(days=5, hour=11)
        reply = (
            '<RESCHEDULE>{"phone":"+14155551234","service":"Haircut",'
            '"new_datetime":"%s"}</RESCHEDULE>' % new_dt
        )
        with patch("core.db.DB_PATH", test_db):
            clean, change = booking.extract_pending_change(reply, sample_business, None)
            assert change and change["action"] == "reschedule"
            assert change["new_datetime"] == new_dt
            ok, msg = booking.confirm_pending_change(change["token"])
            assert ok is True
            from core.db import get_conn

            with get_conn() as con:
                start = con.execute(
                    "SELECT start_at FROM appointments WHERE id=?", (aid,)
                ).fetchone()["start_at"]
        assert start == new_dt

    def test_reschedule_without_new_time_asks(self, test_db, sample_business):
        from core import booking

        bid = sample_business["id"]
        _make_appt(test_db, bid)
        reply = '<RESCHEDULE>{"phone":"+14155551234"}</RESCHEDULE>'
        with patch("core.db.DB_PATH", test_db):
            clean, change = booking.extract_pending_change(reply, sample_business, None)
        assert change is None
        assert "date and time" in clean.lower()


class TestVoiceFunctions:
    """Direct-apply functions used by the native Retell agent's custom functions."""

    def test_voice_find_appointments(self, test_db, sample_business):
        from core import booking

        bid = sample_business["id"]
        _make_appt(test_db, bid)
        with patch("core.db.DB_PATH", test_db):
            appts = booking.voice_find_appointments(bid, "+14155551234")
        assert len(appts) == 1
        assert appts[0]["service"] == "Haircut"

    def test_voice_cancel_applies(self, test_db, sample_business):
        from core import booking
        from core.db import get_conn

        bid = sample_business["id"]
        aid = _make_appt(test_db, bid)
        with patch("core.db.DB_PATH", test_db):
            ok, msg = booking.voice_cancel_appointment(bid, phone="+14155551234", service="Haircut")
            assert ok is True
            with get_conn() as con:
                status = con.execute(
                    "SELECT status FROM appointments WHERE id=?", (aid,)
                ).fetchone()["status"]
        assert status == "cancelled"
        assert "cancelled" in msg.lower()

    def test_voice_cancel_no_match(self, test_db, sample_business):
        from core import booking

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            ok, msg = booking.voice_cancel_appointment(bid, phone="+19990001111")
        assert ok is False
        assert "couldn't find" in msg.lower()

    def test_voice_reschedule_applies(self, test_db, sample_business):
        from core import booking
        from core.db import get_conn

        bid = sample_business["id"]
        aid = _make_appt(test_db, bid, when=_future(days=3, hour=14))
        new_dt = _future(days=5, hour=11)
        with patch("core.db.DB_PATH", test_db), patch(
            "core.db.check_slot_available", return_value=True
        ):
            ok, msg = booking.voice_reschedule_appointment(
                bid, new_datetime=new_dt, phone="+14155551234", service="Haircut"
            )
            assert ok is True
            with get_conn() as con:
                start = con.execute(
                    "SELECT start_at FROM appointments WHERE id=?", (aid,)
                ).fetchone()["start_at"]
        assert start == new_dt

    def test_voice_reschedule_bad_datetime(self, test_db, sample_business):
        from core import booking

        bid = sample_business["id"]
        _make_appt(test_db, bid)
        with patch("core.db.DB_PATH", test_db):
            ok, msg = booking.voice_reschedule_appointment(
                bid, new_datetime="not a date", phone="+14155551234"
            )
        assert ok is False
        assert "date and time" in msg.lower()


class TestVoiceFunctionEndpoints:
    """The Retell custom-function webhook endpoints in voice_bp."""

    def test_cancel_endpoint(self, client, sample_business, test_db):
        from core.db import get_conn

        bid = sample_business["id"]
        aid = _make_appt(test_db, bid)
        with patch("core.db.DB_PATH", test_db), patch(
            "voice_bp._verify_retell_request", return_value=True
        ), patch("voice_bp._get_business_by_phone", return_value=bid):
            resp = client.post(
                "/api/voice/fn/cancel-appointment",
                json={
                    "call": {"from_number": "+14155551234", "to_number": "+442046203253"},
                    "args": {"service": "Haircut"},
                },
            )
            assert resp.status_code == 200
            assert resp.get_json()["success"] is True
            with get_conn() as con:
                status = con.execute(
                    "SELECT status FROM appointments WHERE id=?", (aid,)
                ).fetchone()["status"]
        assert status == "cancelled"

    def test_find_endpoint_no_appointments(self, client, sample_business, test_db):
        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db), patch(
            "voice_bp._verify_retell_request", return_value=True
        ), patch("voice_bp._get_business_by_phone", return_value=bid):
            resp = client.post(
                "/api/voice/fn/find-appointments",
                json={"call": {"from_number": "+19990001111", "to_number": "+442046203253"}},
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["count"] == 0


class TestWidgetChangeEndpoints:
    def test_confirm_change_endpoint(self, client, sample_business, test_db):
        from core import booking

        bid = sample_business["id"]
        aid = _make_appt(test_db, bid)
        key = sample_business["tenant_key"]
        with patch("core.db.DB_PATH", test_db):
            _, change = booking.extract_pending_change(
                '<CANCEL>{"phone":"+14155551234"}</CANCEL>', sample_business, None
            )
            token = change["token"]
            resp = client.post(
                "/api/widget/change/confirm", json={"token": token}, headers={"X-Tenant-Key": key}
            )
            assert resp.status_code == 200
            assert resp.get_json()["success"] is True

    def test_confirm_change_missing_token(self, client, sample_business, test_db):
        key = sample_business["tenant_key"]
        with patch("core.db.DB_PATH", test_db):
            resp = client.post("/api/widget/change/confirm", json={}, headers={"X-Tenant-Key": key})
        assert resp.status_code == 400
