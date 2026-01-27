# tests/test_voice.py — Tests for voice call functionality
# Covers Retell client, webhook handlers, booking confirmation, and voice settings

import os
import sys
import json
import hmac
import hashlib
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Ensure project root is in path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_retell_api_key():
    """Mock Retell API key for testing."""
    with patch('core.voice.RETELL_API_KEY', 'test_api_key_12345'):
        with patch('core.settings.RETELL_API_KEY', 'test_api_key_12345'):
            yield 'test_api_key_12345'


@pytest.fixture
def mock_retell_webhook_secret():
    """Mock Retell webhook secret for testing."""
    with patch('core.voice.RETELL_WEBHOOK_SECRET', 'test_webhook_secret'):
        with patch('core.settings.RETELL_WEBHOOK_SECRET', 'test_webhook_secret'):
            yield 'test_webhook_secret'


@pytest.fixture
def voice_webhook_payload():
    """Sample voice webhook payload for testing."""
    return {
        "event": "call_started",
        "call": {
            "call_id": "test_call_123",
            "agent_id": "agent_test",
            "call_type": "phone_call",
            "from_number": "+14155551234",
            "to_number": "+14155555678",
            "direction": "inbound",
            "start_timestamp": 1706000000000,
            "metadata": {"business_id": 1}
        }
    }


@pytest.fixture
def voice_call_ended_payload():
    """Sample call_ended webhook payload."""
    return {
        "event": "call_ended",
        "call": {
            "call_id": "test_call_123",
            "call_status": "ended",
            "duration_ms": 60000,
            "transcript": "Hello, I'd like to book a haircut for tomorrow.",
            "transcript_object": [
                {"role": "agent", "content": "Hello! How can I help you today?"},
                {"role": "user", "content": "I'd like to book a haircut for tomorrow."}
            ],
            "recording_url": "https://example.com/recording.mp3",
            "call_cost": {"total_cost_cents": 42}
        }
    }


