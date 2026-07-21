# tests/test_booking_confirmation.py — Tests for booking confirmation flow
# Tests for pending bookings, confirmation, and cancellation

import json
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core import pending_store
from core.booking import (
    _BOOKING_KIND,
    PENDING_BOOKING_TTL,
    _cleanup_expired_bookings,
    _generate_booking_token,
    cancel_pending_booking,
    confirm_pending_booking,
    extract_pending_booking,
    get_pending_booking,
)


def _store_booking(token, data, ttl=PENDING_BOOKING_TTL):
    """Helper: stage a pending booking in the shared store (test convenience)."""
    pending_store.put(token, _BOOKING_KIND, data, ttl, business_id=data.get("business_id"))


def _has_booking(token):
    return pending_store.get(token, _BOOKING_KIND) is not None

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
        "datetime": future_slot.strftime("%Y-%m-%d %H:%M"),
    }
    return f"""I'd be happy to book that for you!

<BOOKING>{json.dumps(booking_data)}</BOOKING>

Your appointment has been scheduled."""


# Storage-touching tests take the `test_db` fixture (temp DB per test), so the
# shared pending_store is naturally isolated between tests — no manual cleanup.


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
        assert all(c in "0123456789abcdef" for c in token)


# ============================================================================
# Extract Pending Booking Tests
# ============================================================================


