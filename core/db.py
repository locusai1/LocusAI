import os
import re
import sqlite3

DB_PATH = "receptionist.db"

def get_conn():
    """Create a SQLite connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialise all required tables if they don’t exist."""
    with get_conn() as con:
        con.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS business_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sender TEXT NOT NULL CHECK(sender IN ('user','bot')),
            text TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            session_id INTEGER,
            date TEXT,
            time TEXT,
            service TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses(id),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
        """)


# --- Utility helpers ---

def slugify(name: str) -> str:
    """Convert business name to slug (safe for filenames/URLs)."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# --- Business management ---

def get_or_create_business(name: str):
    """Find a business or create it if it doesn’t exist."""
    slug = slugify(name)
    with get_conn() as con:
        row = con.execute("SELECT id FROM businesses WHERE slug = ?", (slug,)).fetchone()
        if row:
            return row["id"], slug
        con.execute("INSERT INTO businesses (name, slug) VALUES (?, ?)", (name, slug))
        new_id = con.execute("SELECT id FROM businesses WHERE slug = ?", (slug,)).fetchone()["id"]
        return new_id, slug


def add_business_info(business_id: int, key: str, value: str):
    with get_conn() as con:
        con.execute(
            "INSERT INTO business_info (business_id, key, value) VALUES (?, ?, ?)",
            (business_id, key, value)
        )


def get_business_info(business_id: int):
    with get_conn() as con:
        rows = con.execute("SELECT key, value FROM business_info WHERE business_id = ?", (business_id,)).fetchall()
        return {row["key"]: row["value"] for row in rows}


# --- FAQ management ---

def add_faq(business_id: int, question: str, answer: str):
    with get_conn() as con:
        con.execute(
            "INSERT INTO faqs (business_id, question, answer) VALUES (?, ?, ?)",
            (business_id, question, answer)
        )


def get_faqs(business_id: int):
    with get_conn() as con:
        rows = con.execute("SELECT question, answer FROM faqs WHERE business_id = ?", (business_id,)).fetchall()
        return {row["question"]: row["answer"] for row in rows}


# --- Sessions & messages ---

def create_session(business_id: int) -> int:
    with get_conn() as con:
        cur = con.execute("INSERT INTO sessions (business_id) VALUES (?)", (business_id,))
        return cur.lastrowid


def log_message(session_id: int, sender: str, text: str):
    with get_conn() as con:
        con.execute(
            "INSERT INTO messages (session_id, sender, text) VALUES (?, ?, ?)",
            (session_id, sender, text),
        )


# --- Appointments ---

def log_appointment(business_id: int, session_id: int, date: str, time: str, service: str):
    with get_conn() as con:
        con.execute(
            "INSERT INTO appointments (business_id, session_id, date, time, service) VALUES (?, ?, ?, ?, ?)",
            (business_id, session_id, date, time, service),
        )

