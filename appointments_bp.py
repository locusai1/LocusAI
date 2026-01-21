# appointments_bp.py — Appointment management with CSV export, ICS, and email
# Production-grade with proper validation, error handling, and security

import logging
from datetime import datetime
from typing import Optional

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response

from core.db import get_conn, list_businesses, create_appointment
from core.integrations import get_business_provider
from core.ics import make_ics
from core.mailer import send_email
from core.validators import (
    safe_int, validate_email, validate_phone, validate_name,
    validate_datetime, format_datetime, csv_escape, build_csv_row
)

logger = logging.getLogger(__name__)

bp = Blueprint("appointments", __name__)


# ============================================================================
# Authentication & Authorization Helpers
# ============================================================================

def _user() -> Optional[dict]:
    """Get the current user from session."""
    return session.get("user")


def _need_login() -> bool:
    """Check if login is required."""
    return _user() is None


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
    return bool(row)


# ============================================================================
# Routes
# ============================================================================

@bp.route("/appointments")
def appointments_index():
    """List appointments with optional filtering."""
    if _need_login():
        return redirect(url_for("auth.login"))

    business_id = safe_int(request.args.get("business_id"))
    status = (request.args.get("status") or "").strip().lower()

    businesses = list_businesses(limit=500)
    business = next((b for b in businesses if b["id"] == business_id), None) if business_id else None
    appts = []

    if business:
        if not _owner_can_access(business_id):
            flash("Access denied.", "err")
            return redirect(url_for("appointments.appointments_index"))

        with get_conn() as con:
            if status and status in ("pending", "confirmed", "cancelled", "completed"):
                appts = con.execute("""
                    SELECT * FROM appointments
                    WHERE business_id=? AND status=?
                    ORDER BY COALESCE(start_at, created_at) DESC
                    LIMIT 500
                """, (business_id, status)).fetchall()
            else:
                appts = con.execute("""
                    SELECT * FROM appointments
                    WHERE business_id=?
                    ORDER BY COALESCE(start_at, created_at) DESC
                    LIMIT 500
                """, (business_id,)).fetchall()

    return render_template(
        "appointments.html",
        businesses=businesses,
        business=business,
        appts=appts,
        status=status
    )


@bp.route("/appointments/<int:appt_id>/status", methods=["POST"])
def appointments_set_status(appt_id: int):
    """Update appointment status."""
    if _need_login():
        return redirect(url_for("auth.login"))

    new_status = (request.form.get("status") or "").strip().lower()
    return_to = request.form.get("return_to") or url_for("appointments.appointments_index")

    # Validate status
    valid_statuses = ("pending", "confirmed", "cancelled", "completed")
    if new_status not in valid_statuses:
        flash("Invalid status.", "err")
        return redirect(return_to)

    with get_conn() as con:
        row = con.execute("SELECT business_id FROM appointments WHERE id=?", (appt_id,)).fetchone()
        if not row:
            flash("Appointment not found.", "err")
            return redirect(return_to)

        bid = row["business_id"]
        if not _owner_can_access(bid):
            flash("Access denied.", "err")
            return redirect(return_to)

        con.execute("UPDATE appointments SET status=? WHERE id=?", (new_status, appt_id))
        con.commit()

    logger.info(f"Appointment {appt_id} status changed to {new_status} by user {_user().get('id')}")
    flash("Status updated.", "ok")
    return redirect(return_to)


@bp.route("/appointments/export")
def appointments_export_csv():
    """Export appointments to CSV with proper escaping."""
    if _need_login():
        return redirect(url_for("auth.login"))

    business_id = safe_int(request.args.get("business_id"))
    status = (request.args.get("status") or "").strip().lower()

    if not business_id or not _owner_can_access(business_id):
        return Response("Forbidden", status=403, mimetype="text/plain")

    with get_conn() as con:
        if status and status in ("pending", "confirmed", "cancelled", "completed"):
            rows = con.execute("""
                SELECT id, customer_name, phone, service, start_at, status,
                       session_id, created_at, customer_email
                FROM appointments
                WHERE business_id=? AND status=?
                ORDER BY COALESCE(start_at, created_at) DESC
            """, (business_id, status)).fetchall()
        else:
            rows = con.execute("""
                SELECT id, customer_name, phone, service, start_at, status,
                       session_id, created_at, customer_email
                FROM appointments
                WHERE business_id=?
                ORDER BY COALESCE(start_at, created_at) DESC
            """, (business_id,)).fetchall()

    def generate_csv():
        # Header row
        cols = ["id", "customer_name", "phone", "customer_email", "service",
                "start_at", "status", "session_id", "created_at"]
        yield build_csv_row(cols)

        # Data rows with proper escaping
        for r in rows:
            values = [r[c] for c in cols]
            yield build_csv_row(values)

    filename = f"appointments_{business_id}_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        generate_csv(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@bp.route("/appointments/new", methods=["GET", "POST"])
