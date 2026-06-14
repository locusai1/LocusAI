# tests/test_compliance.py — audit log, retention purge, transcript PII redaction

from unittest.mock import patch


class TestRedactPiiText:
    def test_redacts_email(self):
        from core.security import redact_pii_text

        out = redact_pii_text("reach me at sarah@acme.co.uk please")
        assert "sarah@acme.co.uk" not in out
        assert "[email redacted]" in out

    def test_redacts_phone(self):
        from core.security import redact_pii_text

        out = redact_pii_text("call 020 4620 3253 today")
        assert "4620" not in out
        assert "[phone redacted]" in out

    def test_redacts_card_number(self):
        from core.security import redact_pii_text

        out = redact_pii_text("card 4111 1111 1111 1111 on file")
        assert "4111" not in out
        assert "[card redacted]" in out

    def test_keeps_ordinary_text(self):
        from core.security import redact_pii_text

        text = "The haircut costs £25 and takes 30 minutes."
        assert redact_pii_text(text) == text

    def test_handles_empty(self):
        from core.security import redact_pii_text

        assert redact_pii_text("") == ""
        assert redact_pii_text(None) == ""


class TestAuditLog:
    def test_log_and_list(self, test_db):
        from core.audit import list_audit, log_audit

        with patch("core.db.DB_PATH", test_db):
            log_audit(
                "appointment.cancelled",
                business_id=1,
                user_email="admin@x.com",
                entity_type="appointment",
                entity_id=42,
                detail={"reason": "test"},
            )
            rows = list_audit(1)
        assert len(rows) == 1
        assert rows[0]["action"] == "appointment.cancelled"
        assert rows[0]["entity_id"] == "42"
        assert rows[0]["detail"]["reason"] == "test"

    def test_list_filters_by_action_prefix(self, test_db):
        from core.audit import list_audit, log_audit

        with patch("core.db.DB_PATH", test_db):
            log_audit("auth.login", business_id=1)
            log_audit("appointment.status_changed", business_id=1)
            rows = list_audit(1, action_prefix="auth.")
        assert len(rows) == 1
        assert rows[0]["action"] == "auth.login"

    def test_global_events_visible_to_business(self, test_db):
        # business_id NULL (global/admin) rows show in a business's view
        from core.audit import list_audit, log_audit

        with patch("core.db.DB_PATH", test_db):
            log_audit("user.deleted", entity_type="user", entity_id=7)
            rows = list_audit(1)
        assert any(r["action"] == "user.deleted" for r in rows)

    def test_log_never_raises(self):
        # No DB patched / broken path must not raise into the caller
        from core.audit import log_audit

        with patch("core.audit.transaction", side_effect=RuntimeError("boom")):
            log_audit("test.action")  # should swallow

    def test_purge_old_audit(self, test_db):
        from core.audit import list_audit, purge_old_audit
        from core.db import get_conn

        with patch("core.db.DB_PATH", test_db):
            with get_conn() as con:
                con.execute(
                    "INSERT INTO audit_log (action, created_at) VALUES (?, datetime('now','-800 days'))",
                    ("old.event",),
                )
                con.execute("INSERT INTO audit_log (action) VALUES (?)", ("recent.event",))
                con.commit()
            removed = purge_old_audit(keep_days=730)
            rows = list_audit(None)
        assert removed == 1
        assert [r["action"] for r in rows] == ["recent.event"]


class TestRetentionPurge:
    def test_cleanup_purges_old_voice_calls(self, test_db, sample_business):
        from core.db import cleanup_old_data, get_conn

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            with get_conn() as con:
                con.execute("UPDATE businesses SET data_retention_days=30 WHERE id=?", (bid,))
                con.execute(
                    """INSERT INTO voice_calls (business_id, retell_call_id, direction, created_at)
                       VALUES (?, 'old1', 'inbound', datetime('now','-90 days'))""",
                    (bid,),
                )
                con.execute(
                    """INSERT INTO voice_calls (business_id, retell_call_id, direction, created_at)
                       VALUES (?, 'new1', 'inbound', datetime('now'))""",
                    (bid,),
                )
                con.commit()
            counts = cleanup_old_data(bid)
            with get_conn() as con:
                remaining = [
                    r["retell_call_id"]
                    for r in con.execute("SELECT retell_call_id FROM voice_calls").fetchall()
                ]
        assert counts["voice_calls"] == 1
        assert remaining == ["new1"]
