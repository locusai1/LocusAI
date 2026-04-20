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
from core.mailer import send_email

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
            """SELECT id, email, name, password_hash, role,
                      email_verified, trial_ends_at
               FROM users WHERE lower(email)=?""", (email_or_username,)
        ).fetchone()
        if not row:
            row = con.execute(
                """SELECT id, email, name, password_hash, role,
                          email_verified, trial_ends_at
                   FROM users WHERE lower(name)=?""", (email_or_username,)
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
        "email_verified": row["email_verified"] if "email_verified" in row.keys() else 1,
        "trial_ends_at": row["trial_ends_at"] if "trial_ends_at" in row.keys() else None,
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

    # Block unverified users (admins are always treated as verified)
    email_verified = row["email_verified"] if "email_verified" in row.keys() else 1
    if not email_verified and row["role"] != "admin":
        flash(f"Welcome back, {row['name']}. Please verify your email to access your dashboard.", "ok")
        return redirect(url_for("auth.verify_email_pending"))

    flash(f"Welcome back, {row['name']}.", "ok")
    return redirect(url_for("dashboard"))


TRIAL_DAYS = 14


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    """Self-service account registration with email verification."""
    if session.get("user"):
        return redirect(url_for("dashboard"))

    if request.method == "GET":
        return render_template("signup.html")

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    # Validate
    if not name:
        flash("Please enter your name.", "err")
        return render_template("signup.html", name=name, email=email), 400

    email_valid, email_result = validate_email(email)
    if not email_valid:
        flash(email_result or "Please enter a valid email address.", "err")
        return render_template("signup.html", name=name, email=email), 400
    email = email_result

    pw_valid, pw_error = validate_password(password)
    if not pw_valid:
        flash(pw_error or "Password must be at least 8 characters.", "err")
        return render_template("signup.html", name=name, email=email), 400

    # Check email not already taken
    with get_conn() as con:
        existing = con.execute(
            "SELECT id FROM users WHERE lower(email)=?", (email,)
        ).fetchone()

    if existing:
        flash("An account with that email already exists. Try signing in.", "err")
        return render_template("signup.html", name=name, email=email), 409

    # Create user
    password_hash = generate_password_hash(password, method="pbkdf2:sha256:260000")
    trial_ends_at = (datetime.now() + timedelta(days=TRIAL_DAYS)).isoformat()

    try:
        with transaction() as con:
            cur = con.cursor()
            cur.execute(
                """INSERT INTO users(email, name, password_hash, role,
                                    email_verified, trial_ends_at, signup_source)
                   VALUES(?, ?, ?, 'owner', 0, ?, 'signup')""",
                (email, name, password_hash, trial_ends_at)
            )
            user_id = cur.lastrowid
    except Exception as e:
        logger.error(f"Signup failed for {_mask_email(email)}: {e}")
        flash("Something went wrong. Please try again.", "err")
        return render_template("signup.html", name=name, email=email), 500

    # Send verification email
    _send_verification_email(user_id, email, name)

    logger.info(f"New signup: user {user_id} ({_mask_email(email)})")
    return redirect(url_for("auth.verify_email_sent", email=email))


@bp.route("/signup/check-email")
def verify_email_sent():
    """Confirmation page: "check your inbox"."""
    email = request.args.get("email", "")
    return render_template("verify_email_sent.html", email=email)


@bp.route("/verify-email/<token>")
def verify_email(token: str):
    """Click the link from the verification email."""
    now = datetime.now().isoformat()

    with get_conn() as con:
        row = con.execute(
            """SELECT evt.id, evt.user_id, evt.expires_at, evt.verified_at,
                      u.email, u.name
               FROM email_verification_tokens evt
               JOIN users u ON u.id = evt.user_id
               WHERE evt.token=?""",
            (token,)
        ).fetchone()

    if not row or row["expires_at"] < now:
        flash("This verification link has expired. Please request a new one.", "err")
        return redirect(url_for("auth.login"))

    if row["verified_at"]:
        # Already verified — just log them in if possible
        flash("Your email is already verified. Please sign in.", "ok")
        return redirect(url_for("auth.login"))

    # Mark email as verified and activate trial
    verified_at = datetime.now().isoformat()
    trial_ends_at = (datetime.now() + timedelta(days=TRIAL_DAYS)).isoformat()

    try:
        with transaction() as con:
            con.execute(
                "UPDATE email_verification_tokens SET verified_at=? WHERE id=?",
                (verified_at, row["id"])
            )
            con.execute(
                "UPDATE users SET email_verified=1, trial_ends_at=? WHERE id=?",
                (trial_ends_at, row["user_id"])
            )
    except Exception as e:
        logger.error(f"Failed to verify email for user {row['user_id']}: {e}")
        flash("Something went wrong verifying your email. Please try again.", "err")
        return redirect(url_for("auth.login"))

    # Log them in directly
    _regenerate_session()
    session["user"] = {
        "id": row["user_id"],
        "email": row["email"],
        "name": row["name"],
        "role": "owner",
        "email_verified": 1,
        "trial_ends_at": trial_ends_at,
    }
    session["login_time"] = datetime.now().isoformat()

    logger.info(f"Email verified and auto-login: user {row['user_id']} ({_mask_email(row['email'])})")
    flash(f"Welcome to LocusAI, {row['name']}! Your 14-day trial has started.", "ok")
    return redirect(url_for("onboard.business_new"))


@bp.route("/signup/resend-verification", methods=["POST"])
def resend_verification():
    """Resend verification email for logged-in unverified users."""
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    with get_conn() as con:
        row = con.execute(
            "SELECT id, email, name, email_verified FROM users WHERE id=?",
            (user["id"],)
        ).fetchone()

    if not row or row["email_verified"]:
        return redirect(url_for("dashboard"))

    _send_verification_email(row["id"], row["email"], row["name"])
    flash("Verification email sent. Check your inbox.", "ok")
    return redirect(url_for("auth.verify_email_pending"))


@bp.route("/verify-email-pending")
def verify_email_pending():
    """Page shown to logged-in users who haven't verified their email yet."""
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))
    if user.get("email_verified"):
        return redirect(url_for("dashboard"))
    return render_template("verify_email_pending.html", user=user)


