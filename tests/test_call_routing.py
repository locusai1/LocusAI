# tests/test_call_routing.py — inbound call/SMS is routed to the right tenant
#
# Guards the fix where an unmatched number fell back to "the first active
# business", which in a multi-tenant setup misrouted calls (and could leak one
# tenant's caller data to another).

import pytest

from core.db import get_conn


def _add_business(con, name, slug, escalation_phone=None, retell_phone=None):
    cur = con.execute(
        "INSERT INTO businesses (name, slug, tenant_key, escalation_phone, archived) "
        "VALUES (?, ?, ?, ?, 0)",
        (name, slug, f"key-{slug}", escalation_phone),
    )
    bid = cur.lastrowid
    if retell_phone:
        con.execute(
            "INSERT INTO voice_settings (business_id, retell_phone_number) VALUES (?, ?)",
            (bid, retell_phone),
        )
    con.commit()
    return bid


class TestVoiceRouting:
    def test_single_business_unmatched_falls_back(self, test_db):
        """One tenant: an unknown number is unambiguously theirs."""
        from core.voice import _get_business_by_phone

        with get_conn() as con:
            bid = _add_business(con, "Solo", "solo")
        assert _get_business_by_phone("+15550000000") == bid

    def test_matched_number_routes_correctly(self, test_db):
        from core.voice import _get_business_by_phone

        with get_conn() as con:
            _add_business(con, "A", "a", retell_phone="+441111111111")
            bid_b = _add_business(con, "B", "b", retell_phone="+442222222222")
        assert _get_business_by_phone("+442222222222") == bid_b

    def test_multi_tenant_unmatched_returns_none(self, test_db):
        """Two+ tenants: an unknown number must NOT be guessed."""
        from core.voice import _get_business_by_phone

        with get_conn() as con:
            _add_business(con, "A", "a", retell_phone="+441111111111")
            _add_business(con, "B", "b", retell_phone="+442222222222")
        assert _get_business_by_phone("+449999999999") is None


class TestSmsRouting:
    def test_single_business_unmatched_falls_back(self, test_db):
        import sms_bp

        with get_conn() as con:
            bid = _add_business(con, "Solo", "solo", escalation_phone="+15551112222")
        biz = sms_bp._get_business_by_phone("+15559998888")
        assert biz is not None and biz["id"] == bid

    def test_multi_tenant_unmatched_returns_none(self, test_db):
        import sms_bp

        with get_conn() as con:
            _add_business(con, "A", "a", escalation_phone="+441111111111")
            _add_business(con, "B", "b", escalation_phone="+442222222222")
        assert sms_bp._get_business_by_phone("+449999999999") is None
