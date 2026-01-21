# auth_bp.py — Authentication with security best practices
# Includes session fixation protection and proper error handling

import logging
import secrets
from typing import Optional

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash

from core.db import get_conn, transaction
from core.validators import validate_email, validate_password

logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

bp = Blueprint("auth", __name__)


def _regenerate_session() -> None:
    """Regenerate session ID to prevent session fixation attacks."""
    # Store current session data
    old_data = dict(session)

    # Clear the session (this invalidates the old session ID)
    session.clear()

    # Restore the data (Flask will create a new session ID)
    session.update(old_data)

    # Mark session as permanent for proper expiry
    session.permanent = True


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login with security protections."""
    if request.method == "GET":
        # If already logged in, redirect to dashboard
        if session.get("user"):
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    # Extract credentials
    email_or_username = (
        request.form.get("email") or request.form.get("username") or ""
    ).strip().lower()
    password = request.form.get("password") or ""

    # Basic validation
    if not email_or_username or not password:
        flash("Please enter your email and password.", "err")
        return render_template("login.html"), 400

    # Look up user
    with get_conn() as con:
        # Try email first, then username
        row = con.execute(
            "SELECT * FROM users WHERE lower(email)=?", (email_or_username,)
        ).fetchone()
        if not row:
            row = con.execute(
                "SELECT * FROM users WHERE lower(name)=?", (email_or_username,)
            ).fetchone()

    # Verify credentials
    if not row or not check_password_hash(row["password_hash"], password):
        # Log failed attempt (without revealing which part failed)
        security_logger.warning(
            f"Failed login attempt for '{email_or_username}' from {request.remote_addr}"
        )
        flash("Invalid credentials.", "err")
        return render_template("login.html"), 401

    # Regenerate session to prevent session fixation
    _regenerate_session()

    # Build session user
    session["user"] = {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
    }

    # Set login timestamp for session timeout checks
    from datetime import datetime
    session["login_time"] = datetime.now().isoformat()

    # For non-admins, select their first business automatically
    if row["role"] != "admin":
        with get_conn() as con:
            m = con.execute(
                "SELECT business_id FROM business_users WHERE user_id=? ORDER BY created_at LIMIT 1",
                (row["id"],)
            ).fetchone()
        session["active_business_id"] = m["business_id"] if m else None
    else:
        session.setdefault("active_business_id", None)

    # Log successful login
    logger.info(f"User {row['id']} ({row['email']}) logged in from {request.remote_addr}")

    flash(f"Welcome back, {row['name']}.", "ok")
    return redirect(url_for("dashboard"))


@bp.route("/logout")
def logout():
    """Handle user logout."""
    user = session.get("user")
    if user:
        logger.info(f"User {user.get('id')} ({user.get('email')}) logged out")

    session.clear()
    flash("You have been logged out.", "ok")
    return redirect(url_for("auth.login"))


# ============================================================================
# User Management (Admin Only)
# ============================================================================

def create_user(email: str, name: str, password: str, role: str = "owner") -> Optional[int]:
    """Create a new user with proper password hashing.

    Returns:
        User ID on success, None on failure
    """
    # Validate email
    email_valid, email_result = validate_email(email)
    if not email_valid:
        logger.warning(f"User creation failed: {email_result}")
        return None
    email = email_result

    # Validate password
    pw_valid, pw_error = validate_password(password)
    if not pw_valid:
        logger.warning(f"User creation failed: {pw_error}")
        return None

    # Validate role
    if role not in ("admin", "owner"):
        logger.warning(f"User creation failed: invalid role '{role}'")
        return None

    # Hash password
    password_hash = generate_password_hash(password, method="pbkdf2:sha256:260000")

    try:
        with transaction() as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO users(email, name, password_hash, role) VALUES(?, ?, ?, ?)",
                (email, name, password_hash, role)
            )
            user_id = cur.lastrowid
            logger.info(f"Created user {user_id} ({email}) with role {role}")
            return user_id
    except Exception as e:
        logger.error(f"Failed to create user {email}: {e}")
        return None


def change_password(user_id: int, new_password: str) -> bool:
    """Change a user's password.

    Returns:
        True on success, False on failure
    """
    # Validate password
    pw_valid, pw_error = validate_password(new_password)
    if not pw_valid:
        logger.warning(f"Password change failed for user {user_id}: {pw_error}")
        return False

    # Hash new password
    password_hash = generate_password_hash(new_password, method="pbkdf2:sha256:260000")

    try:
        with transaction() as con:
            con.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (password_hash, user_id)
            )
        logger.info(f"Password changed for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to change password for user {user_id}: {e}")
        return False


def assign_user_to_business(user_id: int, business_id: int) -> bool:
    """Assign a user to a business.

    Returns:
        True on success, False on failure
    """
    try:
        with transaction() as con:
            con.execute(
                "INSERT OR IGNORE INTO business_users(user_id, business_id) VALUES(?, ?)",
                (user_id, business_id)
            )
        logger.info(f"User {user_id} assigned to business {business_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to assign user {user_id} to business {business_id}: {e}")
        return False
