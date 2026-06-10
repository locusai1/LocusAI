# tests/test_billing.py — Stripe billing layer (DB, plans, webhooks, routes)

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Plan catalogue
# ---------------------------------------------------------------------------
class TestPlans:
    def test_plan_list_order_and_prices(self):
        from core import billing
        keys = [p["key"] for p in billing.plan_list()]
        assert keys == ["starter", "professional", "business"]
        prices = {p["key"]: p["price_gbp"] for p in billing.plan_list()}
        assert prices == {"starter": 49, "professional": 149, "business": 299}

    def test_professional_is_popular(self):
        from core import billing
        assert billing.plan("professional").get("popular") is True

    def test_unknown_plan_returns_none(self):
        from core import billing
        assert billing.plan("enterprise") is None
        assert billing.plan("") is None

    def test_not_configured_without_keys(self):
        from core import billing
        with patch.object(billing.settings, "STRIPE_SECRET_KEY", None):
            assert billing.is_configured() is False

    def test_configured_with_key(self):
        from core import billing
        with patch.object(billing.settings, "STRIPE_SECRET_KEY", "sk_test_x"):
            assert billing.is_configured() is True


# ---------------------------------------------------------------------------
# Subscription DB layer
# ---------------------------------------------------------------------------
class TestSubscriptionDB:
    def test_insert_then_update(self, test_db, sample_user):
        from core import billing
        with patch("core.db.DB_PATH", test_db):
            uid = sample_user["id"]
            billing.upsert_subscription(
                uid, stripe_customer_id="cus_1",
                stripe_subscription_id="sub_1", plan_key="professional",
                status="active",
            )
            sub = billing.get_subscription(uid)
            assert sub["plan"] == "professional"
            assert sub["status"] == "active"
            assert sub["stripe_customer_id"] == "cus_1"

            # Update by stripe_subscription_id — should not create a 2nd row.
            billing.upsert_subscription(
                uid, stripe_subscription_id="sub_1", status="past_due",
            )
            sub2 = billing.get_subscription(uid)
            assert sub2["status"] == "past_due"
            assert sub2["plan"] == "professional"  # preserved
            with billing.get_conn() as con:
                count = con.execute(
                    "SELECT COUNT(*) c FROM subscriptions WHERE user_id=?", (uid,)
                ).fetchone()["c"]
            assert count == 1

    def test_has_active_subscription_states(self, test_db, sample_user):
        from core import billing
        with patch("core.db.DB_PATH", test_db):
            uid = sample_user["id"]
            assert billing.has_active_subscription(uid) is False

            future = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
            billing.upsert_subscription(
                uid, stripe_subscription_id="sub_a", plan_key="starter",
                status="active", current_period_end=future,
            )
            assert billing.has_active_subscription(uid) is True
            assert billing.current_plan_key(uid) == "starter"

            billing.upsert_subscription(uid, stripe_subscription_id="sub_a", status="canceled")
            assert billing.has_active_subscription(uid) is False
            assert billing.current_plan_key(uid) is None

    def test_expired_period_is_inactive(self, test_db, sample_user):
        from core import billing
        with patch("core.db.DB_PATH", test_db):
            uid = sample_user["id"]
            past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            billing.upsert_subscription(
                uid, stripe_subscription_id="sub_b", plan_key="business",
                status="active", current_period_end=past,
            )
            assert billing.has_active_subscription(uid) is False


