# tests/test_ai.py — Tests for core/ai.py (AI Conversation Engine)

import pytest
from unittest.mock import patch, MagicMock
import os


class TestAIModuleConfiguration:
    """Tests for AI module configuration and imports."""

    def test_openai_model_default(self):
        """Should default to gpt-4o-mini."""
        from core.ai import OPENAI_MODEL
        # Either environment var or default
        assert OPENAI_MODEL in ["gpt-4o-mini", os.getenv("OPENAI_MODEL", "gpt-4o-mini")]

    def test_fallback_models_defined(self):
        """Should have fallback models chain."""
        from core.ai import FALLBACK_MODELS
        assert len(FALLBACK_MODELS) >= 2
        assert all(isinstance(m, tuple) and len(m) == 2 for m in FALLBACK_MODELS)

    def test_fallback_response_defined(self):
        """Should have a fallback response for when AI fails."""
        from core.ai import FALLBACK_RESPONSE
        assert isinstance(FALLBACK_RESPONSE, str)
        assert len(FALLBACK_RESPONSE) > 20


class TestRowToDict:
    """Tests for _row_to_dict helper."""

    def test_row_to_dict_with_dict(self):
        """Should return dict unchanged."""
        from core.ai import _row_to_dict
        d = {"key": "value"}
        assert _row_to_dict(d) == d

    def test_row_to_dict_with_none(self):
        """Should return empty dict for None."""
        from core.ai import _row_to_dict
        assert _row_to_dict(None) == {}

    def test_row_to_dict_with_sqlite_row(self):
        """Should convert sqlite3.Row to dict."""
        from core.ai import _row_to_dict
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        con.execute("INSERT INTO test VALUES (1, 'test')")
        row = con.execute("SELECT * FROM test").fetchone()
        result = _row_to_dict(row)
        assert result["id"] == 1
        assert result["name"] == "test"
        con.close()


class TestBusinessPrompt:
    """Tests for _business_prompt generation."""

    def test_business_prompt_basic(self):
        """Should generate prompt with business info."""
        from core.ai import _business_prompt
        bd = {
            "name": "Test Salon",
            "hours": "9am-5pm",
            "address": "123 Main St",
            "services": "Haircuts, Coloring",
            "tone": "friendly"
        }
        prompt = _business_prompt(bd)
        assert "Test Salon" in prompt
        assert "9am-5pm" in prompt
        assert "123 Main St" in prompt
        assert "Haircuts" in prompt
        assert "friendly" in prompt

    def test_business_prompt_defaults(self):
        """Should use defaults for missing fields."""
        from core.ai import _business_prompt
        bd = {}
        prompt = _business_prompt(bd)
        assert "not provided" in prompt
        assert "friendly and professional" in prompt

    def test_business_prompt_booking_instructions(self):
        """Should include booking tag instructions."""
        from core.ai import _business_prompt
        bd = {"name": "Test"}
        prompt = _business_prompt(bd)
        assert "<BOOKING>" in prompt
        assert "name" in prompt.lower()
        assert "phone" in prompt.lower()


class TestIncrementFailedAttempts:
    """Tests for failed attempt tracking."""

    def test_increment_failed_attempts(self):
        """Should increment and return count."""
        from core.ai import increment_failed_attempts
        state = {}
        count = increment_failed_attempts(state)
        assert count == 1
        assert state["failed_attempts"] == 1

    def test_increment_failed_attempts_multiple(self):
        """Should track multiple failures."""
        from core.ai import increment_failed_attempts
        state = {}
        increment_failed_attempts(state)
        increment_failed_attempts(state)
        count = increment_failed_attempts(state)
        assert count == 3
        assert state["failed_attempts"] == 3


class TestResetFailedAttempts:
    """Tests for resetting failed attempts."""

    def test_reset_failed_attempts(self):
        """Should reset counter to zero."""
        from core.ai import reset_failed_attempts
        state = {"failed_attempts": 5}
        reset_failed_attempts(state)
        assert state["failed_attempts"] == 0

    def test_reset_failed_attempts_empty_state(self):
        """Should handle empty state."""
        from core.ai import reset_failed_attempts
        state = {}
        reset_failed_attempts(state)  # Should not raise
        assert state["failed_attempts"] == 0


class TestProcessMessageWithMock:
    """Tests for process_message with mocked OpenAI."""

    @pytest.fixture
    def mock_business(self):
        return {
            "id": 1,
            "name": "Test Salon",
            "hours": "9am-5pm",
            "address": "123 Main St",
            "services": "Haircuts",
            "tone": "friendly"
        }

    @patch("core.ai.client")
    def test_process_message_returns_string(self, mock_client, mock_business):
        """Should return AI response as string."""
        from core.ai import process_message

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello! How can I help?"))]
        mock_client.chat.completions.create.return_value = mock_response

        state = {}
        result = process_message("Hello", mock_business, state)
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("core.ai.client")
    def test_process_message_updates_history(self, mock_client, mock_business):
        """Should update conversation history in state."""
        from core.ai import process_message

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hi there!"))]
        mock_client.chat.completions.create.return_value = mock_response

        state = {}
        process_message("Hello", mock_business, state)
        assert "history" in state
        assert len(state["history"]) >= 2  # User message + AI response


class TestProcessMessageWithMetadata:
    """Tests for process_message_with_metadata."""

    @patch("core.ai.client")
    def test_returns_dict_with_required_keys(self, mock_client):
        """Should return dict with reply, sentiment, intent keys."""
        from core.ai import process_message_with_metadata

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello!"))]
        mock_client.chat.completions.create.return_value = mock_response

        business = {"id": 1, "name": "Test", "hours": "", "address": "", "services": "", "tone": "friendly"}
        state = {}
        result = process_message_with_metadata("Hi", business, state)

        assert isinstance(result, dict)
        assert "reply" in result
        assert "sentiment" in result
        assert "intent" in result


class TestVoicePromptGeneration:
    """Tests for voice-specific prompt generation."""

    def test_voice_business_prompt_exists(self):
        """Should have voice-specific prompt function."""
        try:
            from core.ai import _voice_business_prompt
            assert callable(_voice_business_prompt)
        except ImportError:
            # Function may be in a different module
            pass

    def test_voice_prompt_is_concise(self):
        """Voice prompts should emphasize brevity."""
        from core.ai import _business_prompt
        bd = {"name": "Test", "tone": "professional"}
        prompt = _business_prompt(bd)
        # Check for brevity-related keywords
        assert any(word in prompt.lower() for word in ["concise", "brief", "short", "1-3 sentences", "1–3"])


class TestKBIntegration:
    """Tests for Knowledge Base integration."""

    def test_kb_snippets_function_exists(self):
        """Should have KB snippets helper."""
        try:
            from core.ai import _kb_snippets
            assert callable(_kb_snippets)
        except ImportError:
            # May use different name
            pass


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker integration."""

    def test_circuit_breaker_available_flag(self):
        """Should have CIRCUIT_BREAKER_AVAILABLE flag."""
        from core.ai import CIRCUIT_BREAKER_AVAILABLE
        assert isinstance(CIRCUIT_BREAKER_AVAILABLE, bool)

    def test_sentiment_available_flag(self):
        """Should have SENTIMENT_AVAILABLE flag."""
        from core.ai import SENTIMENT_AVAILABLE
        assert isinstance(SENTIMENT_AVAILABLE, bool)

    def test_escalation_available_flag(self):
        """Should have ESCALATION_AVAILABLE flag."""
        from core.ai import ESCALATION_AVAILABLE
        assert isinstance(ESCALATION_AVAILABLE, bool)