class TestExtractPendingBooking:
    """Tests for extracting pending bookings from AI responses."""

    def test_extract_booking_from_response(self, booking_response, sample_business, test_db):
        """Should extract booking data from AI response."""
        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 10:00"]
            mock_provider.return_value = mock_prov

            with patch("core.booking._find_local_service_id", return_value=1):
                clean_text, pending = extract_pending_booking(
                    booking_response, sample_business, session_id=123
                )

        assert pending is not None
        assert "token" in pending
        assert pending["customer_name"] == "John Doe"
        assert pending["phone"] == "555-123-4567"
        assert pending["email"] == "john@example.com"
        assert pending["service"] == "Haircut"

    def test_booking_tag_removed_from_text(self, booking_response, sample_business, test_db):
        """Booking tag should be removed from returned text."""
        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 10:00"]
            mock_provider.return_value = mock_prov

            with patch("core.booking._find_local_service_id", return_value=1):
                clean_text, _ = extract_pending_booking(
                    booking_response, sample_business, session_id=123
                )

        assert "<BOOKING>" not in clean_text
        assert "</BOOKING>" not in clean_text

    def test_no_booking_tag_returns_none(self, sample_business, test_db):
        """Text without booking tag should return None for pending."""
        clean_text, pending = extract_pending_booking(
            "Just a normal response.", sample_business, session_id=123
        )

        assert pending is None
        assert clean_text == "Just a normal response."

    def test_pending_booking_stored_in_shared_store(self, booking_response, sample_business, test_db):
        """Pending booking should be persisted to the shared cross-worker store."""
        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 10:00"]
            mock_provider.return_value = mock_prov

            with patch("core.booking._find_local_service_id", return_value=1):
                _, pending = extract_pending_booking(
                    booking_response, sample_business, session_id=123
                )

        assert _has_booking(pending["token"])

    def test_expires_in_included(self, booking_response, sample_business, test_db):
        """Pending booking should include expiration info."""
        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 10:00"]
            mock_provider.return_value = mock_prov

            with patch("core.booking._find_local_service_id", return_value=1):
                _, pending = extract_pending_booking(
                    booking_response, sample_business, session_id=123
                )

        assert "expires_in" in pending
        assert pending["expires_in"] == PENDING_BOOKING_TTL

    def test_invalid_json_handled(self, sample_business, test_db):
        """Invalid JSON in booking tag should be handled gracefully."""
        bad_response = """Here's your booking:
<BOOKING>{invalid json here}</BOOKING>
"""
        clean_text, pending = extract_pending_booking(bad_response, sample_business, session_id=123)

        assert pending is None
        assert "provide your details again" in clean_text

    def test_no_slots_available_handled(self, sample_business, test_db):
        """No available slots should be handled gracefully."""
        booking_data = {
            "name": "John",
            "phone": "555-1234",
            "service": "Haircut",
            "datetime": "2026-01-27 10:00",
        }
        response = f"<BOOKING>{json.dumps(booking_data)}</BOOKING>"

        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = []  # No slots
            mock_provider.return_value = mock_prov

            with patch("core.booking._find_local_service_id", return_value=1):
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

    def test_confirm_valid_booking(self, sample_business, test_db):
        """Should successfully confirm a valid pending booking."""
        # Create a pending booking
        token = _generate_booking_token(1, 123)
        _store_booking(token, {
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
        })

        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.create_booking.return_value = {"external_id": None}
            mock_provider.return_value = mock_prov

            with patch("core.booking.get_business_provider_key", return_value="local"):
                with patch("core.booking.create_appointment", return_value=1):
                    success, message, appt_id = confirm_pending_booking(token)

        assert success is True
        assert appt_id == 1
        assert "confirmed" in message.lower()
        assert not _has_booking(token)  # Should be removed

    def test_confirm_expired_booking(self, test_db):
        """Should fail for expired booking."""
        token = _generate_booking_token(1, 123)
        # Negative TTL stores an already-expired row.
        _store_booking(token, {
            "token": token,
            "business_id": 1,
            "session_id": 123,
        }, ttl=-300)

        success, message, appt_id = confirm_pending_booking(token)

        assert success is False
        assert "expired" in message.lower()
        assert appt_id is None

    def test_confirm_nonexistent_booking(self, test_db):
        """Should fail for nonexistent token."""
        success, message, appt_id = confirm_pending_booking("nonexistent-token")

        assert success is False
        assert "expired" in message.lower() or "processed" in message.lower()
        assert appt_id is None

    def test_confirm_removes_from_pending(self, sample_business, test_db):
        """Confirming should remove booking from pending."""
        token = _generate_booking_token(1, 123)
        _store_booking(token, {
            "token": token,
            "business_id": 1,
            "session_id": 123,
            "customer_name": "John",
            "phone": "555-1234",
            "slot": "2026-01-27 10:00",
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_BOOKING_TTL,
        })

        assert _has_booking(token)

        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.create_booking.return_value = {}
            mock_provider.return_value = mock_prov

            with patch("core.booking.get_business_provider_key", return_value="local"):
                with patch("core.booking.create_appointment", return_value=1):
                    confirm_pending_booking(token)

        assert not _has_booking(token)


# ============================================================================
# Cancel Pending Booking Tests
# ============================================================================


class TestCancelPendingBooking:
    """Tests for cancelling pending bookings."""

    def test_cancel_valid_booking(self, test_db):
        """Should successfully cancel a valid pending booking."""
        token = _generate_booking_token(1, 123)
        _store_booking(token, {
            "token": token,
            "session_id": 123,
            "customer_name": "John",
        })

        success, message = cancel_pending_booking(token)

        assert success is True
        assert "cancelled" in message.lower()
        assert not _has_booking(token)

    def test_cancel_nonexistent_booking(self, test_db):
        """Should fail gracefully for nonexistent token."""
        success, message = cancel_pending_booking("nonexistent-token")

        assert success is False
        assert "no pending booking" in message.lower()

    def test_cancel_already_cancelled(self, test_db):
        """Cancelling twice should fail gracefully."""
        token = _generate_booking_token(1, 123)
        _store_booking(token, {"token": token, "session_id": 123})

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

    def test_get_existing_booking(self, test_db):
        """Should return booking details for valid token."""
        token = _generate_booking_token(1, 123)
        booking_data = {
            "token": token,
            "customer_name": "John",
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_BOOKING_TTL,
        }
        _store_booking(token, booking_data)

        result = get_pending_booking(token)

        assert result is not None
        assert result["customer_name"] == "John"

    def test_get_nonexistent_booking(self, test_db):
        """Should return None for nonexistent token."""
        result = get_pending_booking("nonexistent-token")
        assert result is None


