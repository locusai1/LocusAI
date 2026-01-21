# services_bp.py — Manage services, hours, closures, availability
# Production-grade with proper validation and error handling

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, List

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from core.db import get_conn, list_businesses
from core.authz import user_can_access_business
from core.validators import safe_int, validate_name, validate_date

logger = logging.getLogger(__name__)

bp = Blueprint("services", __name__)


# ============================================================================
# Authentication & Authorization Helpers
# ============================================================================

def _user() -> Optional[dict]:
    """Get the current user from session."""
    return session.get("user")


def _need_login() -> bool:
    """Check if login is required."""
    return _user() is None


def _can_access(bid: int) -> bool:
    """Check if current user can access the given business."""
    return user_can_access_business(_user(), bid)


# ============================================================================
# Services Routes
# ============================================================================

@bp.route("/services", methods=["GET"])
def services_index():
    """List services for a business."""
    if _need_login():
        return redirect(url_for("auth.login"))

    bid = safe_int(request.args.get("business_id"))
    businesses = list_businesses(limit=500)
    services = []

    if bid:
        with get_conn() as con:
            services = con.execute(
                "SELECT * FROM services WHERE business_id=? ORDER BY active DESC, name",
                (bid,)
            ).fetchall()

    return render_template(
        "services.html",
        businesses=businesses,
        business_id=bid,
        services=services
    )


@bp.route("/services/new", methods=["POST"])
def services_new():
    """Create or update a service."""
    if _need_login():
        return redirect(url_for("auth.login"))

    bid = safe_int(request.form.get("business_id"))
    if not _can_access(bid):
        flash("Access denied.", "err")
        return redirect(url_for("services.services_index"))

    name = (request.form.get("name") or "").strip()
    dur = safe_int(request.form.get("duration_min"), 30, min_val=5, max_val=480)
    price = (request.form.get("price") or "").strip()
    active = 1 if request.form.get("active") == "on" else 0

    # Validation
    if not bid:
        flash("Business is required.", "err")
        return redirect(url_for("services.services_index"))

    name_valid, name_result = validate_name(name, "Service name", min_length=1, max_length=100)
    if not name_valid:
        flash(name_result, "err")
        return redirect(url_for("services.services_index", business_id=bid))

    with get_conn() as con:
        con.execute("""
            INSERT INTO services(business_id, name, duration_min, price, active, updated_at)
            VALUES(?, ?, ?, ?, ?, datetime('now', 'localtime'))
            ON CONFLICT(business_id, name) DO UPDATE SET
                duration_min=excluded.duration_min,
                price=excluded.price,
                active=excluded.active,
                updated_at=excluded.updated_at
        """, (bid, name, dur, price or None, active))
        con.commit()

    logger.info(f"Service '{name}' saved for business {bid}")
    flash("Service saved.", "ok")
    return redirect(url_for("services.services_index", business_id=bid))


@bp.route("/services/<int:sid>/delete", methods=["POST"])
def services_delete(sid: int):
    """Delete a service."""
    if _need_login():
        return redirect(url_for("auth.login"))

    with get_conn() as con:
        row = con.execute("SELECT business_id FROM services WHERE id=?", (sid,)).fetchone()
        if not row:
            flash("Service not found.", "err")
            return redirect(url_for("services.services_index"))

        bid = row["business_id"]
        if not _can_access(bid):
            flash("Access denied.", "err")
            return redirect(url_for("services.services_index"))

        con.execute("DELETE FROM services WHERE id=?", (sid,))
        con.commit()

    logger.info(f"Service {sid} deleted from business {bid}")
    flash("Service deleted.", "ok")
    return redirect(url_for("services.services_index", business_id=bid))


# ============================================================================
# Business Hours Routes
# ============================================================================

