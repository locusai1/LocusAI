# tests/test_trial.py — trial expiry enforcement guard

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


def _client(app, user, *, trial_ends_at, role="owner"):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {
            "id": user["id"], "email": user["email"], "name": user["name"],
            "role": role, "trial_ends_at": trial_ends_at,
        }
    return c


def _link(test_db, user, business):
    with patch("core.db.DB_PATH", test_db):
        from core.db import get_conn
        with get_conn() as con:
            con.execute(
                "INSERT OR IGNORE INTO business_users (user_id, business_id) VALUES (?, ?)",
                (user["id"], business["id"]),
            )
            con.commit()


PAST = (datetime.now() - timedelta(days=1)).isoformat()
FUTURE = (datetime.now() + timedelta(days=7)).isoformat()


class TestTrialEnforcement:
    def test_no_trial_date_is_allowed(self, app, sample_user, sample_business, test_db):
        _link(test_db, sample_user, sample_business)
        c = _client(app, sample_user, trial_ends_at=None)
        resp = c.get("/dashboard")
        assert "/billing" not in resp.headers.get("Location", "")
        assert resp.status_code == 200

    def test_active_trial_is_allowed(self, app, sample_user, sample_business, test_db):
        _link(test_db, sample_user, sample_business)
        c = _client(app, sample_user, trial_ends_at=FUTURE)
        resp = c.get("/dashboard")
        assert resp.status_code == 200

    def test_expired_trial_redirects_to_billing(self, app, sample_user, test_db):
        c = _client(app, sample_user, trial_ends_at=PAST)
        resp = c.get("/dashboard")
        assert resp.status_code == 302
        assert "/billing" in resp.headers["Location"]

    def test_admin_never_blocked(self, app, admin_user, test_db):
        c = _client(app, admin_user, trial_ends_at=PAST, role="admin")
        resp = c.get("/dashboard")
        assert resp.status_code == 200

    def test_expired_user_can_still_reach_billing(self, app, sample_user, test_db):
        c = _client(app, sample_user, trial_ends_at=PAST)
        resp = c.get("/billing")
        assert resp.status_code == 200

    def test_expired_user_can_logout(self, app, sample_user, test_db):
        c = _client(app, sample_user, trial_ends_at=PAST)
        resp = c.get("/logout")
        # logout redirects to login, NOT billing
        assert "/billing" not in resp.headers.get("Location", "")

    def test_expired_trial_with_active_subscription_is_allowed(
        self, app, sample_user, sample_business, test_db
    ):
        from core import billing
        _link(test_db, sample_user, sample_business)
        with patch("core.db.DB_PATH", test_db):
            billing.upsert_subscription(
                sample_user["id"], stripe_subscription_id="sub_active",
                plan_key="professional", status="active",
            )
        c = _client(app, sample_user, trial_ends_at=PAST)
        resp = c.get("/dashboard")
        assert resp.status_code == 200
