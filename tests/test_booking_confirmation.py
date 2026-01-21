# tests/test_booking_confirmation.py — Tests for booking confirmation flow
# Tests for pending bookings, confirmation, and cancellation

import pytest
import json
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from core.booking import (
    extract_pending_booking,
    confirm_pending_booking,
    cancel_pending_booking,
    get_pending_booking,
    _PENDING_BOOKINGS,
    _generate_booking_token,
    _cleanup_expired_bookings,
    PENDING_BOOKING_TTL,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_business():
    """Sample business for booking tests."""
    return {
        "id": 1,
        "name": "Test Salon",
        "slug": "test-salon",
    }


@pytest.fixture
def future_slot():
    """A future datetime slot for bookings."""
    now = datetime.now()
    # Next Monday at 10:00
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    future = now + timedelta(days=days_until_monday)
    return future.replace(hour=10, minute=0, second=0, microsecond=0)


@pytest.fixture
def booking_response(future_slot):
    """AI response containing a booking tag."""
    booking_data = {
        "name": "John Doe",
        "phone": "555-123-4567",
        "email": "john@example.com",
        "service": "Haircut",
        "datetime": future_slot.strftime("%Y-%m-%d %H:%M")
    }
    return f"""I'd be happy to book that for you!

<BOOKING>{json.dumps(booking_data)}</BOOKING>

Your appointment has been scheduled."""


@pytest.fixture(autouse=True)
def cleanup_bookings():
    """Clean up pending bookings before and after each test."""
    _PENDING_BOOKINGS.clear()
    yield
    _PENDING_BOOKINGS.clear()


# ============================================================================
# Token Generation Tests
# ============================================================================

class TestTokenGeneration:
    """Tests for booking token generation."""

    def test_token_is_string(self):
        """Token should be a string."""
        token = _generate_booking_token(1, 1)
        assert isinstance(token, str)

    def test_token_has_correct_length(self):
        """Token should be 32 characters (hex)."""
        token = _generate_booking_token(1, 1)
        assert len(token) == 32

    def test_tokens_are_unique(self):
        """Each token should be unique."""
        tokens = [_generate_booking_token(1, 1) for _ in range(100)]
        assert len(set(tokens)) == 100

    def test_token_is_hex(self):
        """Token should be valid hex."""
        token = _generate_booking_token(1, 1)
        assert all(c in '0123456789abcdef' for c in token)


# ============================================================================
# Extract Pending Booking Tests
# ============================================================================

class TestExtractPendingBooking:
    """Tests for extracting pending bookings from AI responses."""

    def test_extract_booking_from_response(self, booking_response, sample_business):
        """Should extract booking data from AI response."""
        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 10:00"]
            mock_provider.return_value = mock_prov

            with patch('core.booking._find_local_service_id', return_value=1):
                clean_text, pending = extract_pending_booking(
                    booking_response, sample_business, session_id=123
                )

        assert pending is not None
        assert "token" in pending
        assert pending["customer_name"] == "John Doe"
        assert pending["phone"] == "555-123-4567"
        assert pending["email"] == "john@example.com"
        assert pending["service"] == "Haircut"

    def test_booking_tag_removed_from_text(self, booking_response, sample_business):
        """Booking tag should be removed from returned text."""
        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 10:00"]
            mock_provider.return_value = mock_prov

            with patch('core.booking._find_local_service_id', return_value=1):
                clean_text, _ = extract_pending_booking(
                    booking_response, sample_business, session_id=123
                )

        assert "<BOOKING>" not in clean_text
        assert "</BOOKING>" not in clean_text

    def test_no_booking_tag_returns_none(self, sample_business):
        """Text without booking tag should return None for pending."""
        clean_text, pending = extract_pending_booking(
            "Just a normal response.",
            sample_business,
            session_id=123
        )

        assert pending is None
        assert clean_text == "Just a normal response."

    def test_pending_booking_stored_in_memory(self, booking_response, sample_business):
        """Pending booking should be stored in memory."""
        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 10:00"]
            mock_provider.return_value = mock_prov

            with patch('core.booking._find_local_service_id', return_value=1):
                _, pending = extract_pending_booking(
                    booking_response, sample_business, session_id=123
                )

        assert pending["token"] in _PENDING_BOOKINGS

    def test_expires_in_included(self, booking_response, sample_business):
        """Pending booking should include expiration info."""
        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 10:00"]
            mock_provider.return_value = mock_prov

            with patch('core.booking._find_local_service_id', return_value=1):
                _, pending = extract_pending_booking(
                    booking_response, sample_business, session_id=123
                )

        assert "expires_in" in pending
        assert pending["expires_in"] == PENDING_BOOKING_TTL

    def test_invalid_json_handled(self, sample_business):
        """Invalid JSON in booking tag should be handled gracefully."""
        bad_response = """Here's your booking:
<BOOKING>{invalid json here}</BOOKING>
"""
        clean_text, pending = extract_pending_booking(
            bad_response, sample_business, session_id=123
        )

        assert pending is None
        assert "provide your details again" in clean_text

    def test_no_slots_available_handled(self, sample_business):
        """No available slots should be handled gracefully."""
        booking_data = {
            "name": "John",
            "phone": "555-1234",
            "service": "Haircut",
            "datetime": "2026-01-27 10:00"
        }
        response = f"<BOOKING>{json.dumps(booking_data)}</BOOKING>"

        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = []  # No slots
            mock_provider.return_value = mock_prov

            with patch('core.booking._find_local_service_id', return_value=1):
                clean_text, pending = extract_pending_booking(
                    response, sample_business, session_id=123
                )

        assert pending is None
        assert "different date" in clean_text or "different time" in clean_text


# ============================================================================
# Confirm Pending Booking Tests
# ============================================================================

class TestConfirmPendingBooking:
    """Tests for confirming pending bookings."""

    def test_confirm_valid_booking(self, sample_business):
        """Should successfully confirm a valid pending booking."""
        # Create a pending booking
        token = _generate_booking_token(1, 123)
        _PENDING_BOOKINGS[token] = {
            "token": token,
            "business_id": sample_business["id"],
            "session_id": 123,
            "customer_name": "John Doe",
            "phone": "555-1234",
            "email": "john@example.com",
            "service_name": "Haircut",
            "service_id": None,
            "local_service_id": 1,
            "slot": "2026-01-27 10:00",
            "notes": None,
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_BOOKING_TTL,
        }

        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.create_booking.return_value = {"external_id": None}
            mock_provider.return_value = mock_prov

            with patch('core.booking.get_business_provider_key', return_value="local"):
                with patch('core.booking.create_appointment', return_value=1):
                    success, message, appt_id = confirm_pending_booking(token)

        assert success is True
        assert appt_id == 1
        assert "confirmed" in message.lower()
        assert token not in _PENDING_BOOKINGS  # Should be removed

    def test_confirm_expired_booking(self):
        """Should fail for expired booking."""
        token = _generate_booking_token(1, 123)
        _PENDING_BOOKINGS[token] = {
            "token": token,
            "business_id": 1,
            "session_id": 123,
            "created_at": time.time() - 600,  # 10 minutes ago
            "expires_at": time.time() - 300,  # Expired 5 minutes ago
        }

        success, message, appt_id = confirm_pending_booking(token)

        assert success is False
        assert "expired" in message.lower()
        assert appt_id is None

    def test_confirm_nonexistent_booking(self):
        """Should fail for nonexistent token."""
        success, message, appt_id = confirm_pending_booking("nonexistent-token")

        assert success is False
        assert "expired" in message.lower() or "processed" in message.lower()
        assert appt_id is None

    def test_confirm_removes_from_pending(self, sample_business):
        """Confirming should remove booking from pending."""
        token = _generate_booking_token(1, 123)
        _PENDING_BOOKINGS[token] = {
            "token": token,
            "business_id": 1,
            "session_id": 123,
            "customer_name": "John",
            "phone": "555-1234",
            "slot": "2026-01-27 10:00",
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_BOOKING_TTL,
        }

        assert token in _PENDING_BOOKINGS

        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.create_booking.return_value = {}
            mock_provider.return_value = mock_prov

            with patch('core.booking.get_business_provider_key', return_value="local"):
                with patch('core.booking.create_appointment', return_value=1):
                    confirm_pending_booking(token)

        assert token not in _PENDING_BOOKINGS


# ============================================================================
# Cancel Pending Booking Tests
# ============================================================================

class TestCancelPendingBooking:
    """Tests for cancelling pending bookings."""

    def test_cancel_valid_booking(self):
        """Should successfully cancel a valid pending booking."""
        token = _generate_booking_token(1, 123)
        _PENDING_BOOKINGS[token] = {
            "token": token,
            "session_id": 123,
            "customer_name": "John",
        }

        success, message = cancel_pending_booking(token)

        assert success is True
        assert "cancelled" in message.lower()
        assert token not in _PENDING_BOOKINGS

    def test_cancel_nonexistent_booking(self):
        """Should fail gracefully for nonexistent token."""
        success, message = cancel_pending_booking("nonexistent-token")

        assert success is False
        assert "no pending booking" in message.lower()

    def test_cancel_already_cancelled(self):
        """Cancelling twice should fail gracefully."""
        token = _generate_booking_token(1, 123)
        _PENDING_BOOKINGS[token] = {"token": token, "session_id": 123}

        # First cancel
        success1, _ = cancel_pending_booking(token)
        assert success1 is True

        # Second cancel
        success2, message = cancel_pending_booking(token)
        assert success2 is False


# ============================================================================
# Get Pending Booking Tests
# ============================================================================

class TestGetPendingBooking:
    """Tests for retrieving pending booking details."""

    def test_get_existing_booking(self):
        """Should return booking details for valid token."""
        token = _generate_booking_token(1, 123)
        booking_data = {
            "token": token,
            "customer_name": "John",
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_BOOKING_TTL,
        }
        _PENDING_BOOKINGS[token] = booking_data

        result = get_pending_booking(token)

        assert result is not None
        assert result["customer_name"] == "John"

    def test_get_nonexistent_booking(self):
        """Should return None for nonexistent token."""
        result = get_pending_booking("nonexistent-token")
        assert result is None


# ============================================================================
# Cleanup Tests
# ============================================================================

class TestCleanupExpiredBookings:
    """Tests for automatic cleanup of expired bookings."""

    def test_cleanup_removes_expired(self):
        """Should remove expired bookings."""
        # Add an expired booking
        expired_token = _generate_booking_token(1, 1)
        _PENDING_BOOKINGS[expired_token] = {
            "created_at": time.time() - 600,  # 10 minutes ago
        }

        # Add a valid booking
        valid_token = _generate_booking_token(1, 2)
        _PENDING_BOOKINGS[valid_token] = {
            "created_at": time.time(),
        }

        _cleanup_expired_bookings()

        assert expired_token not in _PENDING_BOOKINGS
        assert valid_token in _PENDING_BOOKINGS

    def test_cleanup_preserves_valid(self):
        """Should preserve non-expired bookings."""
        token = _generate_booking_token(1, 123)
        _PENDING_BOOKINGS[token] = {
            "created_at": time.time(),
        }

        _cleanup_expired_bookings()

        assert token in _PENDING_BOOKINGS


# ============================================================================
# Integration Tests
# ============================================================================

class TestBookingConfirmationFlow:
    """Integration tests for the complete booking confirmation flow."""

    def test_full_flow_extract_confirm(self, sample_business):
        """Test complete flow from extraction to confirmation."""
        booking_data = {
            "name": "Jane Smith",
            "phone": "555-9876",
            "email": "jane@example.com",
            "service": "Coloring",
            "datetime": "2026-01-27 14:00"
        }
        response = f"<BOOKING>{json.dumps(booking_data)}</BOOKING>"

        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 14:00"]
            mock_prov.create_booking.return_value = {}
            mock_provider.return_value = mock_prov

            with patch('core.booking._find_local_service_id', return_value=2):
                with patch('core.booking.get_business_provider_key', return_value="local"):
                    with patch('core.booking.create_appointment', return_value=5):
                        # Extract
                        _, pending = extract_pending_booking(
                            response, sample_business, session_id=456
                        )

                        assert pending is not None
                        token = pending["token"]

                        # Confirm
                        success, message, appt_id = confirm_pending_booking(token)

        assert success is True
        assert appt_id == 5

    def test_full_flow_extract_cancel(self, sample_business):
        """Test complete flow from extraction to cancellation."""
        booking_data = {
            "name": "Bob Wilson",
            "phone": "555-5555",
            "service": "Haircut",
            "datetime": "2026-01-27 11:00"
        }
        response = f"<BOOKING>{json.dumps(booking_data)}</BOOKING>"

        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 11:00"]
            mock_provider.return_value = mock_prov

            with patch('core.booking._find_local_service_id', return_value=1):
                # Extract
                _, pending = extract_pending_booking(
                    response, sample_business, session_id=789
                )

                assert pending is not None
                token = pending["token"]

                # Cancel
                success, message = cancel_pending_booking(token)

        assert success is True
        assert token not in _PENDING_BOOKINGS

    def test_double_confirm_fails(self, sample_business):
        """Confirming the same booking twice should fail."""
        token = _generate_booking_token(1, 123)
        _PENDING_BOOKINGS[token] = {
            "token": token,
            "business_id": 1,
            "session_id": 123,
            "customer_name": "John",
            "phone": "555-1234",
            "slot": "2026-01-27 10:00",
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_BOOKING_TTL,
        }

        with patch('core.booking.get_business_provider') as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.create_booking.return_value = {}
            mock_provider.return_value = mock_prov

            with patch('core.booking.get_business_provider_key', return_value="local"):
                with patch('core.booking.create_appointment', return_value=1):
                    # First confirm
                    success1, _, _ = confirm_pending_booking(token)
                    assert success1 is True

                    # Second confirm
                    success2, message, _ = confirm_pending_booking(token)
                    assert success2 is False
