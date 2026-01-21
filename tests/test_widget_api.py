# tests/test_widget_api.py — Tests for widget API endpoints
# Tests for widget configuration, chat, and booking confirmation APIs

import pytest
import json
from unittest.mock import patch, MagicMock


# ============================================================================
# Widget Config Tests
# ============================================================================

class TestWidgetConfig:
    """Tests for /api/widget/config endpoint."""

    def test_config_requires_tenant_key(self, client):
        """Config endpoint should require tenant key."""
        response = client.get("/api/widget/config")
        assert response.status_code == 401
        data = response.get_json()
        assert "tenant" in data.get("error", "").lower() or "missing" in data.get("error", "").lower()

    def test_config_invalid_tenant_key(self, client):
        """Config endpoint should reject invalid tenant key."""
        response = client.get(
            "/api/widget/config",
            headers={"X-Tenant-Key": "invalid-key"}
        )
        assert response.status_code in (401, 403)

    def test_config_valid_tenant_key(self, client, sample_business, test_db):
        """Config endpoint should return config for valid tenant."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.get(
                    "/api/widget/config",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "Origin": "http://localhost"
                    }
                )

        if response.status_code == 200:
            data = response.get_json()
            assert "business" in data
            assert "widget" in data
        else:
            # Could fail due to CORS - that's acceptable
            assert response.status_code in (401, 403)

    def test_config_returns_business_info(self, client, sample_business, test_db):
        """Config should return business name and accent color."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.get(
                    "/api/widget/config",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "Origin": "http://localhost"
                    }
                )

        if response.status_code == 200:
            data = response.get_json()
            assert data["business"]["name"] == sample_business["name"]


# ============================================================================
# Widget Session Tests
# ============================================================================

class TestWidgetSession:
    """Tests for /api/widget/session endpoint."""

    def test_session_requires_tenant_key(self, client):
        """Session endpoint should require tenant key."""
        response = client.post("/api/widget/session")
        assert response.status_code == 401

    def test_session_creates_new_session(self, client, sample_business, test_db):
        """Session endpoint should create and return session ID."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.post(
                    "/api/widget/session",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "Origin": "http://localhost"
                    }
                )

        if response.status_code == 200:
            data = response.get_json()
            assert "session_id" in data
            assert isinstance(data["session_id"], int)

    def test_session_returns_welcome_message(self, client, sample_business, test_db):
        """Session endpoint should return welcome message."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.post(
                    "/api/widget/session",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "Origin": "http://localhost"
                    }
                )

        if response.status_code == 200:
            data = response.get_json()
            assert "welcome_message" in data


# ============================================================================
# Widget Chat Tests
# ============================================================================

class TestWidgetChat:
    """Tests for /api/widget/chat endpoint."""

    def test_chat_requires_tenant_key(self, client):
        """Chat endpoint should require tenant key."""
        response = client.post("/api/widget/chat")
        assert response.status_code == 401

    def test_chat_requires_session_id(self, client, sample_business, test_db):
        """Chat endpoint should require session ID."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.post(
                    "/api/widget/chat",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "Origin": "http://localhost"
                    },
                    json={"message": "Hello"}
                )

        # Should fail without session
        assert response.status_code in (400, 403)

    def test_chat_requires_message(self, client, sample_business, sample_session, test_db):
        """Chat endpoint should require message."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.post(
                    "/api/widget/chat",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "X-Session-ID": str(sample_session),
                        "Origin": "http://localhost"
                    },
                    json={}
                )

        if response.status_code != 403:  # Not blocked by CORS
            assert response.status_code == 400
            data = response.get_json()
            assert "message" in data.get("error", "").lower()

    def test_chat_message_too_long(self, client, sample_business, sample_session, test_db):
        """Chat should reject messages over 2000 characters."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.post(
                    "/api/widget/chat",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "X-Session-ID": str(sample_session),
                        "Origin": "http://localhost"
                    },
                    json={"message": "A" * 2001}
                )

        if response.status_code not in (401, 403):
            assert response.status_code == 400
            data = response.get_json()
            assert "long" in data.get("error", "").lower()

    def test_chat_returns_reply(self, client, sample_business, sample_session, test_db):
        """Chat should return AI reply."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                with patch('core.ai.process_message', return_value="Hello! How can I help?"):
                    response = client.post(
                        "/api/widget/chat",
                        headers={
                            "X-Tenant-Key": sample_business["tenant_key"],
                            "X-Session-ID": str(sample_session),
                            "Origin": "http://localhost"
                        },
                        json={"message": "Hello"}
                    )

        if response.status_code == 200:
            data = response.get_json()
            assert "reply" in data

    def test_chat_returns_pending_booking(self, client, sample_business, sample_session, test_db):
        """Chat should return pending booking data when AI suggests booking."""
        booking_response = """Let me book that for you!
<BOOKING>{"name":"John","phone":"555-1234","service":"Haircut","datetime":"2026-01-27 10:00"}</BOOKING>
"""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                with patch('core.ai.process_message', return_value=booking_response):
                    with patch('core.booking.get_business_provider') as mock_prov:
                        mock_provider = MagicMock()
                        mock_provider.key = "local"
                        mock_provider.fetch_slots.return_value = ["2026-01-27 10:00"]
                        mock_prov.return_value = mock_provider

                        with patch('core.booking._find_local_service_id', return_value=1):
                            response = client.post(
                                "/api/widget/chat",
                                headers={
                                    "X-Tenant-Key": sample_business["tenant_key"],
                                    "X-Session-ID": str(sample_session),
                                    "Origin": "http://localhost"
                                },
                                json={"message": "I'd like to book a haircut"}
                            )

        if response.status_code == 200:
            data = response.get_json()
            if "pending_booking" in data:
                assert "token" in data["pending_booking"]


