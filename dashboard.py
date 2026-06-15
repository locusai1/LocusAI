# dashboard.py — LocusAI admin (tenant isolation + branding + pro UI)
# Production-grade Flask application with proper security and error handling

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from core.settings import FLASK_SECRET_KEY, SENTRY_DSN

# Error monitoring — activates only when SENTRY_DSN is set; no-op otherwise.
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[FlaskIntegration()],
            environment=os.getenv("APP_ENV", "dev"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            send_default_pii=False,  # don't ship customer PII to Sentry
        )
        logging.getLogger(__name__).info("Sentry error monitoring enabled")
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN set but sentry-sdk not installed; skipping")
from core import billing
from core.authz import get_allowed_business_ids_for_user, user_can_access_business
from core.csrf import register_csrf
from core.db import (
    ensure_tenant_key,
    get_business_by_id,
    get_conn,
    init_db,
    list_businesses,
    update_business,
)
from core.tenantfs import write_meta_from_db
from core.validators import safe_int, slugify, validate_redirect_url

# ============================================================================
# Application Setup
# ============================================================================

app = Flask(__name__)
register_csrf(app)
app.secret_key = FLASK_SECRET_KEY

APP_ENV = os.getenv("APP_ENV", "dev").lower()
IS_PROD = APP_ENV in ("prod", "production")

# ============================================================================
# Session & Cookie Configuration
# ============================================================================

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",  # Stricter than Lax for forms
    SESSION_COOKIE_SECURE=IS_PROD,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),  # Reduced from 8 hours
    SESSION_REFRESH_EACH_REQUEST=True,  # Extend session on activity
)

# ============================================================================
# Request Size Limits (Security)
# ============================================================================

# Maximum request body size: 16MB (adjust as needed)
# This prevents denial-of-service attacks via large uploads
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

# Note: For file upload endpoints that need larger limits,
# use @app.route decorators with specific limits or validate in the route

# ============================================================================
# Provider Registration
# ============================================================================

import providers.dummy_provider  # noqa: F401
import providers.local_provider  # noqa: F401

try:
    import providers.retell_provider  # noqa: F401
except ImportError:
    pass  # Retell provider is optional

# ============================================================================
# Blueprint Registration
# ============================================================================

from analytics_bp import analytics_bp
from appointments_bp import bp as appointments_bp
from auth_bp import bp as auth_bp
from billing_bp import bp as billing_bp
from chat_bp import bp as chat_bp
from customers_bp import bp as customers_bp
from escalations_bp import escalations_bp
from integrations_bp import bp as integrations_bp
from kb_bp import bp as kb_bp
from onboard_bp import bp as onboard_bp
from public_booking_bp import bp as public_booking_bp
from search_bp import bp as search_bp
from services_bp import bp as services_bp
from webhooks_bp import bp as webhooks_bp
from widget_bp import bp as widget_bp

# SMS Blueprint (optional, requires Twilio or alternative provider)
try:
    from sms_bp import bp as sms_bp

    SMS_AVAILABLE = True
except ImportError:
    SMS_AVAILABLE = False

# Voice Blueprint (optional, requires Retell AI)
try:
    from voice_bp import bp as voice_bp

    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False

