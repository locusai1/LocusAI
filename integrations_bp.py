# integrations_bp.py — pick provider + store config per business
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
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

    return render_template("integrations.html",
                           businesses=businesses,
                           business_id=business_id,
                           business=business,
                           providers=providers,
                           current=current,
                           cfg=cfg,
                           widget=widget,
                           tenant_key=tenant_key)


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