# ============================================================================
# Cleanup Tests
# ============================================================================


class TestCleanupExpiredBookings:
    """Tests for automatic cleanup of expired bookings."""

    def test_cleanup_removes_expired(self, test_db):
        """Should remove expired bookings."""
        # Add an expired booking (negative TTL) and a valid one.
        expired_token = _generate_booking_token(1, 1)
        _store_booking(expired_token, {"created_at": time.time() - 600}, ttl=-300)

        valid_token = _generate_booking_token(1, 2)
        _store_booking(valid_token, {"created_at": time.time()})

        _cleanup_expired_bookings()

        assert not _has_booking(expired_token)
        assert _has_booking(valid_token)

    def test_cleanup_preserves_valid(self, test_db):
        """Should preserve non-expired bookings."""
        token = _generate_booking_token(1, 123)
        _store_booking(token, {"created_at": time.time()})

        _cleanup_expired_bookings()

        assert _has_booking(token)


# ============================================================================
# Integration Tests
# ============================================================================


class TestBookingConfirmationFlow:
    """Integration tests for the complete booking confirmation flow."""

    def test_full_flow_extract_confirm(self, sample_business, test_db):
        """Test complete flow from extraction to confirmation."""
        booking_data = {
            "name": "Jane Smith",
            "phone": "555-9876",
            "email": "jane@example.com",
            "service": "Coloring",
            "datetime": "2026-01-27 14:00",
        }
        response = f"<BOOKING>{json.dumps(booking_data)}</BOOKING>"

        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 14:00"]
            mock_prov.create_booking.return_value = {}
            mock_provider.return_value = mock_prov

            with patch("core.booking._find_local_service_id", return_value=2):
                with patch("core.booking.get_business_provider_key", return_value="local"):
                    with patch("core.booking.create_appointment", return_value=5):
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

    def test_full_flow_extract_cancel(self, sample_business, test_db):
        """Test complete flow from extraction to cancellation."""
        booking_data = {
            "name": "Bob Wilson",
            "phone": "555-5555",
            "service": "Haircut",
            "datetime": "2026-01-27 11:00",
        }
        response = f"<BOOKING>{json.dumps(booking_data)}</BOOKING>"

        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.fetch_slots.return_value = ["2026-01-27 11:00"]
            mock_provider.return_value = mock_prov

            with patch("core.booking._find_local_service_id", return_value=1):
                # Extract
                _, pending = extract_pending_booking(response, sample_business, session_id=789)

                assert pending is not None
                token = pending["token"]

                # Cancel
                success, message = cancel_pending_booking(token)

        assert success is True
        assert not _has_booking(token)

    def test_double_confirm_fails(self, sample_business, test_db):
        """Confirming the same booking twice should fail."""
        token = _generate_booking_token(1, 123)
        _store_booking(token, {
            "token": token,
            "business_id": 1,
            "session_id": 123,
            "customer_name": "John",
            "phone": "555-1234",
            "slot": "2026-01-27 10:00",
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_BOOKING_TTL,
        })

        with patch("core.booking.get_business_provider") as mock_provider:
            mock_prov = MagicMock()
            mock_prov.key = "local"
            mock_prov.create_booking.return_value = {}
            mock_provider.return_value = mock_prov

            with patch("core.booking.get_business_provider_key", return_value="local"):
                with patch("core.booking.create_appointment", return_value=1):
                    # First confirm
                    success1, _, _ = confirm_pending_booking(token)
                    assert success1 is True

                    # Second confirm
                    success2, message, _ = confirm_pending_booking(token)
                    assert success2 is False


# ============================================================================
# Real-Time Availability Tests
# ============================================================================


