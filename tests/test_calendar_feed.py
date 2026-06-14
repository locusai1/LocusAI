# tests/test_calendar_feed.py — iCal subscription feed (universal calendar integration)

from datetime import datetime, timedelta
from unittest.mock import patch


def _add_appt(test_db, bid, when, service="Haircut", status="confirmed", name="Sarah"):
    from core.db import get_conn

    with get_conn() as con:
        con.execute(
            """INSERT INTO appointments (business_id, customer_name, phone, service, start_at, status, source)
               VALUES (?, ?, '+447700900000', ?, ?, ?, 'ai')""",
            (bid, name, service, when, status),
        )
        con.commit()


class TestFeedTokens:
    def test_ensure_creates_and_is_stable(self, test_db, sample_business):
        from core.calendar_feed import ensure_feed_token

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            t1 = ensure_feed_token(bid)
            t2 = ensure_feed_token(bid)
        assert t1 and t1 == t2

    def test_regenerate_changes_token(self, test_db, sample_business):
        from core.calendar_feed import ensure_feed_token, regenerate_feed_token

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            t1 = ensure_feed_token(bid)
            t2 = regenerate_feed_token(bid)
        assert t1 != t2

    def test_lookup_by_token(self, test_db, sample_business):
        from core.calendar_feed import business_by_feed_token, ensure_feed_token

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            token = ensure_feed_token(bid)
            biz = business_by_feed_token(token)
            assert biz and biz["id"] == bid
            assert business_by_feed_token("nope") is None


class TestBuildFeed:
    def test_includes_future_confirmed_excludes_cancelled(self, test_db, sample_business):
        bid = sample_business["id"]
        future = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        cancelled = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        with patch("core.db.DB_PATH", test_db):
            _add_appt(test_db, bid, future, service="Colour", name="Jo")
            _add_appt(test_db, bid, cancelled, service="Trim", status="cancelled", name="Kim")
            from core.calendar_feed import build_feed

            ics = build_feed(bid, "StyleCuts").decode()
        assert "BEGIN:VCALENDAR" in ics
        assert "Colour" in ics and "Jo" in ics
        assert "Trim" not in ics  # cancelled excluded
        assert ics.count("BEGIN:VEVENT") == 1

    def test_escapes_special_chars(self, test_db, sample_business):
        bid = sample_business["id"]
        future = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        with patch("core.db.DB_PATH", test_db):
            _add_appt(test_db, bid, future, service="Cut, Wash; Style", name="A")
            from core.calendar_feed import build_feed

            ics = build_feed(bid).decode()
        assert "Cut\\, Wash\\; Style" in ics


class TestFeedRoute:
    def test_feed_route_returns_calendar(self, client, sample_business, test_db):
        from core.calendar_feed import ensure_feed_token

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            token = ensure_feed_token(bid)
            resp = client.get(f"/calendar/{token}.ics")
        assert resp.status_code == 200
        assert resp.mimetype == "text/calendar"
        assert b"BEGIN:VCALENDAR" in resp.data

    def test_unknown_token_404(self, client, test_db):
        with patch("core.db.DB_PATH", test_db):
            resp = client.get("/calendar/bogustoken.ics")
        assert resp.status_code == 404
