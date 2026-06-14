# tests/test_handoff.py — warm transfer fn endpoint + live call monitor feed

from unittest.mock import patch


def _enable_transfer(test_db, bid, number="+447700900999"):
    from core.db import get_conn

    with get_conn() as con:
        con.execute(
            """INSERT INTO voice_settings (business_id, transfer_enabled, transfer_number)
               VALUES (?, 1, ?)
               ON CONFLICT(business_id) DO UPDATE SET transfer_enabled=1, transfer_number=excluded.transfer_number""",
            (bid, number),
        )
        con.commit()


class TestTransferFn:
    def test_transfer_returns_number_and_marks_call(self, client, sample_business, test_db):
        from core.db import get_conn

        bid = sample_business["id"]
        with get_conn() as con:
            con.execute(
                "INSERT INTO voice_calls (business_id, retell_call_id, direction) VALUES (?, 'tc1', 'inbound')",
                (bid,),
            )
            con.commit()
        _enable_transfer(test_db, bid)
        with (
            patch("core.db.DB_PATH", test_db),
            patch("voice_bp._verify_retell_request", return_value=True),
            patch("voice_bp._get_business_by_phone", return_value=bid),
            patch("core.voice.generate_transfer_briefing", return_value="Caller needs help."),
        ):
            resp = client.post(
                "/api/voice/fn/transfer",
                json={
                    "call": {
                        "call_id": "tc1",
                        "from_number": "+14155551234",
                        "to_number": "+442046203253",
                    },
                    "args": {"reason": "billing question"},
                },
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["transfer"] is True
        assert body["transfer_number"] == "+447700900999"
        assert body["briefing"] == "Caller needs help."
        with get_conn() as con:
            row = con.execute(
                "SELECT transferred, transfer_reason, call_status FROM voice_calls WHERE retell_call_id='tc1'"
            ).fetchone()
        assert row["transferred"] == 1
        assert row["transfer_reason"] == "billing question"
        assert row["call_status"] == "transferred"

    def test_transfer_unconfigured_offers_message(self, client, sample_business, test_db):
        bid = sample_business["id"]
        # No transfer number configured for this business.
        with (
            patch("core.db.DB_PATH", test_db),
            patch("voice_bp._verify_retell_request", return_value=True),
            patch("voice_bp._get_business_by_phone", return_value=bid),
        ):
            resp = client.post(
                "/api/voice/fn/transfer",
                json={"call": {"to_number": "+442046203253"}, "args": {}},
            )
        body = resp.get_json()
        assert body["transfer"] is False
        assert "message" in body

    def test_transfer_requires_signature(self, client, test_db):
        with (
            patch("core.db.DB_PATH", test_db),
            patch("voice_bp._verify_retell_request", return_value=False),
        ):
            resp = client.post("/api/voice/fn/transfer", json={})
        assert resp.status_code == 403


class TestLiveFeed:
    def test_live_requires_auth(self, client, test_db):
        with patch("core.db.DB_PATH", test_db):
            resp = client.get("/api/voice/live")
        assert resp.status_code == 401

    def test_live_lists_ongoing_calls(self, authenticated_client, sample_business, test_db):
        from core.db import get_conn

        bid = sample_business["id"]
        with get_conn() as con:
            con.execute(
                """INSERT INTO voice_calls (business_id, retell_call_id, direction, call_status, transcript)
                   VALUES (?, 'live1', 'inbound', 'ongoing', 'Agent: Hello\nUser: Hi')""",
                (bid,),
            )
            con.execute(
                """INSERT INTO voice_calls (business_id, retell_call_id, direction, call_status)
                   VALUES (?, 'done1', 'inbound', 'ended')""",
                (bid,),
            )
            con.commit()
        with patch("core.db.DB_PATH", test_db):
            resp = authenticated_client.get("/api/voice/live")
        assert resp.status_code == 200
        calls = resp.get_json()["calls"]
        ids = [c["retell_call_id"] for c in calls]
        assert "live1" in ids
        assert "done1" not in ids
        live = next(c for c in calls if c["retell_call_id"] == "live1")
        assert "transcript_tail" in live
        assert "transcript" not in live  # full transcript not leaked