@bp.route("/hours", methods=["GET", "POST"])
def hours_index():
    """View and update business hours."""
    if _need_login():
        return redirect(url_for("auth.login"))

    bid = safe_int(request.values.get("business_id"))

    if request.method == "POST":
        if not _can_access(bid):
            flash("Access denied.", "err")
            return redirect(url_for("services.hours_index"))

        with get_conn() as con:
            for weekday in range(7):
                closed = 1 if request.form.get(f"closed_{weekday}") == "on" else 0
                open_t = request.form.get(f"open_{weekday}") or None
                close_t = request.form.get(f"close_{weekday}") or None

                # Validate time format
                if open_t and not _is_valid_time(open_t):
                    open_t = None
                if close_t and not _is_valid_time(close_t):
                    close_t = None

                con.execute("""
                    INSERT INTO business_hours(business_id, weekday, open_time, close_time, closed)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(business_id, weekday)
                    DO UPDATE SET open_time=excluded.open_time, close_time=excluded.close_time, closed=excluded.closed
                """, (bid, weekday, open_t, close_t, closed))
            con.commit()

        logger.info(f"Hours updated for business {bid}")
        flash("Hours updated.", "ok")
        return redirect(url_for("services.hours_index", business_id=bid))

    # GET request
    businesses = list_businesses(limit=500)
    hours = []

    if bid:
        with get_conn() as con:
            rows = con.execute(
                "SELECT weekday, open_time, close_time, closed FROM business_hours WHERE business_id=? ORDER BY weekday",
                (bid,)
            ).fetchall()

        hours_map = {r["weekday"]: r for r in rows}
        hours = [
            hours_map.get(w, {"weekday": w, "open_time": None, "close_time": None, "closed": 1})
            for w in range(7)
        ]

    return render_template("hours.html", businesses=businesses, business_id=bid, hours=hours)


def _is_valid_time(time_str: str) -> bool:
    """Check if a string is a valid HH:MM time."""
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            return False
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and 0 <= m <= 59
    except (ValueError, AttributeError):
        return False


# ============================================================================
# Closures Routes
# ============================================================================

@bp.route("/closures", methods=["GET", "POST"])
def closures_index():
    """View and manage business closures."""
    if _need_login():
        return redirect(url_for("auth.login"))

    bid = safe_int(request.values.get("business_id"))

    if request.method == "POST":
        if not _can_access(bid):
            flash("Access denied.", "err")
            return redirect(url_for("services.closures_index"))

        date_str = (request.form.get("date") or "").strip()
        reason = (request.form.get("reason") or "").strip()

        # Validate date
        date_valid, parsed_date = validate_date(date_str)
        if not date_valid or not bid:
            flash("Valid business and date are required.", "err")
            return redirect(url_for("services.closures_index", business_id=bid))

        with get_conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO closures(business_id, date, reason) VALUES(?, ?, ?)",
                (bid, date_str, reason or None)
            )
            con.commit()

        logger.info(f"Closure added for business {bid} on {date_str}")
        flash("Closure saved.", "ok")
        return redirect(url_for("services.closures_index", business_id=bid))

    # GET request
    businesses = list_businesses(limit=500)
    rows = []

    if bid:
        with get_conn() as con:
            rows = con.execute(
                "SELECT id, date, reason FROM closures WHERE business_id=? ORDER BY date DESC",
                (bid,)
            ).fetchall()

    return render_template("closures.html", businesses=businesses, business_id=bid, closures=rows)


@bp.route("/closures/<int:cid>/delete", methods=["POST"])
def closures_delete(cid: int):
    """Delete a closure."""
    if _need_login():
        return redirect(url_for("auth.login"))

    with get_conn() as con:
        row = con.execute("SELECT business_id FROM closures WHERE id=?", (cid,)).fetchone()
        if not row:
            flash("Closure not found.", "err")
            return redirect(url_for("services.closures_index"))

        bid = row["business_id"]
        if not _can_access(bid):
            flash("Access denied.", "err")
            return redirect(url_for("services.closures_index"))

        con.execute("DELETE FROM closures WHERE id=?", (cid,))
        con.commit()

    logger.info(f"Closure {cid} deleted from business {bid}")
    flash("Closure deleted.", "ok")
    return redirect(url_for("services.closures_index", business_id=bid))


# ============================================================================
# Availability Helpers
# ============================================================================

def _parse_hhmm(time_str: str) -> Optional[Tuple[int, int]]:
    """Parse HH:MM string to (hour, minute) tuple."""
    try:
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])
    except (ValueError, AttributeError, IndexError):
        return None


def _get_day_hours(con, bid: int, dt: datetime) -> Optional[Tuple[str, str]]:
    """Get business hours for a specific day."""
    weekday = dt.weekday()
    row = con.execute(
        "SELECT open_time, close_time, closed FROM business_hours WHERE business_id=? AND weekday=?",
        (bid, weekday)
    ).fetchone()

    if not row or row["closed"]:
        return None
    if not (row["open_time"] and row["close_time"]):
        return None

    return row["open_time"], row["close_time"]


