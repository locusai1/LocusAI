# tests/test_onboarding.py — setup-progress checklist

from unittest.mock import patch

import pytest


def _empty_business(test_db, name="Empty Co"):
    from core.db import get_conn

    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO businesses (name, slug, tenant_key) VALUES (?, ?, ?)",
            (name, name.lower().replace(" ", "-"), f"key-{name}"),
        )
        con.commit()
        return cur.lastrowid


class TestChecklist:
    def test_fresh_business_nothing_done(self, test_db):
        from core.onboarding import checklist_for_business

        with patch("core.db.DB_PATH", test_db):
            bid = _empty_business(test_db)
            cl = checklist_for_business(bid)
        assert cl["total"] == 6
        assert cl["done"] == 0
        assert cl["complete"] is False
        assert cl["percent"] == 0
        assert all(not s["done"] for s in cl["steps"])

    def test_no_business_is_complete(self, test_db):
        from core.onboarding import checklist_for_business

        with patch("core.db.DB_PATH", test_db):
            cl = checklist_for_business(0)
        assert cl["complete"] is True
        assert cl["steps"] == []

    def test_adding_service_and_appointment_marks_steps(self, test_db):
        from core.db import create_appointment, get_conn
        from core.onboarding import checklist_for_business

        with patch("core.db.DB_PATH", test_db):
            bid = _empty_business(test_db, "Stepwise Co")
            with get_conn() as con:
                con.execute(
                    "INSERT INTO services (business_id, name, duration_min, price, active) "
                    "VALUES (?, 'Haircut', 30, 25, 1)",
                    (bid,),
                )
                con.commit()
            create_appointment(
                business_id=bid,
                customer_name="A",
                phone="+14150000000",
                service="Haircut",
                start_at="2026-07-01 10:00",
                status="confirmed",
            )
            cl = checklist_for_business(bid)
        steps = {s["key"]: s["done"] for s in cl["steps"]}
        assert steps["services"] is True
        assert steps["booking"] is True
        assert steps["hours"] is False
        assert cl["done"] == 2

    def test_endpoints_are_resolvable(self, app, test_db, sample_business):
        """Every step endpoint must url_for cleanly (no broken dashboard links)."""
        from core.onboarding import checklist_for_business

        with patch("core.db.DB_PATH", test_db):
            cl = checklist_for_business(sample_business["id"])
        from flask import url_for

        with app.test_request_context():
            for s in cl["steps"]:
                assert url_for(s["endpoint"])  # raises if endpoint is unknown


class TestDashboardShowsChecklist:
    def test_dashboard_renders_checklist_for_fresh_business(self, authenticated_client):
        resp = authenticated_client.get("/dashboard")
        assert resp.status_code == 200
        assert "Finish setting up your AI receptionist" in resp.get_data(as_text=True)
