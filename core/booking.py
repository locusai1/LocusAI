# core/booking.py — detect + commit AI-suggested bookings
# Supports both auto-commit (legacy) and confirmation flow (new)
from __future__ import annotations
import json
import re
import logging
import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

from core.db import get_conn, create_appointment
from core.integrations import get_business_provider, get_business_provider_key

# Import reminders module (optional)
try:
    from core.reminders import schedule_reminders_for_appointment
    REMINDERS_AVAILABLE = True
except ImportError:
    REMINDERS_AVAILABLE = False

logger = logging.getLogger(__name__)

BOOKING_TAG = re.compile(r"<BOOKING>\s*(\{.*?\})\s*</BOOKING>", re.DOTALL)

# In-memory store for pending bookings (use Redis in production for multi-instance)
# Structure: {token: {booking_data, business_id, session_id, created_at, slot}}
_PENDING_BOOKINGS: Dict[str, Dict[str, Any]] = {}
PENDING_BOOKING_TTL = 300  # 5 minutes

def _parse_when(s: str) -> Optional[datetime]:
    if not s: return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(s, fmt)
        except: pass
    try:
        return datetime.fromisoformat(s.replace("Z",""))
    except:
        return None

def _find_local_service_id(business_id:int, name:str) -> Optional[int]:
    if not name: return None
    name_norm = name.strip().lower()
    with get_conn() as con:
        # exact match
        row = con.execute("SELECT id FROM services WHERE business_id=? AND lower(name)=?", (business_id, name_norm)).fetchone()
        if row: return int(row["id"])
        # prefix or contains
        row = con.execute("SELECT id,name FROM services WHERE business_id=? ORDER BY name", (business_id,)).fetchall()
    for r in row:
        n = r["name"].strip().lower()
        if n.startswith(name_norm) or name_norm in n:
            return int(r["id"])
    return None

def _pick_slot_near(provider, service_id:Optional[int], date_pref:datetime) -> Optional[str]:
    # try preferred date, else today/tomorrow
    for day in [date_pref, date_pref or datetime.now(), datetime.now(), datetime.now()+timedelta(days=1)]:
        date_str = day.strftime("%Y-%m-%d")
        slots = provider.fetch_slots(service_id, date_str) or []
        if not slots: 
            continue
        if date_pref:
            # choose slot closest to requested time
            target = date_pref
            def dist(s):
                try: return abs((datetime.strptime(s, "%Y-%m-%d %H:%M") - target).total_seconds())
                except: return 10**12
            slots.sort(key=dist)
        return slots[0]
    return None


# ============================================================================
# Real-Time Availability Checking
# ============================================================================

def get_available_slots_for_day(
    business_id: int,
    date_str: str,
    service_name: Optional[str] = None,
    limit: int = 10
) -> list:
    """Get available time slots for a specific day.

    Args:
        business_id: Business ID
        date_str: Date in YYYY-MM-DD format
        service_name: Optional service name to get duration
        limit: Max number of slots to return

    Returns:
        List of available slot strings in "HH:MM" format
    """
    provider = get_business_provider(business_id)
    if not provider:
        return []

    # Get service ID if service name provided
    service_id = None
    if service_name:
        service_id = _find_local_service_id(business_id, service_name)
    else:
        # Get first active service as default
        with get_conn() as con:
            row = con.execute(
                "SELECT id FROM services WHERE business_id = ? AND active = 1 LIMIT 1",
                (business_id,)
            ).fetchone()
            if row:
                service_id = row["id"]

    if not service_id:
        return []

    slots = provider.fetch_slots(service_id, date_str) or []

    # Format for voice (just times, not full datetime)
    formatted = []
    for slot in slots[:limit]:
        try:
            dt = datetime.strptime(slot, "%Y-%m-%d %H:%M")
            formatted.append(dt.strftime("%I:%M %p").lstrip("0"))  # "2:30 PM"
        except:
            formatted.append(slot)

    return formatted