app.register_blueprint(auth_bp)
app.register_blueprint(appointments_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(onboard_bp)
app.register_blueprint(kb_bp)
app.register_blueprint(services_bp)
app.register_blueprint(integrations_bp)
app.register_blueprint(search_bp)
app.register_blueprint(widget_bp)
app.register_blueprint(customers_bp)
app.register_blueprint(escalations_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(public_booking_bp)
app.register_blueprint(webhooks_bp)

# Register SMS blueprint if available
if SMS_AVAILABLE:
    app.register_blueprint(sms_bp)

# Register Voice blueprint if available
if VOICE_AVAILABLE:
    app.register_blueprint(voice_bp)

# ============================================================================
# Background Call Sync — keeps the dashboard current without manual clicks
# ============================================================================


def _call_sync_tick():
    """One iteration: pull recent calls from Retell into the local DB."""
    if not VOICE_AVAILABLE:
        return
    from core.voice import sync_calls_from_retell

    with app.app_context():
        from core.db import get_conn

        with get_conn() as con:
            row = con.execute("SELECT id FROM businesses WHERE archived = 0 LIMIT 1").fetchone()
        if row:
            success, msg = sync_calls_from_retell(row["id"])
            if success:
                app.logger.debug(f"Auto-sync: {msg}")


# ============================================================================
# Background Reminder Worker — dispatches due SMS/email reminders every minute
# ============================================================================


def _reminder_tick():
    """One iteration: dispatch any due SMS/email reminders."""
    with app.app_context():
        from core.reminders import process_due_reminders

        stats = process_due_reminders()
        if stats["total"] > 0:
            app.logger.info(
                f"Reminder worker: {stats['sent']} sent, "
                f"{stats['failed']} failed out of {stats['total']}"
            )


# ============================================================================
# Background Appointment Automation — no-show follow-ups & review requests
# ============================================================================


def _appointment_automation_tick():
    """One iteration: no-show follow-ups + review requests."""
    with app.app_context():
        _run_appointment_automations()


def _run_appointment_automations():
    """Execute no-show and review request automations."""
    from core.sms import TELNYX_CONFIGURED, send_sms

    if not TELNYX_CONFIGURED:
        return

    with get_conn() as con:
        # --- No-show follow-up ---
        # Appointments that are past (>30 min ago) and still 'confirmed' with a phone
        no_shows = con.execute("""
            SELECT a.id, a.customer_name, a.phone, a.service, a.start_at,
                   b.name as biz_name, b.id as business_id
            FROM appointments a
            JOIN businesses b ON a.business_id = b.id
            WHERE a.status = 'confirmed'
              AND a.phone IS NOT NULL AND a.phone != ''
              AND datetime(a.start_at) < datetime('now', '-30 minutes')
              AND (a.no_show_sms_sent IS NULL OR a.no_show_sms_sent = 0)
              AND b.archived = 0
            LIMIT 20
        """).fetchall()

        for appt in no_shows:
            try:
                msg = (
                    f"Hi {appt['customer_name']}! We missed you for your "
                    f"{appt['service']} today at {appt['biz_name']}. "
                    f"Would you like to reschedule? Reply YES and we'll sort it out."
                )
                result = send_sms(to=appt["phone"], message=msg)
                if result.get("status") != "error":
                    con.execute(
                        "UPDATE appointments SET no_show_sms_sent=1 WHERE id=?", (appt["id"],)
                    )
                    con.connection.commit()
                    app.logger.info(f"No-show SMS sent for appointment {appt['id']}")
            except Exception as e:
                app.logger.warning(f"No-show SMS failed for appt {appt['id']}: {e}")

        # --- Review request ---
        # Appointments completed 1-24 hours ago, no review request sent yet
        completed = con.execute("""
            SELECT a.id, a.customer_name, a.phone, a.service, a.start_at,
                   b.name as biz_name, b.id as business_id
            FROM appointments a
            JOIN businesses b ON a.business_id = b.id
            WHERE a.status = 'completed'
              AND a.phone IS NOT NULL AND a.phone != ''
              AND datetime(a.start_at) BETWEEN datetime('now', '-24 hours') AND datetime('now', '-1 hour')
              AND (a.review_request_sent IS NULL OR a.review_request_sent = 0)
              AND b.archived = 0
            LIMIT 20
        """).fetchall()

        for appt in completed:
            try:
                msg = (
                    f"Hi {appt['customer_name']}! Hope you enjoyed your "
                    f"{appt['service']} at {appt['biz_name']}. "
                    f"We'd love your feedback — would you mind leaving us a quick review? "
                    f"It really helps us out. Thank you!"
                )
                result = send_sms(to=appt["phone"], message=msg)
                if result.get("status") != "error":
                    con.execute(
                        "UPDATE appointments SET review_request_sent=1 WHERE id=?", (appt["id"],)
                    )
                    con.connection.commit()
                    app.logger.info(f"Review request SMS sent for appointment {appt['id']}")
            except Exception as e:
                app.logger.warning(f"Review request SMS failed for appt {appt['id']}: {e}")

    # --- Post-call lead follow-up (nurture unconverted callers) ---
    try:
        from core.followups import dispatch_due_followups

        n = dispatch_due_followups()
        if n:
            app.logger.info(f"Dispatched {n} lead follow-up SMS")
    except Exception as e:
        app.logger.warning(f"Lead follow-up dispatch failed: {e}")


# Start all three workers under supervision (auto-restart + heartbeat + backoff).
# Skipped under pytest so the suite doesn't spawn live background threads.
from core.workers import heartbeat_snapshot, start_worker


def _webhook_dispatch_tick():
    """One iteration: deliver due outbound webhook events."""
    from core.webhooks import dispatch_pending

    with app.app_context():
        dispatch_pending()


def _digest_tick():
    """One iteration: send weekly performance digests (deduped per week)."""
    from core.digest import send_weekly_digests

    with app.app_context():
        sent = send_weekly_digests()
        if sent:
            app.logger.info(f"Weekly digest: sent {sent}")


def _kb_autolearn_tick():
    """One iteration: let opted-in businesses' KB teach itself from recurring questions."""
    from core.kb_autolearn import run_autolearn_for_enabled

    with app.app_context():
        added = run_autolearn_for_enabled()
        if added:
            app.logger.info(f"KB auto-learn: added {added} entries")
        # Safety net: embed any KB entries missing a semantic vector (bulk imports,
        # AI suggestions, seeded data). No-op without an OpenAI key.
        try:
            from core.semantic_kb import backfill_pending

            embedded = backfill_pending(limit=500)
            if embedded:
                app.logger.info(f"Semantic KB: embedded {embedded} entries")
        except Exception:
            app.logger.debug("semantic backfill skipped", exc_info=True)


def _data_purge_tick():
    """One iteration: enforce per-business data retention + trim the audit log."""
    from core.audit import log_audit, purge_old_audit
    from core.db import cleanup_old_data

    with app.app_context():
        counts = cleanup_old_data()
        audit_removed = purge_old_audit()
        if any(counts.values()) or audit_removed:
            app.logger.info(f"Data purge: {counts}, audit_removed={audit_removed}")
            log_audit(
                "data.retention_purge",
                detail={**counts, "audit_rows_removed": audit_removed},
            )


# Bootstrap an admin from env (ADMIN_EMAIL/ADMIN_PASSWORD) if one is missing.
# Lets you create the production admin via Railway Variables + a redeploy, with
# no CLI access needed; idempotent (only creates when absent).
if not os.getenv("PYTEST_CURRENT_TEST"):
    try:
        from core.bootstrap import ensure_admin

        ensure_admin()
    except Exception:
        app.logger.exception("ensure_admin at startup failed")

if not os.getenv("PYTEST_CURRENT_TEST"):
    start_worker("call_sync", _call_sync_tick, interval=180, initial_delay=10)
    start_worker("reminders", _reminder_tick, interval=60, initial_delay=20)
    start_worker(
        "appointment_automation", _appointment_automation_tick, interval=600, initial_delay=30
    )
    start_worker("webhook_dispatch", _webhook_dispatch_tick, interval=15, initial_delay=15)
    start_worker("weekly_digest", _digest_tick, interval=21600, initial_delay=120)  # ~6h
    start_worker("kb_autolearn", _kb_autolearn_tick, interval=86400, initial_delay=300)  # daily
    start_worker("data_purge", _data_purge_tick, interval=86400, initial_delay=600)  # daily

# ============================================================================
# Logging Configuration
# ============================================================================

os.makedirs("logs", exist_ok=True)


# Structured log format with request ID correlation
class RequestFormatter(logging.Formatter):
    def format(self, record):
        record.request_id = getattr(g, "request_id", "no-request")
        record.user_id = "anonymous"
        user = session.get("user") if session else None
        if user:
            record.user_id = user.get("id", "unknown")
        return super().format(record)


# File handler with rotation by size
file_handler = RotatingFileHandler(
    "logs/app.log",
    maxBytes=10_000_000,  # 10MB
    backupCount=10,
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    RequestFormatter(
        "%(asctime)s [%(request_id)s] [user:%(user_id)s] %(levelname)s %(name)s: %(message)s"
    )
)

# Security event log (separate file for audit)
security_handler = RotatingFileHandler("logs/security.log", maxBytes=10_000_000, backupCount=20)
security_handler.setLevel(logging.WARNING)
security_handler.setFormatter(
    RequestFormatter("%(asctime)s [%(request_id)s] [user:%(user_id)s] SECURITY %(message)s")
)

# Configure app logger
if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
    app.logger.addHandler(file_handler)
    app.logger.addHandler(security_handler)
app.logger.setLevel(logging.INFO if IS_PROD else logging.DEBUG)

# Create a security logger for audit events
security_logger = logging.getLogger("security")
security_logger.addHandler(security_handler)
security_logger.setLevel(logging.INFO)

# ============================================================================
# Request Lifecycle
# ============================================================================


@app.before_request
def _req_start():
    """Initialize request context and enforce tenant isolation."""
    g.request_id = str(uuid.uuid4())[:8]  # Short ID for logs
    g.request_start = datetime.now()

    # Ensure schema exists (idempotent)
    init_db()

    # Skip tenant isolation for widget API routes (they use tenant key auth)
    if request.path.startswith("/api/widget/"):
        g.allowed_business_ids = []
        return

    # Skip for voice webhook routes (they use signature verification)
    if request.path.startswith("/api/voice/webhook"):
        g.allowed_business_ids = []
        return

    # Skip for static files
    if request.path.startswith("/static/"):
        g.allowed_business_ids = []
        return

    # Build allow-list for this user
    user = session.get("user")
    g.allowed_business_ids = get_allowed_business_ids_for_user(user) if user else []

    # Detect business_id from route, query, or session
    bid = _extract_business_id()

    # Enforce tenant isolation for non-admins
    if user and user.get("role") != "admin" and bid:
        if bid not in g.allowed_business_ids:
            security_logger.warning(
                f"Access denied: user {user.get('id')} attempted to access business {bid}"
            )
            abort(403)

    # Keep active_business_id confined to allowed list
    if user and user.get("role") != "admin":
        active = session.get("active_business_id")
        if active not in (g.allowed_business_ids or [None]):
            session["active_business_id"] = (
                g.allowed_business_ids[0] if g.allowed_business_ids else None
            )

    # Set g.active_business_id for use in blueprints
    g.active_business_id = session.get("active_business_id")


def _extract_business_id() -> int:
    """Extract business_id from request context."""
    bid = None

    # Check route parameters first
    if request.view_args and "business_id" in request.view_args:
        bid = safe_int(request.view_args.get("business_id"))

    # Fall back to query parameter
    if not bid:
        bid = safe_int(request.args.get("business_id"))

    # Fall back to session
    if not bid:
        bid = session.get("active_business_id")

    return bid or 0


# Paths a logged-in user can still reach after their trial expires (so they can
# pay, log out, read legal pages, and the app's APIs/webhooks keep working).
_TRIAL_EXPIRED_ALLOWED = (
    "/billing",
    "/logout",
    "/login",
    "/signup",
    "/verify-email",
    "/forgot-password",
    "/reset-password",
    "/privacy",
    "/terms",
    "/health",
    "/static/",
    "/api/",
    "/brand/set",
    "/book/",
)


def _trial_expired(user) -> bool:
    """True only for a trial user whose trial has lapsed and who has no active
    paid subscription. Admins and users without a trial date are never expired."""
    if not user or user.get("role") == "admin":
        return False
    ends_at = user.get("trial_ends_at")
    if not ends_at:
        return False  # admin-created / non-trial accounts
    try:
        end = datetime.fromisoformat(str(ends_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if datetime.now() <= end.replace(tzinfo=None):
        return False  # trial still active
    # Trial date has passed — only "expired" if they haven't paid.
    try:
        return not billing.has_active_subscription(user["id"])
    except Exception:
        app.logger.exception("Trial check failed; allowing access")
        return False


@app.before_request
def _enforce_trial():
    """Gate dashboard access once a free trial expires (prompts upgrade)."""
    path = request.path
    if any(path.startswith(p) for p in _TRIAL_EXPIRED_ALLOWED):
        return
    user = session.get("user")
    if user and _trial_expired(user):
        flash(
            "Your free trial has ended. Choose a plan to keep your AI receptionist running.", "err"
        )
        return redirect(url_for("billing.billing_home"))


@app.after_request
def _set_headers(resp: Response) -> Response:
    """Set security headers on all responses."""
    resp.headers["X-Request-ID"] = g.get("request_id", "")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-XSS-Protection"] = "1; mode=block"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    # Check if this is a widget route (needs different security headers)
    is_widget_route = request.path.startswith("/api/widget/")
    is_widget_frame = request.path == "/api/widget/frame"

    # Frame options: Allow framing for widget iframe, deny for everything else
    if is_widget_frame:
        # Allow widget to be embedded anywhere
        resp.headers.pop("X-Frame-Options", None)
    else:
        resp.headers["X-Frame-Options"] = "DENY"

    # Content Security Policy
    if is_widget_frame:
        # Widget frame needs looser CSP to work in third-party contexts
        csp = [
            "default-src 'self'",
            "img-src 'self' data: https:",
            "style-src 'self' 'unsafe-inline'",
            "font-src 'self' data:",
            "script-src 'self' 'unsafe-inline'",
            "connect-src 'self'",
            "frame-ancestors *",  # Allow embedding anywhere
        ]
    else:
        csp = [
            "default-src 'self'",
            "img-src 'self' data: https:",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com data:",
            "script-src 'self' https://cdn.tailwindcss.com https://cdn.jsdelivr.net 'unsafe-inline'",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]
    resp.headers["Content-Security-Policy"] = "; ".join(csp)

    # HSTS in production
    if IS_PROD:
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"

    # Log slow requests
    if hasattr(g, "request_start"):
        duration = (datetime.now() - g.request_start).total_seconds()
        if duration > 1.0:
            app.logger.warning(f"Slow request: {request.path} took {duration:.2f}s")

    return resp


# ============================================================================
# Error Handlers
# ============================================================================


@app.errorhandler(400)
def bad_request(e):
    """Handle 400 Bad Request errors."""
    app.logger.warning(f"Bad request: {request.path} - {e}")
    return render_template("error_400.html", error=str(e)), 400


@app.errorhandler(413)
def request_entity_too_large(e):
    """Handle 413 Request Entity Too Large errors."""
    max_size_mb = app.config.get("MAX_CONTENT_LENGTH", 0) // (1024 * 1024)
    app.logger.warning(f"Request too large: {request.path}")
    return render_template(
        "error_400.html", error=f"File too large. Maximum upload size is {max_size_mb}MB."
    ), 413


@app.errorhandler(429)
def too_many_requests(e):
    """Handle 429 Too Many Requests errors (rate limiting)."""
    app.logger.warning(f"Rate limit exceeded: {request.path} from {request.remote_addr}")
    return render_template(
        "error_400.html", error="Too many requests. Please wait a moment and try again."
    ), 429


@app.errorhandler(403)
def forbidden(e):
    """Handle 403 Forbidden errors."""
    security_logger.warning(f"Forbidden access attempt: {request.path}")
    return render_template("error_403.html"), 403


@app.errorhandler(404)
def not_found(e):
    """Handle 404 Not Found errors."""
    return render_template("error_404.html"), 404


@app.errorhandler(500)
def internal_error(e):
    """Handle 500 Internal Server errors."""
    app.logger.exception(f"Internal server error: {request.path}")
    return render_template("error_500.html"), 500


@app.errorhandler(Exception)
def handle_exception(e):
    """Handle unexpected exceptions."""
    app.logger.exception(f"Unhandled exception: {e}")
    if IS_PROD:
        return render_template("error_500.html"), 500
    else:
        # In development, let the debugger handle it
        raise e


# ============================================================================
# Branding Context Processor
# ============================================================================


@app.context_processor
def _inject_branding():
    """Inject branding variables into all templates."""
    # Handle business switching from query parameter
    allowed_ids = getattr(g, "allowed_business_ids", None) or []
    bid_from_query = request.args.get("business_id")
    if bid_from_query:
        bq = safe_int(bid_from_query)
        if bq:
            user = session.get("user")
            if (user and user.get("role") == "admin") or (bq in allowed_ids):
                session["active_business_id"] = bq

    bid = session.get("active_business_id")

    # Build nav list (admins = all; owners = only mapped businesses)
    user = session.get("user")
    nav_businesses = []
    if user:
        if user.get("role") == "admin":
            nav_businesses = list_businesses(limit=500)
        else:
            ids = allowed_ids
            if ids:
                with get_conn() as con:
                    placeholders = ",".join("?" * len(ids))
                    q = f"SELECT * FROM businesses WHERE id IN ({placeholders}) ORDER BY id"
                    nav_businesses = [dict(r) for r in con.execute(q, tuple(ids)).fetchall()]

    # Fallback active business to first allowed
    if not bid and nav_businesses:
        session["active_business_id"] = nav_businesses[0]["id"]
        bid = session["active_business_id"]

    # Get branding colors
    color = "#2f6fec"
    logo_path = None
    if bid:
        with get_conn() as con:
            row = con.execute(
                "SELECT accent_color, logo_path FROM businesses WHERE id=?", (bid,)
            ).fetchone()
            if row:
                color = row["accent_color"] or color
                logo_path = row["logo_path"] or None

    # Pending-escalation count for the header notifications bell (cheap COUNT).
    pending_escalations = 0
    if user:
        try:
            with get_conn() as con:
                if user.get("role") == "admin":
                    r = con.execute(
                        "SELECT COUNT(*) c FROM escalations WHERE status='pending'"
                    ).fetchone()
                elif allowed_ids:
                    ph = ",".join("?" * len(allowed_ids))
                    r = con.execute(
                        f"SELECT COUNT(*) c FROM escalations "
                        f"WHERE status='pending' AND business_id IN ({ph})",
                        tuple(allowed_ids),
                    ).fetchone()
                else:
                    r = None
                pending_escalations = r["c"] if r else 0
        except Exception:
            pending_escalations = 0

    return {
        "accent_color": color,
        "business_logo_path": logo_path,
        "nav_businesses": nav_businesses,
        "active_business_id": bid or 0,
        "is_prod": IS_PROD,
        "current_year": datetime.now().year,
        "pending_escalations": pending_escalations,
    }


# ============================================================================
# Routes
# ============================================================================


@app.route("/")
def home():
    """Marketing homepage — redirect to dashboard if already logged in."""
    if session.get("user"):
        return redirect(url_for("dashboard"))
    return render_template("home.html")


@app.route("/calendar/<token>.ics")
def calendar_feed(token):
    """Public iCal subscription feed (secret token = auth). For Google/Outlook/Apple."""
    from core.calendar_feed import build_feed, business_by_feed_token

    biz = business_by_feed_token(token)
    if not biz:
        abort(404)
    ics = build_feed(biz["id"], biz.get("name", ""))
    return Response(
        ics,
        mimetype="text/calendar",
        headers={
            "Content-Disposition": 'inline; filename="locusai.ics"',
            "Cache-Control": "no-cache",
        },
    )


@app.route("/calendar/subscribe", methods=["POST"])
def calendar_subscribe_token():
    """Create the feed token (or rotate it) for the active business."""
    if session.get("user") is None:
        return jsonify({"error": "unauthorized"}), 401
    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        return jsonify({"error": "no business"}), 400
    from core.calendar_feed import ensure_feed_token, feed_path, regenerate_feed_token

    rotate = (request.get_json(silent=True) or {}).get("rotate")
    token = regenerate_feed_token(business_id) if rotate else ensure_feed_token(business_id)
    if not token:
        return jsonify({"error": "failed"}), 400
    return jsonify({"url": request.url_root.rstrip("/") + feed_path(token)})


@app.route("/try")
def try_demo():
    """Public 'try it now' page — build a live AI receptionist from any website."""
    return render_template("try.html")


@app.route("/api/try/start", methods=["POST"])
def try_start():
    """Scrape a prospect's site and start an ephemeral demo (session-stored)."""
    from core.demo import build_demo_context
    from core.security import check_rate_limit

    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    allowed, _ = check_rate_limit(f"demo_start:{ip}", limit=8, window_seconds=300)
    if not allowed:
        return jsonify({"error": "Too many demos started. Please wait a moment."}), 429

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:80]
    url = (data.get("url") or "").strip()[:300]
    if not name:
        return jsonify({"error": "Please enter your business name."}), 400

    ok, ctx = build_demo_context(name, url)
    if not ok:
        return jsonify({"error": ctx.get("error", "Could not start demo.")}), 400

    session["demo"] = {"ctx": ctx, "history": []}
    session.modified = True
    return jsonify({"greeting": ctx["greeting"], "scraped": bool(ctx.get("context"))})


@app.route("/api/try/chat", methods=["POST"])
def try_chat():
    """One demo turn — real AI seeded with the scraped site, no side effects."""
    from core.demo import demo_reply
    from core.security import check_rate_limit

    demo = session.get("demo")
    if not demo:
        return jsonify({"error": "Start a demo first."}), 400

    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    allowed, _ = check_rate_limit(f"demo_chat:{ip}", limit=30, window_seconds=300)
    if not allowed:
        return jsonify({"error": "You've hit the demo limit. Sign up to keep going!"}), 429

    message = (request.get_json(silent=True) or {}).get("message", "").strip()[:500]
    if not message:
        return jsonify({"error": "empty"}), 400

    history = demo.get("history", [])
    reply = demo_reply(demo["ctx"], history, message)
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    demo["history"] = history[-24:]
    session["demo"] = demo
    session.modified = True
    return jsonify({"reply": reply})


@app.post("/brand/set")
def set_brand():
    """Set the active business for the session."""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))

    b = safe_int(request.form.get("active_business_id"))
    user = session.get("user")

    if user and (user.get("role") == "admin" or b in (g.allowed_business_ids or [])):
        session["active_business_id"] = b
        app.logger.info(f"User {user.get('id')} switched to business {b}")
    else:
        security_logger.warning(
            f"User {user.get('id') if user else 'unknown'} attempted unauthorized brand switch to {b}"
        )

    # Validate redirect URL to prevent open redirect
    return_to = validate_redirect_url(request.form.get("return_to"), default=url_for("dashboard"))
    return redirect(return_to)


@app.route("/dashboard")
@app.route("/businesses")
def dashboard():
    """Main dashboard with KPIs, AI activity, and business insights."""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))

    # Build the business list this user can see
    user = session.get("user")
    if user and user.get("role") == "admin":
        businesses = list_businesses(limit=500)
    else:
        businesses = []
        ids = g.allowed_business_ids or []
        if ids:
            with get_conn() as con:
                placeholders = ",".join("?" * len(ids))
                q = f"SELECT * FROM businesses WHERE id IN ({placeholders}) ORDER BY id"
                businesses = [dict(r) for r in con.execute(q, tuple(ids)).fetchall()]

    # Calculate KPIs
    appt_counts = {}
    kpis = {"today": 0, "pending": 0, "confirmed": 0, "total": 0}
    series_labels = []
    series_values = []

    # Extended metrics for new dashboard
    ai_stats = {
        "calls_today": 0,
        "chats_today": 0,
        "bookings_today": 0,
        "calls_week": 0,
        "chats_week": 0,
    }
    upcoming_appointments = []
    recent_activity = []
    escalation_count = 0
    week_comparison = {"this_week": 0, "last_week": 0, "change_pct": 0}
    voice_stats = {"total_week": 0, "avg_duration": 0, "booked_calls": 0}
    top_services = []
    new_customers_week = 0
    total_customers = 0
    recent_calls = []
    sentiment_breakdown = {"positive": 0, "neutral": 0, "negative": 0}
    voice_series_values = [0] * 7

    if businesses:
        ids = [b["id"] for b in businesses]
        placeholders = ",".join("?" * len(ids))

        with get_conn() as con:
            # Total appointments
            row = con.execute(
                f"SELECT COUNT(*) c FROM appointments WHERE business_id IN ({placeholders})",
                tuple(ids),
            ).fetchone()
            kpis["total"] = row["c"] if row else 0

            # Today's appointments
            row = con.execute(
                f"""
                SELECT COUNT(*) c FROM appointments
                WHERE business_id IN ({placeholders})
                  AND date(COALESCE(start_at, created_at)) = date('now', 'localtime')
            """,
                tuple(ids),
            ).fetchone()
            kpis["today"] = row["c"] if row else 0

            # Status counts
            rows = con.execute(
                f"""
                SELECT status, COUNT(*) c FROM appointments
                WHERE business_id IN ({placeholders})
                GROUP BY status
            """,
                tuple(ids),
            ).fetchall()
            for r in rows or []:
                if r["status"] in ("pending", "confirmed"):
                    kpis[r["status"]] = r["c"]

            # Per-business today counts
            for b in businesses:
                row = con.execute(
                    """
                    SELECT COUNT(*) c FROM appointments
                    WHERE business_id = ?
                      AND date(COALESCE(start_at, created_at)) = date('now', 'localtime')
                """,
                    (b["id"],),
                ).fetchone()
                appt_counts[b["id"]] = row["c"] if row else 0

            # 7-day series for chart
            start = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
            rows = con.execute(
                f"""
                SELECT date(COALESCE(start_at, created_at)) d, COUNT(*) c
                FROM appointments
                WHERE business_id IN ({placeholders})
                  AND date(COALESCE(start_at, created_at)) >= date(?)
                GROUP BY d ORDER BY d
            """,
                (*ids, start),
            ).fetchall()

            data = {r["d"]: r["c"] for r in rows or []}
            for i in range(7):
                d = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
                series_labels.append(d)
                series_values.append(int(data.get(d, 0)))

            # === NEW: AI Activity Stats ===
            # Today's chat sessions
            row = con.execute(
                f"""
                SELECT COUNT(*) c FROM sessions
                WHERE business_id IN ({placeholders})
                  AND date(created_at) = date('now', 'localtime')
            """,
                tuple(ids),
            ).fetchone()
            ai_stats["chats_today"] = row["c"] if row else 0

            # This week's chats
            row = con.execute(
                f"""
                SELECT COUNT(*) c FROM sessions
                WHERE business_id IN ({placeholders})
                  AND date(created_at) >= date('now', '-7 days')
            """,
                tuple(ids),
            ).fetchone()
            ai_stats["chats_week"] = row["c"] if row else 0

            # Today's AI-booked appointments
            row = con.execute(
                f"""
                SELECT COUNT(*) c FROM appointments
                WHERE business_id IN ({placeholders})
                  AND source = 'ai'
                  AND date(created_at) = date('now', 'localtime')
            """,
                tuple(ids),
            ).fetchone()
            ai_stats["bookings_today"] = row["c"] if row else 0

            # Voice calls (if table exists)
            try:
                row = con.execute(
                    f"""
                    SELECT COUNT(*) c FROM voice_calls
                    WHERE business_id IN ({placeholders})
                      AND date(created_at) = date('now', 'localtime')
                """,
                    tuple(ids),
                ).fetchone()
                ai_stats["calls_today"] = row["c"] if row else 0

                row = con.execute(
                    f"""
                    SELECT COUNT(*) c FROM voice_calls
                    WHERE business_id IN ({placeholders})
                      AND date(created_at) >= date('now', '-7 days')
                """,
                    tuple(ids),
                ).fetchone()
                ai_stats["calls_week"] = row["c"] if row else 0
            except Exception:
                pass  # voice_calls table may not exist

            # === NEW: Upcoming Appointments ===
            rows = con.execute(
                f"""
                SELECT id, customer_name, service, start_at, status, business_id
                FROM appointments
                WHERE business_id IN ({placeholders})
                  AND datetime(start_at) > datetime('now', 'localtime')
                  AND status IN ('pending', 'confirmed')
                ORDER BY start_at ASC
                LIMIT 5
            """,
                tuple(ids),
            ).fetchall()
            upcoming_appointments = [dict(r) for r in rows] if rows else []

            # === NEW: Recent Activity Feed ===
            # Combine recent messages, appointments, escalations
            activity_items = []

            # Recent bookings
            rows = con.execute(
                f"""
                SELECT 'booking' as type, customer_name as title, service as subtitle,
                       created_at as timestamp, id
                FROM appointments
                WHERE business_id IN ({placeholders})
                  AND date(created_at) >= date('now', '-1 day')
                ORDER BY created_at DESC
                LIMIT 5
            """,
                tuple(ids),
            ).fetchall()
            activity_items.extend([dict(r) for r in rows] if rows else [])

            # Recent escalations
            try:
                rows = con.execute(
                    f"""
                    SELECT 'escalation' as type, reason as title, status as subtitle,
                           created_at as timestamp, id
                    FROM escalations
                    WHERE business_id IN ({placeholders})
                      AND date(created_at) >= date('now', '-1 day')
                    ORDER BY created_at DESC
                    LIMIT 3
                """,
                    tuple(ids),
                ).fetchall()
                activity_items.extend([dict(r) for r in rows] if rows else [])
            except Exception:
                pass

            # Recent voice calls
            try:
                rows = con.execute(
                    f"""
                    SELECT 'call' as type,
                           COALESCE(from_number, 'Unknown') as title,
                           COALESCE(duration_seconds || 's', 'In progress') as subtitle,
                           created_at as timestamp, id
                    FROM voice_calls
                    WHERE business_id IN ({placeholders})
                      AND date(created_at) >= date('now', '-1 day')
                    ORDER BY created_at DESC
                    LIMIT 3
                """,
                    tuple(ids),
                ).fetchall()
                activity_items.extend([dict(r) for r in rows] if rows else [])
            except Exception:
                pass

            # Sort by timestamp and take top 8
            activity_items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            recent_activity = activity_items[:8]

            # === NEW: Pending Escalations Count ===
            try:
                row = con.execute(
                    f"""
                    SELECT COUNT(*) c FROM escalations
                    WHERE business_id IN ({placeholders})
                      AND status = 'pending'
                """,
                    tuple(ids),
                ).fetchone()
                escalation_count = row["c"] if row else 0
            except Exception:
                pass

            # === NEW: Week-over-Week Comparison ===
            row = con.execute(
                f"""
                SELECT COUNT(*) c FROM appointments
                WHERE business_id IN ({placeholders})
                  AND date(created_at) >= date('now', '-7 days')
            """,
                tuple(ids),
            ).fetchone()
            week_comparison["this_week"] = row["c"] if row else 0

            row = con.execute(
                f"""
                SELECT COUNT(*) c FROM appointments
                WHERE business_id IN ({placeholders})
                  AND date(created_at) >= date('now', '-14 days')
                  AND date(created_at) < date('now', '-7 days')
            """,
                tuple(ids),
            ).fetchone()
            week_comparison["last_week"] = row["c"] if row else 0

            if week_comparison["last_week"] > 0:
                change = week_comparison["this_week"] - week_comparison["last_week"]
                week_comparison["change_pct"] = round((change / week_comparison["last_week"]) * 100)
            elif week_comparison["this_week"] > 0:
                week_comparison["change_pct"] = 100

            # Voice stats for the week
            voice_stats = {"total_week": 0, "avg_duration": 0, "booked_calls": 0}
            try:
                row = con.execute(
                    f"""
                    SELECT COUNT(*) total, AVG(duration_seconds) avg_dur,
                           SUM(CASE WHEN booking_confirmed=1 THEN 1 ELSE 0 END) booked
                    FROM voice_calls
                    WHERE business_id IN ({placeholders})
                      AND date(created_at) >= date('now', '-7 days')
                """,
                    tuple(ids),
                ).fetchone()
                if row:
                    voice_stats["total_week"] = row["total"] or 0
                    voice_stats["avg_duration"] = round(row["avg_dur"] or 0)
                    voice_stats["booked_calls"] = row["booked"] or 0
            except Exception:
                pass

            # Top services by booking count (all time)
            top_services = []
            try:
                rows = con.execute(
                    f"""
                    SELECT service, COUNT(*) cnt FROM appointments
                    WHERE business_id IN ({placeholders})
                      AND service IS NOT NULL AND service != ''
                      AND status IN ('confirmed','completed','pending')
                    GROUP BY service ORDER BY cnt DESC LIMIT 5
                """,
                    tuple(ids),
                ).fetchall()
                top_services = [dict(r) for r in rows] if rows else []
            except Exception:
                pass

            # New customers this week
            new_customers_week = 0
            try:
                row = con.execute(
                    f"""
                    SELECT COUNT(*) c FROM customers
                    WHERE business_id IN ({placeholders})
                      AND date(created_at) >= date('now', '-7 days')
                """,
                    tuple(ids),
                ).fetchone()
                new_customers_week = row["c"] if row else 0
            except Exception:
                pass

            # Total customers
            total_customers = 0
            try:
                row = con.execute(
                    f"SELECT COUNT(*) c FROM customers WHERE business_id IN ({placeholders})",
                    tuple(ids),
                ).fetchone()
                total_customers = row["c"] if row else 0
            except Exception:
                pass

            # Recent calls (last 8)
            recent_calls = []
            try:
                rows = con.execute(
                    f"""
                    SELECT retell_call_id, from_number, duration_seconds, call_status,
                           transcript, created_at, sentiment, booking_confirmed
                    FROM voice_calls
                    WHERE business_id IN ({placeholders})
                    ORDER BY created_at DESC LIMIT 8
                """,
                    tuple(ids),
                ).fetchall()
                recent_calls = [dict(r) for r in rows] if rows else []
            except Exception:
                pass

            # Sentiment breakdown from calls
            sentiment_breakdown = {"positive": 0, "neutral": 0, "negative": 0}
            try:
                rows = con.execute(
                    f"""
                    SELECT sentiment, COUNT(*) c FROM voice_calls
                    WHERE business_id IN ({placeholders}) AND sentiment IS NOT NULL
                    GROUP BY sentiment
                """,
                    tuple(ids),
                ).fetchall()
                for r in rows:
                    s = (r["sentiment"] or "").lower()
                    if s in sentiment_breakdown:
                        sentiment_breakdown[s] = r["c"]
            except Exception:
                pass

            # Voice calls per day for chart (last 7 days)
            voice_series_values = []
            try:
                voice_data = {}
                rows = con.execute(
                    f"""
                    SELECT date(created_at) d, COUNT(*) c FROM voice_calls
                    WHERE business_id IN ({placeholders})
                      AND date(created_at) >= date(?)
                    GROUP BY d
                """,
                    (*ids, start),
                ).fetchall()
                voice_data = {r["d"]: r["c"] for r in rows} if rows else {}
                for i in range(7):
                    d = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
                    voice_series_values.append(int(voice_data.get(d, 0)))
            except Exception:
                voice_series_values = [0] * 7

    from datetime import datetime as dt

    # Onboarding checklist for the active business (shown until complete)
    try:
        from core.onboarding import checklist_for_business

        onboarding = checklist_for_business(getattr(g, "active_business_id", 0) or 0)
    except Exception:
        onboarding = {"steps": [], "complete": True, "done": 0, "total": 0, "percent": 100}

    return render_template(
        "dashboard.html",
        businesses=businesses,
        business=None,
        onboarding=onboarding,
        appt_counts=appt_counts,
        kpis=kpis,
        series_labels=series_labels,
        series_values=series_values,
        now=dt.now(),
        ai_stats=ai_stats,
        upcoming_appointments=upcoming_appointments,
        recent_activity=recent_activity,
        escalation_count=escalation_count,
        week_comparison=week_comparison,
        voice_stats=voice_stats,
        top_services=top_services,
        new_customers_week=new_customers_week,
        total_customers=total_customers,
        recent_calls=recent_calls,
        sentiment_breakdown=sentiment_breakdown,
        voice_series_values=voice_series_values,
    )