# ---------------------------------------------------------------------------
# Webhook event handling
# ---------------------------------------------------------------------------
class TestWebhookEvents:
    def _event(self, etype, obj):
        return {"type": etype, "data": {"object": obj}}

    def test_checkout_completed_creates_subscription(self, test_db, sample_user):
        from core import billing
        with patch("core.db.DB_PATH", test_db):
            uid = sample_user["id"]
            ev = self._event("checkout.session.completed", {
                "customer": "cus_x", "subscription": "sub_x",
                "client_reference_id": str(uid),
                "metadata": {"user_id": str(uid), "plan": "professional"},
            })
            assert billing.apply_event(ev) is True
            sub = billing.get_subscription(uid)
            assert sub["stripe_subscription_id"] == "sub_x"
            assert sub["plan"] == "professional"
            assert sub["status"] == "active"

    def test_subscription_deleted_marks_canceled(self, test_db, sample_user):
        from core import billing
        with patch("core.db.DB_PATH", test_db):
            uid = sample_user["id"]
            billing.upsert_subscription(
                uid, stripe_customer_id="cus_y", stripe_subscription_id="sub_y",
                plan_key="starter", status="active",
            )
            ev = self._event("customer.subscription.deleted", {
                "id": "sub_y", "customer": "cus_y", "status": "canceled",
                "metadata": {"user_id": str(uid)},
            })
            assert billing.apply_event(ev) is True
            assert billing.get_subscription(uid)["status"] == "canceled"

    def test_invoice_payment_failed_marks_past_due(self, test_db, sample_user):
        from core import billing
        with patch("core.db.DB_PATH", test_db):
            uid = sample_user["id"]
            billing.upsert_subscription(
                uid, stripe_customer_id="cus_z", stripe_subscription_id="sub_z",
                plan_key="business", status="active",
            )
            ev = self._event("invoice.payment_failed", {"customer": "cus_z"})
            assert billing.apply_event(ev) is True
            assert billing.get_subscription(uid)["status"] == "past_due"

    def test_unhandled_event_returns_false(self, test_db, sample_user):
        from core import billing
        with patch("core.db.DB_PATH", test_db):
            ev = self._event("payout.created", {"id": "po_1"})
            assert billing.apply_event(ev) is False

    def test_subscription_updated_matches_by_customer(self, test_db, sample_user):
        """When metadata is missing, we fall back to matching by stripe ids."""
        from core import billing
        with patch("core.db.DB_PATH", test_db):
            uid = sample_user["id"]
            billing.upsert_subscription(
                uid, stripe_customer_id="cus_m", stripe_subscription_id="sub_m",
                plan_key="starter", status="active",
            )
            ev = self._event("customer.subscription.updated", {
                "id": "sub_m", "customer": "cus_m", "status": "active",
                "cancel_at_period_end": True, "metadata": {},
            })
            assert billing.apply_event(ev) is True
            assert billing.get_subscription(uid)["cancel_at_period_end"] == 1


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
class TestBillingRoutes:
    def test_billing_page_renders_for_authenticated_user(self, authenticated_client):
        resp = authenticated_client.get("/billing")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Starter" in body and "Professional" in body and "Business" in body
        assert "£49" in body and "£149" in body and "£299" in body

    def test_billing_page_redirects_anonymous(self, client):
        resp = client.get("/billing")
        assert resp.status_code in (301, 302)
        assert "/login" in resp.headers.get("Location", "")

    @staticmethod
    def _csrf(client):
        """Seed a CSRF token into the session and return it (custom CSRF guard)."""
        with client.session_transaction() as sess:
            sess["csrf_token"] = "test-csrf-token"
        return "test-csrf-token"

    def test_checkout_without_stripe_flashes_and_redirects(self, authenticated_client):
        from core import billing
        tok = self._csrf(authenticated_client)
        with patch.object(billing.settings, "STRIPE_SECRET_KEY", None):
            resp = authenticated_client.post("/billing/checkout/professional",
                                             data={"csrf_token": tok})
            assert resp.status_code in (302, 303)
            assert "/billing" in resp.headers.get("Location", "")

    def test_checkout_unknown_plan(self, authenticated_client):
        tok = self._csrf(authenticated_client)
        resp = authenticated_client.post("/billing/checkout/enterprise",
                                         data={"csrf_token": tok})
        assert resp.status_code in (302, 303)

    def test_webhook_rejects_unconfigured_or_bad_sig(self, client):
        from core import billing
        with patch.object(billing.settings, "STRIPE_SECRET_KEY", None):
            resp = client.post("/api/billing/webhook", data=b"{}",
                               headers={"Stripe-Signature": "x"})
            assert resp.status_code == 400

    def test_checkout_creates_session_when_configured(self, authenticated_client):
        """With Stripe mocked, checkout redirects to the returned URL."""
        from core import billing
        tok = self._csrf(authenticated_client)
        with patch.object(billing.settings, "STRIPE_SECRET_KEY", "sk_test_x"), \
             patch.object(billing.settings, "STRIPE_PRICE_PROFESSIONAL", "price_pro"), \
             patch("core.billing.create_checkout_session", return_value="https://checkout.stripe.com/c/sess_123"):
            resp = authenticated_client.post("/billing/checkout/professional",
                                             data={"csrf_token": tok})
            assert resp.status_code == 303
            assert resp.headers["Location"] == "https://checkout.stripe.com/c/sess_123"
