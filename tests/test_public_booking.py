# tests/test_public_booking.py — public self-serve booking page /book/<slug>

from datetime import date, timedelta
from unittest.mock import patch

import pytest


def _next_weekday():
    d = date.today() + timedelta(days=1)
    while d.weekday() >= 5:  # skip Sat/Sun (sample business is Mon-Fri)
        d += timedelta(days=1)
    return d.isoformat()


def _service_id(test_db, business_id):
    from core.db import get_conn
    with get_conn() as con:
        r = con.execute("SELECT id FROM services WHERE business_id=? AND active=1 LIMIT 1",
                        (business_id,)).fetchone()
    return r["id"]


def _csrf(client):
    with client.session_transaction() as sess:
        sess["csrf_token"] = "pbk-token"
    return "pbk-token"


class TestPublicBookingPage:
    def test_unknown_slug_404(self, client):
        assert client.get("/book/does-not-exist").status_code == 404

    def test_page_renders(self, client, sample_business):
        resp = client.get(f"/book/{sample_business['slug']}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert sample_business["name"] in body
        assert "Haircut" in body  # a seeded service

    def test_slots_json(self, client, sample_business, test_db):
        sid = _service_id(test_db, sample_business["id"])
        with patch("core.db.DB_PATH", test_db):
            resp = client.get(f"/book/{sample_business['slug']}/slots",
                              query_string={"service_id": sid, "date": _next_weekday()})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "slots" in data
        assert len(data["slots"]) > 0
        assert "value" in data["slots"][0] and "label" in data["slots"][0]

    def test_slots_rejects_foreign_service(self, client, sample_business, test_db):
        with patch("core.db.DB_PATH", test_db):
            resp = client.get(f"/book/{sample_business['slug']}/slots",
                              query_string={"service_id": 99999, "date": _next_weekday()})
        assert resp.get_json()["slots"] == []


class TestPublicBookingSubmit:
    def test_successful_booking(self, client, sample_business, test_db):
        sid = _service_id(test_db, sample_business["id"])
        day = _next_weekday()
        with patch("core.db.DB_PATH", test_db):
            slots = client.get(f"/book/{sample_business['slug']}/slots",
                               query_string={"service_id": sid, "date": day}).get_json()["slots"]
            slot_value = slots[0]["value"]
            tok = _csrf(client)
            resp = client.post(f"/book/{sample_business['slug']}", data={
                "csrf_token": tok, "service_id": sid, "slot": slot_value,
                "name": "Web Booker", "phone": "+14155551212", "email": "web@example.com",
            })
            assert resp.status_code in (302, 303)
            assert "booked=1" in resp.headers["Location"]
            from core.db import get_conn
            with get_conn() as con:
                row = con.execute(
                    "SELECT * FROM appointments WHERE business_id=? AND customer_name=?",
                    (sample_business["id"], "Web Booker")).fetchone()
            assert row is not None
            assert row["start_at"] == slot_value
            assert row["source"] == "api"
            assert row["status"] == "confirmed"

    def test_missing_phone_rejected(self, client, sample_business, test_db):
        sid = _service_id(test_db, sample_business["id"])
        with patch("core.db.DB_PATH", test_db):
            tok = _csrf(client)
            resp = client.post(f"/book/{sample_business['slug']}", data={
                "csrf_token": tok, "service_id": sid, "slot": f"{_next_weekday()} 10:00",
                "name": "No Phone",
            })
        assert resp.status_code == 400
        assert "phone" in resp.get_data(as_text=True).lower()

    def test_unknown_slug_submit_404(self, client, test_db):
        with patch("core.db.DB_PATH", test_db):
            tok = _csrf(client)
            resp = client.post("/book/nope", data={"csrf_token": tok, "name": "X"})
        assert resp.status_code == 404