@app.route("/business/<int:business_id>/edit", methods=["GET", "POST"])
def edit_business(business_id: int):
    """Edit business details."""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))

    # Enforce tenant isolation
    user = session.get("user")
    if user and user.get("role") != "admin":
        if not user_can_access_business(user, business_id):
            abort(403)

    b = get_business_by_id(business_id)
    if not b:
        flash("Business not found.", "err")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        fields = {
            k: request.form.get(k)
            for k in [
                "name",
                "slug",
                "hours",
                "address",
                "services",
                "tone",
                "escalation_phone",
                "escalation_email",
                "accent_color",
            ]
        }

        # Generate slug from name if not provided
        desired_slug = (fields.get("slug") or "").strip()
        name = fields.get("name") or b.get("name", "")
        fields["slug"] = slugify(desired_slug or name)

        # Self-improving KB toggle (checkbox: absent = off).
        fields["kb_autolearn_enabled"] = 1 if request.form.get("kb_autolearn_enabled") else 0
        # Transcript PII redaction toggle (compliance; checkbox absent = off).
        fields["redact_transcripts"] = 1 if request.form.get("redact_transcripts") else 0

        ensure_tenant_key(business_id)

        try:
            update_business(business_id, **{k: v for k, v in fields.items() if v is not None})
            write_meta_from_db(business_id)
            from core.audit import log_audit_from_request

            log_audit_from_request(
                "business.updated",
                business_id=business_id,
                entity_type="business",
                entity_id=business_id,
                detail={"fields": sorted(fields.keys())},
            )
            flash("Business updated.", "ok")
            app.logger.info(f"Business {business_id} updated by user {user.get('id')}")
        except Exception as e:
            app.logger.exception(f"Failed to update business {business_id}")
            flash(f"Update failed: {e}", "err")

        session["active_business_id"] = business_id
        return redirect(url_for("edit_business", business_id=business_id))

    session["active_business_id"] = business_id
    return render_template("edit_business.html", business=b)


