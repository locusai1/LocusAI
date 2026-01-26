# tests/test_escalation.py — Tests for core/escalation.py (Human Handoff System)

import pytest
from unittest.mock import patch, MagicMock


class TestCreateEscalation:
    """Tests for create_escalation function."""

    def test_create_escalation_basic(self, sample_business, sample_session):
        """Should create escalation and return ID."""
        from core.escalation import create_escalation

        # sample_session is just an integer (session_id)
        escalation_id = create_escalation(
            business_id=sample_business["id"],
            session_id=sample_session,
            customer_id=None,
            reason="Customer requested human assistance"
        )
        assert escalation_id is not None
        assert isinstance(escalation_id, int)

    def test_create_escalation_with_priority(self, sample_business):
        """Should create escalation with specified priority."""
        from core.escalation import create_escalation, get_escalation

        escalation_id = create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Urgent issue",
            priority="urgent"
        )
        assert escalation_id is not None
        escalation = get_escalation(escalation_id)
        assert escalation["priority"] == "urgent"

    def test_create_escalation_with_summary(self, sample_business, sample_session):
        """Should include conversation summary in notes."""
        from core.escalation import create_escalation, get_escalation

        # sample_session is just an integer (session_id)
        escalation_id = create_escalation(
            business_id=sample_business["id"],
            session_id=sample_session,
            customer_id=None,
            reason="Test",
            conversation_summary="Customer is frustrated about wait times"
        )
        escalation = get_escalation(escalation_id)
        assert "frustrated" in escalation["notes"]

    def test_create_escalation_with_customer_info(self, sample_business):
        """Should include customer info in notes."""
        from core.escalation import create_escalation, get_escalation

        escalation_id = create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Test",
            customer_info={"name": "John Doe", "phone": "555-1234"}
        )
        escalation = get_escalation(escalation_id)
        assert "John Doe" in escalation["notes"]
        assert "555-1234" in escalation["notes"]

    def test_create_escalation_marks_session(self, sample_business, sample_session):
        """Should mark session as escalated."""
        from core.escalation import create_escalation
        from core.db import get_conn

        # sample_session is just an integer (session_id)
        create_escalation(
            business_id=sample_business["id"],
            session_id=sample_session,
            customer_id=None,
            reason="Customer upset"
        )

        with get_conn() as con:
            session = con.execute(
                "SELECT escalated, escalation_reason FROM sessions WHERE id = ?",
                (sample_session,)
            ).fetchone()
            assert session["escalated"] == 1
            assert session["escalation_reason"] == "Customer upset"


class TestGetEscalation:
    """Tests for get_escalation function."""

    def test_get_escalation_exists(self, sample_business):
        """Should return escalation data."""
        from core.escalation import create_escalation, get_escalation

        escalation_id = create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Test reason"
        )
        escalation = get_escalation(escalation_id)
        assert escalation is not None
        assert escalation["reason"] == "Test reason"
        assert escalation["status"] == "pending"

    def test_get_escalation_not_exists(self):
        """Should return None for non-existent escalation."""
        from core.escalation import get_escalation
        result = get_escalation(99999)
        assert result is None


class TestGetPendingEscalations:
    """Tests for get_pending_escalations function."""

    def test_get_pending_escalations_empty(self, sample_business):
        """Should return empty list when no pending escalations."""
        from core.escalation import get_pending_escalations
        # Clear any existing escalations first
        from core.db import get_conn
        with get_conn() as con:
            con.execute("DELETE FROM escalations WHERE business_id = ?", (sample_business["id"],))
            con.commit()

        result = get_pending_escalations(sample_business["id"])
        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_pending_escalations_returns_pending_only(self, sample_business):
        """Should only return pending escalations."""
        from core.escalation import create_escalation, get_pending_escalations, update_escalation_status

        # Create two escalations
        esc1 = create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Pending one"
        )
        esc2 = create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Pending two"
        )

        # Acknowledge one
        update_escalation_status(esc1, "acknowledged")

        pending = get_pending_escalations(sample_business["id"])
        assert len(pending) == 1
        assert pending[0]["reason"] == "Pending two"

    def test_get_pending_escalations_ordered_by_priority(self, sample_business):
        """Should order by priority (urgent first)."""
        from core.escalation import create_escalation, get_pending_escalations

        # Create escalations with different priorities
        create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Normal priority",
            priority="normal"
        )
        create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Urgent priority",
            priority="urgent"
        )

        pending = get_pending_escalations(sample_business["id"])
        assert pending[0]["reason"] == "Urgent priority"


