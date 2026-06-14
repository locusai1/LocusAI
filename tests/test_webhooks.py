# tests/test_webhooks.py — outbound webhooks / event bus

from unittest.mock import MagicMock, patch

import pytest


class TestSecurity:
    def test_sign_payload_deterministic(self):
        from core.webhooks import sign_payload

        sig = sign_payload("secret", b'{"a":1}')
        assert sig.startswith("sha256=")
        assert sig == sign_payload("secret", b'{"a":1}')
        assert sig != sign_payload("other", b'{"a":1}')

    def test_generate_secret_prefixed(self):
        from core.webhooks import generate_secret

        assert generate_secret().startswith("whsec_")

    def test_ssrf_blocks_private_and_local(self):
        from core.webhooks import is_safe_url

        for bad in [
            "http://localhost/x",
            "http://127.0.0.1/x",
            "http://10.0.0.5/x",
            "http://192.168.1.10/x",
            "http://169.254.1.1/x",
            "ftp://example.com",
            "file:///etc/passwd",
            "http://[::1]/x",
        ]:
            assert is_safe_url(bad) is False, bad

    def test_ssrf_allows_public(self):
        from core import webhooks

        with patch(
            "core.webhooks.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]
        ):
            assert webhooks.is_safe_url("https://example.com/hook") is True


class TestEndpointCrud:
    def test_create_list_delete(self, test_db, sample_business):
        from core import webhooks

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            res = webhooks.create_endpoint(bid, "https://example.com/h", "all", "desc")
            assert res["secret"].startswith("whsec_")
            eps = webhooks.list_endpoints(bid)
            assert len(eps) == 1 and eps[0]["url"] == "https://example.com/h"
            assert webhooks.delete_endpoint(bid, res["id"]) is True
            assert webhooks.list_endpoints(bid) == []


class TestEmit:
    def test_emit_queues_for_matching_endpoints(self, test_db, sample_business):
        from core import webhooks

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            webhooks.create_endpoint(bid, "https://a.example.com/h", "all")
            webhooks.create_endpoint(bid, "https://b.example.com/h", "escalation.created")
            # booking.created should hit only the 'all' endpoint
            n = webhooks.emit_event(bid, "booking.created", {"appointment_id": 1})
            assert n == 1
            n2 = webhooks.emit_event(bid, "escalation.created", {"escalation_id": 9})
            assert n2 == 2  # both 'all' and the specific one
            assert len(webhooks.recent_deliveries(bid)) == 3

    def test_emit_no_endpoints_is_noop(self, test_db, sample_business):
        from core import webhooks

        with patch("core.db.DB_PATH", test_db):
            assert webhooks.emit_event(sample_business["id"], "booking.created", {}) == 0


class TestDispatch:
    def _one_delivery(self, test_db, webhooks, bid):
        webhooks.create_endpoint(bid, "https://example.com/h", "all")
        webhooks.emit_event(bid, "booking.created", {"appointment_id": 1})

    def test_success_marks_delivered(self, test_db, sample_business):
        from core import webhooks

        bid = sample_business["id"]
        with (
            patch("core.db.DB_PATH", test_db),
            patch("core.webhooks.is_safe_url", return_value=True),
            patch("httpx.post", return_value=MagicMock(status_code=200)),
        ):
            self._one_delivery(test_db, webhooks, bid)
            assert webhooks.dispatch_pending() == 1
            d = webhooks.recent_deliveries(bid)[0]
            assert d["status"] == "success"
            assert d["response_code"] == 200

    def test_signature_header_sent(self, test_db, sample_business):
        from core import webhooks

        bid = sample_business["id"]
        captured = {}

        def fake_post(url, content=None, headers=None, timeout=None):
            captured["headers"] = headers
            captured["content"] = content
            return MagicMock(status_code=200)

        with (
            patch("core.db.DB_PATH", test_db),
            patch("core.webhooks.is_safe_url", return_value=True),
            patch("httpx.post", side_effect=fake_post),
        ):
            self._one_delivery(test_db, webhooks, bid)
            webhooks.dispatch_pending()
        assert captured["headers"]["X-LocusAI-Signature"].startswith("sha256=")
        assert captured["headers"]["X-LocusAI-Event"] == "booking.created"

    def test_5xx_schedules_retry(self, test_db, sample_business):
        from core import webhooks

        bid = sample_business["id"]
        with (
            patch("core.db.DB_PATH", test_db),
            patch("core.webhooks.is_safe_url", return_value=True),
            patch("httpx.post", return_value=MagicMock(status_code=500)),
        ):
            self._one_delivery(test_db, webhooks, bid)
            webhooks.dispatch_pending()
            d = webhooks.recent_deliveries(bid)[0]
            assert d["status"] == "pending"
            assert d["attempts"] == 1

    def test_unsafe_url_fails_delivery(self, test_db, sample_business):
        from core import webhooks

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            webhooks.create_endpoint(bid, "http://127.0.0.1/h", "all")
            webhooks.emit_event(bid, "booking.created", {"x": 1})
            webhooks.dispatch_pending()
            d = webhooks.recent_deliveries(bid)[0]
            assert d["status"] == "failed"
            assert "SSRF" in (d["last_error"] or "")

    def test_max_attempts_fails(self, test_db, sample_business):
        from core import webhooks
        from core.db import get_conn

        bid = sample_business["id"]
        with (
            patch("core.db.DB_PATH", test_db),
            patch("core.webhooks.is_safe_url", return_value=True),
            patch("httpx.post", return_value=MagicMock(status_code=500)),
        ):
            r = webhooks.create_endpoint(bid, "https://example.com/h", "all")
            # Pre-load a delivery already at attempts=4 (next attempt = 5 = MAX)
            with get_conn() as con:
                con.execute(
                    "INSERT INTO webhook_deliveries (endpoint_id, business_id, event_type, "
                    "payload, status, attempts, next_attempt_at) "
                    "VALUES (?, ?, 'booking.created', '{}', 'pending', 4, '2000-01-01T00:00:00')",
                    (r["id"], bid),
                )
                con.commit()
            webhooks.dispatch_pending()
            d = webhooks.recent_deliveries(bid)[0]
            assert d["status"] == "failed"
            assert d["attempts"] == 5


class TestManagementUI:
    def test_page_requires_login(self, client):
        resp = client.get("/integrations/webhooks")
        assert resp.status_code in (301, 302)

    def test_create_blocks_unsafe_url(self, authenticated_client, sample_business, test_db):
        with authenticated_client.session_transaction() as s:
            s["csrf_token"] = "t"
        resp = authenticated_client.post(
            "/integrations/webhooks",
            data={
                "csrf_token": "t",
                "business_id": sample_business["id"],
                "url": "http://localhost/evil",
                "events": "all",
            },
        )
        assert resp.status_code in (302, 303)  # redirected with error flash
        from core import webhooks

        with patch("core.db.DB_PATH", test_db):
            assert webhooks.list_endpoints(sample_business["id"]) == []  # nothing created

    def test_index_renders(self, authenticated_client, sample_business):
        resp = authenticated_client.get(
            f"/integrations/webhooks?business_id={sample_business['id']}"
        )
        assert resp.status_code == 200
        assert "Webhooks" in resp.get_data(as_text=True)
