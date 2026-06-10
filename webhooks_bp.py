# webhooks_bp.py — management UI for outbound webhooks (Zapier/Make/n8n-ready)

import logging
from flask import (
    Blueprint, render_template, request, redirect, url_for, session, flash, g,
)

from core.db import get_conn
from core import webhooks
from core.validators import safe_int

logger = logging.getLogger(__name__)

bp = Blueprint("webhooks", __name__)


def _user():
    return session.get("user")


def _can_access(business_id: int) -> bool:
    user = _user()
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    with get_conn() as con:
        return bool(con.execute(
            "SELECT 1 FROM business_users WHERE user_id=? AND business_id=?",
            (user["id"], business_id)).fetchone())


@bp.route("/integrations/webhooks")
def webhooks_index():
    if not _user():
        return redirect(url_for("auth.login"))
    business_id = safe_int(request.args.get("business_id")) or getattr(g, "active_business_id", 0)
    if not business_id or not _can_access(business_id):
        flash("Select a business to manage webhooks.", "err")
        return redirect(url_for("integrations.integrations_index"))

    return render_template(
        "webhooks.html",
        business_id=business_id,
        endpoints=webhooks.list_endpoints(business_id),
        deliveries=webhooks.recent_deliveries(business_id),
        event_types=webhooks.EVENT_TYPES,
        new_secret=session.pop("_new_webhook_secret", None),
    )


@bp.post("/integrations/webhooks")
def webhooks_create():
    if not _user():
        return redirect(url_for("auth.login"))
    business_id = safe_int(request.form.get("business_id")) or getattr(g, "active_business_id", 0)
    if not business_id or not _can_access(business_id):
        flash("Access denied.", "err")
        return redirect(url_for("integrations.integrations_index"))

    url = (request.form.get("url") or "").strip()
    description = (request.form.get("description") or "").strip() or None
    selected = request.form.getlist("events")
    events = "all" if (not selected or "all" in selected) else ",".join(selected)

    if not webhooks.is_safe_url(url):
        flash("That URL isn't allowed. Use a public https:// endpoint "
              "(internal/private addresses are blocked for security).", "err")
        return redirect(url_for("webhooks.webhooks_index", business_id=business_id))

    result = webhooks.create_endpoint(business_id, url, events, description)
    # Show the signing secret once.
    session["_new_webhook_secret"] = result["secret"]
    flash("Webhook endpoint added. Copy your signing secret now — it won't be shown again.", "ok")
    return redirect(url_for("webhooks.webhooks_index", business_id=business_id))


@bp.post("/integrations/webhooks/<int:endpoint_id>/delete")
def webhooks_delete(endpoint_id):
    if not _user():
        return redirect(url_for("auth.login"))
    business_id = safe_int(request.form.get("business_id")) or getattr(g, "active_business_id", 0)
    if not business_id or not _can_access(business_id):
        flash("Access denied.", "err")
        return redirect(url_for("integrations.integrations_index"))
    if webhooks.delete_endpoint(business_id, endpoint_id):
        flash("Webhook endpoint removed.", "ok")
    return redirect(url_for("webhooks.webhooks_index", business_id=business_id))


@bp.post("/integrations/webhooks/<int:endpoint_id>/test")
def webhooks_test(endpoint_id):
    if not _user():
        return redirect(url_for("auth.login"))
    business_id = safe_int(request.form.get("business_id")) or getattr(g, "active_business_id", 0)
    if not business_id or not _can_access(business_id):
        flash("Access denied.", "err")
        return redirect(url_for("integrations.integrations_index"))
    if webhooks.send_test_event(business_id, endpoint_id):
        flash("Test event queued — it'll be delivered within ~15 seconds.", "ok")
    else:
        flash("Couldn't queue a test for that endpoint.", "err")
    return redirect(url_for("webhooks.webhooks_index", business_id=business_id))
