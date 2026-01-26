# tests/conftest.py — Pytest configuration and fixtures for LocusAI tests
# Provides comprehensive test infrastructure for all modules

import os
import sys
import tempfile
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Ensure project root is in path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Set test environment variables before importing app modules
os.environ.setdefault('FLASK_SECRET_KEY', 'test-secret-key-for-pytest-only')
os.environ.setdefault('ENV', 'test')


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture
def test_db():
    """Create a temporary test database with schema initialized."""
    # Create temp file for test database
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    # Patch the database path
    with patch('core.db.DB_PATH', db_path):
        from core.db import init_db, get_conn

        # Initialize schema
        init_db()

        yield db_path

    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def db_conn(test_db):
    """Get a database connection to the test database."""
    with patch('core.db.DB_PATH', test_db):
        from core.db import get_conn
        with get_conn() as conn:
            yield conn


@pytest.fixture
def sample_business(test_db):
    """Create a sample business for testing."""
    with patch('core.db.DB_PATH', test_db):
        from core.db import get_conn

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO businesses (name, slug, tenant_key, hours, address, tone)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                'Test Business',
                'test-business',
                'test-tenant-key-12345',
                '{"mon": "9:00-17:00"}',
                '123 Test Street',
                'friendly'
            ))
            business_id = cursor.lastrowid

            # Add services
            cursor.execute("""
                INSERT INTO services (business_id, name, duration_min, price, active)
                VALUES (?, ?, ?, ?, ?)
            """, (business_id, 'Haircut', 30, '25.00', 1))

            cursor.execute("""
                INSERT INTO services (business_id, name, duration_min, price, active)
                VALUES (?, ?, ?, ?, ?)
            """, (business_id, 'Coloring', 90, '75.00', 1))

            # Add business hours (Mon-Fri 9-17, Sat 10-14, Sun closed)
            for weekday in range(7):
                if weekday < 5:  # Mon-Fri
                    cursor.execute("""
                        INSERT INTO business_hours (business_id, weekday, open_time, close_time, closed)
                        VALUES (?, ?, ?, ?, ?)
                    """, (business_id, weekday, '09:00', '17:00', 0))
                elif weekday == 5:  # Sat
                    cursor.execute("""
                        INSERT INTO business_hours (business_id, weekday, open_time, close_time, closed)
                        VALUES (?, ?, ?, ?, ?)
                    """, (business_id, weekday, '10:00', '14:00', 0))
                else:  # Sun
                    cursor.execute("""
                        INSERT INTO business_hours (business_id, weekday, open_time, close_time, closed)
                        VALUES (?, ?, ?, ?, ?)
                    """, (business_id, weekday, None, None, 1))

            # Add widget settings
            cursor.execute("""
                INSERT INTO widget_settings (business_id, enabled, allowed_domains)
                VALUES (?, ?, ?)
            """, (business_id, 1, '["localhost", "127.0.0.1", "*"]'))

            conn.commit()

            # Return business dict
            row = conn.execute(
                "SELECT * FROM businesses WHERE id = ?", (business_id,)
            ).fetchone()

            yield dict(row)


@pytest.fixture
def sample_session(test_db, sample_business):
    """Create a sample chat session for testing."""
    with patch('core.db.DB_PATH', test_db):
        from core.db import create_session

        session_id = create_session(sample_business['id'])
        yield session_id


@pytest.fixture
def sample_user(test_db):
    """Create a sample user for testing."""
    with patch('core.db.DB_PATH', test_db):
        from core.db import get_conn
        from werkzeug.security import generate_password_hash

        with get_conn() as conn:
            cursor = conn.cursor()
            # Use pbkdf2 method for compatibility with Python 3.9
            cursor.execute("""
                INSERT INTO users (email, name, password_hash, role)
                VALUES (?, ?, ?, ?)
            """, (
                'test@example.com',
                'Test User',
                generate_password_hash('TestPass123', method='pbkdf2:sha256'),
                'owner'
            ))
            user_id = cursor.lastrowid
            conn.commit()

            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()

            yield dict(row)


@pytest.fixture
def admin_user(test_db):
    """Create an admin user for testing."""
    with patch('core.db.DB_PATH', test_db):
        from core.db import get_conn
        from werkzeug.security import generate_password_hash

        with get_conn() as conn:
            cursor = conn.cursor()
            # Use pbkdf2 method for compatibility with Python 3.9
            cursor.execute("""
                INSERT INTO users (email, name, password_hash, role)
                VALUES (?, ?, ?, ?)
            """, (
                'admin@example.com',
                'Admin User',
                generate_password_hash('AdminPass123', method='pbkdf2:sha256'),
                'admin'
            ))
            user_id = cursor.lastrowid
            conn.commit()

            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()

            yield dict(row)


# ============================================================================
# Flask App Fixtures
# ============================================================================

@pytest.fixture
def app(test_db):
    """Create Flask test application."""
    with patch('core.db.DB_PATH', test_db):
        # Import after patching
        from dashboard import app as flask_app

        flask_app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'SECRET_KEY': 'test-secret-key',
        })

        yield flask_app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def authenticated_client(app, sample_user, sample_business, test_db):
    """Create authenticated Flask test client."""
    with patch('core.db.DB_PATH', test_db):
        from core.db import get_conn

        # Link user to business
        with get_conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO business_users (user_id, business_id)
                VALUES (?, ?)
            """, (sample_user['id'], sample_business['id']))
            conn.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user'] = {
                    'id': sample_user['id'],
                    'email': sample_user['email'],
                    'name': sample_user['name'],
                    'role': sample_user['role'],
                }
                sess['active_business_id'] = sample_business['id']
            yield client


# ============================================================================
# Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_openai():
    """Mock OpenAI API calls."""
    with patch('core.ai.openai') as mock:
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="This is a test AI response."))
        ]
        mock.chat.completions.create.return_value = mock_response
        yield mock


@pytest.fixture
def mock_mailer():
    """Mock email sending."""
    with patch('core.mailer.send_email') as mock:
        mock.return_value = True
        yield mock


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def future_datetime():
    """Get a future datetime for booking tests."""
    # Next Monday at 10:00
    now = datetime.now()
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    return (now + timedelta(days=days_until_monday)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )


@pytest.fixture
def booking_json(future_datetime):
    """Sample booking JSON for testing."""
    return {
        "name": "John Doe",
        "phone": "555-123-4567",
        "email": "john@example.com",
        "service": "Haircut",
        "datetime": future_datetime.strftime("%Y-%m-%d %H:%M")
    }


@pytest.fixture
def ai_response_with_booking(booking_json):
    """Sample AI response containing a booking tag."""
    import json
    return f"""I'd be happy to book that for you! Let me confirm the details:

<BOOKING>{json.dumps(booking_json)}</BOOKING>

Your appointment has been scheduled. Is there anything else I can help you with?"""


# ============================================================================
# Cleanup
# ============================================================================

@pytest.fixture(autouse=True)
def cleanup_pending_bookings():
    """Clean up pending bookings after each test."""
    yield

    # Clear pending bookings
    try:
        from core.booking import _PENDING_BOOKINGS
        _PENDING_BOOKINGS.clear()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset circuit breaker state after each test."""
    yield

    try:
        from core.circuit_breaker import _ai_circuit_breaker
        if _ai_circuit_breaker:
            _ai_circuit_breaker._circuits.clear()
    except ImportError:
        pass