@app.route("/business/<int:business_id>/logo", methods=["POST"])
def upload_logo(business_id: int):
    """Upload a logo for a business."""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))

    user = session.get("user")
    if user and user.get("role") != "admin":
        if not user_can_access_business(user, business_id):
            abort(403)

    b = get_business_by_id(business_id)
    if not b:
        flash("Business not found.", "err")
        return redirect(url_for("dashboard"))

    if "logo" not in request.files:
        flash("No file selected.", "err")
        return redirect(url_for("edit_business", business_id=business_id))

    file = request.files["logo"]
    if file.filename == "":
        flash("No file selected.", "err")
        return redirect(url_for("edit_business", business_id=business_id))

    # Validate file extension
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        flash("Invalid file type. Please upload PNG, JPG, WebP, or SVG.", "err")
        return redirect(url_for("edit_business", business_id=business_id))

    # Generate unique filename
    filename = f"logo_{business_id}_{uuid.uuid4().hex[:8]}{ext}"
    logo_dir = os.path.join(app.static_folder, "logos")
    os.makedirs(logo_dir, exist_ok=True)
    filepath = os.path.join(logo_dir, filename)

    # Remove old logo if exists
    old_logo = b.get("logo_path")
    if old_logo:
        old_path = os.path.join(app.static_folder, old_logo)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    # Save new logo
    file.save(filepath)

    # Update database
    logo_path = f"logos/{filename}"
    update_business(business_id, logo_path=logo_path)

    flash("Logo uploaded successfully.", "ok")
    return redirect(url_for("edit_business", business_id=business_id))


