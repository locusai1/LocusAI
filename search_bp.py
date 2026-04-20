# search_bp.py — Global search across customers, appointments, KB, businesses
from flask import Blueprint, render_template, request, session, redirect, url_for, g
from core.db import get_conn

bp = Blueprint("search", __name__)

def _need_login():
    return session.get("user") is None


@bp.route("/search")
def search_index():
    if _need_login():
        return redirect(url_for("auth.login"))

    q = (request.args.get("q") or "").strip()
    businesses = []
    appts = []
    customers = []
    kb_entries = []

    if q and len(q) >= 2:
        like = f"%{q.lower()}%"
        business_id = getattr(g, "active_business_id", None)

        with get_conn() as con:
            # Businesses (admin sees all, owner sees theirs)
            user = session.get("user", {})
            if user.get("role") == "admin":
                businesses = con.execute("""
                    SELECT * FROM businesses
                    WHERE (lower(name) LIKE ? OR lower(slug) LIKE ?) AND archived = 0
                    ORDER BY id DESC LIMIT 20
                """, (like, like)).fetchall()
            elif business_id:
                businesses = con.execute("""
                    SELECT * FROM businesses
                    WHERE id = ? AND (lower(name) LIKE ? OR lower(slug) LIKE ?) AND archived = 0
                    LIMIT 5
                """, (business_id, like, like)).fetchall()

            # Appointments — scoped to active business if set
            appt_query = """
                SELECT a.*, b.name AS business_name
                FROM appointments a
                JOIN businesses b ON b.id = a.business_id
                WHERE (lower(a.customer_name) LIKE ? OR lower(a.phone) LIKE ? OR lower(a.service) LIKE ?)
            """
            appt_params = [like, like, like]
            if business_id:
                appt_query += " AND a.business_id = ?"
                appt_params.append(business_id)
            appt_query += " ORDER BY a.id DESC LIMIT 50"
            appts = con.execute(appt_query, appt_params).fetchall()

            # Customers — scoped to active business
            if business_id:
                customers = con.execute("""
                    SELECT id, name, email, phone, total_appointments, created_at
                    FROM customers
                    WHERE business_id = ?
                      AND (lower(name) LIKE ? OR lower(email) LIKE ? OR lower(phone) LIKE ?)
                    ORDER BY total_appointments DESC LIMIT 30
                """, (business_id, like, like, like)).fetchall()

            # KB entries — use FTS5 if available, fallback to LIKE
            if business_id:
                try:
                    kb_entries = con.execute("""
                        SELECT k.id, k.question, k.answer, k.tags
                        FROM kb_entries k
                        WHERE k.business_id = ?
                          AND (lower(k.question) LIKE ? OR lower(k.answer) LIKE ? OR lower(k.tags) LIKE ?)
                        ORDER BY k.id DESC LIMIT 10
                    """, (business_id, like, like, like)).fetchall()
                except Exception:
                    pass

    return render_template(
        "search.html",
        q=q,
        businesses=businesses,
        appts=appts,
        customers=customers,
        kb_entries=kb_entries,
    )
