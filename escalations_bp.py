# escalations_bp.py — Escalation management routes
# Production-grade escalation dashboard for human handoff

from typing import Optional
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, g
from core.db import get_business_by_id, get_conn
from core.escalation import (
    get_pending_escalations,
    get_all_escalations,
    get_escalation,
    update_escalation_status
)
import logging

logger = logging.getLogger(__name__)

escalations_bp = Blueprint("escalations", __name__)


# =============================================================================
# Authentication Helpers
# =============================================================================

def _user() -> Optional[dict]:
    """Get the current user from session."""
    return session.get("user")


def _need_login():
    """Redirect to login if not authenticated."""
    if _user() is None:
        flash("Please log in to continue.", "err")
        return redirect(url_for("auth.login"))
    return None


def _owner_can_access(business_id: int) -> bool:
    """Check if current user can access the given business."""
    user = _user()
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    with get_conn() as con:
        row = con.execute(
            "SELECT 1 FROM business_users WHERE user_id=? AND business_id=?",
            (user["id"], business_id)
        ).fetchone()
        return row is not None


# =============================================================================
# Template Filters
# =============================================================================

@escalations_bp.app_template_filter('priority_badge')
def priority_badge_filter(priority: str) -> str:
    """Return Tailwind classes for priority badge."""
    badges = {
        'urgent': 'bg-red-100 text-red-800 border-red-200',
        'high': 'bg-orange-100 text-orange-800 border-orange-200',
        'normal': 'bg-blue-100 text-blue-800 border-blue-200',
        'low': 'bg-gray-100 text-gray-600 border-gray-200',
    }
    return badges.get(priority, badges['normal'])


@escalations_bp.app_template_filter('status_badge')
def status_badge_filter(status: str) -> str:
    """Return Tailwind classes for status badge."""
    badges = {
        'pending': 'bg-yellow-100 text-yellow-800 border-yellow-200',
        'acknowledged': 'bg-blue-100 text-blue-800 border-blue-200',
        'resolved': 'bg-green-100 text-green-800 border-green-200',
    }
    return badges.get(status, badges['pending'])


# =============================================================================
# Main Routes
# =============================================================================

@escalations_bp.route("/escalations")
def escalations_index():
    """Show escalations dashboard."""
    redir = _need_login()
    if redir:
        return redir

    business_id = getattr(g, 'active_business_id', None)
    if not business_id:
        flash("Please select a business first.", "err")
        return redirect(url_for("dashboard"))

    # Explicit authorization check (defense in depth)
    if not _owner_can_access(business_id):
        flash("Access denied.", "err")
        return redirect(url_for("dashboard"))

    business = get_business_by_id(business_id)
    if not business:
        flash("Business not found.", "err")
        return redirect(url_for("dashboard"))

    # Get filter from query params
    status_filter = request.args.get("status", "pending")
    valid_statuses = ("all", "pending", "acknowledged", "resolved")
    if status_filter not in valid_statuses:
        status_filter = "pending"

    # Fetch escalations
    if status_filter == "all":
        escalations = get_all_escalations(business_id, status=None, limit=100)
    else:
        escalations = get_all_escalations(business_id, status=status_filter, limit=100)

    # Count by status for tabs
    all_escalations = get_all_escalations(business_id, status=None, limit=500)
    counts = {
        "pending": sum(1 for e in all_escalations if e.get("status") == "pending"),
        "acknowledged": sum(1 for e in all_escalations if e.get("status") == "acknowledged"),
        "resolved": sum(1 for e in all_escalations if e.get("status") == "resolved"),
        "all": len(all_escalations)
    }

    return render_template(
        "escalations.html",
        escalations=escalations,
        status_filter=status_filter,
        counts=counts,
        business=business
    )