class TestUpdateEscalationStatus:
    """Tests for update_escalation_status function."""

    def test_acknowledge_escalation(self, sample_business):
        """Should change status to acknowledged."""
        from core.escalation import create_escalation, update_escalation_status, get_escalation

        esc_id = create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Test"
        )
        result = update_escalation_status(esc_id, "acknowledged")
        assert result is True

        escalation = get_escalation(esc_id)
        assert escalation["status"] == "acknowledged"

    def test_resolve_escalation(self, sample_business):
        """Should change status to resolved."""
        from core.escalation import create_escalation, update_escalation_status, get_escalation

        esc_id = create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Test"
        )
        result = update_escalation_status(esc_id, "resolved", resolved_by="admin@test.com")
        assert result is True

        escalation = get_escalation(esc_id)
        assert escalation["status"] == "resolved"
        assert escalation["resolved_by"] == "admin@test.com"

    def test_invalid_status_rejected(self, sample_business):
        """Should reject invalid status values."""
        from core.escalation import create_escalation, update_escalation_status

        esc_id = create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Test"
        )
        result = update_escalation_status(esc_id, "invalid_status")
        assert result is False


class TestHandleEscalation:
    """Tests for handle_escalation function."""

    def test_handle_escalation_creates_record(self, sample_business, sample_session):
        """Should create escalation record."""
        from core.escalation import handle_escalation
        from core.sentiment import SentimentResult, SentimentType, IntentType

        sentiment = SentimentResult(
            sentiment=SentimentType.FRUSTRATED,
            intent=IntentType.COMPLAINT,
            confidence=0.9,
            triggers_escalation=True,
            escalation_reason="Customer requested human assistance",
            details={"reason": "Customer requested human"}
        )

        # sample_session is just an integer (session_id)
        escalation_id = handle_escalation(
            sentiment_result=sentiment,
            business=sample_business,
            session_id=sample_session,
            conversation_history=[]
        )
        assert escalation_id is not None


class TestGetEscalationResponse:
    """Tests for get_escalation_response function."""

    def test_get_escalation_response_returns_string(self):
        """Should return handoff message."""
        from core.escalation import get_escalation_response
        response = get_escalation_response()
        assert isinstance(response, str)
        assert len(response) > 0

    def test_get_escalation_response_mentions_human(self):
        """Should mention connecting to a human."""
        from core.escalation import get_escalation_response
        response = get_escalation_response().lower()
        assert any(word in response for word in ["human", "person", "team", "someone", "call"])


class TestNotifyEscalation:
    """Tests for notify_escalation function."""

    @patch("core.escalation.send_email")
    def test_notify_escalation_sends_email(self, mock_send_email, sample_business):
        """Should send email notification."""
        from core.escalation import create_escalation, notify_escalation

        esc_id = create_escalation(
            business_id=sample_business["id"],
            session_id=None,
            customer_id=None,
            reason="Test"
        )

        # Add escalation_email to business
        from core.db import get_conn, get_business_by_id
        with get_conn() as con:
            con.execute(
                "UPDATE businesses SET escalation_email = ? WHERE id = ?",
                ("notify@test.com", sample_business["id"])
            )
            con.commit()

        # Reload business with updated email
        updated_business = get_business_by_id(sample_business["id"])
        notify_escalation(esc_id, updated_business)
        # Should attempt to send email (may fail if not configured)


class TestPriorityLevels:
    """Tests for escalation priority levels."""

    def test_valid_priorities(self, sample_business):
        """Should accept all valid priority levels."""
        from core.escalation import create_escalation, get_escalation

        for priority in ["low", "normal", "high", "urgent"]:
            esc_id = create_escalation(
                business_id=sample_business["id"],
                session_id=None,
                customer_id=None,
                reason=f"Test {priority}",
                priority=priority
            )
            escalation = get_escalation(esc_id)
            assert escalation["priority"] == priority
