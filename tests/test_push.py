# tests/test_push.py — Web Push (PWA) subscriptions + VAPID + graceful degradation

from unittest.mock import patch


class TestVapidKeys:
    def test_generate_vapid_keys_shape(self):
        from core.push import generate_vapid_keys

        keys = generate_vapid_keys()
        assert keys["public_key"]  # base64url, no padding
        assert "=" not in keys["public_key"]
        assert "BEGIN" in keys["private_key"]  # PEM

    def test_private_key_pem_from_base64(self):
        import base64

        from core import push

        pem = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
        b64 = base64.b64encode(pem.encode()).decode()
        with patch.object(push, "VAPID_PRIVATE_KEY", b64):
            assert push._private_key_pem() == pem

    def test_private_key_pem_passthrough(self):
        from core import push

        pem = "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----"
        with patch.object(push, "VAPID_PRIVATE_KEY", pem):
            assert push._private_key_pem() == pem


class TestSubscriptions:
    def test_save_and_lookup(self, test_db, sample_user, sample_business):
        from core.db import get_conn
        from core.push import _subscriptions_for_business, save_subscription

        uid = sample_user["id"]
        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            with get_conn() as con:
                con.execute(
                    "INSERT OR IGNORE INTO business_users (user_id, business_id) VALUES (?, ?)",
                    (uid, bid),
                )
                con.commit()
            ok = save_subscription(
                uid,
                {"endpoint": "https://push/x", "keys": {"p256dh": "k", "auth": "a"}},
                business_id=bid,
            )
            subs = _subscriptions_for_business(bid)
        assert ok is True
        assert len(subs) == 1
        assert subs[0]["endpoint"] == "https://push/x"

    def test_save_rejects_incomplete(self, test_db, sample_user):
        from core.push import save_subscription

        with patch("core.db.DB_PATH", test_db):
            assert save_subscription(sample_user["id"], {"endpoint": "x"}) is False

    def test_save_upserts_on_endpoint(self, test_db, sample_user):
        from core.db import get_conn
        from core.push import save_subscription

        uid = sample_user["id"]
        with patch("core.db.DB_PATH", test_db):
            sub = {"endpoint": "https://push/y", "keys": {"p256dh": "k1", "auth": "a1"}}
            save_subscription(uid, sub)
            sub["keys"]["p256dh"] = "k2"
            save_subscription(uid, sub)
            with get_conn() as con:
                rows = con.execute(
                    "SELECT p256dh FROM push_subscriptions WHERE endpoint='https://push/y'"
                ).fetchall()
        assert len(rows) == 1
        assert rows[0]["p256dh"] == "k2"


class TestSendDegradation:
    def test_send_noop_when_unconfigured(self, test_db, sample_business):
        from core import push

        with (
            patch.object(push, "VAPID_PUBLIC_KEY", ""),
            patch.object(push, "VAPID_PRIVATE_KEY", ""),
        ):
            assert push.send_push_to_business(sample_business["id"], "t", "b") == 0


class TestEndpoints:
    def test_public_key_endpoint(self, client):
        resp = client.get("/api/push/public-key")
        assert resp.status_code == 200
        assert "key" in resp.get_json()

    def test_subscribe_blocked_without_auth(self, client):
        # CSRF (403) fires before the auth check (401); either way it's blocked.
        resp = client.post("/api/push/subscribe", json={})
        assert resp.status_code in (401, 403)

    def test_service_worker_served_at_root(self, client):
        resp = client.get("/sw.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers.get("Content-Type", "")
        assert resp.headers.get("Service-Worker-Allowed") == "/"
