# dashboard.py — AxisAI admin (tenant isolation + branding + pro UI)
# Production-grade Flask application with proper security and error handling

import os
import uuid
import logging
import json
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, abort, Response
)

from core.settings import FLASK_SECRET_KEY
from core.db import (
    init_db, list_businesses, get_business_by_id, update_business,
    get_conn, ensure_tenant_key
)
from core.validators import slugify, validate_redirect_url, safe_int
from core.tenantfs import write_meta_from_db
from core.csrf import register_csrf
from core.authz import get_allowed_business_ids_for_user, user_can_access_business

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
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Note: For file upload endpoints that need larger limits,
# use @app.route decorators with specific limits or validate in the route

# ============================================================================
# Provider Registration
# ============================================================================

import providers.local_provider  # noqa: F401
import providers.dummy_provider  # noqa: F401

# ============================================================================
# Blueprint Registration
# ============================================================================

from auth_bp import bp as auth_bp
from appointments_bp import bp as appointments_bp
from chat_bp import bp as chat_bp
from onboard_bp import bp as onboard_bp
from kb_bp import bp as kb_bp
from services_bp import bp as services_bp
from integrations_bp import bp as integrations_bp
from search_bp import bp as search_bp
from widget_bp import bp as widget_bp
from customers_bp import bp as customers_bp
from escalations_bp import escalations_bp
from analytics_bp import analytics_bp

# SMS Blueprint (optional, requires Twilio or alternative provider)
try:
    from sms_bp import bp as sms_bp
    SMS_AVAILABLE = True
except ImportError:
    SMS_AVAILABLE = False

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

# Register SMS blueprint if available
if SMS_AVAILABLE:
    app.register_blueprint(sms_bp)

# ============================================================================
# Logging Configuration
# ============================================================================

os.makedirs("logs", exist_ok=True)

# Structured log format with request ID correlation
class RequestFormatter(logging.Formatter):
    def format(self, record):
        record.request_id = getattr(g, 'request_id', 'no-request')
        record.user_id = 'anonymous'
        user = session.get("user") if session else None
        if user:
            record.user_id = user.get("id", "unknown")
        return super().format(record)