@app.route("/business/<int:business_id>/logo/delete", methods=["POST"])
def delete_logo(business_id: int):
    """Delete a business logo and revert to default."""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))

    user = session.get("user")
    if user and user.get("role") != "admin":
        if not user_can_access_business(user, business_id):
            abort(403)

    b = get_business_by_id(business_id)
    if not b:
        flash("Business not found.", "err")
        return redirect(url_for("dashboard"))

    # Remove logo file if exists
    logo_path = b.get("logo_path")
    if logo_path:
        full_path = os.path.join(app.static_folder, logo_path)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except OSError:
                pass

        # Clear logo_path in database
        update_business(business_id, logo_path=None)
        flash("Logo removed. Using default logo.", "ok")
    else:
        flash("No custom logo to remove.", "err")

    return redirect(url_for("edit_business", business_id=business_id))


@app.route("/voice/live")
def voice_live():
    """Live call monitor — watch in-progress calls and request a human handoff."""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))
    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        flash("Select a business to monitor calls.", "err")
        return redirect(url_for("dashboard"))
    business = get_business_by_id(business_id)
    return render_template("voice_live.html", business=business)


@app.route("/voice")
def voice_dashboard():
    """Voice AI analytics and call management page."""
    business_id = g.get("active_business_id") or session.get("active_business_id")

    stats = {
        "total_calls": 0,
        "calls_today": 0,
        "calls_week": 0,
        "containment_rate": 0,
        "avg_duration": 0,
        "booked_calls": 0,
        "missed_calls": 0,
        "messages_waiting": 0,
        "intent_breakdown": {},
        "outcome_breakdown": {},
        "sentiment_breakdown": {},
        "daily_series": [],
        "daily_labels": [],
    }
    calls = []
    messages = []

    if business_id:
        with get_conn() as con:
            # Totals
            row = con.execute(
                """
                SELECT
                  COUNT(*) as total,
                  SUM(CASE WHEN date(started_at) = date('now') THEN 1 ELSE 0 END) as today,
                  SUM(CASE WHEN date(started_at) >= date('now','-7 days') THEN 1 ELSE 0 END) as week,
                  AVG(CASE WHEN duration_seconds > 0 THEN duration_seconds END) as avg_dur,
                  SUM(CASE WHEN booking_confirmed=1 THEN 1 ELSE 0 END) as booked,
                  SUM(CASE WHEN call_outcome='missed' OR call_intent='missed' THEN 1 ELSE 0 END) as missed,
                  SUM(CASE WHEN caller_message IS NOT NULL AND caller_message != '' THEN 1 ELSE 0 END) as msgs
                FROM voice_calls WHERE business_id = ?
            """,
                (business_id,),
            ).fetchone()
            if row:
                stats["total_calls"] = row["total"] or 0
                stats["calls_today"] = row["today"] or 0
                stats["calls_week"] = row["week"] or 0
                stats["avg_duration"] = round(row["avg_dur"] or 0)
                stats["booked_calls"] = row["booked"] or 0
                stats["missed_calls"] = row["missed"] or 0
                stats["messages_waiting"] = row["msgs"] or 0

            # Containment rate
            cont = con.execute(
                """
                SELECT
                  COUNT(*) as total,
                  SUM(CASE WHEN containment=1 THEN 1 ELSE 0 END) as handled
                FROM voice_calls WHERE business_id = ? AND call_outcome IS NOT NULL
            """,
                (business_id,),
            ).fetchone()
            if cont and cont["total"] > 0:
                stats["containment_rate"] = round((cont["handled"] / cont["total"]) * 100)

            # Intent breakdown
            rows = con.execute(
                """
                SELECT call_intent, COUNT(*) as cnt FROM voice_calls
                WHERE business_id = ? AND call_intent IS NOT NULL
                GROUP BY call_intent ORDER BY cnt DESC
            """,
                (business_id,),
            ).fetchall()
            stats["intent_breakdown"] = {r["call_intent"]: r["cnt"] for r in rows}

            # Outcome breakdown
            rows = con.execute(
                """
                SELECT call_outcome, COUNT(*) as cnt FROM voice_calls
                WHERE business_id = ? AND call_outcome IS NOT NULL
                GROUP BY call_outcome ORDER BY cnt DESC
            """,
                (business_id,),
            ).fetchall()
            stats["outcome_breakdown"] = {r["call_outcome"]: r["cnt"] for r in rows}

            # Sentiment breakdown
            rows = con.execute(
                """
                SELECT sentiment, COUNT(*) as cnt FROM voice_calls
                WHERE business_id = ? AND sentiment IS NOT NULL
                GROUP BY sentiment
            """,
                (business_id,),
            ).fetchall()
            stats["sentiment_breakdown"] = {r["sentiment"].lower(): r["cnt"] for r in rows}

            # 14-day daily series
            rows = con.execute(
                """
                SELECT date(started_at) as d, COUNT(*) as cnt
                FROM voice_calls WHERE business_id = ?
                  AND date(started_at) >= date('now', '-13 days')
                GROUP BY d ORDER BY d
            """,
                (business_id,),
            ).fetchall()
            day_map = {r["d"]: r["cnt"] for r in rows}
            from datetime import timedelta

            today = datetime.now().date()
            for i in range(13, -1, -1):
                d = (today - timedelta(days=i)).isoformat()
                stats["daily_labels"].append(d)
                stats["daily_series"].append(day_map.get(d, 0))

            # Recent calls (last 50)
            rows = con.execute(
                """
                SELECT * FROM voice_calls WHERE business_id = ?
                ORDER BY started_at DESC LIMIT 50
            """,
                (business_id,),
            ).fetchall()
            calls = [dict(r) for r in rows]

            # Voicemail messages
            rows = con.execute(
                """
                SELECT * FROM voice_calls
                WHERE business_id = ? AND caller_message IS NOT NULL AND caller_message != ''
                ORDER BY started_at DESC LIMIT 20
            """,
                (business_id,),
            ).fetchall()
            messages = [dict(r) for r in rows]

    # Voice settings for config panel
    voice_settings = {}
    if business_id:
        try:
            from core.voice import get_voice_settings

            voice_settings = get_voice_settings(business_id)
        except Exception:
            pass

    return render_template(
        "voice.html",
        stats=stats,
        calls=calls,
        messages=messages,
        voice_settings=voice_settings,
        now=datetime.now(),
    )


