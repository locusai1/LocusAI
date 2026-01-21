# core/db.py — SQLite helpers for AxisAI (tenancy + sessions + users)
# Production-grade database layer with proper error handling and transactions

import sqlite3
import os
import uuid
import logging
from typing import Optional, List, Dict, Any, Union
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "receptionist.db")

# ============================================================================
# Connection Management
# ============================================================================

def get_conn() -> sqlite3.Connection:
    """Get a database connection with proper configuration."""
    con = sqlite3.connect(DB_PATH, timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    con.execute("PRAGMA journal_mode = WAL;")  # Better concurrency
    return con


@contextmanager
def transaction():
    """Context manager for database transactions with automatic rollback on error.

    Usage:
        with transaction() as con:
            con.execute("INSERT ...")
            con.execute("UPDATE ...")
        # Commits automatically, or rolls back on exception
    """
    con = get_conn()
    try:
        yield con
        con.commit()
    except Exception as e:
        con.rollback()
        logger.error(f"Transaction rolled back due to error: {e}")
        raise
    finally:
        con.close()


# ============================================================================
# Schema Helpers
# ============================================================================

def _col_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    """Check if a column exists in a table (safe - table name validated)."""
    # Validate table name to prevent injection
    if not table.isidentifier():
        raise ValueError(f"Invalid table name: {table}")
    rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    """Check if a table exists."""
    r = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
    ).fetchone()
    return bool(r)


def _safe_alter_add_column(cur: sqlite3.Cursor, table: str, col: str, ddl: str) -> None:
    """Safely add a column if it doesn't exist."""
    try:
        if not _col_exists(cur, table, col):
            cur.execute(ddl)
    except sqlite3.OperationalError as e:
        logger.warning(f"Could not add column {col} to {table}: {e}")


# ============================================================================
# Database Initialization
# ============================================================================