# File handler with rotation by size
file_handler = RotatingFileHandler(
    "logs/app.log",
    maxBytes=10_000_000,  # 10MB
    backupCount=10
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(RequestFormatter(
    '%(asctime)s [%(request_id)s] [user:%(user_id)s] %(levelname)s %(name)s: %(message)s'
))

# Security event log (separate file for audit)
security_handler = RotatingFileHandler(
    "logs/security.log",
    maxBytes=10_000_000,
    backupCount=20
)
security_handler.setLevel(logging.WARNING)
security_handler.setFormatter(RequestFormatter(
    '%(asctime)s [%(request_id)s] [user:%(user_id)s] SECURITY %(message)s'
))

# Configure app logger
if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
    app.logger.addHandler(file_handler)
    app.logger.addHandler(security_handler)
app.logger.setLevel(logging.INFO if IS_PROD else logging.DEBUG)

# Create a security logger for audit events
security_logger = logging.getLogger('security')
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
    if hasattr(g, 'request_start'):
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
    max_size_mb = app.config.get('MAX_CONTENT_LENGTH', 0) // (1024 * 1024)
    app.logger.warning(f"Request too large: {request.path}")
    return render_template(
        "error_400.html",
        error=f"File too large. Maximum upload size is {max_size_mb}MB."
    ), 413


@app.errorhandler(429)
def too_many_requests(e):
    """Handle 429 Too Many Requests errors (rate limiting)."""
    app.logger.warning(f"Rate limit exceeded: {request.path} from {request.remote_addr}")
    return render_template(
        "error_400.html",
        error="Too many requests. Please wait a moment and try again."
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
    bid_from_query = request.args.get("business_id")
    if bid_from_query:
        bq = safe_int(bid_from_query)
        if bq:
            user = session.get("user")
            if (user and user.get("role") == "admin") or (bq in (g.allowed_business_ids or [])):
                session["active_business_id"] = bq

    bid = session.get("active_business_id")

    # Build nav list (admins = all; owners = only mapped businesses)
    user = session.get("user")
    nav_businesses = []
    if user:
        if user.get("role") == "admin":
            nav_businesses = list_businesses(limit=500)
        else:
            ids = g.allowed_business_ids or []
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

    return {
        "accent_color": color,
        "business_logo_path": logo_path,
        "nav_businesses": nav_businesses,
        "active_business_id": bid or 0,
        "is_prod": IS_PROD,
        "current_year": datetime.now().year,
    }


# ============================================================================
# Routes
# ============================================================================

@app.route("/")
def home():
    """Redirect to dashboard."""
    return redirect(url_for("dashboard"))


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
    return_to = validate_redirect_url(
        request.form.get("return_to"),
        default=url_for("dashboard")
    )
    return redirect(return_to)


@app.route("/dashboard")
@app.route("/businesses")
def dashboard():
    """Main dashboard with KPIs and business list."""
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

    if businesses:
        ids = [b["id"] for b in businesses]
        placeholders = ",".join("?" * len(ids))

        with get_conn() as con:
            # Total appointments
            row = con.execute(
                f"SELECT COUNT(*) c FROM appointments WHERE business_id IN ({placeholders})",
                tuple(ids)
            ).fetchone()
            kpis["total"] = row["c"] if row else 0

            # Today's appointments
            row = con.execute(f"""
                SELECT COUNT(*) c FROM appointments
                WHERE business_id IN ({placeholders})
                  AND date(COALESCE(start_at, created_at)) = date('now', 'localtime')
            """, tuple(ids)).fetchone()
            kpis["today"] = row["c"] if row else 0

            # Status counts
            rows = con.execute(f"""
                SELECT status, COUNT(*) c FROM appointments
                WHERE business_id IN ({placeholders})
                GROUP BY status
            """, tuple(ids)).fetchall()
            for r in rows or []:
                if r["status"] in ("pending", "confirmed"):
                    kpis[r["status"]] = r["c"]

            # Per-business today counts
            for b in businesses:
                row = con.execute("""
                    SELECT COUNT(*) c FROM appointments
                    WHERE business_id = ?
                      AND date(COALESCE(start_at, created_at)) = date('now', 'localtime')
                """, (b["id"],)).fetchone()
                appt_counts[b["id"]] = row["c"] if row else 0

            # 7-day series for chart
            start = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
            rows = con.execute(f"""
                SELECT date(COALESCE(start_at, created_at)) d, COUNT(*) c
                FROM appointments
                WHERE business_id IN ({placeholders})
                  AND date(COALESCE(start_at, created_at)) >= date(?)
                GROUP BY d ORDER BY d
            """, (*ids, start)).fetchall()

            data = {r["d"]: r["c"] for r in rows or []}
            for i in range(7):
                d = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
                series_labels.append(d)
                series_values.append(int(data.get(d, 0)))

    from datetime import datetime as dt
    return render_template(
        "dashboard.html",
        businesses=businesses,
        business=None,
        appt_counts=appt_counts,
        kpis=kpis,
        series_labels=series_labels,
        series_values=series_values,
        now=dt.now()
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
            k: request.form.get(k) for k in [
                "name", "slug", "hours", "address", "services", "tone",
                "escalation_phone", "escalation_email", "accent_color"
            ]
        }

        # Generate slug from name if not provided
        desired_slug = (fields.get("slug") or "").strip()
        name = fields.get("name") or b.get("name", "")
        fields["slug"] = slugify(desired_slug or name)

        ensure_tenant_key(business_id)

        try:
            update_business(business_id, **{k: v for k, v in fields.items() if v is not None})
            write_meta_from_db(business_id)
            flash("Business updated.", "ok")
            app.logger.info(f"Business {business_id} updated by user {user.get('id')}")
        except Exception as e:
            app.logger.exception(f"Failed to update business {business_id}")
            flash(f"Update failed: {e}", "err")

        session["active_business_id"] = business_id
        return redirect(url_for("edit_business", business_id=business_id))

    session["active_business_id"] = business_id
    return render_template("edit_business.html", business=b)


@app.route("/health")
def health():
    """Basic health check endpoint for load balancers."""
    return Response(
        json.dumps({"status": "ok", "timestamp": datetime.now().isoformat()}),
        mimetype="application/json"
    )


@app.route("/health/live")
def health_live():
    """Liveness probe - simple check that the process is alive."""
    return Response(
        json.dumps({"status": "alive", "timestamp": datetime.now().isoformat()}),
        mimetype="application/json"
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
        free_gb = free / (1024 ** 3)
        if free_gb < 1:
            checks["disk_space"] = f"warning: {free_gb:.1f}GB free"
        else:
            checks["disk_space"] = "ok"
    except Exception:
        checks["disk_space"] = "unknown"

    status_code = 200 if all_healthy else 503
    status = "ready" if all_healthy else "degraded"

    return Response(
        json.dumps({
            "status": status,
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
            "environment": APP_ENV
        }),
        mimetype="application/json",
        status=status_code
    )


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
