# integrations_bp.py — pick provider + store config per business
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g
from core.db import get_conn, list_businesses, get_business_by_id, ensure_tenant_key
import json

bp = Blueprint("integrations", __name__)

def _user(): return session.get("user")
def _need_login(): return _user() is None


def _get_widget_settings(business_id):
    """Get widget settings for a business with defaults."""
    defaults = {
        "enabled": 1,
        "position": "bottom-right",
        "primary_color": None,
        "welcome_message": "Hi! How can I help you today?",
        "placeholder_text": "Type a message...",
        "allowed_domains": "",
        "show_branding": 1,
        "auto_open_delay": None,
    }

    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM widget_settings WHERE business_id = ?",
            (business_id,)
        ).fetchone()

        if row:
            settings = dict(row)
            for key, value in defaults.items():
                if key not in settings or settings[key] is None:
                    settings[key] = value
            return settings

    return {**defaults, "business_id": business_id}


@bp.route("/integrations", methods=["GET","POST"])
def integrations_index():
    if _need_login(): return redirect(url_for("auth.login"))

    business_id = int((request.values.get("business_id") or 0))
    providers = [
        {"key":"local", "name":"Local (in-app scheduler)"},
        {"key":"dummy", "name":"Dummy External (demo)"},
        # Future: {"key":"google_calendar","name":"Google Calendar"}, etc.
    ]
    current = None
    cfg = {}
    widget = {}
    tenant_key = ""
    business = None

    if request.method=="POST":
        key = (request.form.get("provider_key") or "local").strip()
        raw = request.form.get("config_json") or "{}"
        try:
            data = json.loads(raw)
        except Exception:
            flash("Config must be valid JSON.", "err")
            return redirect(url_for("integrations.integrations_index", business_id=business_id))
        with get_conn() as con:
            con.execute("""
              INSERT INTO integrations(business_id,provider_key,status,account_json,updated_at)
              VALUES(?,?,?,?,datetime('now','localtime'))
              ON CONFLICT(business_id,provider_key)
              DO UPDATE SET status=excluded.status, account_json=excluded.account_json, updated_at=excluded.updated_at
            """, (business_id, key, "active", json.dumps(data)))
        flash("Integration saved.", "ok")
        return redirect(url_for("integrations.integrations_index", business_id=business_id))

    businesses = list_businesses(limit=500)
    if business_id:
        business = get_business_by_id(business_id)
        tenant_key = ensure_tenant_key(business_id)
        widget = _get_widget_settings(business_id)

        with get_conn() as con:
            row = con.execute("""
              SELECT provider_key, account_json FROM integrations
              WHERE business_id=? AND status='active'
              ORDER BY id DESC LIMIT 1
            """,(business_id,)).fetchone()
        if row:
            current = row["provider_key"]
            try: cfg = json.loads(row["account_json"] or "{}")
            except: cfg = {}

    # Google Calendar status
    gcal_connected = False
    gcal_calendar_id = None
    try:
        from core.google_calendar import get_business_gcal_config, GOOGLE_CONFIGURED as GCAL_CONFIGURED
        gcal_cfg = get_business_gcal_config(business_id) if business_id else None
        gcal_connected = bool(gcal_cfg)
        gcal_calendar_id = gcal_cfg.get("calendar_id") if gcal_cfg else None
    except Exception:
        GCAL_CONFIGURED = False

    return render_template("integrations.html",
                           businesses=businesses,
                           business_id=business_id,
                           business=business,
                           providers=providers,
                           current=current,
                           cfg=cfg,
                           widget=widget,
                           tenant_key=tenant_key,
                           gcal_configured=GCAL_CONFIGURED,
                           gcal_connected=gcal_connected,
                           gcal_calendar_id=gcal_calendar_id)


@bp.route("/integrations/widget", methods=["POST"])
def widget_settings():
    """Update widget settings for a business."""
    if _need_login():
        return redirect(url_for("auth.login"))

    business_id = int(request.form.get("business_id") or 0)
    if not business_id:
        flash("Business is required.", "err")
        return redirect(url_for("integrations.integrations_index"))

    # Parse form values
    enabled = 1 if request.form.get("enabled") == "on" else 0
    position = request.form.get("position", "bottom-right")
    primary_color = request.form.get("primary_color", "").strip() or None
    welcome_message = request.form.get("welcome_message", "").strip() or "Hi! How can I help you today?"
    placeholder_text = request.form.get("placeholder_text", "").strip() or "Type a message..."
    allowed_domains_raw = request.form.get("allowed_domains", "").strip()
    show_branding = 1 if request.form.get("show_branding") == "on" else 0

    # Parse auto_open_delay
    auto_open_delay = None
    auto_open_raw = request.form.get("auto_open_delay", "").strip()
    if auto_open_raw:
        try:
            auto_open_delay = int(auto_open_raw)
            if auto_open_delay < 1 or auto_open_delay > 300:
                auto_open_delay = None
        except ValueError:
            pass

    # Convert allowed domains to JSON array
    allowed_domains = None
    if allowed_domains_raw:
        domains = [d.strip() for d in allowed_domains_raw.split(",") if d.strip()]
        if domains:
            allowed_domains = json.dumps(domains)

    # Save to database
    with get_conn() as con:
        con.execute("""
            INSERT INTO widget_settings (
                business_id, enabled, position, primary_color, welcome_message,
                placeholder_text, allowed_domains, show_branding, auto_open_delay, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(business_id) DO UPDATE SET
                enabled = excluded.enabled,
                position = excluded.position,
                primary_color = excluded.primary_color,
                welcome_message = excluded.welcome_message,
                placeholder_text = excluded.placeholder_text,
                allowed_domains = excluded.allowed_domains,
                show_branding = excluded.show_branding,
                auto_open_delay = excluded.auto_open_delay,
                updated_at = excluded.updated_at
        """, (business_id, enabled, position, primary_color, welcome_message,
              placeholder_text, allowed_domains, show_branding, auto_open_delay))
        con.commit()

    flash("Widget settings saved.", "ok")
    return redirect(url_for("integrations.integrations_index", business_id=business_id))


