# core/booking.py — detect + commit AI-suggested bookings
from __future__ import annotations
import json, re, logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict
from core.db import get_conn, create_appointment
from core.integrations import get_business_provider, get_business_provider_key

logger = logging.getLogger(__name__)

BOOKING_TAG = re.compile(r"<BOOKING>\s*(\{.*?\})\s*</BOOKING>", re.DOTALL)

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
    with get_conn() as con:
        create_appointment(con,
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
            customer_id=customer_id
        )

    # Build confirmation text
    confirm = f"\n\n✅ Booking saved for **{svc_name or 'selected service'}** at **{chosen_slot}**"
    if name: confirm += f" under **{name}**"
    if phone: confirm += f" ({phone})"
    if external_id: confirm += f". Ref: {external_id}"
    confirm += "."

    # Remove the <BOOKING> tag from the visible reply (optional)
    clean_text = BOOKING_TAG.sub("", text).strip()
    return (clean_text + confirm).strip(), True