def appointments_new():
    """Create a new appointment with validation."""
    if _need_login():
        return redirect(url_for("auth.login"))

    bid = safe_int(request.values.get("business_id"))
    if not bid:
        flash("Select a business first.", "err")
        return redirect(url_for("appointments.appointments_index"))

    if not _owner_can_access(bid):
        flash("Access denied.", "err")
        return redirect(url_for("appointments.appointments_index"))

    provider = get_business_provider(bid)

    # Load services depending on provider
    services = []
    local_mode = (provider.key == "local")
    if local_mode:
        with get_conn() as con:
            services = con.execute(
                "SELECT id, name, duration_min, price FROM services WHERE business_id=? AND active=1 ORDER BY name",
                (bid,)
            ).fetchall()
    else:
        try:
            services = provider.fetch_services() or []
        except Exception as e:
            logger.error(f"Failed to fetch services from provider: {e}")
            services = []

    # Load slots when service+date picked
    slots = []
    chosen_service_id = request.values.get("service_id")
    date_str = request.values.get("date") or datetime.now().strftime("%Y-%m-%d")

    if chosen_service_id:
        sid_int = safe_int(chosen_service_id)
        if sid_int:
            try:
                slots = provider.fetch_slots(sid_int, date_str) or []
            except Exception as e:
                logger.error(f"Failed to fetch slots: {e}")
                slots = []

    if request.method == "POST":
        # Extract and validate form data
        name = (request.form.get("customer_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        sid = safe_int(request.form.get("service_id"))
        slot = (request.form.get("slot") or "").strip()

        # Validation
        errors = []

        name_valid, name_result = validate_name(name, "Customer name")
        if not name_valid:
            errors.append(name_result)
        else:
            name = name_result

        if phone:
            phone_valid, phone_result = validate_phone(phone)
            if not phone_valid:
                errors.append(phone_result)
            else:
                phone = phone_result

        if email:
            email_valid, email_result = validate_email(email)
            if not email_valid:
                errors.append(email_result)
            else:
                email = email_result

        if not sid:
            errors.append("Service is required")

        if not slot:
            errors.append("Time slot is required")

        # Validate datetime format
        if slot:
            dt_valid, parsed_dt = validate_datetime(slot)
            if not dt_valid:
                errors.append("Invalid time slot format")

        if errors:
            for err in errors:
                flash(err, "err")
            return render_template(
                "appointments_new.html",
                business_id=bid,
                services=services,
                local_mode=local_mode,
                slots=slots,
                date=date_str,
                service_id=sid,
                values=request.form
            )

        # Re-validate slot availability (race condition protection)
        try:
            valid_slots = set(provider.fetch_slots(sid, date_str) or [])
        except Exception as e:
            logger.error(f"Slot validation failed: {e}")
            valid_slots = set()

        if slot not in valid_slots:
            flash("Selected slot is no longer available. Please pick another.", "err")
            return render_template(
                "appointments_new.html",
                business_id=bid,
                services=services,
                local_mode=local_mode,
                slots=list(valid_slots),
                date=date_str,
                service_id=sid,
                values=request.form
            )

        # Get service details
        svc_name = ""
        duration_min = 60
        if local_mode:
            with get_conn() as con:
                row = con.execute(
                    "SELECT name, duration_min FROM services WHERE id=? AND business_id=?",
                    (sid, bid)
                ).fetchone()
            if row:
                svc_name = row["name"]
                duration_min = row["duration_min"]
        else:
            for s in services:
                if s.get("id") == sid:
                    svc_name = s.get("name", "")
                    duration_min = safe_int(s.get("duration_min"), 60, min_val=5, max_val=480)
                    break

        # Create external booking if applicable
        ext_id = None
        try:
            res = provider.create_booking({
                "customer_name": name,
                "phone": phone,
                "email": email,
                "service_id": sid,
                "service_name": svc_name,
                "start_at": slot,
            }) or {}
            ext_id = res.get("external_id")
        except Exception as e:
            logger.warning(f"External booking creation failed (continuing): {e}")
            ext_id = None

        # Save to local database
        appt_id = create_appointment(
            business_id=bid,
            customer_name=name,
            phone=phone,
            customer_email=email,
            service=svc_name,
            start_at=slot,
            status="confirmed",
            external_provider_key=provider.key,
            external_id=ext_id,
            source="owner",
            notes=notes
        )

        if not appt_id:
            flash("Failed to create appointment. Please try again.", "err")
            return render_template(
                "appointments_new.html",
                business_id=bid,
                services=services,
                local_mode=local_mode,
                slots=slots,
                date=date_str,
                service_id=sid,
                values=request.form
            )

        # Generate ICS and send email
        try:
            dt_valid, start_dt = validate_datetime(slot)
            if dt_valid and start_dt:
                business = next((b for b in list_businesses(limit=500) if b["id"] == bid), None)
                address = business.get("address", "") if business else ""
                business_name = business.get("name", "AxisAI") if business else "AxisAI"

                ics = make_ics(
                    summary=f"{svc_name} — {business_name}",
                    description=f"Service: {svc_name}\nCustomer: {name}\nPhone: {phone}",
                    start=start_dt,
                    duration_min=duration_min,
                    location=address
                )

                # Send confirmation email if address provided
                if email:
                    send_email(
                        to_email=email,
                        subject=f"Appointment confirmed — {svc_name}",
                        body=f"Hi {name},\n\nYour appointment for {svc_name} is booked at {format_datetime(start_dt)}.\n\nThanks,\n{business_name}",
                        attachments=[("appointment.ics", "text/calendar", ics)]
                    )
        except Exception as e:
            logger.error(f"Failed to generate ICS or send email: {e}")
            # Don't fail the appointment creation

        logger.info(f"Appointment {appt_id} created by user {_user().get('id')} for business {bid}")
        flash("Appointment created successfully.", "ok")
        return redirect(url_for("appointments.appointments_index", business_id=bid))

    # GET request - show form
    return render_template(
        "appointments_new.html",
        business_id=bid,
        services=services,
        local_mode=local_mode,
        slots=slots,
        date=date_str,
        service_id=safe_int(chosen_service_id),
        values={}
    )


@bp.route("/appointments/<int:appt_id>/ics")
def appointments_ics(appt_id: int):
    """Download ICS calendar file for an appointment."""
    if _need_login():
        return redirect(url_for("auth.login"))

    with get_conn() as con:
        appt = con.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()

    if not appt:
        return Response("Appointment not found", status=404, mimetype="text/plain")

    bid = appt["business_id"]
    if not _owner_can_access(bid):
        return Response("Forbidden", status=403, mimetype="text/plain")

    # Get service duration
    duration = 60
    svc_name = appt["service"] or "Appointment"
    with get_conn() as con:
        row = con.execute(
            "SELECT duration_min FROM services WHERE business_id=? AND name=?",
            (bid, svc_name)
        ).fetchone()
        if row:
            duration = safe_int(row["duration_min"], 60, min_val=5, max_val=480)

    # Parse start time
    dt_valid, start_dt = validate_datetime(appt["start_at"])
    if not dt_valid or not start_dt:
        return Response("Invalid appointment time", status=400, mimetype="text/plain")

    # Get business info
    biz = next((b for b in list_businesses(limit=500) if b["id"] == bid), None)
    address = biz.get("address", "") if biz else ""
    business_name = biz.get("name", "AxisAI") if biz else "AxisAI"

    ics = make_ics(
        summary=f"{svc_name} — {business_name}",
        description=f"Service: {svc_name}\nCustomer: {appt['customer_name']}\nPhone: {appt['phone']}",
        start=start_dt,
        duration_min=min(duration, 480),
        location=address
    )

    filename = f"appointment_{appt_id}.ics"
    return Response(
        ics,
        mimetype="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