@escalations_bp.route("/escalations/<int:escalation_id>")
def escalation_detail(escalation_id: int):
    """View single escalation detail."""
    redir = _need_login()
    if redir:
        return redir

    business_id = getattr(g, 'active_business_id', None)
    if not business_id:
        flash("Please select a business first.", "err")
        return redirect(url_for("dashboard"))

    # Explicit authorization check (defense in depth)
    if not _owner_can_access(business_id):
        flash("Access denied.", "err")
        return redirect(url_for("dashboard"))

    escalation = get_escalation(escalation_id)
    if not escalation:
        flash("Escalation not found.", "err")
        return redirect(url_for("escalations.escalations_index"))

    if escalation.get("business_id") != business_id:
        flash("Access denied.", "err")
        return redirect(url_for("escalations.escalations_index"))

    business = get_business_by_id(business_id)

    return render_template(
        "escalation_detail.html",
        escalation=escalation,
        business=business
    )


@escalations_bp.route("/escalations/<int:escalation_id>/acknowledge", methods=["POST"])
def acknowledge_escalation(escalation_id: int):
    """Mark escalation as acknowledged."""
    redir = _need_login()
    if redir:
        return redir

    business_id = getattr(g, 'active_business_id', None)

    escalation = get_escalation(escalation_id)
    if not escalation or escalation.get("business_id") != business_id:
        flash("Escalation not found.", "err")
        return redirect(url_for("escalations.escalations_index"))

    if update_escalation_status(escalation_id, "acknowledged"):
        flash("Escalation acknowledged.", "ok")
    else:
        flash("Failed to update escalation.", "err")

    return redirect(url_for("escalations.escalation_detail", escalation_id=escalation_id))


@escalations_bp.route("/escalations/<int:escalation_id>/resolve", methods=["POST"])
def resolve_escalation(escalation_id: int):
    """Mark escalation as resolved."""
    redir = _need_login()
    if redir:
        return redir

    business_id = getattr(g, 'active_business_id', None)
    user_email = g.user.get("email", "staff") if hasattr(g, "user") and g.user else "staff"

    escalation = get_escalation(escalation_id)
    if not escalation or escalation.get("business_id") != business_id:
        flash("Escalation not found.", "err")
        return redirect(url_for("escalations.escalations_index"))

    resolution_notes = request.form.get("resolution_notes", "").strip()

    if update_escalation_status(
        escalation_id,
        "resolved",
        resolved_by=user_email,
        resolution_notes=resolution_notes or "Resolved"
    ):
        flash("Escalation resolved.", "ok")
    else:
        flash("Failed to resolve escalation.", "err")

    return redirect(url_for("escalations.escalations_index"))


# =============================================================================
# API Routes
# =============================================================================

@escalations_bp.route("/api/escalations/pending")
def api_pending_escalations():
    """Get pending escalations as JSON (for notifications/polling)."""
    if _user() is None:
        return jsonify({"error": "Unauthorized"}), 401

    business_id = getattr(g, 'active_business_id', None)
    if not business_id:
        return jsonify({"error": "No business selected"}), 400

    # Explicit authorization check (defense in depth)
    if not _owner_can_access(business_id):
        return jsonify({"error": "Access denied"}), 403

    escalations = get_pending_escalations(business_id, limit=20)
    return jsonify({
        "count": len(escalations),
        "escalations": escalations
    })


@escalations_bp.route("/api/escalations/<int:escalation_id>/status", methods=["POST"])
def api_update_status(escalation_id: int):
    """Update escalation status via API."""
    if _user() is None:
        return jsonify({"error": "Unauthorized"}), 401

    business_id = getattr(g, 'active_business_id', None)

    # Explicit authorization check (defense in depth)
    if not _owner_can_access(business_id):
        return jsonify({"error": "Access denied"}), 403

    escalation = get_escalation(escalation_id)
    if not escalation or escalation.get("business_id") != business_id:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json() or {}
    new_status = data.get("status")

    if new_status not in ("pending", "acknowledged", "resolved"):
        return jsonify({"error": "Invalid status"}), 400

    if update_escalation_status(
        escalation_id,
        new_status,
        resolved_by=data.get("resolved_by"),
        resolution_notes=data.get("resolution_notes")
    ):
        return jsonify({"success": True, "status": new_status})
    else:
        return jsonify({"error": "Update failed"}), 500