class TestAvailabilityFunctions:
    """Tests for real-time availability checking functions."""

    def test_get_available_slots_for_day(self):
        """Should return formatted time slots."""
        with patch("core.booking.get_business_provider") as mock_provider:
            with patch("core.booking._find_local_service_id", return_value=1):
                mock_prov = MagicMock()
                mock_prov.fetch_slots.return_value = [
                    "2026-01-27 09:00",
                    "2026-01-27 10:00",
                    "2026-01-27 14:30",
                ]
                mock_provider.return_value = mock_prov

                from core.booking import get_available_slots_for_day

                slots = get_available_slots_for_day(1, "2026-01-27", "Haircut")

                assert len(slots) == 3
                assert "9:00 AM" in slots
                assert "10:00 AM" in slots
                assert "2:30 PM" in slots

    def test_get_available_slots_no_provider(self):
        """Should return empty list if no provider."""
        with patch("core.booking.get_business_provider", return_value=None):
            from core.booking import get_available_slots_for_day

            slots = get_available_slots_for_day(999, "2026-01-27")
            assert slots == []

    def test_get_next_available_slots(self):
        """Should return slots across multiple days."""
        with patch("core.booking.get_business_provider") as mock_provider:
            with patch("core.booking._find_local_service_id", return_value=1):
                with patch("core.booking.get_conn"):
                    mock_prov = MagicMock()
                    # Return slots for any date (first call gets slots, rest empty)
                    call_count = [0]

                    def fake_fetch_slots(service_id, date_str):
                        call_count[0] += 1
                        if call_count[0] == 1:
                            return [f"{date_str} 10:00", f"{date_str} 11:00"]
                        elif call_count[0] == 2:
                            return [f"{date_str} 14:00"]
                        return []

                    mock_prov.fetch_slots.side_effect = fake_fetch_slots
                    mock_provider.return_value = mock_prov

                    from core.booking import get_next_available_slots

                    slots = get_next_available_slots(1, num_slots=5)

                    # Should have found slots
                    assert len(slots) >= 1
                    assert "times" in slots[0]
                    assert len(slots[0]["times"]) >= 1

    def test_check_time_available_true(self):
        """Should return True when slot is available."""
        with patch("core.db.check_slot_available", return_value=True):
            with patch("core.booking._find_local_service_id", return_value=1):
                with patch("core.booking.get_conn"):
                    from core.booking import check_time_available

                    is_available, alternative = check_time_available(1, "2026-01-27", "10:00")

                    assert is_available is True
                    assert alternative is None

    def test_check_time_available_false_with_alternative(self):
        """Should suggest alternative when slot is taken."""
        with patch("core.db.check_slot_available", return_value=False):
            with patch(
                "core.booking.get_available_slots_for_day", return_value=["11:00 AM", "2:00 PM"]
            ):
                from core.booking import check_time_available

                is_available, alternative = check_time_available(1, "2026-01-27", "10:00")

                assert is_available is False
                assert alternative == "11:00 AM"

    def test_format_availability_for_voice(self):
        """Should format availability in a voice-friendly way."""
        with patch("core.booking.get_next_available_slots") as mock_slots:
            mock_slots.return_value = [
                {"day": "Today", "date": "2026-01-27", "times": ["10:00 AM", "2:30 PM"]},
                {"day": "Tomorrow", "date": "2026-01-28", "times": ["9:00 AM"]},
            ]

            from core.booking import format_availability_for_voice

            result = format_availability_for_voice(1)

            assert "Available times:" in result
            assert "Today:" in result
            assert "10:00 AM" in result
            assert "Tomorrow:" in result

    def test_format_availability_no_slots(self):
        """Should return helpful message when no slots available."""
        with patch("core.booking.get_next_available_slots", return_value=[]):
            from core.booking import format_availability_for_voice

            result = format_availability_for_voice(1)

            assert "No availability" in result or "Ask the caller" in result
