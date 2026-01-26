# tests/test_db.py — Tests for core/db.py (Database Layer)

import pytest
import sqlite3
import os
from contextlib import contextmanager


class TestConnectionManagement:
    """Tests for database connection functions."""

    def test_get_conn_returns_connection(self):
        """Should return a valid SQLite connection."""
        from core.db import get_conn
        con = get_conn()
        assert isinstance(con, sqlite3.Connection)
        con.close()

    def test_get_conn_row_factory(self):
        """Should set row_factory to sqlite3.Row."""
        from core.db import get_conn
        con = get_conn()
        assert con.row_factory == sqlite3.Row
        con.close()

    def test_get_conn_foreign_keys_enabled(self):
        """Should enable foreign keys."""
        from core.db import get_conn
        con = get_conn()
        result = con.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1
        con.close()

    def test_get_conn_wal_mode(self):
        """Should use WAL journal mode."""
        from core.db import get_conn
        con = get_conn()
        result = con.execute("PRAGMA journal_mode").fetchone()
        assert result[0].lower() == "wal"
        con.close()


class TestTransaction:
    """Tests for transaction context manager."""

    def test_transaction_commits_on_success(self):
        """Should commit transaction on success."""
        from core.db import transaction, get_conn

        test_name = f"test_business_{os.getpid()}"

        with transaction() as con:
            con.execute(
                "INSERT INTO businesses (name, slug) VALUES (?, ?)",
                (test_name, test_name)
            )

        # Verify committed
        with get_conn() as con:
            row = con.execute(
                "SELECT name FROM businesses WHERE slug = ?", (test_name,)
            ).fetchone()
            assert row is not None
            assert row["name"] == test_name

        # Cleanup
        with get_conn() as con:
            con.execute("DELETE FROM businesses WHERE slug = ?", (test_name,))
            con.commit()

    def test_transaction_rollback_on_error(self):
        """Should rollback transaction on error."""
        from core.db import transaction, get_conn

        test_name = f"rollback_test_{os.getpid()}"

        try:
            with transaction() as con:
                con.execute(
                    "INSERT INTO businesses (name, slug) VALUES (?, ?)",
                    (test_name, test_name)
                )
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Should not be committed
        with get_conn() as con:
            row = con.execute(
                "SELECT name FROM businesses WHERE slug = ?", (test_name,)
            ).fetchone()
            assert row is None


class TestSchemaHelpers:
    """Tests for schema helper functions."""

    def test_col_exists_true(self):
        """Should return True for existing column."""
        from core.db import get_conn, _col_exists
        with get_conn() as con:
            cur = con.cursor()
            assert _col_exists(cur, "businesses", "name") is True

    def test_col_exists_false(self):
        """Should return False for non-existing column."""
        from core.db import get_conn, _col_exists
        with get_conn() as con:
            cur = con.cursor()
            assert _col_exists(cur, "businesses", "nonexistent_column") is False

    def test_col_exists_invalid_table(self):
        """Should raise error for invalid table name."""
        from core.db import get_conn, _col_exists
        with get_conn() as con:
            cur = con.cursor()
            with pytest.raises(ValueError):
                _col_exists(cur, "invalid-table-name!", "col")

    def test_table_exists_true(self):
        """Should return True for existing table."""
        from core.db import get_conn, _table_exists
        with get_conn() as con:
            cur = con.cursor()
            assert _table_exists(cur, "businesses") is True

    def test_table_exists_false(self):
        """Should return False for non-existing table."""
        from core.db import get_conn, _table_exists
        with get_conn() as con:
            cur = con.cursor()
            assert _table_exists(cur, "nonexistent_table") is False


class TestInitDb:
    """Tests for init_db function."""

    def test_init_db_creates_tables(self):
        """Should create all required tables."""
        from core.db import init_db, get_conn, _table_exists

        init_db()

        required_tables = [
            "businesses", "users", "sessions", "messages",
            "appointments", "services", "customers", "escalations",
            "kb_entries", "business_hours", "closures"
        ]

        with get_conn() as con:
            cur = con.cursor()
            for table in required_tables:
                assert _table_exists(cur, table), f"Table {table} should exist"

    def test_init_db_idempotent(self):
        """Should be safe to call multiple times."""
        from core.db import init_db
        init_db()
        init_db()  # Should not raise


