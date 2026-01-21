# search_bp.py — global search across businesses & appointments
from flask import Blueprint, render_template, request, session, redirect, url_for
from core.db import get_conn, list_businesses

bp = Blueprint("search", __name__)

def _need_login(): return session.get("user") is None

@bp.route("/search")
def search_index():
    if _need_login(): return redirect(url_for("auth.login"))
    q=(request.args.get("q") or "").strip()
    businesses=[]; appts=[]
    if q:
        like=f"%{q.lower()}%"
        with get_conn() as con:
            businesses = con.execute("""
              SELECT * FROM businesses
              WHERE lower(name) LIKE ? OR lower(slug) LIKE ?
              ORDER BY id DESC LIMIT 50
            """,(like, like)).fetchall()
            appts = con.execute("""
              SELECT a.*, b.name AS business_name
              FROM appointments a
              JOIN businesses b ON b.id=a.business_id
              WHERE lower(a.customer_name) LIKE ? OR lower(a.phone) LIKE ? OR lower(a.service) LIKE ?
              ORDER BY a.id DESC LIMIT 100
            """,(like, like, like)).fetchall()
    return render_template("search.html", q=q, businesses=businesses, appts=appts)
