#!/usr/bin/env python
"""Seed a rich, realistic demo business into the database.

Idempotent: keyed on slug — re-running won't create duplicates. Designed to give
the dashboard something alive to look at during the production launch phase
(services, hours, knowledge base, customers, a spread of appointments, and voice
+ widget settings). Links the business to the admin user so it's selectable.

Run inside the Railway container (so it hits the /data volume DB):
    railway ssh python tools/seed_demo_business.py
Optionally pass an owner email to link to:
    railway ssh python tools/seed_demo_business.py founder@locusai.uk
"""

import os
import sys
from datetime import datetime, timedelta

# Allow running as a plain script (python tools/seed_demo_business.py) by putting
# the repo root on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import create_business, ensure_tenant_key, get_conn, init_db  # noqa: E402

SLUG = "aurora-hair"
NAME = "Aurora Hair & Beauty"


def _dt(days: int, hour: int, minute: int = 0) -> str:
    d = datetime.now() + timedelta(days=days)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")


SERVICES = [
    ("Women's Cut & Finish", 45, "£45"),
    ("Men's Cut", 30, "£25"),
    ("Cut & Blow Dry", 45, "£40"),
    ("Full Head Colour", 120, "£85"),
    ("Highlights", 150, "£95"),
    ("Balayage", 180, "£120"),
    ("Blow Dry", 30, "£30"),
]

# weekday: 0=Mon .. 6=Sun
HOURS = [
    (0, None, None, 1),  # Mon closed
    (1, "09:00", "18:00", 0),
    (2, "09:00", "18:00", 0),
    (3, "09:00", "20:00", 0),  # late night Thu
    (4, "09:00", "18:00", 0),
    (5, "09:00", "17:00", 0),  # Sat
    (6, None, None, 1),  # Sun closed
]

KB = [
    (
        "Do you take walk-ins?",
        "We welcome walk-ins when we have availability, but we recommend booking ahead — especially "
        "on Thursdays and Saturdays — so we can guarantee your preferred stylist and time.",
    ),
    (
        "What is your cancellation policy?",
        "We kindly ask for at least 24 hours' notice to cancel or reschedule. Cancellations within "
        "24 hours may be subject to a 50% charge.",
    ),
    (
        "Where are you located and is there parking?",
        "We're at 14 Camden High Street, London NW1. There's paid street parking nearby and the "
        "Camden Town tube station is a 3-minute walk away.",
    ),
    (
        "Do you offer a consultation before colour services?",
        "Yes — all colour and balayage services include a free consultation, and we recommend a patch "
        "test at least 48 hours before your first colour appointment.",
    ),
    (
        "What hair products do you use?",
        "We use Olaplex, Kerastase and Wella Professionals. Most products we use are available to buy "
        "in-salon if you'd like to maintain your look at home.",
    ),
    (
        "Do you sell gift cards?",
        "Yes! Gift cards are available in any amount and can be used for any service or product. Ask "
        "us in-salon or mention it when you book.",
    ),
    (
        "Can I request a specific stylist?",
        "Absolutely. Just let us know who you'd like to see when booking and we'll arrange it around "
        "their availability.",
    ),
]

CUSTOMERS = [
    ("Sarah Mitchell", "sarah.mitchell@example.com", "+447700900111"),
    ("James Patel", "james.patel@example.com", "+447700900222"),
    ("Emma Thompson", "emma.t@example.com", "+447700900333"),
    ("Olivia Bennett", "olivia.bennett@example.com", "+447700900444"),
    ("Daniel Carter", "dan.carter@example.com", "+447700900555"),
    ("Grace Okafor", "grace.okafor@example.com", "+447700900666"),
]

# (customer_index, service, day_offset, hour, status, source)
APPOINTMENTS = [
    (0, "Women's Cut & Finish", 1, 10, "confirmed", "ai"),
    (1, "Men's Cut", 1, 14, "confirmed", "ai"),
    (2, "Balayage", 2, 11, "confirmed", "owner"),
    (3, "Highlights", 3, 13, "pending", "ai"),
    (4, "Cut & Blow Dry", 5, 16, "confirmed", "ai"),
    (5, "Full Head Colour", 6, 10, "confirmed", "ai"),
    (0, "Blow Dry", -7, 11, "completed", "ai"),
    (1, "Men's Cut", -14, 15, "completed", "owner"),
    (2, "Women's Cut & Finish", -3, 12, "cancelled", "ai"),
]


