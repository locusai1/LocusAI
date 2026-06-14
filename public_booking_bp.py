# public_booking_bp.py — public, shareable self-serve booking page at /book/<slug>
#
# No login required. Shows a business's services + real availability and lets a
# customer book a slot directly (race-safe), creating the appointment, customer
# record and reminders. CSRF-protected, rate-limited, fully validated.

import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from core.db import (
    create_appointment_atomic,
    get_business_by_slug,
    get_conn,
)
from core.integrations import get_business_provider, get_business_provider_key
from core.validators import validate_email, validate_name, validate_phone

logger = logging.getLogger(__name__)

bp = Blueprint("public_booking", __name__)

# Simple in-process rate limiter (per IP) — replace with Redis for multi-instance.
_BOOK_HITS = defaultdict(list)
_BOOK_LIMIT = 8  # bookings/slot-lookups
_BOOK_WINDOW = 60  # seconds


def _rate_ok(key: str) -> bool:
    now = time.time()
    hits = [t for t in _BOOK_HITS[key] if now - t < _BOOK_WINDOW]
    hits.append(now)
    _BOOK_HITS[key] = hits
    return len(hits) <= _BOOK_LIMIT


def _active_services(business_id: int):
    with get_conn() as con:
        return [
            dict(r)
            for r in con.execute(
                "SELECT id, name, duration_min, price FROM services "
                "WHERE business_id=? AND active=1 ORDER BY name",
                (business_id,),
            ).fetchall()
        ]


def _get_business_or_404(slug: str):
    biz = get_business_by_slug(slug)
    if not biz or biz.get("archived"):
        abort(404)
    return biz


@bp.route("/book/<slug>")
def book_page(slug):
    biz = _get_business_or_404(slug)
    services = _active_services(biz["id"])
    return render_template(
        "public_booking.html",
        business=biz,
        services=services,
        booked=request.args.get("booked") == "1",
        min_date=date.today().isoformat(),
        max_date=(date.today() + timedelta(days=60)).isoformat(),
    )


@bp.route("/book/<slug>/slots")
def book_slots(slug):
    """JSON: available slots for a service on a date."""
    biz = _get_business_or_404(slug)
    if not _rate_ok(f"slots:{request.remote_addr}"):
        return jsonify({"error": "Too many requests"}), 429

    service_id = request.args.get("service_id", type=int)
    date_str = (request.args.get("date") or "").strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"slots": []})

    # Only allow services that belong to this business.
    services = {s["id"]: s for s in _active_services(biz["id"])}
    if service_id not in services:
        return jsonify({"slots": []})

    provider = get_business_provider(biz["id"])
    raw = provider.fetch_slots(service_id, date_str) or []
    slots = []
    for s in raw:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
            slots.append({"value": s, "label": dt.strftime("%I:%M %p").lstrip("0")})
        except ValueError:
            continue
    return jsonify({"slots": slots})


@bp.post("/book/<slug>")
def book_submit(slug):
    biz = _get_business_or_404(slug)
    if not _rate_ok(f"book:{request.remote_addr}"):
        return render_template(
            "public_booking.html",
            business=biz,
            services=_active_services(biz["id"]),
            error="Too many attempts. Please wait a minute and try again.",
            min_date=date.today().isoformat(),
            max_date=(date.today() + timedelta(days=60)).isoformat(),
        ), 429

    services = {s["id"]: s for s in _active_services(biz["id"])}
    service_id = request.form.get("service_id", type=int)
    slot = (request.form.get("slot") or "").strip()
    name_ok, name = validate_name(request.form.get("name"), "Name")
    phone_raw = (request.form.get("phone") or "").strip()
    phone_ok, phone = validate_phone(phone_raw)
    email_ok, email = validate_email(request.form.get("email"))

    def _err(msg):
        return render_template(
            "public_booking.html",
            business=biz,
            services=list(services.values()),
            error=msg,
            min_date=date.today().isoformat(),
            max_date=(date.today() + timedelta(days=60)).isoformat(),
        ), 400

    if service_id not in services:
        return _err("Please choose a service.")
    if not slot:
        return _err("Please choose an available time.")
    try:
        datetime.strptime(slot, "%Y-%m-%d %H:%M")
    except ValueError:
        return _err("That time slot looks invalid — please pick again.")
    if not name_ok:
        return _err(name)
    if not phone_raw or not phone_ok:
        return _err("A valid phone number is required so we can confirm your booking.")
    if not email_ok:
        return _err(email)

    svc = services[service_id]
    provider_key = get_business_provider_key(biz["id"])

    # Find/create the customer record (best-effort).
    customer_id = None
    try:
        from customers_bp import find_or_create_customer

        customer_id = find_or_create_customer(
            business_id=biz["id"],
            name=name,
            email=email or None,
            phone=phone or phone_raw,
            source="public_booking",
        )
    except Exception as e:
        logger.warning(f"Public booking: customer link failed: {e}")

    appt_id, err = create_appointment_atomic(
        business_id=biz["id"],
        start_at=slot,
        duration_min=svc["duration_min"] or 30,
        customer_name=name,
        phone=phone or phone_raw,
        service=svc["name"],
        status="confirmed",
        source="api",  # public self-serve (table CHECK: ai|owner|api)
        notes="Booked via public booking page",
        customer_email=email or None,
        external_provider_key=provider_key,
        customer_id=customer_id,
    )
    if err or not appt_id:
        return _err(err or "Sorry, that time was just taken. Please choose another.")

    # Schedule reminders (best-effort).
    try:
        from core.reminders import schedule_reminders_for_appointment

        schedule_reminders_for_appointment(
            appt_id, slot, customer_email=email or None, customer_phone=phone or phone_raw
        )
    except Exception as e:
        logger.warning(f"Public booking: reminder scheduling failed: {e}")

    try:
        from core.webhooks import emit_event

        emit_event(
            biz["id"],
            "booking.created",
            {
                "appointment_id": appt_id,
                "service": svc["name"],
                "start_at": slot,
                "customer_name": name,
                "phone": phone or phone_raw,
                "email": email or None,
                "source": "public",
            },
        )
    except Exception:
        pass

    logger.info(f"Public booking {appt_id} for business {biz['id']} via /book/{slug}")
    return redirect(url_for("public_booking.book_page", slug=slug, booked="1"))
