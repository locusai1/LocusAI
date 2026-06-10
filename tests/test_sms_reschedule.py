# tests/test_sms_reschedule.py — SMS reschedule/cancel (auto-applied, no confirm UI)

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


def _future(days=4, hour=14):
    d = datetime.now() + timedelta(days=days)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")


def _inbound(body, frm="+14155551234", to="+442046203253"):
    return {"data": {"event_type": "message.received", "payload": {
        "id": "m1", "from": {"phone_number": frm},
        "to": [{"phone_number": to}], "text": body}}}


def _make_appt(test_db, business_id, phone="+14155551234", service="Haircut", when=None):
    from core.db import create_appointment
    return create_appointment(business_id=business_id, customer_name="SMS Cust",
                              phone=phone, service=service, start_at=when or _future(),
                              status="confirmed", source="ai")


class TestSmsCancel:
    def test_cancel_applied_via_sms(self, client, sample_business, test_db):
        with patch("core.db.DB_PATH", test_db):
            aid = _make_appt(test_db, sample_business["id"])
            ai_reply = 'Okay, cancelling that for you. <CANCEL>{"phone":"+14155551234"}</CANCEL>'
            with patch("core.ai.process_message", return_value=ai_reply):
                resp = client.post("/api/sms/webhook", json=_inbound("please cancel my appointment"))
            assert resp.status_code == 200
            from core.db import get_conn
            with get_conn() as con:
                status = con.execute("SELECT status FROM appointments WHERE id=?", (aid,)).fetchone()["status"]
            assert status == "cancelled"

    def test_reschedule_applied_via_sms(self, client, sample_business, test_db):
        with patch("core.db.DB_PATH", test_db):
            aid = _make_appt(test_db, sample_business["id"], when=_future(days=4, hour=14))
            new_dt = _future(days=6, hour=11)
            ai_reply = ('No problem. <RESCHEDULE>{"phone":"+14155551234",'
                        '"new_datetime":"%s"}</RESCHEDULE>' % new_dt)
            with patch("core.ai.process_message", return_value=ai_reply):
                resp = client.post("/api/sms/webhook", json=_inbound("move it please"))
            assert resp.status_code == 200
            from core.db import get_conn
            with get_conn() as con:
                start = con.execute("SELECT start_at FROM appointments WHERE id=?", (aid,)).fetchone()["start_at"]
            assert start == new_dt

    def test_normal_message_unaffected(self, client, sample_business, test_db):
        """A reply with no change tag passes through cleanly."""
        with patch("core.db.DB_PATH", test_db):
            with patch("core.ai.process_message", return_value="We're open 9 to 5, Monday to Friday."):
                resp = client.post("/api/sms/webhook", json=_inbound("what are your hours?"))
            assert resp.status_code == 200