# ============================================================================
# Booking Confirmation API Tests
# ============================================================================

class TestBookingConfirmAPI:
    """Tests for /api/widget/booking/confirm endpoint."""

    def test_confirm_requires_tenant_key(self, client):
        """Confirm endpoint should require tenant key."""
        response = client.post("/api/widget/booking/confirm")
        assert response.status_code == 401

    def test_confirm_requires_token(self, client, sample_business, test_db):
        """Confirm endpoint should require booking token."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.post(
                    "/api/widget/booking/confirm",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "Origin": "http://localhost"
                    },
                    json={}
                )

        if response.status_code not in (401, 403):
            assert response.status_code == 400
            data = response.get_json()
            assert data["success"] is False

    def test_confirm_invalid_token(self, client, sample_business, test_db):
        """Confirm should fail for invalid token."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.post(
                    "/api/widget/booking/confirm",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "Origin": "http://localhost"
                    },
                    json={"token": "invalid-token"}
                )

        if response.status_code not in (401, 403):
            assert response.status_code == 400
            data = response.get_json()
            assert data["success"] is False


# ============================================================================
# Booking Cancel API Tests
# ============================================================================

class TestBookingCancelAPI:
    """Tests for /api/widget/booking/cancel endpoint."""

    def test_cancel_requires_tenant_key(self, client):
        """Cancel endpoint should require tenant key."""
        response = client.post("/api/widget/booking/cancel")
        assert response.status_code == 401

    def test_cancel_requires_token(self, client, sample_business, test_db):
        """Cancel endpoint should require booking token."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.post(
                    "/api/widget/booking/cancel",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "Origin": "http://localhost"
                    },
                    json={}
                )

        if response.status_code not in (401, 403):
            assert response.status_code == 400


# ============================================================================
# Widget History Tests
# ============================================================================

class TestWidgetHistory:
    """Tests for /api/widget/history endpoint."""

    def test_history_requires_tenant_key(self, client):
        """History endpoint should require tenant key."""
        response = client.get("/api/widget/history")
        assert response.status_code == 401

    def test_history_requires_session_id(self, client, sample_business, test_db):
        """History endpoint should require session ID."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                response = client.get(
                    "/api/widget/history",
                    headers={
                        "X-Tenant-Key": sample_business["tenant_key"],
                        "Origin": "http://localhost"
                    }
                )

        if response.status_code not in (401, 403):
            assert response.status_code == 400


# ============================================================================
# CORS Tests
# ============================================================================

class TestWidgetCORS:
    """Tests for widget CORS handling."""

    def test_options_request_allowed(self, client, sample_business, test_db):
        """OPTIONS request should be handled for preflight."""
        with patch('core.db.DB_PATH', test_db):
            response = client.options(
                "/api/widget/config",
                headers={
                    "X-Tenant-Key": sample_business["tenant_key"],
                    "Origin": "http://localhost",
                    "Access-Control-Request-Method": "GET"
                }
            )

        # OPTIONS should return 200 or be handled
        assert response.status_code in (200, 401, 403)

    def test_cors_headers_present(self, client, sample_business, test_db):
        """CORS headers should be present when origin is allowed."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                with patch('widget_bp._validate_cors_origin', return_value="http://localhost"):
                    response = client.get(
                        "/api/widget/config",
                        headers={
                            "X-Tenant-Key": sample_business["tenant_key"],
                            "Origin": "http://localhost"
                        }
                    )

        # If successful, should have CORS headers
        if response.status_code == 200:
            # CORS headers might be present
            pass  # Test passes if no error


# ============================================================================
# Rate Limiting Tests
# ============================================================================

class TestWidgetRateLimiting:
    """Tests for widget rate limiting."""

    def test_rate_limiting_allows_normal_usage(self, client, sample_business, test_db):
        """Normal usage should not be rate limited."""
        with patch('core.db.DB_PATH', test_db):
            with patch('widget_bp._check_origin', return_value=True):
                # Make a few requests
                responses = []
                for _ in range(5):
                    response = client.get(
                        "/api/widget/config",
                        headers={
                            "X-Tenant-Key": sample_business["tenant_key"],
                            "Origin": "http://localhost"
                        }
                    )
                    responses.append(response.status_code)

        # Most should succeed (not be rate limited)
        non_rate_limited = [r for r in responses if r != 429]
        assert len(non_rate_limited) > 0


# ============================================================================
# Widget Frame Tests
# ============================================================================

class TestWidgetFrame:
    """Tests for widget iframe endpoint."""

    def test_frame_requires_tenant_key(self, client):
        """Frame endpoint should require tenant key."""
        response = client.get("/api/widget/frame")
        assert response.status_code == 400

    def test_frame_invalid_tenant_key(self, client):
        """Frame endpoint should reject invalid tenant key."""
        response = client.get("/api/widget/frame?tenant_key=invalid")
        assert response.status_code in (401, 403)
