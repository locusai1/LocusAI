# tests/test_call_recovery.py — never-drop-a-call owner recovery

from unittest.mock import patch


class TestIsRecoverable:
    def test_error_status_is_recoverable(self):
        from core.call_recovery import is_recoverable

        assert is_recoverable({"direction": "inbound", "call_status": "error"})

    def test_voicemail_is_recoverable(self):
        from core.call_recovery import is_recoverable

        assert is_recoverable(
            {"direction": "inbound", "caller_message": "Please call me back about a booking"}
        )

    def test_missed_outcome_is_recoverable(self):
        from core.call_recovery import is_recoverable

        assert is_recoverable({"direction": "inbound", "call_outcome": "no_answer"})

    def test_zero_duration_uncontained_is_recoverable(self):
        from core.call_recovery import is_recoverable

        assert is_recoverable({"direction": "inbound", "duration_seconds": 0, "containment": 0})

    def test_resolved_contained_call_not_recoverable(self):
        from core.call_recovery import is_recoverable

        assert not is_recoverable(
            {
                "direction": "inbound",
                "call_status": "ended",
                "call_outcome": "booked",
                "duration_seconds": 120,
                "containment": 1,
            }
        )

    def test_outbound_not_recoverable(self):
        from core.call_recovery import is_recoverable

        assert not is_recoverable({"direction": "outbound", "call_status": "error"})

    def test_already_alerted_not_recoverable(self):
        from core.call_recovery import is_recoverable

        assert not is_recoverable(
            {"direction": "inbound", "call_status": "error", "recovery_alerted": 1}
        )


class TestRecoverCall:
    def _seed_call(self, test_db, sample_business, **overrides):
        from core.db import get_conn

        bid = sample_business["id"]
        cols = {
            "business_id": bid,
            "retell_call_id": "callX",
            "direction": "inbound",
            "from_number": "+447700900123",
            "call_status": "error",
        }
        cols.update(overrides)
        with get_conn() as con:
            con.execute(
                "UPDATE businesses SET escalation_email='owner@biz.com', escalation_phone='+447700900999' WHERE id=?",
                (bid,),
            )
            keys = ",".join(cols)
            qs = ",".join(["?"] * len(cols))
            con.execute(f"INSERT INTO voice_calls ({keys}) VALUES ({qs})", tuple(cols.values()))
            con.commit()
        return cols

    def test_alerts_owner_and_dedupes(self, test_db, sample_business):
        with patch("core.db.DB_PATH", test_db):
            call = self._seed_call(test_db, sample_business)
            from core import call_recovery
            from core.db import get_conn

            with (
                patch.object(call_recovery, "_recovery_enabled", return_value=True),
                patch("core.mailer.send_email", return_value=True) as mock_email,
                patch("core.sms.TELNYX_CONFIGURED", True),
                patch("core.sms.send_sms", return_value={"status": "ok"}) as mock_sms,
            ):
                res = call_recovery.recover_call({**call, "recovery_alerted": 0})
                assert res["alerted"] is True
                assert "email" in res["channels"]
                assert "sms" in res["channels"]
                mock_email.assert_called_once()
                mock_sms.assert_called_once()

                # Dedup: flag set, second call sees recovery_alerted and bails.
                with get_conn() as con:
                    row = con.execute(
                        "SELECT recovery_alerted FROM voice_calls WHERE retell_call_id='callX'"
                    ).fetchone()
                assert row["recovery_alerted"] == 1

    def test_disabled_business_no_alert(self, test_db, sample_business):
        with patch("core.db.DB_PATH", test_db):
            call = self._seed_call(test_db, sample_business)
            from core import call_recovery

            with patch.object(call_recovery, "_recovery_enabled", return_value=False):
                res = call_recovery.recover_call({**call, "recovery_alerted": 0})
            assert res["alerted"] is False
            assert res["channels"] == []
