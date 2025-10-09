# core/db.py
import sqlite3
from contextlib import contextmanager

DB_PATH = "receptionist.db"

def _connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    # Enforce FK constraints
    con.execute("PRAGMA foreign_keys = ON;")
    return con

@contextmanager
def get_conn():
    con = _connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()

# ---------- Schema helpers ----------

def _table_exists(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
        (name,),
    ).fetchone()
    return bool(row)

def _has_column(con, table: str, column: str) -> bool:
    cols = con.execute(f"PRAGMA table_info({table});").fetchall()
    return any(c["name"] == column for c in cols)

def _ensure_table_businesses(con):
    if not _table_exists(con, "businesses"):
        con.execute("""
            CREATE TABLE businesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                slug TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
    # ensure optional columns exist
    for col in ("hours", "address", "services", "tone"):
        if not _has_column(con, "businesses", col):
            con.execute(f"ALTER TABLE businesses ADD COLUMN {col} TEXT;")

def _ensure_table_sessions(con):
    if not _table_exists(con, "sessions"):
        con.execute("""
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (business_id) REFERENCES businesses(id)
            );
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_sessions_business_id ON sessions(business_id);")

def _ensure_table_messages(con):
    if not _table_exists(con, "messages"):
        con.execute("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sender TEXT NOT NULL CHECK(sender IN ('user','bot')),
                text TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);")
    else:
        # make sure required columns exist (for older DBs)
        for col in ("session_id", "timestamp", "sender", "text"):
            if not _has_column(con, "messages", col):
                # we won't try to rebuild; raise to reveal mismatch
                raise RuntimeError(f"messages table missing required column: {col}")

def init_db():
    """Create/upgrade tables and indexes idempotently."""
    with get_conn() as con:
        _ensure_table_businesses(con)
        _ensure_table_sessions(con)
        _ensure_table_messages(con)

# ---------- Business helpers ----------

def create_business(name: str, slug: str, hours: str = None, address: str = None,
                    services: str = None, tone: str = None) -> int:
    with get_conn() as con:
        cur = con.execute("""
            INSERT INTO businesses (name, slug, hours, address, services, tone)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, slug, hours, address, services, tone))
        return cur.lastrowid

def update_business(business_id: int, **fields) -> None:
    if not fields:
        return
    cols = []
    vals = []
    for k, v in fields.items():
        if k not in {"name", "slug", "hours", "address", "services", "tone"}:
            continue
        cols.append(f"{k}=?")
        vals.append(v)
    if not cols:
        return
    vals.append(business_id)
    with get_conn() as con:
        con.execute(f"UPDATE businesses SET {', '.join(cols)} WHERE id=?;", vals)

def get_business_by_id(business_id: int):
    with get_conn() as con:
        return con.execute("SELECT * FROM businesses WHERE id=?;", (business_id,)).fetchone()

def list_businesses(limit: int = 100):
    with get_conn() as con:
        return con.execute(
            "SELECT * FROM businesses ORDER BY id DESC LIMIT ?;", (limit,)
        ).fetchall()

# ---------- Session & Messages ----------

def create_session(business_id: int) -> int:
    with get_conn() as con:
        cur = con.execute(
            "INSERT INTO sessions (business_id) VALUES (?)",
            (business_id,)
        )
        return cur.lastrowid

def log_message(session_id: int, sender: str, text) -> int:
    """
    Persist a message. Coerces None -> "" to satisfy NOT NULL on messages.text.
    'sender' must be 'user' or 'bot' to satisfy CHECK constraint.
    Returns inserted message id.
    """
    if sender not in ("user", "bot"):
        raise ValueError("sender must be 'user' or 'bot'")
    if text is None:
        text = ""
    else:
        text = str(text)

    with get_conn() as con:
        cur = con.execute(
            "INSERT INTO messages (session_id, sender, text) VALUES (?, ?, ?)",
            (session_id, sender, text),
        )
        return cur.lastrowid

def get_session_messages(session_id: int, limit: int = 100):
    with get_conn() as con:
        return con.execute("""
            SELECT id, session_id, timestamp, sender, text
            FROM messages
            WHERE session_id=?
            ORDER BY id DESC
            LIMIT ?;
        """, (session_id, limit)).fetchall()
