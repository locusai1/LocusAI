# tests/test_limits.py — plan-based feature gating

from unittest.mock import patch

import pytest


def _link_owner(test_db, user_id, business_id):
    from core.db import get_conn
    with get_conn() as con:
        con.execute("INSERT OR IGNORE INTO business_users (user_id, business_id) VALUES (?, ?)",
                    (user_id, business_id))
        con.commit()


def _give_plan(test_db, user_id, plan_key):
    from core import billing
    billing.upsert_subscription(user_id, stripe_subscription_id=f"sub_{plan_key}_{user_id}",
                                plan_key=plan_key, status="active")


class TestEffectivePlan:
    def test_no_subscription_is_ungated(self, test_db, sample_business, sample_user):
        from core import limits
        with patch("core.db.DB_PATH", test_db):
            _link_owner(test_db, sample_user["id"], sample_business["id"])
            assert limits.effective_plan_key(sample_business["id"]) is None

    def test_active_paid_plan_detected(self, test_db, sample_business, sample_user):
        from core import limits
        with patch("core.db.DB_PATH", test_db):
            _link_owner(test_db, sample_user["id"], sample_business["id"])
            _give_plan(test_db, sample_user["id"], "professional")
            assert limits.effective_plan_key(sample_business["id"]) == "professional"


class TestQuota:
    def test_ungated_never_over(self, test_db, sample_business, sample_user):
        from core import limits
        with patch("core.db.DB_PATH", test_db):
            _link_owner(test_db, sample_user["id"], sample_business["id"])
            st = limits.quota_status(sample_business["id"])
            assert st["gated"] is False and st["over"] is False
            assert limits.can_start_conversation(sample_business["id"]) is True

    def test_starter_over_limit_blocks(self, test_db, sample_business, sample_user):
        from core import limits
        with patch("core.db.DB_PATH", test_db):
            _link_owner(test_db, sample_user["id"], sample_business["id"])
            _give_plan(test_db, sample_user["id"], "starter")  # limit 100
            with patch("core.limits.conversations_this_month", return_value=100):
                assert limits.can_start_conversation(sample_business["id"]) is False
            with patch("core.limits.conversations_this_month", return_value=42):
                assert limits.can_start_conversation(sample_business["id"]) is True

    def test_business_plan_unlimited(self, test_db, sample_business, sample_user):
        from core import limits
        with patch("core.db.DB_PATH", test_db):
            _link_owner(test_db, sample_user["id"], sample_business["id"])
            _give_plan(test_db, sample_user["id"], "business")  # conversations -1
            with patch("core.limits.conversations_this_month", return_value=99999):
                assert limits.can_start_conversation(sample_business["id"]) is True

    def test_conversations_counted(self, test_db, sample_business):
        from core import limits
        from core.db import create_session
        with patch("core.db.DB_PATH", test_db):
            create_session(sample_business["id"])
            create_session(sample_business["id"])
            assert limits.conversations_this_month(sample_business["id"]) >= 2


class TestChannelAndUsers:
    def test_channels_by_plan(self, test_db, sample_business, sample_user):
        from core import limits
        with patch("core.db.DB_PATH", test_db):
            _link_owner(test_db, sample_user["id"], sample_business["id"])
            _give_plan(test_db, sample_user["id"], "starter")  # web only
            assert limits.channel_allowed(sample_business["id"], "web") is True
            assert limits.channel_allowed(sample_business["id"], "voice") is False
            assert limits.channel_allowed(sample_business["id"], "sms") is False

    def test_channels_ungated_all_allowed(self, test_db, sample_business, sample_user):
        from core import limits
        with patch("core.db.DB_PATH", test_db):
            _link_owner(test_db, sample_user["id"], sample_business["id"])
            for ch in ("web", "voice", "sms"):
                assert limits.channel_allowed(sample_business["id"], ch) is True

    def test_user_limit(self, test_db, sample_business, sample_user):
        from core import limits
        with patch("core.db.DB_PATH", test_db):
            _link_owner(test_db, sample_user["id"], sample_business["id"])
            _give_plan(test_db, sample_user["id"], "starter")  # users: 1
            # already 1 owner -> cannot add another
            assert limits.can_add_user(sample_business["id"]) is False


class TestWidgetEnforcement:
    def test_session_blocked_when_over_quota(self, client, sample_business, test_db):
        key = sample_business["tenant_key"]
        with patch("core.db.DB_PATH", test_db), \
             patch("core.limits.can_start_conversation", return_value=False):
            resp = client.post("/api/widget/session", headers={"X-Tenant-Key": key})
        assert resp.status_code == 402
        assert resp.get_json()["error"] == "conversation_limit_reached"

    def test_session_ok_when_ungated(self, client, sample_business, test_db):
        key = sample_business["tenant_key"]
        with patch("core.db.DB_PATH", test_db):
            resp = client.post("/api/widget/session", headers={"X-Tenant-Key": key})
        assert resp.status_code == 200
        assert "session_id" in resp.get_json()
