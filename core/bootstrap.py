# core/bootstrap.py — first-run admin bootstrap from environment
#
# If ADMIN_EMAIL + ADMIN_PASSWORD are set and that admin doesn't exist yet,
# create it on startup. Safe + idempotent: it only CREATES a missing account
# (never overwrites an existing one), so it can't clobber a password you've
# changed. Also self-heals the admin after an ephemeral-disk wipe on Railway
# (until a persistent volume is attached).

import logging
import os

logger = logging.getLogger(__name__)


def ensure_admin() -> bool:
    """Create the env-specified admin if it's missing. Returns True if created."""
    email = (os.getenv("ADMIN_EMAIL") or "").strip()
    password = os.getenv("ADMIN_PASSWORD") or ""
    if not email or not password:
        return False
    if len(password) < 8:
        logger.warning("ADMIN_PASSWORD too short (<8 chars); skipping admin bootstrap")
        return False
    try:
        from werkzeug.security import generate_password_hash

        from core.db import get_conn, init_db

        init_db()
        with get_conn() as con:
            existing = con.execute(
                "SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)
            ).fetchone()
            if existing:
                return False  # already there — leave it untouched
            has_verified = any(
                r["name"] == "email_verified" for r in con.execute("PRAGMA table_info(users)")
            )
            pw_hash = generate_password_hash(password, method="pbkdf2:sha256:260000")
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
            con.commit()
        logger.info("Bootstrapped admin account '%s' from environment", email)
        return True
    except Exception:
        logger.exception("Admin bootstrap failed")
        return False
