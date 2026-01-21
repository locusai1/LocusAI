# auth_bp.py — Authentication with security best practices
# Includes session fixation protection, account lockout, and proper error handling

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash

from core.db import get_conn, transaction
from core.validators import validate_email, validate_password

logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

bp = Blueprint("auth", __name__)


def _mask_email(email: str) -> str:
    """Mask email for logging to protect PII.

    Example: 'john.doe@example.com' -> 'j***@e***.com'
    """
    if not email or '@' not in email:
        return '***'

    local, domain = email.rsplit('@', 1)
    parts = domain.rsplit('.', 1)

    masked_local = local[0] + '***' if local else '***'
    if len(parts) == 2:
        masked_domain = parts[0][0] + '***.' + parts[1] if parts[0] else '***.' + parts[1]
    else:
        masked_domain = '***'

    return f"{masked_local}@{masked_domain}"

# ============================================================================
# Account Lockout Configuration
# ============================================================================

# In-memory store for failed attempts (use Redis in production for multi-instance)
# Structure: {"email:ip": {"count": int, "first_attempt": datetime, "locked_until": datetime}}
_failed_attempts: Dict[str, Dict] = {}

# Lockout settings
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
ATTEMPT_WINDOW_MINUTES = 30  # Reset counter after this period of no attempts


def _get_lockout_key(email: str, ip: str) -> str:
    """Generate a key for tracking failed attempts."""
    return f"{email.lower().strip()}:{ip}"


def _cleanup_old_attempts() -> None:
    """Remove expired lockout entries to prevent memory bloat."""
    now = datetime.now()
    cutoff = now - timedelta(minutes=ATTEMPT_WINDOW_MINUTES * 2)
    keys_to_remove = []

    for key, data in _failed_attempts.items():
        # Remove if locked_until has passed AND first_attempt is old
        locked_until = data.get("locked_until")
        first_attempt = data.get("first_attempt")

        if locked_until and now > locked_until:
            if first_attempt and first_attempt < cutoff:
                keys_to_remove.append(key)
        elif first_attempt and first_attempt < cutoff:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del _failed_attempts[key]


def check_account_lockout(email: str, ip: str) -> Tuple[bool, Optional[int]]:
    """Check if an account/IP is locked out.

    Returns:
        (is_locked, seconds_remaining) - seconds_remaining is None if not locked
    """
    _cleanup_old_attempts()

    key = _get_lockout_key(email, ip)
    data = _failed_attempts.get(key)

    if not data:
        return False, None

    locked_until = data.get("locked_until")
    if locked_until and datetime.now() < locked_until:
        remaining = int((locked_until - datetime.now()).total_seconds())
        return True, remaining

    return False, None


def record_failed_attempt(email: str, ip: str) -> Tuple[int, bool]:
    """Record a failed login attempt.

    Returns:
        (attempt_count, is_now_locked)
    """
    _cleanup_old_attempts()

    key = _get_lockout_key(email, ip)
    now = datetime.now()

    data = _failed_attempts.get(key)

    if not data:
        # First failed attempt
        _failed_attempts[key] = {
            "count": 1,
            "first_attempt": now,
            "locked_until": None
        }
        return 1, False

    # Check if we should reset the counter (window expired)
    first_attempt = data.get("first_attempt")
    if first_attempt and now - first_attempt > timedelta(minutes=ATTEMPT_WINDOW_MINUTES):
        # Reset counter
        _failed_attempts[key] = {
            "count": 1,
            "first_attempt": now,
            "locked_until": None
        }
        return 1, False

    # Increment counter
    data["count"] = data.get("count", 0) + 1

    # Check if we should lock
    if data["count"] >= MAX_FAILED_ATTEMPTS:
        data["locked_until"] = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
        security_logger.warning(
            f"Account locked due to {data['count']} failed attempts: {email} from {ip}"
        )
        return data["count"], True

    return data["count"], False


def clear_failed_attempts(email: str, ip: str) -> None:
    """Clear failed attempts after successful login."""
    key = _get_lockout_key(email, ip)
    if key in _failed_attempts:
        del _failed_attempts[key]


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
    """Handle user login with security protections including account lockout."""
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
    client_ip = request.remote_addr or "unknown"

    # Basic validation
    if not email_or_username or not password:
        flash("Please enter your email and password.", "err")
        return render_template("login.html"), 400

    # Check for account lockout BEFORE attempting authentication
    is_locked, remaining_seconds = check_account_lockout(email_or_username, client_ip)
    if is_locked:
        remaining_minutes = (remaining_seconds or 0) // 60 + 1
        security_logger.warning(
            f"Login blocked (account locked) for '{email_or_username}' from {client_ip}"
        )
        flash(
            f"Account temporarily locked due to too many failed attempts. "
            f"Please try again in {remaining_minutes} minute(s).",
            "err"
        )
        return render_template("login.html"), 429

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
        # Record the failed attempt
        attempt_count, is_now_locked = record_failed_attempt(email_or_username, client_ip)

        # Log failed attempt (without revealing which part failed)
        security_logger.warning(
            f"Failed login attempt ({attempt_count}/{MAX_FAILED_ATTEMPTS}) "
            f"for '{email_or_username}' from {client_ip}"
        )

        if is_now_locked:
            flash(
                f"Account temporarily locked due to too many failed attempts. "
                f"Please try again in {LOCKOUT_DURATION_MINUTES} minutes.",
                "err"
            )
            return render_template("login.html"), 429

        remaining = MAX_FAILED_ATTEMPTS - attempt_count
        if remaining <= 2:
            flash(f"Invalid credentials. {remaining} attempt(s) remaining before lockout.", "err")
        else:
            flash("Invalid credentials.", "err")
        return render_template("login.html"), 401

    # Successful login - clear any failed attempts
    clear_failed_attempts(email_or_username, client_ip)

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

    # Log successful login (email masked for privacy)
    logger.info(f"User {row['id']} ({_mask_email(row['email'])}) logged in from {client_ip}")

    flash(f"Welcome back, {row['name']}.", "ok")
    return redirect(url_for("dashboard"))


@bp.route("/logout")
def logout():
    """Handle user logout."""
    user = session.get("user")
    if user:
        logger.info(f"User {user.get('id')} ({_mask_email(user.get('email', ''))}) logged out")

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
            logger.info(f"Created user {user_id} ({_mask_email(email)}) with role {role}")
            return user_id
    except Exception as e:
        logger.error(f"Failed to create user {_mask_email(email)}: {e}")
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