def _send_verification_email(user_id: int, email: str, name: str) -> None:
    """Generate a verification token and send the email."""
    token = secrets.token_hex(32)
    expires_at = (datetime.now() + timedelta(hours=24)).isoformat()
    try:
        with transaction() as con:
            # Invalidate any existing unused tokens
            con.execute(
                "UPDATE email_verification_tokens SET expires_at=? WHERE user_id=? AND verified_at IS NULL",
                (datetime.now().isoformat(), user_id)
            )
            con.execute(
                "INSERT INTO email_verification_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
                (user_id, token, expires_at)
            )

        from core.settings import APP_BASE_URL
        verify_url = f"{APP_BASE_URL}/verify-email/{token}"
        send_email(
            to_email=email,
            subject="Verify your LocusAI email address",
            body=(
                f"Hi {name},\n\n"
                f"Thanks for signing up for LocusAI! Click the link below to verify your email address and start your {TRIAL_DAYS}-day free trial:\n\n"
                f"{verify_url}\n\n"
                f"This link expires in 24 hours.\n\n"
                f"If you didn't create a LocusAI account, you can safely ignore this email.\n\n"
                f"— The LocusAI Team"
            )
        )
    except Exception as e:
        logger.error(f"Failed to send verification email to {_mask_email(email)}: {e}")


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Step 1: user enters email, receives reset link."""
    if request.method == "GET":
        return render_template("forgot_password.html")

    email = (request.form.get("email") or "").strip().lower()
    if not email:
        flash("Please enter your email address.", "err")
        return render_template("forgot_password.html"), 400

    with get_conn() as con:
        user = con.execute(
            "SELECT id, email, name FROM users WHERE lower(email)=?", (email,)
        ).fetchone()

    if user:
        token = secrets.token_hex(32)
        expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
        try:
            with transaction() as con:
                # Invalidate any existing unused tokens for this user
                con.execute(
                    "UPDATE password_reset_tokens SET used=1 WHERE user_id=? AND used=0",
                    (user["id"],)
                )
                con.execute(
                    "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
                    (user["id"], token, expires_at)
                )

            from core.settings import APP_BASE_URL
            reset_url = f"{APP_BASE_URL}/reset-password/{token}"
            send_email(
                to_email=user["email"],
                subject="Reset your LocusAI password",
                body=(
                    f"Hi {user['name']},\n\n"
                    f"Someone requested a password reset for your LocusAI account.\n\n"
                    f"Click the link below to choose a new password (valid for 1 hour):\n\n"
                    f"{reset_url}\n\n"
                    f"If you didn't request this, you can safely ignore this email. "
                    f"Your password won't change.\n\n"
                    f"— The LocusAI Team"
                )
            )
            logger.info(f"Password reset email sent to user {user['id']} ({_mask_email(email)})")
        except Exception as e:
            logger.error(f"Failed to create reset token for {_mask_email(email)}: {e}")

    # Always show the same message — don't reveal whether the email exists
    flash("If that email is registered, you'll receive a reset link shortly.", "ok")
    return redirect(url_for("auth.forgot_password"))


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    """Step 2: user clicks link, sets new password."""
    now = datetime.now().isoformat()

    with get_conn() as con:
        row = con.execute(
            """SELECT prt.id, prt.user_id, prt.expires_at, prt.used, u.email, u.name
               FROM password_reset_tokens prt
               JOIN users u ON u.id = prt.user_id
               WHERE prt.token=?""",
            (token,)
        ).fetchone()

    token_invalid = (
        not row
        or row["used"]
        or row["expires_at"] < now
    )

    if request.method == "GET":
        if token_invalid:
            flash("This reset link is invalid or has expired. Please request a new one.", "err")
            return redirect(url_for("auth.forgot_password"))
        return render_template("reset_password.html", token=token)

    # POST — process the new password
    if token_invalid:
        flash("This reset link is invalid or has expired. Please request a new one.", "err")
        return redirect(url_for("auth.forgot_password"))

    new_password = request.form.get("password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if not new_password:
        flash("Please enter a new password.", "err")
        return render_template("reset_password.html", token=token), 400

    if new_password != confirm_password:
        flash("Passwords do not match.", "err")
        return render_template("reset_password.html", token=token), 400

    pw_valid, pw_error = validate_password(new_password)
    if not pw_valid:
        flash(pw_error or "Password must be at least 8 characters.", "err")
        return render_template("reset_password.html", token=token), 400

    success = change_password(row["user_id"], new_password)
    if not success:
        flash("Failed to update password. Please try again.", "err")
        return render_template("reset_password.html", token=token), 500

    # Mark token as used
    try:
        with transaction() as con:
            con.execute(
                "UPDATE password_reset_tokens SET used=1 WHERE id=?",
                (row["id"],)
            )
    except Exception as e:
        logger.error(f"Failed to mark reset token {row['id']} as used: {e}")

    logger.info(f"Password reset completed for user {row['user_id']} ({_mask_email(row['email'])})")
    flash("Password updated. You can now sign in with your new password.", "ok")
    return redirect(url_for("auth.login"))


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


# ============================================================================
# User Management Routes (Admin Only)
# ============================================================================

def _require_admin():
    """Return redirect if user is not an admin, else None."""
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))
    if user.get("role") != "admin":
        flash("Admin access required.", "err")
        return redirect(url_for("dashboard"))
    return None


@bp.route("/users")
def users_list():
    """List all users — admin only."""
    check = _require_admin()
    if check:
        return check

    with get_conn() as con:
        users = con.execute("""
            SELECT u.id, u.email, u.name, u.role, u.created_at,
                   GROUP_CONCAT(b.name, ', ') as businesses
            FROM users u
            LEFT JOIN business_users bu ON u.id = bu.user_id
            LEFT JOIN businesses b ON bu.business_id = b.id
            GROUP BY u.id
            ORDER BY u.created_at DESC
        """).fetchall()
        users = [dict(u) for u in users]

        businesses = con.execute(
            "SELECT id, name FROM businesses WHERE archived=0 ORDER BY name"
        ).fetchall()
        businesses = [dict(b) for b in businesses]

    return render_template("admin_users.html", users=users, businesses=businesses)


@bp.route("/users/new", methods=["POST"])
def users_new():
    """Create a new user — admin only."""
    check = _require_admin()
    if check:
        return check

    email = (request.form.get("email") or "").strip()
    name = (request.form.get("name") or "").strip()
    password = request.form.get("password") or ""
    role = request.form.get("role", "owner").strip()
    business_id = request.form.get("business_id")

    if not email or not name or not password:
        flash("Email, name, and password are required.", "err")
        return redirect(url_for("auth.users_list"))

    user_id = create_user(email=email, name=name, password=password, role=role)
    if not user_id:
        flash("Failed to create user. Check email format and password strength (8+ chars).", "err")
        return redirect(url_for("auth.users_list"))

    if business_id:
        try:
            assign_user_to_business(user_id, int(business_id))
        except Exception:
            pass

    logger.info(f"Admin created user {user_id} ({_mask_email(email)})")
    flash(f"User {name} created successfully.", "ok")
    return redirect(url_for("auth.users_list"))


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
def users_delete(user_id: int):
    """Delete a user — admin only. Cannot delete yourself."""
    check = _require_admin()
    if check:
        return check

    current_user = session.get("user")
    if current_user and current_user.get("id") == user_id:
        flash("Cannot delete your own account.", "err")
        return redirect(url_for("auth.users_list"))

    try:
        with transaction() as con:
            con.execute("DELETE FROM business_users WHERE user_id=?", (user_id,))
            con.execute("DELETE FROM users WHERE id=?", (user_id,))
        logger.info(f"Admin deleted user {user_id}")
        flash("User deleted.", "ok")
    except Exception as e:
        logger.error(f"Failed to delete user {user_id}: {e}")
        flash("Failed to delete user.", "err")

    return redirect(url_for("auth.users_list"))


@bp.route("/users/<int:user_id>/assign", methods=["POST"])
def users_assign(user_id: int):
    """Assign a user to a business — admin only."""
    check = _require_admin()
    if check:
        return check

    business_id = request.form.get("business_id")
    if not business_id:
        flash("Select a business.", "err")
        return redirect(url_for("auth.users_list"))

    success = assign_user_to_business(user_id, int(business_id))
    if success:
        flash("User assigned to business.", "ok")
    else:
        flash("Failed to assign user.", "err")

    return redirect(url_for("auth.users_list"))


@bp.route("/users/<int:user_id>/unassign", methods=["POST"])
def users_unassign(user_id: int):
    """Remove a user from a business — admin only."""
    check = _require_admin()
    if check:
        return check

    business_id = request.form.get("business_id")
    if not business_id:
        flash("Select a business.", "err")
        return redirect(url_for("auth.users_list"))

    try:
        with transaction() as con:
            con.execute(
                "DELETE FROM business_users WHERE user_id=? AND business_id=?",
                (user_id, int(business_id))
            )
        flash("User removed from business.", "ok")
    except Exception as e:
        logger.error(f"Failed to unassign user {user_id}: {e}")
        flash("Failed.", "err")

    return redirect(url_for("auth.users_list"))


@bp.route("/users/<int:user_id>/password", methods=["POST"])
def users_change_password(user_id: int):
    """Change a user's password — admin only."""
    check = _require_admin()
    if check:
        return check

    new_password = request.form.get("password", "")
    if not new_password:
        flash("Password required.", "err")
        return redirect(url_for("auth.users_list"))

    success = change_password(user_id, new_password)
    if success:
        flash("Password updated.", "ok")
    else:
        flash("Password must be 8+ characters.", "err")

    return redirect(url_for("auth.users_list"))
