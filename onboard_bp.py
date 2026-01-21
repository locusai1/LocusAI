# onboard_bp.py — Create new businesses via UI
# Production-grade with proper validation and error handling

import logging
import sqlite3
from typing import Optional

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from core.db import get_conn, init_db, create_business
from core.validators import slugify, validate_name, validate_slug, validate_email, safe_int

logger = logging.getLogger(__name__)

bp = Blueprint("onboard", __name__)


def _logged_in() -> bool:
    """Check if user is logged in."""
    return session.get("user") is not None


def _is_admin() -> bool:
    """Check if current user is admin."""
    user = session.get("user")
    return user and user.get("role") == "admin"


@bp.route("/business/new", methods=["GET", "POST"])
def business_new():
    """Create a new business."""
    if not _logged_in():
        return redirect(url_for("auth.login"))

    # Only admins can create new businesses
    if not _is_admin():
        flash("Only administrators can create new businesses.", "err")
        return redirect(url_for("dashboard"))

    init_db()

    if request.method == "POST":
        # Extract form data
        name = (request.form.get("name") or "").strip()
        slug = (request.form.get("slug") or "").strip()
        hours = (request.form.get("hours") or "").strip()
        address = (request.form.get("address") or "").strip()
        services = (request.form.get("services") or "").strip()
        tone = (request.form.get("tone") or "").strip()
        esc_phone = (request.form.get("escalation_phone") or "").strip()
        esc_email = (request.form.get("escalation_email") or "").strip()
        retention = request.form.get("data_retention_days") or ""

        # Validation
        errors = []

        # Validate name
        name_valid, name_result = validate_name(name, "Business name", min_length=2, max_length=100)
        if not name_valid:
            errors.append(name_result)
        else:
            name = name_result

        # Generate slug from name if not provided
        if not slug:
            slug = slugify(name)

        # Validate slug
        slug_valid, slug_result = validate_slug(slug)
        if not slug_valid:
            errors.append(slug_result)
        else:
            slug = slug_result

        # Validate escalation email if provided
        if esc_email:
            email_valid, email_result = validate_email(esc_email)
            if not email_valid:
                errors.append(f"Escalation email: {email_result}")
            else:
                esc_email = email_result

        # Validate retention days
        rdays = None
        if retention:
            rdays = safe_int(retention, default=365, min_val=30, max_val=3650)

        if errors:
            for err in errors:
                flash(err, "err")
            return render_template("onboard.html", form=request.form, business=None)

        # Check for duplicate slug
        with get_conn() as con:
            existing = con.execute(
                "SELECT id FROM businesses WHERE slug = ?", (slug,)
            ).fetchone()
            if existing:
                flash(f"A business with slug '{slug}' already exists.", "err")
                return render_template("onboard.html", form=request.form, business=None)

        # Create the business
        try:
            new_id = create_business(
                name=name,
                slug=slug,
                hours=hours or None,
                address=address or None,
                services=services or None,
                tone=tone or None,
                escalation_phone=esc_phone or None,
                escalation_email=esc_email or None,
                data_retention_days=rdays
            )

            if new_id:
                logger.info(f"Business {new_id} ({name}) created by user {session.get('user', {}).get('id')}")
                flash("Business created successfully.", "ok")
                return redirect(url_for("edit_business", business_id=new_id))
            else:
                flash("Failed to create business. Please try again.", "err")

        except sqlite3.IntegrityError:
            flash("Name or slug already exists. Please choose a unique value.", "err")
        except Exception as e:
            logger.exception(f"Error creating business: {e}")
            flash("An error occurred while creating the business.", "err")

        return render_template("onboard.html", form=request.form, business=None)

    return render_template("onboard.html", form={}, business=None)