@app.route("/sw.js")
def service_worker():
    """Serve the service worker from root so its scope covers the whole app."""
    resp = send_from_directory(app.static_folder, "sw.js")
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/api/push/public-key")
def push_public_key():
    """Expose the VAPID public key (empty string when push isn't configured)."""
    from core.push import public_key

    return jsonify({"key": public_key() or ""})


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    if session.get("user") is None:
        return jsonify({"error": "unauthorized"}), 401
    from core.push import save_subscription

    sub = request.get_json(silent=True) or {}
    user_id = session["user"].get("id")
    business_id = g.get("active_business_id") or session.get("active_business_id")
    ua = request.headers.get("User-Agent", "")[:300]
    ok = save_subscription(user_id, sub, business_id=business_id, user_agent=ua)
    return jsonify({"success": ok}), (200 if ok else 400)


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    if session.get("user") is None:
        return jsonify({"error": "unauthorized"}), 401
    from core.push import remove_subscription

    endpoint = (request.get_json(silent=True) or {}).get("endpoint")
    if endpoint:
        remove_subscription(endpoint)
    return jsonify({"success": True})


@app.route("/audit")
def audit_log_view():
    """Compliance audit trail for the active business (and global admin events)."""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))
    business_id = g.get("active_business_id") or session.get("active_business_id")
    from core.audit import list_audit

    entries = list_audit(business_id, limit=300)
    return render_template("audit_log.html", entries=entries)