# ============================================================================
# Google Calendar OAuth
# ============================================================================

@bp.route("/integrations/google/connect")
def google_connect():
    """Start Google Calendar OAuth flow."""
    if _need_login():
        return redirect(url_for("auth.login"))

    business_id = int(request.args.get("business_id") or 0)
    if not business_id:
        flash("Select a business first.", "err")
        return redirect(url_for("integrations.integrations_index"))

    try:
        from core.google_calendar import get_authorization_url, GOOGLE_CONFIGURED
        if not GOOGLE_CONFIGURED:
            flash("Google Calendar credentials not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env", "err")
            return redirect(url_for("integrations.integrations_index", business_id=business_id))

        # Use the current server URL for the redirect URI
        redirect_uri = request.url_root.rstrip("/") + "/integrations/google/callback"
        # Store redirect_uri in session for callback
        session["gcal_redirect_uri"] = redirect_uri
        session["gcal_business_id"] = business_id

        auth_url = get_authorization_url(business_id, redirect_uri=redirect_uri)
        if not auth_url:
            flash("Failed to generate Google authorization URL.", "err")
            return redirect(url_for("integrations.integrations_index", business_id=business_id))

        return redirect(auth_url)

    except Exception as e:
        flash(f"Google Calendar error: {e}", "err")
        return redirect(url_for("integrations.integrations_index", business_id=business_id))


@bp.route("/integrations/google/callback")
def google_callback():
    """Handle Google Calendar OAuth callback."""
    if _need_login():
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    error = request.args.get("error")
    state = request.args.get("state", "")

    if error:
        flash(f"Google authorization denied: {error}", "err")
        return redirect(url_for("integrations.integrations_index"))

    if not code:
        flash("No authorization code received from Google.", "err")
        return redirect(url_for("integrations.integrations_index"))

    # Extract business_id from state or session
    business_id = session.pop("gcal_business_id", None)
    redirect_uri = session.pop("gcal_redirect_uri", None)

    if not business_id:
        try:
            business_id = int(state.split(":")[0])
        except Exception:
            flash("Invalid OAuth state.", "err")
            return redirect(url_for("integrations.integrations_index"))

    if not redirect_uri:
        redirect_uri = request.url_root.rstrip("/") + "/integrations/google/callback"

    try:
        from core.google_calendar import (
            exchange_code_for_tokens,
            list_calendars,
            save_business_gcal_config,
        )

        tokens = exchange_code_for_tokens(code, redirect_uri=redirect_uri)
        if not tokens:
            flash("Failed to exchange authorization code for tokens.", "err")
            return redirect(url_for("integrations.integrations_index", business_id=business_id))

        # Get list of calendars and default to primary
        calendars = list_calendars(tokens)
        primary_id = "primary"
        for cal in calendars:
            if cal.get("primary"):
                primary_id = cal["id"]
                break

        config = {
            "tokens": tokens,
            "calendar_id": primary_id,
            "calendars": calendars,
            "connected_at": json.dumps(None),  # placeholder
        }

        save_business_gcal_config(business_id, config)
        flash("Google Calendar connected successfully!", "ok")

    except Exception as e:
        flash(f"Failed to connect Google Calendar: {e}", "err")

    return redirect(url_for("integrations.integrations_index", business_id=business_id))


@bp.route("/integrations/google/disconnect", methods=["POST"])
def google_disconnect():
    """Disconnect Google Calendar for a business."""
    if _need_login():
        return redirect(url_for("auth.login"))

    business_id = int(request.form.get("business_id") or 0)

    try:
        from core.google_calendar import disconnect_gcal
        disconnect_gcal(business_id)
        flash("Google Calendar disconnected.", "ok")
    except Exception as e:
        flash(f"Error disconnecting: {e}", "err")

    return redirect(url_for("integrations.integrations_index", business_id=business_id))


@bp.route("/integrations/google/select-calendar", methods=["POST"])
def google_select_calendar():
    """Update which Google Calendar to use for a business."""
    if _need_login():
        return redirect(url_for("auth.login"))

    business_id = int(request.form.get("business_id") or 0)
    calendar_id = request.form.get("calendar_id", "primary")

    try:
        from core.google_calendar import get_business_gcal_config, save_business_gcal_config
        config = get_business_gcal_config(business_id)
        if config:
            config["calendar_id"] = calendar_id
            save_business_gcal_config(business_id, config)
            flash(f"Calendar updated.", "ok")
        else:
            flash("Google Calendar not connected.", "err")
    except Exception as e:
        flash(f"Error: {e}", "err")

    return redirect(url_for("integrations.integrations_index", business_id=business_id))
