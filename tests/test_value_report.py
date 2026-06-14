# tests/test_value_report.py — "what LocusAI did for you" value report

from datetime import datetime, timedelta
from unittest.mock import patch


def _ai_appt(test_db, bid, service="Haircut", status="confirmed"):
    from core.db import create_appointment

    with patch("core.db.DB_PATH", test_db):
        return create_appointment(
            business_id=bid,
            customer_name="Jane",
            phone="+14155551234",
            service=service,
            start_at=(datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
            status=status,
            source="ai",
        )


def _voice_call(test_db, bid, started_at, duration=120, status="ended"):
    from core.db import get_conn

    with patch("core.db.DB_PATH", test_db), get_conn() as con:
        con.execute(
            "INSERT INTO voice_calls (business_id, retell_call_id, direction, from_number, "
            "call_status, started_at, duration_seconds) VALUES (?, ?, 'inbound', '+14155551234', ?, ?, ?)",
            (bid, f"call_{started_at}_{duration}", status, started_at, duration),
        )
        con.commit()


class TestComputeValueReport:
    def test_counts_ai_bookings_and_revenue(self, test_db, sample_business):
        from core.value_report import compute_value_report

        bid = sample_business["id"]
        _ai_appt(test_db, bid)  # Haircut = 25.00
        _ai_appt(test_db, bid)
        with patch("core.db.DB_PATH", test_db):
            r = compute_value_report(bid, days=30)
        assert r["ai_bookings"] == 2
        assert r["revenue_captured"] == 50.0
        assert r["headline_value"] == 50.0

    def test_cancelled_excluded_from_revenue(self, test_db, sample_business):
        from core.value_report import compute_value_report

        bid = sample_business["id"]
        _ai_appt(test_db, bid, status="confirmed")
        _ai_appt(test_db, bid, status="cancelled")
        with patch("core.db.DB_PATH", test_db):
            r = compute_value_report(bid, days=30)
        assert r["ai_bookings"] == 2  # both counted as handled
        assert r["revenue_captured"] == 25.0  # only the non-cancelled one

    def test_after_hours_calls_detected(self, test_db, sample_business):
        from core.value_report import compute_value_report

        bid = sample_business["id"]
        # Find a recent weekday (Mon-Fri) for deterministic hours (9-17).
        d = datetime.now()
        while d.weekday() >= 5:  # back up to a weekday
            d -= timedelta(days=1)
        in_hours = d.replace(hour=11, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")
        after = d.replace(hour=21, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")
        _voice_call(test_db, bid, in_hours)
        _voice_call(test_db, bid, after)
        with patch("core.db.DB_PATH", test_db):
            r = compute_value_report(bid, days=30)
        assert r["calls_answered"] == 2
        assert r["after_hours_calls"] == 1

    def test_missed_calls_not_counted_answered(self, test_db, sample_business):
        from core.value_report import compute_value_report

        bid = sample_business["id"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _voice_call(test_db, bid, now, duration=0, status="error")  # missed
        with patch("core.db.DB_PATH", test_db):
            r = compute_value_report(bid, days=30)
        assert r["calls_answered"] == 0

    def test_leads_recovered_counts_sent(self, test_db, sample_business):
        from core.db import get_conn
        from core.value_report import compute_value_report

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            with get_conn() as con:
                con.execute(
                    "INSERT INTO lead_followups (business_id, voice_call_id, phone, message, "
                    "scheduled_for, status) VALUES (?, 1, '+1', 'm', datetime('now'), 'sent')",
                    (bid,),
                )
                con.execute(
                    "INSERT INTO lead_followups (business_id, voice_call_id, phone, message, "
                    "scheduled_for, status) VALUES (?, 2, '+1', 'm', datetime('now'), 'pending')",
                    (bid,),
                )
                con.commit()
            r = compute_value_report(bid, days=30)
        assert r["leads_recovered"] == 1  # only 'sent'


class TestEndpoint:
    def test_value_report_page(self, authenticated_client, sample_business, test_db):
        _ai_appt(test_db, sample_business["id"])
        with patch("core.db.DB_PATH", test_db):
            resp = authenticated_client.get(
                f"/analytics/value?days=30&business_id={sample_business['id']}"
            )
        assert resp.status_code == 200
        assert b"Value Report" in resp.data
