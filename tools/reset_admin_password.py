#!/usr/bin/env python3
"""Reset (or create) the admin login — safe to run against production.

Hashes the password exactly the way the app does (pbkdf2:sha256:260000) and
writes to whatever database core.db points at (respects LOCUSAI_DB_PATH, so on
Railway it targets the live DB / volume).

Usage:
    python tools/reset_admin_password.py --email you@example.com --password 'NewStrongPass1'
    # or pass via env:
    ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='NewStrongPass1' python tools/reset_admin_password.py
    # omit the password to auto-generate a strong one (printed once):
    python tools/reset_admin_password.py --email you@example.com

On Railway (uses the deployed env + DB):
    railway run python tools/reset_admin_password.py --email you@example.com
"""

import argparse
import os
import secrets
import string
import sys

# Ensure project root on path when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from core.db import DB_PATH, get_conn, init_db  # noqa: E402

_HASH_METHOD = "pbkdf2:sha256:260000"  # must match auth_bp.py


def _gen_password(n: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    # Ensure at least one letter + one digit.
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if any(c.isalpha() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def _has_column(con, table: str, column: str) -> bool:
    return any(r["name"] == column for r in con.execute(f"PRAGMA table_info({table})"))


def reset_admin(email: str, password: str) -> str:
    email = email.strip()
    if not email or "@" not in email:
        raise SystemExit("error: a valid --email is required")
    if len(password) < 8:
        raise SystemExit("error: password must be at least 8 characters")

    init_db()  # ensure schema exists
    pw_hash = generate_password_hash(password, method=_HASH_METHOD)

    with get_conn() as con:
        has_verified = _has_column(con, "users", "email_verified")
        row = con.execute(
            "SELECT id FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
        if row:
            con.execute(
                "UPDATE users SET password_hash=?, role='admin' WHERE id=?", (pw_hash, row["id"])
            )
            if has_verified:
                con.execute("UPDATE users SET email_verified=1 WHERE id=?", (row["id"],))
            action = "updated"
        else:
            if has_verified:
                con.execute(
                    "INSERT INTO users (email, name, password_hash, role, email_verified) "
                    "VALUES (?, ?, ?, 'admin', 1)",
                    (email, "Admin", pw_hash),
                )
            else:
                con.execute(
                    "INSERT INTO users (email, name, password_hash, role) "
                    "VALUES (?, ?, ?, 'admin')",
                    (email, "Admin", pw_hash),
                )
            action = "created"
        con.commit()
    return action


def main():
    ap = argparse.ArgumentParser(description="Reset or create the LocusAI admin login.")
    ap.add_argument("--email", default=os.getenv("ADMIN_EMAIL"), help="admin email")
    ap.add_argument(
        "--password",
        default=os.getenv("ADMIN_PASSWORD"),
        help="new password (auto-generated if omitted)",
    )
    args = ap.parse_args()

    if not args.email:
        raise SystemExit("error: --email (or ADMIN_EMAIL) is required")
    password = args.password or _gen_password()
    generated = not args.password

    action = reset_admin(args.email, password)

    print(f"\n✅ Admin {action}: {args.email}")
    print(f"   Database: {DB_PATH}")
    if generated:
        print(f"   Password (save this now — shown once): {password}")
    else:
        print("   Password: (the one you provided)")
    print("\nLog in at /login with the above credentials.\n")


if __name__ == "__main__":
    main()