def get_next_available_slots(
    business_id: int,
    service_name: Optional[str] = None,
    num_slots: int = 5,
    days_ahead: int = 7
) -> list:
    """Get the next available slots across multiple days.

    Returns slots in a voice-friendly format like:
    [
        {"day": "Today", "date": "2026-01-27", "times": ["2:30 PM", "3:00 PM"]},
        {"day": "Tomorrow", "date": "2026-01-28", "times": ["10:00 AM", "11:00 AM"]},
    ]
    """
    from datetime import date

    provider = get_business_provider(business_id)
    if not provider:
        return []

    service_id = None
    if service_name:
        service_id = _find_local_service_id(business_id, service_name)
    else:
        with get_conn() as con:
            row = con.execute(
                "SELECT id FROM services WHERE business_id = ? AND active = 1 LIMIT 1",
                (business_id,)
            ).fetchone()
            if row:
                service_id = row["id"]

    if not service_id:
        return []

    today = date.today()
    results = []
    total_slots = 0

    for i in range(days_ahead):
        if total_slots >= num_slots:
            break

        check_date = today + timedelta(days=i)
        date_str = check_date.strftime("%Y-%m-%d")
        slots = provider.fetch_slots(service_id, date_str) or []

        if not slots:
            continue

        # Format day name
        if i == 0:
            day_name = "Today"
        elif i == 1:
            day_name = "Tomorrow"
        else:
            day_name = check_date.strftime("%A")  # "Monday", "Tuesday", etc.

        # Format times
        times = []
        for slot in slots:
            if total_slots >= num_slots:
                break
            try:
                dt = datetime.strptime(slot, "%Y-%m-%d %H:%M")
                times.append(dt.strftime("%I:%M %p").lstrip("0"))
            except:
                times.append(slot.split(" ")[-1] if " " in slot else slot)
            total_slots += 1

        if times:
            results.append({
                "day": day_name,
                "date": date_str,
                "times": times
            })

    return results


