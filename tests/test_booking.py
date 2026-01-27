import sqlite3, os
from core.db import init_db, get_conn, create_session, get_business_by_id

# Use the booking helper after imports so providers can lazy-load
from core.booking import maybe_commit_booking

def test_booking_commit_basic():
    init_db()
    # Ensure a business exists
    with get_conn() as con:
        con.execute("INSERT OR IGNORE INTO businesses(name,slug) VALUES('Test Clinic','test_clinic')")
        row = con.execute("SELECT id FROM businesses WHERE slug='test_clinic'").fetchone()
        bid = row["id"]

        # Seed a Checkup service (30m) and Mon-Fri hours 09:00–18:00
        con.execute("INSERT OR IGNORE INTO services(business_id,name,duration_min,price,active) VALUES(?,?,?,?,1)",
                    (bid, 'Checkup', 30, '£75'))
        # Seed all weekdays (0..6). 0=Mon
        for w in range(0,7):
            if w <= 4:  # Mon-Fri open
                con.execute("""INSERT OR IGNORE INTO business_hours(business_id,weekday,open_time,close_time,closed)
                               VALUES(?,?,?,?,0)""", (bid, w, '09:00','18:00'))
            elif w == 5:  # Sat 10-14
                con.execute("""INSERT OR IGNORE INTO business_hours(business_id,weekday,open_time,close_time,closed)
                               VALUES(?,?,?,?,0)""", (bid, w, '10:00','14:00'))
            else:  # Sun closed
                con.execute("""INSERT OR IGNORE INTO business_hours(business_id,weekday,open_time,close_time,closed)
                               VALUES(?,?,?,?,1)""", (bid, w, None, None))

    session_id = create_session(bid)
    business = get_business_by_id(bid)

    # Choose a Monday in the future (2025-10-20 is a Monday)
    reply = "<BOOKING>{\"name\":\"Tester\",\"phone\":\"07000 000000\",\"service\":\"Checkup\",\"datetime\":\"2025-10-20 10:00\"}</BOOKING>"

    clean, committed = maybe_commit_booking(reply, business, session_id)
    assert committed is True, f"Expected booking commit, got text: {clean}"

    with get_conn() as con:
        row = con.execute("""SELECT customer_name, phone, service, start_at, status, external_provider_key
                             FROM appointments WHERE business_id=?
                             ORDER BY id DESC LIMIT 1""", (bid,)).fetchone()
        assert row is not None
        assert row["customer_name"] == "Tester"
        assert row["service"].lower().startswith("checkup")
        assert row["status"] in ("pending","confirmed")
        assert row["start_at"] is not None
        # provider_key should default to local
        assert (row["external_provider_key"] or "local") == "local"