class TestBusinessOperations:
    """Tests for business CRUD operations."""

    def test_list_businesses(self):
        """Should list all non-archived businesses."""
        from core.db import list_businesses
        result = list_businesses()
        assert isinstance(result, list)

    def test_get_business_by_id(self, sample_business):
        """Should return business by ID."""
        from core.db import get_business_by_id
        business = get_business_by_id(sample_business["id"])
        assert business is not None
        assert business["id"] == sample_business["id"]

    def test_get_business_by_id_not_found(self):
        """Should return None for non-existent business."""
        from core.db import get_business_by_id
        result = get_business_by_id(99999)
        assert result is None

    def test_get_business_by_slug(self, sample_business):
        """Should return business by slug."""
        from core.db import get_business_by_slug
        business = get_business_by_slug(sample_business["slug"])
        assert business is not None
        assert business["slug"] == sample_business["slug"]

    def test_create_business(self):
        """Should create a new business."""
        from core.db import create_business, get_business_by_id, get_conn
        import uuid

        unique_name = f"Test Business {uuid.uuid4().hex[:8]}"
        unique_slug = f"test-biz-{uuid.uuid4().hex[:8]}"

        business_id = create_business(name=unique_name, slug=unique_slug)
        assert business_id is not None
        assert isinstance(business_id, int)

        # Verify created
        business = get_business_by_id(business_id)
        assert business["name"] == unique_name
        assert business["slug"] == unique_slug

        # Cleanup
        with get_conn() as con:
            con.execute("DELETE FROM businesses WHERE id = ?", (business_id,))
            con.commit()

    def test_update_business(self, sample_business):
        """Should update business fields."""
        from core.db import update_business, get_business_by_id

        original_address = sample_business.get("address", "")
        new_address = "456 Updated Street"

        result = update_business(sample_business["id"], address=new_address)
        assert result is True

        updated = get_business_by_id(sample_business["id"])
        assert updated["address"] == new_address


class TestSessionOperations:
    """Tests for session operations."""

    def test_create_session(self, sample_business):
        """Should create a new session."""
        from core.db import create_session
        session_id = create_session(sample_business["id"])
        assert isinstance(session_id, int)
        assert session_id > 0

    def test_get_session_messages_empty(self, sample_session):
        """Should return empty list for new session."""
        from core.db import get_session_messages
        # sample_session is just an integer (session_id)
        messages = get_session_messages(sample_session)
        assert isinstance(messages, list)

    def test_log_message(self, sample_session):
        """Should log message to session."""
        from core.db import log_message, get_session_messages
        # sample_session is just an integer (session_id)
        log_message(sample_session, "user", "Hello!")
        log_message(sample_session, "bot", "Hi there!")

        messages = get_session_messages(sample_session)
        assert len(messages) >= 2


class TestAppointmentOperations:
    """Tests for appointment operations."""

    def test_create_appointment(self, sample_business):
        """Should create appointment."""
        from core.db import create_appointment
        from datetime import datetime, timedelta

        start = datetime.now() + timedelta(days=1)
        appt_id = create_appointment(
            business_id=sample_business["id"],
            customer_name="Test Customer",
            phone="555-1234",
            service="Haircut",
            start_at=start.isoformat()
        )
        assert isinstance(appt_id, int)
        assert appt_id > 0

    def test_get_appointment_by_id(self, sample_business):
        """Should retrieve appointment by ID."""
        from core.db import create_appointment, get_appointment_by_id
        from datetime import datetime, timedelta

        start = datetime.now() + timedelta(days=1)
        appt_id = create_appointment(
            business_id=sample_business["id"],
            customer_name="Retrieve Test",
            phone="555-5555",
            service="Test",
            start_at=start.isoformat()
        )

        appt = get_appointment_by_id(appt_id)
        assert appt is not None
        assert appt["customer_name"] == "Retrieve Test"

    def test_update_appointment_status(self, sample_business):
        """Should update appointment status."""
        from core.db import create_appointment, update_appointment_status, get_appointment_by_id
        from datetime import datetime, timedelta

        start = datetime.now() + timedelta(days=1)
        appt_id = create_appointment(
            business_id=sample_business["id"],
            customer_name="Status Test",
            phone="555-0000",
            service="Test",
            start_at=start.isoformat()
        )

        update_appointment_status(appt_id, "confirmed")
        appt = get_appointment_by_id(appt_id)
        assert appt["status"] == "confirmed"


class TestSlotAvailability:
    """Tests for slot availability checking."""

    def test_check_slot_available_empty(self, sample_business):
        """Should return True for empty slot."""
        from core.db import check_slot_available
        from datetime import datetime, timedelta

        # Far future time unlikely to have appointments
        future = datetime.now() + timedelta(days=100)
        available = check_slot_available(
            sample_business["id"],
            future.isoformat(),
            duration_min=30
        )
        assert available is True


class TestEnsureTenantKey:
    """Tests for tenant key generation."""

    def test_ensure_tenant_key_existing(self, sample_business):
        """Should return existing tenant key."""
        from core.db import ensure_tenant_key

        key = ensure_tenant_key(sample_business["id"])
        assert key == sample_business["tenant_key"]

    def test_ensure_tenant_key_creates_new(self):
        """Should create key if missing."""
        from core.db import create_business, ensure_tenant_key, get_conn
        import uuid

        # Create business without tenant key
        unique_slug = f"no-key-{uuid.uuid4().hex[:8]}"
        with get_conn() as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO businesses (name, slug) VALUES (?, ?)",
                (f"No Key Business {unique_slug}", unique_slug)
            )
            biz_id = cur.lastrowid
            con.commit()

        # Should create a new key
        key = ensure_tenant_key(biz_id)
        assert key is not None
        assert len(key) > 10

        # Cleanup
        with get_conn() as con:
            con.execute("DELETE FROM businesses WHERE id = ?", (biz_id,))
            con.commit()


class TestCleanupOldData:
    """Tests for data retention cleanup."""

    def test_cleanup_old_data_runs(self):
        """Should run cleanup without error."""
        from core.db import cleanup_old_data
        result = cleanup_old_data()
        assert isinstance(result, dict)
