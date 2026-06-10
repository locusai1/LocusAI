# tests/test_calendar.py — appointment calendar view

from datetime import datetime, date
from unittest.mock import patch

import pytest


class TestCalendar:
    def test_requires_login(self, client):
        resp = client.get("/appointments/calendar")
        assert resp.status_code in (301, 302)
        assert "/login" in resp.headers.get("Location", "")

    def test_renders_month_grid(self, authenticated_client, sample_business):
        resp = authenticated_client.get(
            f"/appointments/calendar?business_id={sample_business['id']}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # weekday header + current month title present
        assert "Mon" in body and "Sun" in body
        assert datetime.now().strftime("%B") in body
        assert "cal-grid" in body

    def test_week_view(self, authenticated_client, sample_business):
        resp = authenticated_client.get(
            f"/appointments/calendar?business_id={sample_business['id']}&view=week")
        assert resp.status_code == 200
        assert "Week of" in resp.get_data(as_text=True)

    def test_appointment_shows_on_calendar(self, authenticated_client, sample_business, test_db):
        from core.db import create_appointment
        # An appointment later today should appear as a chip.
        when = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)
        with patch("core.db.DB_PATH", test_db):
            create_appointment(
                business_id=sample_business["id"], customer_name="Cal Tester",
                phone="+14155559999", service="Trim", start_at=when.strftime("%Y-%m-%d %H:%M"),
                status="confirmed",
            )
        resp = authenticated_client.get(
            f"/appointments/calendar?business_id={sample_business['id']}"
            f"&year={when.year}&month={when.month}")
        body = resp.get_data(as_text=True)
        assert "Trim" in body
        assert "cal-confirmed" in body

    def test_invalid_month_falls_back(self, authenticated_client, sample_business):
        resp = authenticated_client.get(
            f"/appointments/calendar?business_id={sample_business['id']}&year=abc&month=99")
        assert resp.status_code == 200  # doesn't crash