@pytest.fixture
def voice_settings(test_db, sample_business):
    """Create voice settings for test business."""
    with patch('core.db.DB_PATH', test_db):
        from core.db import get_conn

        with get_conn() as conn:
            conn.execute("""
                INSERT INTO voice_settings (
                    business_id, retell_agent_id, retell_phone_number,
                    greeting_message, transfer_number, booking_enabled
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                sample_business['id'],
                'agent_test_123',
                '+14155559999',
                'Welcome to Test Business!',
                '+14155550000',
                1
            ))
            conn.commit()

            row = conn.execute(
                "SELECT * FROM voice_settings WHERE business_id = ?",
                (sample_business['id'],)
            ).fetchone()

            yield dict(row)


# ============================================================================
# Signature Verification Tests
# ============================================================================

class TestSignatureVerification:
    """Tests for Retell webhook signature verification."""

    def test_valid_signature_accepted(self, mock_retell_webhook_secret):
        """Valid HMAC signature passes verification."""
        from core.voice import verify_retell_signature

        payload = b'{"event": "test"}'
        secret = mock_retell_webhook_secret

        # Generate valid signature
        signature = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        assert verify_retell_signature(payload, signature, secret) is True

    def test_invalid_signature_rejected(self, mock_retell_webhook_secret):
        """Invalid signature fails verification."""
        from core.voice import verify_retell_signature

        payload = b'{"event": "test"}'
        invalid_signature = "invalid_signature_12345"

        assert verify_retell_signature(payload, invalid_signature, mock_retell_webhook_secret) is False

    def test_empty_signature_rejected(self, mock_retell_webhook_secret):
        """Empty signature fails verification."""
        from core.voice import verify_retell_signature

        payload = b'{"event": "test"}'

        assert verify_retell_signature(payload, "", mock_retell_webhook_secret) is False

    def test_no_secret_allows_request(self):
        """When no secret configured, requests are allowed (dev mode)."""
        from core.voice import verify_retell_signature

        payload = b'{"event": "test"}'

        # With no secret, should allow (for development)
        assert verify_retell_signature(payload, "any_signature", None) is True


# ============================================================================
# Voice Session Management Tests
# ============================================================================

class TestVoiceSessionManagement:
    """Tests for voice session creation and management."""

    def test_create_voice_session(self, test_db, sample_business):
        """Creates a new voice session."""
        with patch('core.db.DB_PATH', test_db):
            from core.voice import get_or_create_voice_session

            session_id = get_or_create_voice_session(
                business_id=sample_business['id'],
                phone_number='+14155551234',
                call_id='test_call_001'
            )

            assert session_id is not None
            assert session_id > 0

    def test_reuse_recent_voice_session(self, test_db, sample_business):
        """Reuses an existing session from the same phone within 24 hours."""
        with patch('core.db.DB_PATH', test_db):
            from core.db import get_conn, transaction

            # Create an existing session
            with transaction() as con:
                cur = con.cursor()
                cur.execute("""
                    INSERT INTO sessions (business_id, channel, phone)
                    VALUES (?, 'voice', ?)
                """, (sample_business['id'], '+14155551234'))
                existing_session_id = cur.lastrowid

            from core.voice import get_or_create_voice_session

            # Should reuse the existing session
            session_id = get_or_create_voice_session(
                business_id=sample_business['id'],
                phone_number='+14155551234',
                call_id='test_call_002'
            )

            assert session_id == existing_session_id


# ============================================================================
# Voice Call Record Tests
# ============================================================================

class TestVoiceCallRecords:
    """Tests for voice call record CRUD operations."""

    def test_create_voice_call_record(self, test_db, sample_business):
        """Creates a voice call record."""
        with patch('core.db.DB_PATH', test_db):
            from core.voice import create_voice_call_record, get_voice_call
            from core.db import transaction

            # First create a session
            with transaction() as con:
                cur = con.cursor()
                cur.execute("""
                    INSERT INTO sessions (business_id, channel, phone)
                    VALUES (?, 'voice', ?)
                """, (sample_business['id'], '+14155551234'))
                session_id = cur.lastrowid

            record_id = create_voice_call_record(
                business_id=sample_business['id'],
                session_id=session_id,
                retell_call_id='retell_test_001',
                direction='inbound',
                from_number='+14155551234',
                to_number='+14155555678',
                retell_agent_id='agent_test'
            )

            assert record_id is not None
            assert record_id > 0

            # Verify record was created
            call = get_voice_call('retell_test_001')
            assert call is not None
            assert call['direction'] == 'inbound'
            assert call['call_status'] == 'ongoing'

    def test_update_voice_call(self, test_db, sample_business):
        """Updates a voice call record."""
        with patch('core.db.DB_PATH', test_db):
            from core.voice import create_voice_call_record, update_voice_call, get_voice_call
            from core.db import transaction

            # Create session and call
            with transaction() as con:
                cur = con.cursor()
                cur.execute("""
                    INSERT INTO sessions (business_id, channel, phone)
                    VALUES (?, 'voice', ?)
                """, (sample_business['id'], '+14155551234'))
                session_id = cur.lastrowid

            create_voice_call_record(
                business_id=sample_business['id'],
                session_id=session_id,
                retell_call_id='retell_test_002',
                direction='inbound',
                from_number='+14155551234',
                to_number='+14155555678'
            )

            # Update the call
            result = update_voice_call(
                'retell_test_002',
                call_status='ended',
                duration_seconds=60,
                transcript='Test transcript'
            )

            assert result is True

            # Verify update
            call = get_voice_call('retell_test_002')
            assert call['call_status'] == 'ended'
            assert call['duration_seconds'] == 60
            assert call['transcript'] == 'Test transcript'


# ============================================================================
# Voice Settings Tests
# ============================================================================

class TestVoiceSettings:
    """Tests for per-business voice configuration."""

    def test_default_settings_returned(self, test_db, sample_business):
        """Returns default settings for unconfigured business."""
        with patch('core.db.DB_PATH', test_db):
            from core.voice import get_voice_settings

            settings = get_voice_settings(sample_business['id'])

            assert settings is not None
            assert settings['business_id'] == sample_business['id']
            assert settings['booking_enabled'] is True
            assert settings['transfer_enabled'] is True

    def test_custom_settings_saved(self, test_db, sample_business):
        """Custom voice settings persist correctly."""
        with patch('core.db.DB_PATH', test_db):
            from core.voice import get_voice_settings, update_voice_settings

            # Update settings
            result = update_voice_settings(
                sample_business['id'],
                retell_agent_id='custom_agent_123',
                greeting_message='Custom greeting!',
                booking_enabled=False
            )

            assert result is True

            # Verify settings
            settings = get_voice_settings(sample_business['id'])
            assert settings['retell_agent_id'] == 'custom_agent_123'
            assert settings['greeting_message'] == 'Custom greeting!'
            assert settings['booking_enabled'] is False


# ============================================================================
# Voice Booking Confirmation Tests
# ============================================================================

class TestVoiceBookingConfirmation:
    """Tests for voice booking confirmation flow."""

    def test_store_pending_booking(self):
        """Stores a pending booking for voice confirmation."""
        from core.voice import (
            store_voice_pending_booking,
            get_voice_pending_booking,
            clear_voice_pending_booking
        )

        call_id = 'test_call_booking_001'
        booking_data = {
            'name': 'John Doe',
            'phone': '+14155551234',
            'service': 'Haircut',
            'datetime': '2026-01-25 14:00'
        }

        store_voice_pending_booking(call_id, booking_data)

        # Retrieve booking
        pending = get_voice_pending_booking(call_id)
        assert pending is not None
        assert pending['name'] == 'John Doe'
        assert pending['service'] == 'Haircut'

        # Clear booking
        cleared = clear_voice_pending_booking(call_id)
        assert cleared is not None

        # Should be gone now
        assert get_voice_pending_booking(call_id) is None

    def test_extract_voice_booking_from_response(self):
        """Extracts booking details from AI response."""
        from core.voice import extract_voice_booking, clear_voice_pending_booking

        call_id = 'test_call_extract_001'
        ai_response = (
            'I have a haircut scheduled for tomorrow at 2pm. '
            '<VOICE_BOOKING>{"name":"John","phone":"555-1234","service":"Haircut","datetime":"2026-01-25 14:00"}</VOICE_BOOKING> '
            'Would you like me to confirm this booking?'
        )

        cleaned, booking_data = extract_voice_booking(ai_response, call_id)

        # Tag should be removed
        assert '<VOICE_BOOKING>' not in cleaned
        assert 'Would you like me to confirm' in cleaned

        # Booking data should be extracted
        assert booking_data is not None
        assert booking_data['name'] == 'John'
        assert booking_data['service'] == 'Haircut'

        # Clean up
        clear_voice_pending_booking(call_id)

    def test_detect_confirmation_response(self):
        """Detects verbal confirmation from transcript."""
        from core.voice import detect_booking_response

        # Positive confirmations
        assert detect_booking_response("Yes, please confirm") == 'confirm'
        assert detect_booking_response("Yeah that sounds good") == 'confirm'
        assert detect_booking_response("Sure, book it") == 'confirm'
        assert detect_booking_response("Absolutely!") == 'confirm'

        # Cancellations
        assert detect_booking_response("No, cancel that") == 'cancel'
        assert detect_booking_response("Wait, I need a different time") == 'cancel'
        assert detect_booking_response("Nevermind") == 'cancel'

        # Unclear
        assert detect_booking_response("Can you tell me more?") is None


# ============================================================================
# Circuit Breaker Tests
# ============================================================================

class TestVoiceCircuitBreaker:
    """Tests for voice service circuit breaker."""

    def test_circuit_breaker_initial_state(self):
        """Circuit breaker starts in closed state."""
        from core.voice import get_voice_circuit_breaker
        from core.circuit_breaker import CircuitState

        # Reset for clean test
        import core.voice
        core.voice._voice_circuit_breaker = None

        breaker = get_voice_circuit_breaker()
        state = breaker.get_state("retell:api")

        assert state['state'] == CircuitState.CLOSED

    def test_circuit_breaker_singleton(self):
        """Gets the same circuit breaker instance."""
        from core.voice import get_voice_circuit_breaker

        breaker1 = get_voice_circuit_breaker()
        breaker2 = get_voice_circuit_breaker()

        assert breaker1 is breaker2


# ============================================================================
# Webhook Handler Tests
# ============================================================================

class TestWebhookHandlers:
    """Tests for webhook event handlers."""

    def test_handle_call_started(self, test_db, sample_business, voice_webhook_payload):
        """call_started event creates voice_calls record."""
        with patch('core.db.DB_PATH', test_db):
            # Patch the metadata to include business_id
            voice_webhook_payload['call']['metadata']['business_id'] = sample_business['id']

            from core.voice import handle_call_started, get_voice_call

            result = handle_call_started(voice_webhook_payload)

            assert 'call_id' in result
            assert result['call_id'] == 'test_call_123'
            assert result['business_id'] == sample_business['id']

            # Verify call record was created
            call = get_voice_call('test_call_123')
            assert call is not None
            assert call['direction'] == 'inbound'

    def test_handle_call_ended(self, test_db, sample_business, voice_webhook_payload, voice_call_ended_payload):
        """call_ended event updates voice_calls record."""
        with patch('core.db.DB_PATH', test_db):
            voice_webhook_payload['call']['metadata']['business_id'] = sample_business['id']

            from core.voice import handle_call_started, handle_call_ended, get_voice_call

            # First start the call
            handle_call_started(voice_webhook_payload)

            # Then end it
            result = handle_call_ended(voice_call_ended_payload)

            assert result['call_id'] == 'test_call_123'
            assert result['duration_seconds'] == 60

            # Verify record was updated
            call = get_voice_call('test_call_123')
            assert call['call_status'] == 'ended'
            assert call['duration_seconds'] == 60
            assert 'haircut' in call['transcript'].lower()


# ============================================================================
# Retell Client Tests
# ============================================================================

class TestRetellClient:
    """Tests for Retell API client."""

    def test_client_not_configured(self):
        """Raises error when API key not configured."""
        with patch('core.voice.RETELL_API_KEY', None):
            from core.voice import get_retell_client, RetellClientError

            # Reset singleton
            import core.voice
            core.voice._retell_client = None

            with pytest.raises(RetellClientError) as exc_info:
                get_retell_client()

            assert "not configured" in str(exc_info.value)

    def test_is_retell_configured(self, mock_retell_api_key):
        """Checks Retell configuration status."""
        from core.voice import is_retell_configured

        assert is_retell_configured() is True

    def test_is_retell_not_configured(self):
        """Returns False when not configured."""
        with patch('core.voice.RETELL_API_KEY', None):
            from core.voice import is_retell_configured

            assert is_retell_configured() is False


# ============================================================================
# Voice AI Prompt Tests
# ============================================================================

class TestVoiceAIPrompt:
    """Tests for voice-optimized AI prompts."""

    def test_voice_prompt_is_shorter(self):
        """Voice prompt instructs for shorter responses."""
        from core.ai import _voice_business_prompt

        bd = {
            'name': 'Test Business',
            'hours': '9-5',
            'address': '123 Test St',
            'services': 'Haircut, Coloring',
            'tone': 'friendly'
        }

        prompt = _voice_business_prompt(bd)

        # Should mention voice/phone call
        assert 'voice' in prompt.lower() or 'phone' in prompt.lower()

        # Should mention keeping responses brief/short
        assert 'brevity' in prompt.lower() or 'short' in prompt.lower() or '1-2 sentences' in prompt.lower()

        # Should use VOICE_BOOKING tag
        assert 'VOICE_BOOKING' in prompt

    def test_voice_prompt_sentiment_adjustment(self):
        """Voice prompt adjusts for frustrated caller."""
        from core.ai import _voice_business_prompt

        bd = {'name': 'Test', 'tone': 'friendly'}
        sentiment_context = {'sentiment': 'frustrated'}

        prompt = _voice_business_prompt(bd, sentiment_context)

        # Should mention empathy for frustrated caller
        assert 'frustrated' in prompt.lower() or 'empathetic' in prompt.lower()


# ============================================================================
# Integration Tests
# ============================================================================

class TestVoiceIntegration:
    """Integration tests for complete voice flows."""

    def test_full_inbound_call_flow(self, test_db, sample_business, voice_webhook_payload, voice_call_ended_payload):
        """Tests complete inbound call lifecycle."""
        with patch('core.db.DB_PATH', test_db):
            voice_webhook_payload['call']['metadata']['business_id'] = sample_business['id']

            from core.voice import (
                handle_call_started,
                handle_call_ended,
                get_voice_call
            )

            # 1. Call starts
            start_result = handle_call_started(voice_webhook_payload)
            assert start_result['call_id'] == 'test_call_123'

            # 2. Call ends
            end_result = handle_call_ended(voice_call_ended_payload)
            assert end_result['duration_seconds'] == 60

            # 3. Verify final state
            call = get_voice_call('test_call_123')
            assert call['call_status'] == 'ended'
            assert call['transcript'] is not None
            assert call['cost_cents'] == 42


# ============================================================================
# Caller Recognition Tests
# ============================================================================

class TestCallerRecognition:
    """Tests for caller recognition (phone number lookup)."""

    def test_get_caller_info_known_customer(self, test_db, sample_business):
        """Should find customer by phone number."""
        with patch('core.db.DB_PATH', test_db):
            # Create a test customer
            from core.db import get_conn
            with get_conn() as con:
                con.execute(
                    """INSERT INTO customers (business_id, name, email, phone, total_appointments)
                       VALUES (?, ?, ?, ?, ?)""",
                    (sample_business['id'], 'Sarah Smith', 'sarah@example.com', '+14155551234', 5)
                )
                con.commit()

            from core.voice import get_caller_info
            result = get_caller_info(sample_business['id'], '+14155551234')

            assert result is not None
            assert result['name'] == 'Sarah Smith'
            assert result['email'] == 'sarah@example.com'

    def test_get_caller_info_unknown_number(self, test_db, sample_business):
        """Should return None for unknown phone numbers."""
        with patch('core.db.DB_PATH', test_db):
            from core.voice import get_caller_info
            result = get_caller_info(sample_business['id'], '+19995551234')

            assert result is None

    def test_get_caller_info_partial_phone_match(self, test_db, sample_business):
        """Should match phone numbers ignoring country code."""
        with patch('core.db.DB_PATH', test_db):
            # Create customer with local format
            from core.db import get_conn
            with get_conn() as con:
                con.execute(
                    """INSERT INTO customers (business_id, name, phone)
                       VALUES (?, ?, ?)""",
                    (sample_business['id'], 'John Doe', '4155559999')
                )
                con.commit()

            from core.voice import get_caller_info
            # Search with full international format
            result = get_caller_info(sample_business['id'], '+14155559999')

            assert result is not None
            assert result['name'] == 'John Doe'

    def test_get_caller_info_with_appointment_history(self, test_db, sample_business):
        """Should include last service and visit info."""
        with patch('core.db.DB_PATH', test_db):
            from core.db import get_conn
            from datetime import datetime, timedelta

            # Create customer
            with get_conn() as con:
                con.execute(
                    """INSERT INTO customers (business_id, name, phone)
                       VALUES (?, ?, ?)""",
                    (sample_business['id'], 'Jane Wilson', '+14155558888')
                )

                # Create past appointment
                past_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M')
                con.execute(
                    """INSERT INTO appointments (business_id, customer_name, phone, service, start_at, status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (sample_business['id'], 'Jane Wilson', '+14155558888', 'Haircut', past_date, 'completed')
                )
                con.commit()

            from core.voice import get_caller_info
            result = get_caller_info(sample_business['id'], '+14155558888')

            assert result is not None
            assert result['name'] == 'Jane Wilson'
            assert result.get('last_service') == 'Haircut'
            assert result.get('visit_count', 0) >= 1

    def test_voice_prompt_with_customer_info(self):
        """Voice prompt should include caller recognition context."""
        from core.ai import _voice_business_prompt

        bd = {'name': 'StyleCuts', 'tone': 'friendly'}
        customer_info = {
            'name': 'Sarah Smith',
            'total_appointments': 5,
            'last_service': 'Haircut',
            'last_visit': 'January 15'
        }

        prompt = _voice_business_prompt(bd, customer_info=customer_info)

        # Should include caller name
        assert 'Sarah Smith' in prompt
        # Should mention they're a returning customer
        assert 'returning' in prompt.lower() or 'previous' in prompt.lower() or 'visit' in prompt.lower()
        # Should mention last service
        assert 'Haircut' in prompt

    def test_voice_prompt_without_customer_info(self):
        """Voice prompt should work without customer info."""
        from core.ai import _voice_business_prompt

        bd = {'name': 'StyleCuts', 'tone': 'friendly'}
        prompt = _voice_business_prompt(bd, customer_info=None)

        # Should still be a valid prompt
        assert 'StyleCuts' in prompt
        assert 'CALLER RECOGNIZED' not in prompt


# ============================================================================
# Expanded Intents Tests (Cancel, Reschedule, Status)
# ============================================================================

class TestExpandedIntents:
    """Tests for expanded voice intents: cancel, reschedule, status check."""

    def test_detect_appointment_intent_status(self):
        """Should detect status check intent."""
        from core.voice import detect_appointment_intent

        assert detect_appointment_intent("When is my next appointment?") == 'status'
        assert detect_appointment_intent("Do I have any appointments scheduled?") == 'status'
        assert detect_appointment_intent("What time is my booking?") == 'status'
        assert detect_appointment_intent("Check my upcoming appointments") == 'status'

    def test_detect_appointment_intent_cancel(self):
        """Should detect cancellation intent."""
        from core.voice import detect_appointment_intent

        assert detect_appointment_intent("I need to cancel my appointment") == 'cancel'
        assert detect_appointment_intent("Cancel the booking please") == 'cancel'
        assert detect_appointment_intent("I can't make my appointment") == 'cancel'
        assert detect_appointment_intent("I won't be able to make it") == 'cancel'

    def test_detect_appointment_intent_reschedule(self):
        """Should detect reschedule intent."""
        from core.voice import detect_appointment_intent

        assert detect_appointment_intent("I need to reschedule my appointment") == 'reschedule'
        assert detect_appointment_intent("Can I move my booking to another time?") == 'reschedule'
        assert detect_appointment_intent("I want to change the date") == 'reschedule'
        assert detect_appointment_intent("Can I switch my appointment to Friday?") == 'reschedule'

    def test_detect_appointment_intent_none(self):
        """Should return None for non-intent messages."""
        from core.voice import detect_appointment_intent

        assert detect_appointment_intent("Hello, how are you?") is None
        assert detect_appointment_intent("I'd like to book an appointment") is None
        assert detect_appointment_intent("What services do you offer?") is None

    def test_get_caller_upcoming_appointments(self, test_db, sample_business):
        """Should retrieve upcoming appointments for a caller."""
        with patch('core.db.DB_PATH', test_db):
            from core.db import get_conn
            from datetime import datetime, timedelta

            # Create future appointment
            future_date = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d 14:00')
            with get_conn() as con:
                con.execute(
                    """INSERT INTO appointments (business_id, customer_name, phone, service, start_at, status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (sample_business['id'], 'Test Customer', '+14155551234', 'Haircut', future_date, 'confirmed')
                )
                con.commit()

            from core.voice import get_caller_upcoming_appointments
            appointments = get_caller_upcoming_appointments(sample_business['id'], '+14155551234')

            assert len(appointments) == 1
            assert appointments[0]['service'] == 'Haircut'
            assert appointments[0]['status'] == 'confirmed'

    def test_get_caller_upcoming_appointments_excludes_past(self, test_db, sample_business):
        """Should not include past appointments."""
        with patch('core.db.DB_PATH', test_db):
            from core.db import get_conn
            from datetime import datetime, timedelta

            # Create past appointment
            past_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d 14:00')
            with get_conn() as con:
                con.execute(
                    """INSERT INTO appointments (business_id, customer_name, phone, service, start_at, status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (sample_business['id'], 'Test Customer', '+14155551234', 'Haircut', past_date, 'completed')
                )
                con.commit()

            from core.voice import get_caller_upcoming_appointments
            appointments = get_caller_upcoming_appointments(sample_business['id'], '+14155551234')

            assert len(appointments) == 0

    def test_format_appointments_for_voice(self):
        """Should format appointments in human-readable way."""
        from core.voice import format_appointments_for_voice
        from datetime import datetime, timedelta

        future_date = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d 14:30')
        appointments = [
            {'service': 'Haircut', 'start_at': future_date, 'status': 'confirmed'}
        ]

        formatted = format_appointments_for_voice(appointments)

        assert 'Haircut' in formatted
        assert '2:30 PM' in formatted

    def test_format_appointments_for_voice_empty(self):
        """Should return empty string for no appointments."""
        from core.voice import format_appointments_for_voice

        formatted = format_appointments_for_voice([])
        assert formatted == ""

    def test_cancel_caller_appointment(self, test_db, sample_business):
        """Should cancel a caller's appointment."""
        with patch('core.db.DB_PATH', test_db):
            from core.db import get_conn, get_appointment_by_id
            from datetime import datetime, timedelta

            # Create future appointment
            future_date = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d 14:00')
            with get_conn() as con:
                cur = con.cursor()
                cur.execute(
                    """INSERT INTO appointments (business_id, customer_name, phone, service, start_at, status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (sample_business['id'], 'Test Customer', '+14155551234', 'Haircut', future_date, 'confirmed')
                )
                con.commit()
                appt_id = cur.lastrowid

            from core.voice import cancel_caller_appointment
            success, message, cancelled = cancel_caller_appointment(
                sample_business['id'], '+14155551234'
            )

            assert success is True
            assert 'cancelled' in message.lower()
            assert cancelled is not None
            assert cancelled['id'] == appt_id

            # Verify it was actually cancelled
            appt = get_appointment_by_id(appt_id)
            assert appt['status'] == 'cancelled'

    def test_cancel_caller_appointment_no_appointment(self, test_db, sample_business):
        """Should return failure when no appointment exists."""
        with patch('core.db.DB_PATH', test_db):
            from core.voice import cancel_caller_appointment
            success, message, cancelled = cancel_caller_appointment(
                sample_business['id'], '+19999999999'
            )

            assert success is False
            assert 'don\'t see' in message.lower() or "couldn't find" in message.lower()
            assert cancelled is None

    def test_reschedule_caller_appointment(self, test_db, sample_business):
        """Should reschedule a caller's appointment."""
        with patch('core.db.DB_PATH', test_db):
            from core.db import get_conn, get_appointment_by_id
            from datetime import datetime, timedelta

            # Create service (use INSERT OR REPLACE to handle existing)
            with get_conn() as con:
                con.execute(
                    """INSERT OR REPLACE INTO services (business_id, name, duration_min, active)
                       VALUES (?, ?, ?, ?)""",
                    (sample_business['id'], 'Reschedule Test Service', 30, 1)
                )
                con.commit()

            # Create future appointment
            future_date = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d 14:00')
            with get_conn() as con:
                cur = con.cursor()
                cur.execute(
                    """INSERT INTO appointments (business_id, customer_name, phone, service, start_at, status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (sample_business['id'], 'Test Customer', '+14155557777', 'Reschedule Test Service', future_date, 'confirmed')
                )
                con.commit()
                appt_id = cur.lastrowid

            from core.voice import reschedule_caller_appointment
            new_date = (datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d 10:00')
            success, message, updated = reschedule_caller_appointment(
                sample_business['id'], '+14155557777', new_date
            )

            assert success is True
            assert 'moved' in message.lower() or 'rescheduled' in message.lower()
            assert updated is not None

            # Verify it was actually rescheduled
            appt = get_appointment_by_id(appt_id)
            assert appt['start_at'] == new_date

    def test_pending_change_store_and_retrieve(self):
        """Should store and retrieve pending changes."""
        from core.voice import (
            store_voice_pending_change,
            get_voice_pending_change,
            clear_voice_pending_change
        )

        call_id = 'test_call_456'
        change_data = {'appointment_id': 123}

        store_voice_pending_change(call_id, 'cancel', change_data)

        pending = get_voice_pending_change(call_id)
        assert pending is not None
        assert pending['type'] == 'cancel'
        assert pending['data']['appointment_id'] == 123

        # Clear and verify
        cleared = clear_voice_pending_change(call_id)
        assert cleared is not None
        assert get_voice_pending_change(call_id) is None

    def test_voice_prompt_with_appointments_context(self):
        """Voice prompt should include appointments context."""
        from core.ai import _voice_business_prompt

        bd = {'name': 'StyleCuts', 'tone': 'friendly'}
        appointments_context = "Upcoming appointments: Haircut on Tuesday, January 28 at 2:30 PM"

        prompt = _voice_business_prompt(bd, appointments_context=appointments_context)

        assert 'Upcoming appointments' in prompt
        assert 'VOICE_CANCEL' in prompt
        assert 'VOICE_RESCHEDULE' in prompt