def _is_closure(con, bid: int, dt: datetime) -> bool:
    """Check if a date is a closure."""
    date_str = dt.strftime("%Y-%m-%d")
    row = con.execute("SELECT 1 FROM closures WHERE business_id=? AND date=?", (bid, date_str)).fetchone()
    return bool(row)


def _get_appointments_on(con, bid: int, date_str: str) -> List:
    """Get all appointments for a date."""
    return con.execute("""
        SELECT id, COALESCE(start_at, created_at) AS start_at, service, session_id
        FROM appointments
        WHERE business_id=? AND date(COALESCE(start_at, created_at))=date(?)
        ORDER BY start_at
    """, (bid, date_str)).fetchall()


def _slots_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Check if two time slots overlap."""
    return not (a_end <= b_start or b_end <= a_start)


def _parse_appointment_time(time_str: str) -> Optional[datetime]:
    """Parse an appointment time string."""
    if not time_str:
        return None

    # Try common formats
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue

    # Try ISO format
    try:
        return datetime.fromisoformat(time_str.replace("Z", ""))
    except ValueError:
        return None


# ============================================================================
# Availability Route
# ============================================================================

@bp.route("/availability")
def availability():
    """Show available time slots for a service on a date."""
    if _need_login():
        return redirect(url_for("auth.login"))

    bid = safe_int(request.args.get("business_id"))
    service_id = safe_int(request.args.get("service_id"))
    date_str = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")

    businesses = list_businesses(limit=500)
    services = []
    slots = []
    chosen = None

    if bid:
        with get_conn() as con:
            services = con.execute(
                "SELECT * FROM services WHERE business_id=? AND active=1 ORDER BY name",
                (bid,)
            ).fetchall()

            if service_id:
                chosen = con.execute(
                    "SELECT * FROM services WHERE id=? AND business_id=?",
                    (service_id, bid)
                ).fetchone()

                if chosen:
                    # Parse date
                    try:
                        day = datetime.strptime(date_str, "%Y-%m-%d")
                    except ValueError:
                        day = datetime.now()
                        date_str = day.strftime("%Y-%m-%d")

                    # Check if closed
                    if not _is_closure(con, bid, day):
                        day_hours = _get_day_hours(con, bid, day)
                        if day_hours:
                            h1 = _parse_hhmm(day_hours[0])
                            h2 = _parse_hhmm(day_hours[1])

                            if h1 and h2:
                                start = day.replace(hour=h1[0], minute=h1[1], second=0, microsecond=0)
                                end = day.replace(hour=h2[0], minute=h2[1], second=0, microsecond=0)

                                # Get existing appointments
                                appts = _get_appointments_on(con, bid, date_str)
                                busy = []

                                for appt in appts:
                                    appt_start = _parse_appointment_time(appt["start_at"])
                                    if not appt_start:
                                        continue

                                    # Get duration
                                    dur = 30
                                    if appt["service"]:
                                        row = con.execute(
                                            "SELECT duration_min FROM services WHERE business_id=? AND name=?",
                                            (bid, appt["service"])
                                        ).fetchone()
                                        if row:
                                            dur = row["duration_min"]

                                    appt_end = appt_start + timedelta(minutes=dur)
                                    busy.append((appt_start, appt_end))

                                # Generate available slots
                                slot_duration = chosen["duration_min"]
                                step = timedelta(minutes=15)
                                current = start

                                while current + timedelta(minutes=slot_duration) <= end:
                                    slot_start = current
                                    slot_end = current + timedelta(minutes=slot_duration)

                                    # Check for conflicts
                                    has_conflict = any(
                                        _slots_overlap(slot_start, slot_end, b_start, b_end)
                                        for b_start, b_end in busy
                                    )

                                    if not has_conflict:
                                        slots.append(slot_start.strftime("%Y-%m-%d %H:%M"))

                                    current += step

    return render_template(
        "availability.html",
        businesses=businesses,
        business_id=bid,
        services=services,
        service_id=service_id,
        date=date_str,
        chosen=chosen,
        slots=slots
    )