def check_time_available(
    business_id: int,
    date_str: str,
    time_str: str,
    service_name: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """Check if a specific time slot is available.

    Args:
        business_id: Business ID
        date_str: Date in YYYY-MM-DD format
        time_str: Time in HH:MM format (24-hour)
        service_name: Optional service name

    Returns:
        (is_available, suggested_alternative or None)
    """
    from core.db import check_slot_available

    # Get service duration
    duration_min = 30  # default
    if service_name:
        service_id = _find_local_service_id(business_id, service_name)
        if service_id:
            with get_conn() as con:
                row = con.execute(
                    "SELECT duration_min FROM services WHERE id = ?",
                    (service_id,)
                ).fetchone()
                if row:
                    duration_min = row["duration_min"]

    # Check availability
    start_at = f"{date_str} {time_str}"
    is_available = check_slot_available(business_id, start_at, duration_min)

    if is_available:
        return True, None

    # Find alternative - get available slots for that day
    slots = get_available_slots_for_day(business_id, date_str, service_name, limit=3)
    if slots:
        return False, slots[0]  # Suggest first available

    return False, None


def format_availability_for_voice(business_id: int, service_name: Optional[str] = None) -> str:
    """Format availability info for inclusion in voice AI prompt.

    Returns a concise string the AI can use to inform callers about availability.
    """
    slots = get_next_available_slots(business_id, service_name, num_slots=6, days_ahead=5)

    if not slots:
        return "No availability information. Ask the caller for their preferred time and let them know you'll check."

    lines = ["Available times:"]
    for slot_info in slots[:3]:  # Max 3 days
        day = slot_info["day"]
        times = ", ".join(slot_info["times"][:3])  # Max 3 times per day
        lines.append(f"  {day}: {times}")

    return "\n".join(lines)


# ============================================================================
# Pending Booking Management (Confirmation Flow)
# ============================================================================

def _generate_booking_token(business_id: int, session_id: int) -> str:
    """Generate a unique token for a pending booking."""
    data = f"{business_id}:{session_id}:{time.time()}:{id(object())}"
    return hashlib.sha256(data.encode()).hexdigest()[:32]


def _cleanup_expired_bookings() -> None:
    """Remove expired pending bookings to prevent memory bloat."""
    now = time.time()
    expired = [
        token for token, data in _PENDING_BOOKINGS.items()
        if now - data.get("created_at", 0) > PENDING_BOOKING_TTL
    ]
    for token in expired:
        del _PENDING_BOOKINGS[token]
        logger.debug(f"Expired pending booking token: {token[:8]}...")


def extract_pending_booking(
    text: str,
    business: Dict,
    session_id: Optional[int]
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Extract booking data from AI response without committing.

    Returns:
        (cleaned_text, pending_booking_data) where pending_booking_data contains:
        - token: Unique token to confirm/cancel this booking
        - customer_name, phone, email, service, datetime: Booking details
        - slot: The actual available slot found
        - expires_at: When this pending booking expires

        If no booking tag found, returns (original_text, None)
    """
    _cleanup_expired_bookings()

    m = BOOKING_TAG.search(text or "")
    if not m:
        return text, None

    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid booking JSON in AI response: {e}")
        clean_text = BOOKING_TAG.sub("", text).strip()
        return clean_text + "\n\n[I tried to create a booking but encountered an issue. Could you please provide your details again?]", None

    # Extract and normalize fields
    name = (payload.get("name") or "").strip() or None
    phone = (payload.get("phone") or "").strip() or None
    email = (payload.get("email") or "").strip() or None
    svc_name = (payload.get("service") or "").strip() or None
    svc_id = payload.get("service_id")
    when_raw = payload.get("datetime") or payload.get("when") or ""
    when_dt = _parse_when(when_raw)
    notes = (payload.get("notes") or "").strip() or None

    bid = int(business["id"])
    provider = get_business_provider(bid)

    # Map service for local provider
    local_service_id = None
    if provider.key == "local":
        if svc_id is not None:
            local_service_id = int(svc_id)
        else:
            local_service_id = _find_local_service_id(bid, svc_name or "")
    else:
        # External providers
        ext_id = None
        try:
            services = provider.fetch_services()
            if svc_id:
                if any(s["id"] == svc_id for s in services):
                    ext_id = svc_id
            elif svc_name:
                nm = svc_name.strip().lower()
                for s in services:
                    if s["name"].strip().lower().startswith(nm) or nm in s["name"].strip().lower():
                        ext_id = s["id"]
                        break
            svc_id = ext_id
        except Exception:
            pass

    # Find available slot
    chosen_slot = _pick_slot_near(
        provider,
        local_service_id if provider.key == "local" else svc_id,
        when_dt or datetime.now()
    )

    if not chosen_slot:
        clean_text = BOOKING_TAG.sub("", text).strip()
        return clean_text + "\n\n[I couldn't find any available slots for that time. Would you like to try a different date or time?]", None

    # Generate token and store pending booking
    token = _generate_booking_token(bid, session_id or 0)
    now = time.time()

    pending_data = {
        "token": token,
        "business_id": bid,
        "session_id": session_id,
        "customer_name": name,
        "phone": phone,
        "email": email,
        "service_name": svc_name,
        "service_id": svc_id,
        "local_service_id": local_service_id,
        "slot": chosen_slot,
        "notes": notes,
        "created_at": now,
        "expires_at": now + PENDING_BOOKING_TTL,
    }

    _PENDING_BOOKINGS[token] = pending_data
    logger.info(f"Created pending booking {token[:8]}... for session {session_id}")

    # Clean the AI response text
    clean_text = BOOKING_TAG.sub("", text).strip()

    # Return data for the widget to display
    return clean_text, {
        "token": token,
        "customer_name": name,
        "phone": phone,
        "email": email,
        "service": svc_name,
        "datetime": chosen_slot,
        "expires_in": PENDING_BOOKING_TTL,
    }


def confirm_pending_booking(token: str) -> Tuple[bool, str, Optional[int]]:
    """
    Confirm and commit a pending booking.

    Args:
        token: The pending booking token

    Returns:
        (success, message, appointment_id)
    """
    _cleanup_expired_bookings()

    if token not in _PENDING_BOOKINGS:
        return False, "Booking has expired or was already processed. Please start a new booking.", None

    pending = _PENDING_BOOKINGS.pop(token)

    # Verify it hasn't expired
    if time.time() > pending.get("expires_at", 0):
        return False, "Booking has expired. Please start a new booking.", None

    bid = pending["business_id"]
    session_id = pending.get("session_id")

    provider = get_business_provider(bid)
    provider_key = get_business_provider_key(bid)

    # Re-verify the slot is still available
    chosen_slot = pending["slot"]
    local_service_id = pending.get("local_service_id")
    svc_id = pending.get("service_id")

    # Create booking on external provider if applicable
    external_id = None
    try:
        result = provider.create_booking({
            "customer_name": pending.get("customer_name"),
            "phone": pending.get("phone"),
            "service_id": local_service_id if provider.key == "local" else svc_id,
            "service_name": pending.get("service_name"),
            "start_at": chosen_slot,
        }) or {}
        external_id = result.get("external_id")
    except Exception as e:
        logger.warning(f"External provider booking failed: {e}")
        external_id = None

    # Find or create customer
    customer_id = None
    name = pending.get("customer_name")
    email = pending.get("email")
    phone = pending.get("phone")

    try:
        from customers_bp import find_or_create_customer
        if name or email or phone:
            customer_id = find_or_create_customer(
                business_id=bid,
                name=name,
                email=email,
                phone=phone,
                source="ai_booking"
            )
            if customer_id:
                logger.info(f"Linked confirmed booking to customer {customer_id}")
    except Exception as e:
        logger.warning(f"Could not create/find customer for booking: {e}")

    # Save to database
    appt_id = None
    with get_conn() as con:
        appt_id = create_appointment(
            business_id=bid,
            customer_name=name or "",
            phone=phone or "",
            customer_email=email,
            service=pending.get("service_name") or "",
            start_at=chosen_slot,
            status="pending",
            session_id=session_id,
            external_provider_key=provider_key,
            external_id=external_id,
            source="ai",
            customer_id=customer_id,
            con=con
        )

    # Schedule reminders
    if appt_id and REMINDERS_AVAILABLE:
        try:
            reminder_ids = schedule_reminders_for_appointment(
                appointment_id=appt_id,
                start_at=chosen_slot,
                customer_email=email,
                customer_phone=phone
            )
            if reminder_ids:
                logger.info(f"Scheduled {len(reminder_ids)} reminders for confirmed booking {appt_id}")
        except Exception as e:
            logger.warning(f"Failed to schedule reminders for booking {appt_id}: {e}")

    # Build confirmation message
    svc_name = pending.get("service_name") or "your appointment"
    confirm_msg = f"Your booking for {svc_name} on {chosen_slot} has been confirmed!"
    if external_id:
        confirm_msg += f" Reference: {external_id}"

    logger.info(f"Confirmed booking {appt_id} from pending token {token[:8]}...")
    return True, confirm_msg, appt_id


def cancel_pending_booking(token: str) -> Tuple[bool, str]:
    """
    Cancel a pending booking (before confirmation).

    Args:
        token: The pending booking token

    Returns:
        (success, message)
    """
    if token in _PENDING_BOOKINGS:
        pending = _PENDING_BOOKINGS.pop(token)
        logger.info(f"Cancelled pending booking {token[:8]}... for session {pending.get('session_id')}")
        return True, "Booking cancelled. Let me know if you'd like to book a different time."

    return False, "No pending booking found to cancel."


def get_pending_booking(token: str) -> Optional[Dict[str, Any]]:
    """Get details of a pending booking by token."""
    _cleanup_expired_bookings()
    return _PENDING_BOOKINGS.get(token)


# ============================================================================
# Legacy Auto-Commit Flow (for backward compatibility)
# ============================================================================

def maybe_commit_booking(text:str, business:Dict, session_id:Optional[int]) -> Tuple[str,bool]:
    """
    Scan text for <BOOKING>{...}</BOOKING>, validate via provider, insert into DB,
    and return (possibly updated_text, committed:bool).
    """
    m = BOOKING_TAG.search(text or "")
    if not m:
        return text, False

    try:
        payload = json.loads(m.group(1))
    except Exception:
        return text + "\n\n[Note: booking details detected but invalid JSON.]", False

    name  = (payload.get("name")  or "").strip() or None
    phone = (payload.get("phone") or "").strip() or None
    svc_name = (payload.get("service") or "").strip() or None
    svc_id   = payload.get("service_id")
    when_raw = payload.get("datetime") or payload.get("when") or ""
    when_dt  = _parse_when(when_raw)

    bid = int(business["id"])
    provider = get_business_provider(bid)
    provider_key = get_business_provider_key(bid)

    # Map service for local provider
    local_service_id = None
    if provider.key == "local":
        if svc_id is not None:
            local_service_id = int(svc_id)
        else:
            local_service_id = _find_local_service_id(bid, svc_name or "")
    else:
        # External providers: expect external ids; if not provided, attempt to match by name
        ext_id = None
        try:
            services = provider.fetch_services()
            if svc_id:
                if any(s["id"] == svc_id for s in services):
                    ext_id = svc_id
            elif svc_name:
                nm = svc_name.strip().lower()
                for s in services:
                    if s["name"].strip().lower().startswith(nm) or nm in s["name"].strip().lower():
                        ext_id = s["id"]; break
            svc_id = ext_id
        except Exception:
            pass

    # Choose an actual free slot
    # For local: pass local_service_id; for external: pass provider's service id
    chosen_slot = _pick_slot_near(provider, local_service_id if provider.key=="local" else svc_id, when_dt or datetime.now())
    if not chosen_slot:
        return text + "\n\n[Note: booking details detected but no free slots found.]", False

    # Create booking on provider (optional) and save locally
    external_id = None
    try:
        result = provider.create_booking({
            "customer_name": name,
            "phone": phone,
            "service_id": local_service_id if provider.key=="local" else svc_id,
            "service_name": svc_name,
            "start_at": chosen_slot,
        }) or {}
        external_id = result.get("external_id")
    except Exception:
        external_id = None

    # Find or create customer
    customer_id = None
    email = (payload.get("email") or "").strip() or None
    try:
        # Import here to avoid circular imports
        from customers_bp import find_or_create_customer
        if name or email or phone:
            customer_id = find_or_create_customer(
                business_id=bid,
                name=name,
                email=email,
                phone=phone,
                source="ai_booking"
            )
            if customer_id:
                logger.info(f"Linked booking to customer {customer_id}")
    except Exception as e:
        logger.warning(f"Could not create/find customer for booking: {e}")

    # Save locally
    appt_id = None
    with get_conn() as con:
        appt_id = create_appointment(
            business_id=bid,
            customer_name=name or "",
            phone=phone or "",
            customer_email=email,
            service=svc_name or (str(svc_id) if svc_id else ""),
            start_at=chosen_slot,
            status="pending",
            session_id=session_id,
            external_provider_key=provider_key,
            external_id=external_id,
            source="ai",
            customer_id=customer_id,
            con=con
        )

    # Schedule reminders for the appointment
    if appt_id and REMINDERS_AVAILABLE:
        try:
            reminder_ids = schedule_reminders_for_appointment(
                appointment_id=appt_id,
                start_at=chosen_slot,
                customer_email=email,
                customer_phone=phone
            )
            if reminder_ids:
                logger.info(f"Scheduled {len(reminder_ids)} reminders for AI booking {appt_id}")
        except Exception as e:
            logger.warning(f"Failed to schedule reminders for AI booking {appt_id}: {e}")

    # Build confirmation text
    confirm = f"\n\n✅ Booking saved for **{svc_name or 'selected service'}** at **{chosen_slot}**"
    if name: confirm += f" under **{name}**"
    if phone: confirm += f" ({phone})"
    if external_id: confirm += f". Ref: {external_id}"
    confirm += "."

    # Remove the <BOOKING> tag from the visible reply (optional)
    clean_text = BOOKING_TAG.sub("", text).strip()
    return (clean_text + confirm).strip(), True
