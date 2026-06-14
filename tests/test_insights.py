# tests/test_insights.py — missed-revenue, demand, benchmarking

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch


def _call(
    test_db, bid, started_at, duration=120, status="ended", booking_discussed=0, booking_confirmed=0
):
    from core.db import get_conn

    with patch("core.db.DB_PATH", test_db), get_conn() as con:
        con.execute(
            "INSERT INTO voice_calls (business_id, retell_call_id, direction, from_number, "
            "call_status, started_at, duration_seconds, booking_discussed, booking_confirmed) "
            "VALUES (?, ?, 'inbound', '+1', ?, ?, ?, ?, ?)",
            (
                bid,
                uuid.uuid4().hex,
                status,
                started_at,
                duration,
                booking_discussed,
                booking_confirmed,
            ),
        )
        con.commit()


def _ai_appt(test_db, bid, service="Haircut"):
    from core.db import create_appointment

    with patch("core.db.DB_PATH", test_db):
        return create_appointment(
            business_id=bid,
            customer_name="J",
            phone="+1",
            service=service,
            start_at=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
            status="confirmed",
            source="ai",
        )


class TestMissedRevenue:
    def test_counts_missed_and_unconverted(self, test_db, sample_business):
        from core.insights import compute_missed_revenue

        bid = sample_business["id"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _call(test_db, bid, now, duration=0, status="error")  # missed
        _call(
            test_db, bid, now, duration=90, booking_discussed=1, booking_confirmed=0
        )  # unconverted
        _call(test_db, bid, now, duration=90, booking_discussed=1, booking_confirmed=1)  # converted
        with patch("core.db.DB_PATH", test_db):
            r = compute_missed_revenue(bid, days=30)
        assert r["missed_calls"] == 1
        assert r["unconverted_booking_calls"] == 1
        assert r["lost_opportunities"] == 2
        # Haircut £25 + Coloring £75 → avg 50 → 2 * 50 = 100
        assert r["avg_booking_value"] == 50.0
        assert r["estimated_lost_revenue"] == 100.0

    def test_no_signals(self, test_db, sample_business):
        from core.insights import compute_missed_revenue

        with patch("core.db.DB_PATH", test_db):
            r = compute_missed_revenue(sample_business["id"], days=30)
        assert r["lost_opportunities"] == 0
        assert r["estimated_lost_revenue"] == 0.0


class TestDemandInsights:
    def test_peaks_and_top_services(self, test_db, sample_business):
        from core.insights import compute_demand_insights

        bid = sample_business["id"]
        d = datetime.now()
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        at = d.replace(hour=10, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")
        _call(test_db, bid, at)
        _call(test_db, bid, at)
        _ai_appt(test_db, bid, "Haircut")
        _ai_appt(test_db, bid, "Haircut")
        _ai_appt(test_db, bid, "Coloring")
        with patch("core.db.DB_PATH", test_db):
            r = compute_demand_insights(bid, days=30)
        assert r["peak_hour"] == 10
        assert r["top_services"][0]["name"] == "Haircut"
        assert r["top_services"][0]["count"] == 2


class TestBenchmarks:
    def test_unavailable_below_cohort(self, test_db, sample_business):
        from core.insights import compute_benchmarks

        bid = sample_business["id"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _call(test_db, bid, now)
        with patch("core.db.DB_PATH", test_db):
            r = compute_benchmarks(bid, days=30)
        assert r["available"] is False  # only 1 business with data < MIN_COHORT

    def test_available_with_cohort(self, test_db, sample_business):
        from core.db import get_conn
        from core.insights import compute_benchmarks

        bid = sample_business["id"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Create 3 more businesses with call activity → cohort of 4.
        with patch("core.db.DB_PATH", test_db):
            with get_conn() as con:
                for i in range(3):
                    cur = con.execute(
                        "INSERT INTO businesses (name, slug, tenant_key) VALUES (?, ?, ?)",
                        (f"Biz{i}", f"biz{i}", f"key{i}"),
                    )
                    other = cur.lastrowid
                    con.execute(
                        "INSERT INTO voice_calls (business_id, retell_call_id, direction, "
                        "from_number, call_status, started_at, duration_seconds) "
                        "VALUES (?, ?, 'inbound', '+1', 'ended', ?, 90)",
                        (other, f"oc{i}", now),
                    )
                con.commit()
            _call(test_db, bid, now)
            r = compute_benchmarks(bid, days=30)
        assert r["available"] is True
        assert r["cohort_size"] == 4
        assert "your_answer_rate" in r


class TestEndpoint:
    def test_insights_page(self, authenticated_client, sample_business, test_db):
        with patch("core.db.DB_PATH", test_db):
            resp = authenticated_client.get(
                f"/analytics/insights?days=30&business_id={sample_business['id']}"
            )
        assert resp.status_code == 200
        assert b"Business Insights" in resp.data