def main(owner_email: str = "founder@locusai.uk") -> None:
    init_db()

    with get_conn() as con:
        existing = con.execute("SELECT id FROM businesses WHERE slug=?", (SLUG,)).fetchone()
    if existing:
        bid = existing["id"]
        print(f"Business '{SLUG}' already exists (id={bid}); skipping creation.")
    else:
        bid = create_business(
            NAME,
            SLUG,
            address="14 Camden High Street, London NW1 0JH",
            tone="Warm, friendly and professional. Upbeat without being pushy.",
            escalation_email=owner_email,
            escalation_phone="+447700900000",
            accent_color="#b8794f",
            data_retention_days=365,
        )
        if not bid:
            print("ERROR: could not create business.")
            return
        print(f"Created business '{NAME}' (id={bid}).")

    ensure_tenant_key(bid)

    with get_conn() as con:
        cur = con.cursor()

        # Services
        for name, dur, price in SERVICES:
            cur.execute(
                """INSERT INTO services (business_id, name, duration_min, price, active)
                   SELECT ?, ?, ?, ?, 1
                   WHERE NOT EXISTS (SELECT 1 FROM services WHERE business_id=? AND name=?)""",
                (bid, name, dur, price, bid, name),
            )

        # Business hours (reset + insert)
        cur.execute("DELETE FROM business_hours WHERE business_id=?", (bid,))
        for wd, open_t, close_t, closed in HOURS:
            cur.execute(
                """INSERT INTO business_hours (business_id, weekday, open_time, close_time, closed)
                   VALUES (?, ?, ?, ?, ?)""",
                (bid, wd, open_t, close_t, closed),
            )

        # Knowledge base
        for q, a in KB:
            cur.execute(
                """INSERT INTO kb_entries (business_id, question, answer, tags, active)
                   SELECT ?, ?, ?, 'faq', 1
                   WHERE NOT EXISTS (SELECT 1 FROM kb_entries WHERE business_id=? AND question=?)""",
                (bid, q, a, bid, q),
            )

        # Customers
        cust_ids = []
        for name, email, phone in CUSTOMERS:
            row = cur.execute(
                "SELECT id FROM customers WHERE business_id=? AND phone=?", (bid, phone)
            ).fetchone()
            if row:
                cust_ids.append(row["id"])
                continue
            cur.execute(
                """INSERT INTO customers (business_id, name, email, phone, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, datetime('now','-30 days'), datetime('now'))""",
                (bid, name, email, phone),
            )
            cust_ids.append(cur.lastrowid)

        # Appointments (only if none exist yet, to stay idempotent)
        existing_appts = cur.execute(
            "SELECT COUNT(*) AS n FROM appointments WHERE business_id=?", (bid,)
        ).fetchone()["n"]
        if existing_appts == 0:
            for ci, service, day, hour, status, source in APPOINTMENTS:
                c_name, c_email, c_phone = CUSTOMERS[ci]
                cur.execute(
                    """INSERT INTO appointments
                       (business_id, customer_name, phone, customer_email, service, start_at,
                        status, customer_id, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        bid,
                        c_name,
                        c_phone,
                        c_email,
                        service,
                        _dt(day, hour),
                        status,
                        cust_ids[ci],
                        source,
                    ),
                )
            print(f"Inserted {len(APPOINTMENTS)} appointments.")
        else:
            print(f"{existing_appts} appointments already present; not adding more.")

        # Voice settings
        cur.execute(
            """INSERT INTO voice_settings
               (business_id, greeting_message, transfer_enabled, transfer_number,
                missed_call_recovery_enabled, after_hours_enabled, recording_enabled, booking_enabled)
               VALUES (?, ?, 1, ?, 1, 1, 1, 1)
               ON CONFLICT(business_id) DO UPDATE SET
                   transfer_enabled=1, transfer_number=excluded.transfer_number,
                   missed_call_recovery_enabled=1""",
            (
                bid,
                "Hello, thanks for calling Aurora Hair & Beauty. Just to let you know, this call may "
                "be recorded for quality purposes. How can I help you today?",
                "+447700900000",
            ),
        )

        # Widget settings
        cur.execute(
            """INSERT INTO widget_settings (business_id, enabled, welcome_message, primary_color)
               VALUES (?, 1, ?, '#b8794f')
               ON CONFLICT(business_id) DO UPDATE SET enabled=1""",
            (
                bid,
                "Hi! 👋 Welcome to Aurora Hair & Beauty. How can I help — booking, prices or hours?",
            ),
        )

        # Link to the owner/admin user so they can select it
        owner = cur.execute("SELECT id FROM users WHERE email=?", (owner_email,)).fetchone()
        if owner:
            cur.execute(
                """INSERT OR IGNORE INTO business_users (user_id, business_id)
                   VALUES (?, ?)""",
                (owner["id"], bid),
            )
            print(f"Linked business to user {owner_email} (id={owner['id']}).")
        else:
            print(f"WARNING: user {owner_email} not found — business not linked to anyone.")

        con.commit()

    # Summary
    with get_conn() as con:
        tk = con.execute("SELECT tenant_key FROM businesses WHERE id=?", (bid,)).fetchone()[
            "tenant_key"
        ]
        ns = con.execute("SELECT COUNT(*) n FROM services WHERE business_id=?", (bid,)).fetchone()[
            "n"
        ]
        nk = con.execute(
            "SELECT COUNT(*) n FROM kb_entries WHERE business_id=?", (bid,)
        ).fetchone()["n"]
        na = con.execute(
            "SELECT COUNT(*) n FROM appointments WHERE business_id=?", (bid,)
        ).fetchone()["n"]
        nc = con.execute("SELECT COUNT(*) n FROM customers WHERE business_id=?", (bid,)).fetchone()[
            "n"
        ]
    print("\n=== Seed complete ===")
    print(f"  Business id : {bid}  ({NAME})")
    print(f"  Services    : {ns}")
    print(f"  KB entries  : {nk}")
    print(f"  Customers   : {nc}")
    print(f"  Appointments: {na}")
    print(f"  Tenant key  : {tk}")


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "founder@locusai.uk"
    main(email)
