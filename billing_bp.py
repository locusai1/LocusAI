# billing_bp.py — Stripe billing routes for LocusAI
#
# Routes:
#   GET  /billing                      pricing + manage page
#   POST /billing/checkout/<plan_key>  start Stripe Checkout
#   GET  /billing/success              post-checkout landing
#   GET  /billing/cancel               checkout abandoned
#   POST /billing/portal               open Stripe Customer Portal
#   POST /api/billing/webhook          Stripe webhook (CSRF-exempt via /api/ prefix)
#
# Degrades gracefully: when Stripe isn't configured, the page still shows the
# plans but the action buttons explain that billing isn't live yet.

import logging

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from core import billing
from core.settings import APP_BASE_URL

logger = logging.getLogger(__name__)

bp = Blueprint("billing", __name__)


def _current_user():
    return session.get("user")


@bp.route("/billing")
def billing_home():
    user = _current_user()
    if not user:
        return redirect(url_for("auth.login"))

    sub = billing.get_subscription(user["id"])
    active = billing.has_active_subscription(user["id"])
    current_key = billing.current_plan_key(user["id"]) if active else None

    return render_template(
        "billing.html",
        plans=billing.plan_list(),
        subscription=sub,
        is_active=active,
        current_plan_key=current_key,
        billing_configured=billing.is_configured(),
        current_plan=billing.plan(current_key) if current_key else None,
    )


@bp.post("/billing/checkout/<plan_key>")
def checkout(plan_key):
    user = _current_user()
    if not user:
        return redirect(url_for("auth.login"))

    if not billing.plan(plan_key):
        flash("Unknown plan selected.", "err")
        return redirect(url_for("billing.billing_home"))

    if not billing.is_configured():
        flash(
            "Billing isn't live yet — Stripe keys haven't been configured. "
            "Your trial continues in the meantime.",
            "err",
        )
        return redirect(url_for("billing.billing_home"))

    success_url = (
        APP_BASE_URL.rstrip("/") + url_for("billing.success") + "?session_id={CHECKOUT_SESSION_ID}"
    )
    cancel_url = APP_BASE_URL.rstrip("/") + url_for("billing.cancel")
    checkout_url = billing.create_checkout_session(user, plan_key, success_url, cancel_url)

    if not checkout_url:
        flash("Could not start checkout. Please try again or contact support.", "err")
        return redirect(url_for("billing.billing_home"))
    return redirect(checkout_url, code=303)


@bp.route("/billing/success")
def success():
    user = _current_user()
    if not user:
        return redirect(url_for("auth.login"))
    flash(
        "🎉 Welcome aboard! Your subscription is active. It may take a few seconds to appear here.",
        "ok",
    )
    return redirect(url_for("billing.billing_home"))


@bp.route("/billing/cancel")
def cancel():
    if not _current_user():
        return redirect(url_for("auth.login"))
    flash("Checkout cancelled — no charge was made.", "err")
    return redirect(url_for("billing.billing_home"))


@bp.post("/billing/portal")
def portal():
    user = _current_user()
    if not user:
        return redirect(url_for("auth.login"))
    return_url = APP_BASE_URL.rstrip("/") + url_for("billing.billing_home")
    portal_url = billing.create_billing_portal_session(user["id"], return_url)
    if not portal_url:
        flash("Couldn't open the billing portal. Do you have an active subscription?", "err")
        return redirect(url_for("billing.billing_home"))
    return redirect(portal_url, code=303)


@bp.post("/api/billing/webhook")
def webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    event = billing.verify_webhook(payload, sig)
    if event is None:
        # Either not configured or bad signature — 400 so Stripe retries only on real errors.
        return jsonify({"error": "invalid signature or billing not configured"}), 400
    try:
        billing.apply_event(event)
    except Exception:
        logger.exception("Error applying Stripe webhook event")
        return jsonify({"error": "processing error"}), 500
    return jsonify({"received": True}), 200