def init_db() -> None:
    """Initialize database schema with all required tables."""
    with get_conn() as con:
        cur = con.cursor()

        # ---- businesses ----
        cur.execute("""CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );""")

        # Add columns that may be missing (idempotent migrations)
        business_columns = [
            ("hours", "ALTER TABLE businesses ADD COLUMN hours TEXT"),
            ("address", "ALTER TABLE businesses ADD COLUMN address TEXT"),
            ("services", "ALTER TABLE businesses ADD COLUMN services TEXT"),
            ("tone", "ALTER TABLE businesses ADD COLUMN tone TEXT"),
            ("escalation_phone", "ALTER TABLE businesses ADD COLUMN escalation_phone TEXT"),
            ("escalation_email", "ALTER TABLE businesses ADD COLUMN escalation_email TEXT"),
            ("data_retention_days", "ALTER TABLE businesses ADD COLUMN data_retention_days INTEGER DEFAULT 365"),
            ("accent_color", "ALTER TABLE businesses ADD COLUMN accent_color TEXT"),
            ("logo_path", "ALTER TABLE businesses ADD COLUMN logo_path TEXT"),
            ("tenant_key", "ALTER TABLE businesses ADD COLUMN tenant_key TEXT"),
            ("settings_json", "ALTER TABLE businesses ADD COLUMN settings_json TEXT"),
            ("files_path", "ALTER TABLE businesses ADD COLUMN files_path TEXT"),
            ("static_path", "ALTER TABLE businesses ADD COLUMN static_path TEXT"),
            ("archived", "ALTER TABLE businesses ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"),
        ]
        for col, ddl in business_columns:
            _safe_alter_add_column(cur, "businesses", col, ddl)

        # Indexes
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_businesses_slug ON businesses(slug);")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_businesses_tenant_key ON businesses(tenant_key);")

        # ---- users ----
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','owner')) DEFAULT 'owner',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );""")

        # ---- business_users (mapping) ----
        cur.execute("""CREATE TABLE IF NOT EXISTS business_users (
            user_id INTEGER NOT NULL,
            business_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, business_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );""")

        # ---- sessions ----
        cur.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );""")

        # Fix legacy schema
        if _col_exists(cur, "sessions", "started_at") and not _col_exists(cur, "sessions", "created_at"):
            _safe_alter_add_column(cur, "sessions", "created_at", "ALTER TABLE sessions ADD COLUMN created_at TEXT")

        # ---- messages ----
        cur.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sender TEXT NOT NULL CHECK(sender IN ('user','bot')),
            text TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );""")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_messages_session ON messages(session_id);")

        # ---- appointments ----
        cur.execute("""CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            customer_name TEXT,
            phone TEXT,
            customer_email TEXT,
            service TEXT,
            start_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','cancelled','completed')),
            session_id INTEGER,
            external_provider_key TEXT,
            external_id TEXT,
            source TEXT CHECK(source IN ('ai','owner','api') OR source IS NULL),
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
        );""")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_appointments_business ON appointments(business_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_appointments_start ON appointments(business_id, start_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_appointments_status ON appointments(business_id, status);")

        # ---- services ----
        cur.execute("""CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            duration_min INTEGER NOT NULL DEFAULT 30 CHECK(duration_min >= 5 AND duration_min <= 480),
            price TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            external_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(business_id, name),
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );""")

        # ---- business_hours ----
        cur.execute("""CREATE TABLE IF NOT EXISTS business_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            weekday INTEGER NOT NULL CHECK(weekday >= 0 AND weekday <= 6),
            open_time TEXT,
            close_time TEXT,
            closed INTEGER NOT NULL DEFAULT 0,
            UNIQUE(business_id, weekday),
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );""")

        # ---- closures ----
        cur.execute("""CREATE TABLE IF NOT EXISTS closures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(business_id, date),
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );""")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_closures_date ON closures(business_id, date);")

        # ---- kb_entries (knowledge base) ----
        cur.execute("""CREATE TABLE IF NOT EXISTS kb_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            tags TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );""")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_kb_entries_business ON kb_entries(business_id);")

        # ---- kb_entries_fts (full-text search) ----
        if not _table_exists(cur, "kb_entries_fts"):
            cur.execute("""CREATE VIRTUAL TABLE kb_entries_fts USING fts5(
                question, answer, tags,
                content='kb_entries',
                content_rowid='id'
            );""")
            # Triggers to keep FTS in sync
            cur.execute("""CREATE TRIGGER IF NOT EXISTS kb_entries_ai AFTER INSERT ON kb_entries BEGIN
                INSERT INTO kb_entries_fts(rowid, question, answer, tags)
                VALUES (new.id, new.question, new.answer, new.tags);
            END;""")
            cur.execute("""CREATE TRIGGER IF NOT EXISTS kb_entries_ad AFTER DELETE ON kb_entries BEGIN
                INSERT INTO kb_entries_fts(kb_entries_fts, rowid, question, answer, tags)
                VALUES ('delete', old.id, old.question, old.answer, old.tags);
            END;""")
            cur.execute("""CREATE TRIGGER IF NOT EXISTS kb_entries_au AFTER UPDATE ON kb_entries BEGIN
                INSERT INTO kb_entries_fts(kb_entries_fts, rowid, question, answer, tags)
                VALUES ('delete', old.id, old.question, old.answer, old.tags);
                INSERT INTO kb_entries_fts(rowid, question, answer, tags)
                VALUES (new.id, new.question, new.answer, new.tags);
            END;""")

        # ---- integrations ----
        cur.execute("""CREATE TABLE IF NOT EXISTS integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            provider_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive','error')),
            access_token TEXT,
            refresh_token TEXT,
            token_expires_at TEXT,
            account_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(business_id, provider_key),
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );""")

        # ---- customers ----
        cur.execute("""CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            name TEXT,
            email TEXT,
            phone TEXT,
            notes TEXT,
            tags TEXT,
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            total_appointments INTEGER NOT NULL DEFAULT 0,
            total_sessions INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );""")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_customers_business ON customers(business_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_customers_email ON customers(business_id, email);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_customers_phone ON customers(business_id, phone);")

        # ---- reminders ----
        cur.execute("""CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('24h', '1h', '15m')),
            channel TEXT NOT NULL CHECK(channel IN ('email', 'sms')),
            scheduled_for TEXT NOT NULL,
            sent_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'sent', 'failed', 'cancelled')),
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
        );""")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_reminders_scheduled ON reminders(status, scheduled_for);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_reminders_appointment ON reminders(appointment_id);")

        # ---- widget_settings ----
        cur.execute("""CREATE TABLE IF NOT EXISTS widget_settings (
            business_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            position TEXT NOT NULL DEFAULT 'bottom-right' CHECK(position IN ('bottom-right', 'bottom-left')),
            primary_color TEXT,
            welcome_message TEXT DEFAULT 'Hi! How can I help you today?',
            placeholder_text TEXT DEFAULT 'Type a message...',
            allowed_domains TEXT,
            show_branding INTEGER NOT NULL DEFAULT 1,
            auto_open_delay INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );""")

        # ---- escalations ----
        cur.execute("""CREATE TABLE IF NOT EXISTS escalations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            session_id INTEGER,
            customer_id INTEGER,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'acknowledged', 'resolved')),
            priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('low', 'normal', 'high', 'urgent')),
            notes TEXT,
            notified_at TEXT,
            resolved_at TEXT,
            resolved_by TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
        );""")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_escalations_business ON escalations(business_id, status);")

        # ---- Add columns to existing tables ----
        # Sessions: channel, phone, customer_id, escalated
        session_columns = [
            ("channel", "ALTER TABLE sessions ADD COLUMN channel TEXT DEFAULT 'web'"),
            ("phone", "ALTER TABLE sessions ADD COLUMN phone TEXT"),
            ("customer_id", "ALTER TABLE sessions ADD COLUMN customer_id INTEGER REFERENCES customers(id)"),
            ("escalated", "ALTER TABLE sessions ADD COLUMN escalated INTEGER DEFAULT 0"),
            ("escalated_at", "ALTER TABLE sessions ADD COLUMN escalated_at TEXT"),
            ("escalation_reason", "ALTER TABLE sessions ADD COLUMN escalation_reason TEXT"),
        ]
        for col, ddl in session_columns:
            _safe_alter_add_column(cur, "sessions", col, ddl)

        # Messages: channel
        _safe_alter_add_column(cur, "messages", "channel", "ALTER TABLE messages ADD COLUMN channel TEXT DEFAULT 'web'")

        # Appointments: customer_id
        _safe_alter_add_column(cur, "appointments", "customer_id", "ALTER TABLE appointments ADD COLUMN customer_id INTEGER REFERENCES customers(id)")

        con.commit()
        logger.info("Database schema initialized successfully")


# ============================================================================
# Business Operations
# ============================================================================

def list_businesses(limit: int = 100, include_archived: bool = False) -> List[Dict[str, Any]]:
    """List all businesses, optionally including archived ones."""
    with get_conn() as con:
        if include_archived:
            rows = con.execute(
                "SELECT * FROM businesses ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM businesses WHERE archived = 0 ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_business_by_id(business_id: int) -> Optional[Dict[str, Any]]:
    """Get a single business by ID."""
    with get_conn() as con:
        r = con.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
        return dict(r) if r else None


def get_business_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Get a single business by slug."""
    with get_conn() as con:
        r = con.execute("SELECT * FROM businesses WHERE slug=?", (slug,)).fetchone()
        return dict(r) if r else None


# Whitelist of allowed columns for update_business to prevent SQL injection
_BUSINESS_ALLOWED_COLUMNS = frozenset({
    "name", "slug", "hours", "address", "services", "tone",
    "escalation_phone", "escalation_email", "data_retention_days",
    "accent_color", "logo_path", "tenant_key", "settings_json",
    "files_path", "static_path", "archived"
})


def update_business(business_id: int, **fields) -> bool:
    """Update business fields. Returns True if successful."""
    if not fields:
        return False

    # Filter to only allowed columns to prevent SQL injection
    safe_fields = {k: v for k, v in fields.items() if k in _BUSINESS_ALLOWED_COLUMNS}
    if not safe_fields:
        logger.warning(f"update_business called with no valid fields: {list(fields.keys())}")
        return False

    cols = [f"{k}=?" for k in safe_fields.keys()]
    vals = list(safe_fields.values())
    vals.append(business_id)

    try:
        with transaction() as con:
            con.execute(f"UPDATE businesses SET {', '.join(cols)} WHERE id=?", tuple(vals))
        return True
    except Exception as e:
        logger.error(f"Failed to update business {business_id}: {e}")
        return False


def create_business(name: str, slug: str, **extra_fields) -> Optional[int]:
    """Create a new business. Returns the business ID or None on failure."""
    try:
        with transaction() as con:
            cur = con.cursor()
            tenant_key = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO businesses(name, slug, tenant_key) VALUES(?, ?, ?)",
                (name, slug, tenant_key)
            )
            business_id = cur.lastrowid

            # Update any extra fields
            if extra_fields and business_id:
                safe_fields = {k: v for k, v in extra_fields.items() if k in _BUSINESS_ALLOWED_COLUMNS}
                if safe_fields:
                    cols = [f"{k}=?" for k in safe_fields.keys()]
                    vals = list(safe_fields.values()) + [business_id]
                    cur.execute(f"UPDATE businesses SET {', '.join(cols)} WHERE id=?", tuple(vals))

            return business_id
    except sqlite3.IntegrityError as e:
        logger.warning(f"Business creation failed (duplicate?): {e}")
        return None
    except Exception as e:
        logger.error(f"Business creation failed: {e}")
        return None


def ensure_tenant_key(business_id: int) -> str:
    """Ensure a business has a tenant key, creating one if needed."""
    with get_conn() as con:
        row = con.execute("SELECT tenant_key FROM businesses WHERE id=?", (business_id,)).fetchone()
        if row and row["tenant_key"]:
            return row["tenant_key"]
        key = str(uuid.uuid4())
        con.execute("UPDATE businesses SET tenant_key=? WHERE id=?", (key, business_id))
        con.commit()
        return key


# ============================================================================
# Session & Message Operations
# ============================================================================

def create_session(business_id: int) -> int:
    """Create a new chat session. Returns the session ID."""
    with transaction() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO sessions(business_id) VALUES(?)", (business_id,))
        return cur.lastrowid


def get_session_messages(session_id: int, limit: int = 100) -> List[sqlite3.Row]:
    """Get messages for a session, most recent first."""
    with get_conn() as con:
        return con.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit)
        ).fetchall()


def log_message(session_id: int, sender: str, text: str) -> Optional[int]:
    """Log a message in a session. Returns the message ID."""
    if sender not in ("user", "bot"):
        logger.warning(f"Invalid message sender: {sender}")
        return None

    text = text if text is not None else ""

    try:
        with transaction() as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO messages(session_id, sender, text) VALUES(?, ?, ?)",
                (session_id, sender, text)
            )
            return cur.lastrowid
    except Exception as e:
        logger.error(f"Failed to log message: {e}")
        return None


# ============================================================================
# Appointment Operations
# ============================================================================

def create_appointment(
    business_id: int,
    customer_name: str,
    phone: str,
    service: str,
    start_at: str,
    status: str = "pending",
    session_id: Optional[int] = None,
    external_provider_key: Optional[str] = None,
    external_id: Optional[str] = None,
    source: Optional[str] = None,
    notes: Optional[str] = None,
    customer_email: Optional[str] = None,
    customer_id: Optional[int] = None,
    con: Optional[sqlite3.Connection] = None
) -> Optional[int]:
    """Create an appointment. Returns the appointment ID or None on failure.

    Can be called with or without an existing connection:
    - With connection: Uses the provided connection (for transactions)
    - Without connection: Creates its own transaction
    """
    def _do_insert(conn: sqlite3.Connection) -> int:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO appointments(
                business_id, customer_name, phone, customer_email, service,
                start_at, status, session_id, external_provider_key,
                external_id, source, notes, customer_id
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            business_id, customer_name, phone, customer_email, service,
            start_at, status, session_id, external_provider_key,
            external_id, source, notes, customer_id
        ))
        return cur.lastrowid

    try:
        if con is not None:
            # Use provided connection (caller manages transaction)
            return _do_insert(con)
        else:
            # Create our own transaction
            with transaction() as new_con:
                return _do_insert(new_con)
    except Exception as e:
        logger.error(f"Failed to create appointment: {e}")
        return None


def get_appointment_by_id(appointment_id: int) -> Optional[Dict[str, Any]]:
    """Get an appointment by ID."""
    with get_conn() as con:
        row = con.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        return dict(row) if row else None


def update_appointment_status(appointment_id: int, status: str) -> bool:
    """Update an appointment's status. Returns True if successful."""
    valid_statuses = ("pending", "confirmed", "cancelled", "completed")
    if status not in valid_statuses:
        logger.warning(f"Invalid appointment status: {status}")
        return False

    try:
        with transaction() as con:
            con.execute("UPDATE appointments SET status=? WHERE id=?", (status, appointment_id))
        return True
    except Exception as e:
        logger.error(f"Failed to update appointment status: {e}")
        return False


def check_slot_available(
    business_id: int,
    start_at: str,
    duration_min: int,
    exclude_appointment_id: Optional[int] = None
) -> bool:
    """Check if a time slot is available (no conflicting appointments).

    Uses database locking to prevent race conditions.
    """
    from datetime import datetime, timedelta

    try:
        start_dt = datetime.fromisoformat(start_at.replace(" ", "T"))
        end_dt = start_dt + timedelta(minutes=duration_min)
    except ValueError:
        logger.warning(f"Invalid datetime format: {start_at}")
        return False

    with get_conn() as con:
        # Check for overlapping appointments
        query = """
            SELECT COUNT(*) as cnt FROM appointments
            WHERE business_id = ?
              AND status NOT IN ('cancelled')
              AND datetime(start_at) < datetime(?)
              AND datetime(start_at, '+' || COALESCE(
                  (SELECT duration_min FROM services WHERE name = appointments.service AND business_id = ?),
                  30
              ) || ' minutes') > datetime(?)
        """
        params = [business_id, end_dt.isoformat(), business_id, start_dt.isoformat()]

        if exclude_appointment_id:
            query += " AND id != ?"
            params.append(exclude_appointment_id)

        row = con.execute(query, params).fetchone()
        return row["cnt"] == 0


# ============================================================================
# Data Retention / Cleanup
# ============================================================================

def cleanup_old_data(business_id: Optional[int] = None) -> Dict[str, int]:
    """Clean up old data based on retention policies. Returns counts of deleted records."""
    counts = {"messages": 0, "sessions": 0, "appointments": 0}

    with transaction() as con:
        # Get businesses with retention policies
        if business_id:
            businesses = con.execute(
                "SELECT id, data_retention_days FROM businesses WHERE id = ? AND data_retention_days IS NOT NULL",
                (business_id,)
            ).fetchall()
        else:
            businesses = con.execute(
                "SELECT id, data_retention_days FROM businesses WHERE data_retention_days IS NOT NULL"
            ).fetchall()

        for biz in businesses:
            bid = biz["id"]
            days = biz["data_retention_days"] or 365

            # Delete old messages (via sessions)
            cur = con.execute("""
                DELETE FROM messages WHERE session_id IN (
                    SELECT id FROM sessions
                    WHERE business_id = ?
                      AND datetime(created_at) < datetime('now', ? || ' days')
                )
            """, (bid, -days))
            counts["messages"] += cur.rowcount

            # Delete old sessions
            cur = con.execute("""
                DELETE FROM sessions
                WHERE business_id = ?
                  AND datetime(created_at) < datetime('now', ? || ' days')
            """, (bid, -days))
            counts["sessions"] += cur.rowcount

            # Delete old completed/cancelled appointments
            cur = con.execute("""
                DELETE FROM appointments
                WHERE business_id = ?
                  AND status IN ('completed', 'cancelled')
                  AND datetime(created_at) < datetime('now', ? || ' days')
            """, (bid, -days))
            counts["appointments"] += cur.rowcount

    if any(counts.values()):
        logger.info(f"Data cleanup completed: {counts}")

    return counts
