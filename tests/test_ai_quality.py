# tests/test_ai_quality.py — confidence gating, call feedback, test-AI sandbox

from unittest.mock import patch


class TestConfidenceGate:
    def test_strips_marker_and_flags(self):
        from core.ai import strip_confidence_marker

        clean, low = strip_confidence_marker("I'll have someone confirm that. <UNSURE/>")
        assert low is True
        assert "<UNSURE" not in clean
        assert clean == "I'll have someone confirm that."

    def test_no_marker(self):
        from core.ai import strip_confidence_marker

        clean, low = strip_confidence_marker("A haircut is £25.")
        assert low is False
        assert clean == "A haircut is £25."

    def test_metadata_surfaces_low_confidence(self, sample_business):
        from core import ai

        with patch.object(ai, "_call_ai_with_resilience", return_value="Let me check. <UNSURE/>"):
            out = ai.process_message_with_metadata("Do you sell gift cards?", sample_business, {})
        assert out["low_confidence"] is True
        assert "<UNSURE" not in out["reply"]


class TestFeedback:
    def test_record_and_summary(self, test_db, sample_business):
        from core.feedback import feedback_summary, record_feedback

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            assert record_feedback(bid, "up", voice_call_id=1) is True
            assert record_feedback(bid, "down", voice_call_id=2, note="wrong price") is True
            summary = feedback_summary(bid)
        assert summary["up"] == 1
        assert summary["down"] == 1
        assert summary["needs_review"][0]["note"] == "wrong price"

    def test_rerate_overwrites(self, test_db, sample_business):
        from core.feedback import feedback_summary, record_feedback

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            record_feedback(bid, "up", voice_call_id=5)
            record_feedback(bid, "down", voice_call_id=5)  # same call, changed mind
            summary = feedback_summary(bid)
        assert summary["up"] == 0
        assert summary["down"] == 1

    def test_invalid_rating_rejected(self, test_db, sample_business):
        from core.feedback import record_feedback

        with patch("core.db.DB_PATH", test_db):
            assert record_feedback(sample_business["id"], "meh", voice_call_id=9) is False
            assert record_feedback(sample_business["id"], "up") is False  # no target

    def test_endpoint(self, authenticated_client, sample_business, test_db):
        with authenticated_client.session_transaction() as s:
            s["csrf_token"] = "t"
            s["active_business_id"] = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            resp = authenticated_client.post(
                "/api/call-feedback",
                data={
                    "csrf_token": "t",
                    "business_id": sample_business["id"],
                    "voice_call_id": "3",
                    "rating": "down",
                    "note": "missed the booking",
                },
            )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True


class TestSandbox:
    def test_sandbox_chat_no_side_effects(self, authenticated_client, sample_business, test_db):
        with authenticated_client.session_transaction() as s:
            s["csrf_token"] = "t"
            s["active_business_id"] = sample_business["id"]
        from core import ai

        with (
            patch("core.db.DB_PATH", test_db),
            patch.object(ai, "_call_ai_with_resilience", return_value="Sure, we offer haircuts!"),
        ):
            resp = authenticated_client.post(
                "/api/test-ai/chat", data={"csrf_token": "t", "message": "Do you do haircuts?"}
            )
        assert resp.status_code == 200
        assert "haircuts" in resp.get_json()["reply"].lower()

    def test_sandbox_strips_booking_tag(self, authenticated_client, sample_business, test_db):
        with authenticated_client.session_transaction() as s:
            s["csrf_token"] = "t"
            s["active_business_id"] = sample_business["id"]
        from core import ai

        reply = 'Booked! <BOOKING>{"name":"x"}</BOOKING>'
        with (
            patch("core.db.DB_PATH", test_db),
            patch.object(ai, "_call_ai_with_resilience", return_value=reply),
        ):
            resp = authenticated_client.post(
                "/api/test-ai/chat", data={"csrf_token": "t", "message": "book me in"}
            )
        body = resp.get_json()
        assert "<BOOKING>" not in body["reply"]
        assert "Booked!" in body["reply"]