@app.route("/test-ai")
def test_ai():
    """Sandbox: chat with your own AI receptionist without side effects."""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))
    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        flash("Select a business to test its AI.", "err")
        return redirect(url_for("dashboard"))
    session.pop("sandbox_state", None)  # fresh conversation each visit
    business = get_business_by_id(business_id)
    return render_template("test_ai.html", business=business)


@app.route("/api/test-ai/chat", methods=["POST"])
def test_ai_chat():
    """Run one sandbox turn: real AI, no bookings/escalations/SMS persisted."""
    if session.get("user") is None:
        return jsonify({"error": "unauthorized"}), 401
    business_id = g.get("active_business_id") or session.get("active_business_id")
    if not business_id:
        return jsonify({"error": "no business"}), 400
    business = get_business_by_id(business_id)
    if not business:
        return jsonify({"error": "no business"}), 400

    text = (request.form.get("message") or "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400

    from core.ai import process_message_with_metadata

    st = session.get("sandbox_state") or {"history": []}
    result = process_message_with_metadata(
        text, dict(business), st, suppress_escalation=True
    )
    session["sandbox_state"] = st  # persists updated history for multi-turn

    # Strip machine tags so the sandbox shows what a customer would hear.
    reply = re.sub(
        r"<(BOOKING|CANCEL|RESCHEDULE)>.*?</\1>", "", result.get("reply", ""), flags=re.DOTALL
    ).strip()
    return jsonify(
        {
            "reply": reply,
            "low_confidence": result.get("low_confidence", False),
            "sentiment": result.get("sentiment"),
        }
    )


@app.route("/api/test-ai/reset", methods=["POST"])
def test_ai_reset():
    if session.get("user") is None:
        return jsonify({"error": "unauthorized"}), 401
    session.pop("sandbox_state", None)
    return jsonify({"ok": True})


@app.route("/api/call-feedback", methods=["POST"])
def call_feedback():
    """Record an owner thumbs up/down on a handled call or chat."""
    user = session.get("user")
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    business_id = safe_int(request.form.get("business_id")) or g.get(
        "active_business_id"
    ) or session.get("active_business_id")
    if not business_id:
        return jsonify({"error": "no business"}), 400
    if user.get("role") != "admin" and not user_can_access_business(user, business_id):
        return jsonify({"error": "forbidden"}), 403

    from core.feedback import record_feedback

    ok = record_feedback(
        business_id,
        (request.form.get("rating") or "").strip(),
        voice_call_id=safe_int(request.form.get("voice_call_id")) or None,
        session_id=safe_int(request.form.get("session_id")) or None,
        note=request.form.get("note"),
        created_by=user.get("id"),
    )
    return (jsonify({"ok": True}) if ok else (jsonify({"error": "invalid"}), 400))


@app.route("/health")
def health():
    """Basic health check endpoint for load balancers."""
    return Response(
        json.dumps({"status": "ok", "timestamp": datetime.now().isoformat()}),
        mimetype="application/json",
    )


@app.route("/health/live")
def health_live():
    """Liveness probe - simple check that the process is alive."""
    return Response(
        json.dumps({"status": "alive", "timestamp": datetime.now().isoformat()}),
        mimetype="application/json",
    )


@app.route("/health/ready")
def health_ready():
    """Readiness probe - deep health check for dependencies."""
    checks = {}
    all_healthy = True

    # Check database connectivity
    try:
        with get_conn() as con:
            con.execute("SELECT 1").fetchone()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:50]}"
        all_healthy = False
        app.logger.error(f"Health check - database failed: {e}")

    # Check OpenAI API key is configured
    from core.settings import OPENAI_API_KEY

    if OPENAI_API_KEY and len(OPENAI_API_KEY) > 10:
        checks["openai_configured"] = "ok"
    else:
        checks["openai_configured"] = "warning: not configured"
        # Don't mark as unhealthy - some features work without AI

    # Check disk space (logs directory)
    try:
        import shutil

        total, used, free = shutil.disk_usage(".")
        free_gb = free / (1024**3)
        if free_gb < 1:
            checks["disk_space"] = f"warning: {free_gb:.1f}GB free"
        else:
            checks["disk_space"] = "ok"
    except Exception:
        checks["disk_space"] = "unknown"

    # Background worker heartbeats (informational — not part of all_healthy)
    try:
        checks["workers"] = heartbeat_snapshot()
    except Exception:
        checks["workers"] = "unavailable"

    status_code = 200 if all_healthy else 503
    status = "ready" if all_healthy else "degraded"

    return Response(
        json.dumps(
            {
                "status": status,
                "checks": checks,
                "timestamp": datetime.now().isoformat(),
                "environment": APP_ENV,
            }
        ),
        mimetype="application/json",
        status=status_code,
    )


# ============================================================================
# Legal Pages (Public — no login required)
# ============================================================================


@app.route("/privacy")
def privacy():
    """Privacy Policy — public page, no auth required."""
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    """Terms of Service — public page, no auth required."""
    return render_template("terms.html")


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    init_db()

    if IS_PROD:
        # Production should use gunicorn/uWSGI, not Flask dev server
        app.logger.warning(
            "Running Flask development server in production mode is not recommended. "
            "Use: gunicorn -w 4 -b 0.0.0.0:5050 dashboard:app"
        )

    app.run(host="127.0.0.1", port=5050, debug=(not IS_PROD))
