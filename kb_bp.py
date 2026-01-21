# kb_bp.py — Knowledge Base management (RBAC-ready)
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from core.db import get_conn, list_businesses
from core.authz import user_can_access_business

bp = Blueprint("kb", __name__)

def _logged_in():
    return session.get("user") is not None

def _user():
    return session.get("user")

def _can_access(bid):
    return user_can_access_business(_user(), bid)

def _int(x, default=0):
    try: return int(x)
    except: return default

@bp.route("/kb")
def kb_index():
    if not _logged_in():
        return redirect(url_for("auth.login"))

    business_id = _int(request.args.get("business_id", "0"))
    q = (request.args.get("q") or "").strip()
    businesses = list_businesses(limit=500)
    entries = []
    if business_id:
        with get_conn() as con:
            if q:
                try:
                    entries = con.execute("""
                      SELECT e.id, e.question, e.answer, e.tags, e.active, e.updated_at
                      FROM kb_entries_fts f
                      JOIN kb_entries e ON e.id=f.rowid
                      WHERE e.business_id=? AND e.active IN (0,1) AND f MATCH ?
                      ORDER BY e.updated_at DESC LIMIT 200;
                    """,(business_id, q)).fetchall()
                except Exception:
                    entries = con.execute("""
                      SELECT id, question, answer, tags, active, updated_at
                      FROM kb_entries
                      WHERE business_id=? AND (question LIKE '%'||?||'%' OR answer LIKE '%'||?||'%')
                      ORDER BY updated_at DESC LIMIT 200;
                    """,(business_id, q, q)).fetchall()
            else:
                entries = con.execute("""
                  SELECT id, question, answer, tags, active, updated_at
                  FROM kb_entries WHERE business_id=? ORDER BY updated_at DESC LIMIT 200;
                """,(business_id,)).fetchall()
    return render_template("kb_list.html", businesses=businesses, business_id=business_id, q=q, entries=entries)

@bp.route("/kb/new", methods=["GET","POST"])
def kb_new():
    if not _logged_in():
        return redirect(url_for("auth.login"))
    business_id = _int(request.values.get("business_id", "0"))
    if request.method == "POST":
        if not _can_access(business_id):
            flash("Access denied.", "err")
            return redirect(url_for("kb.kb_index"))
        question = (request.form.get("question") or "").strip()
        answer   = (request.form.get("answer") or "").strip()
        tags     = (request.form.get("tags") or "").strip()
        active   = 1 if (request.form.get("active") == "on") else 0
        if not business_id or not question or not answer:
            flash("Business, question and answer are required.", "err")
            return redirect(url_for("kb.kb_new", business_id=business_id))
        with get_conn() as con:
            cur = con.cursor()
            cur.execute("""
              INSERT INTO kb_entries(business_id,question,answer,tags,active,updated_at)
              VALUES(?,?,?,?,?,datetime('now','localtime'));
            """, (business_id,question,answer,tags,active))
        flash("KB entry created.", "ok")
        return redirect(url_for("kb.kb_index", business_id=business_id))
    businesses = list_businesses(limit=500)
    return render_template("kb_edit.html", mode="new", businesses=businesses, entry=None, business_id=business_id)

@bp.route("/kb/<int:entry_id>/edit", methods=["GET","POST"])
def kb_edit(entry_id:int):
    if not _logged_in():
        return redirect(url_for("auth.login"))
    with get_conn() as con:
        entry = con.execute("SELECT * FROM kb_entries WHERE id=?", (entry_id,)).fetchone()
    if not entry:
        flash("KB entry not found.", "err")
        return redirect(url_for("kb.kb_index"))
    if not _can_access(entry["business_id"]):
        flash("Access denied.", "err")
        return redirect(url_for("kb.kb_index"))
    if request.method == "POST":
        business_id = _int(request.form.get("business_id", entry["business_id"]))
        question = (request.form.get("question") or "").strip()
        answer   = (request.form.get("answer") or "").strip()
        tags     = (request.form.get("tags") or "").strip()
        active   = 1 if (request.form.get("active") == "on") else 0
        if not business_id or not question or not answer:
            flash("Business, question and answer are required.", "err")
            return redirect(url_for("kb.kb_edit", entry_id=entry_id))
        with get_conn() as con:
            con.execute("""
              UPDATE kb_entries
              SET business_id=?, question=?, answer=?, tags=?, active=?, updated_at=datetime('now','localtime')
              WHERE id=?;
            """,(business_id,question,answer,tags,active,entry_id))
        flash("KB entry updated.", "ok")
        return redirect(url_for("kb.kb_index", business_id=business_id))
    businesses = list_businesses(limit=500)
    return render_template("kb_edit.html", mode="edit", businesses=businesses, entry=entry, business_id=entry["business_id"])

@bp.route("/kb/<int:entry_id>/delete", methods=["POST"])
def kb_delete(entry_id:int):
    if not _logged_in():
        return redirect(url_for("auth.login"))
    with get_conn() as con:
        row = con.execute("SELECT business_id FROM kb_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            flash("Entry not found.", "err")
            return redirect(url_for("kb.kb_index"))
        bid = row["business_id"]
        if not _can_access(bid):
            flash("Access denied.", "err")
            return redirect(url_for("kb.kb_index"))
        con.execute("DELETE FROM kb_entries WHERE id=?", (entry_id,))
    flash("KB entry deleted.", "ok")
    return redirect(url_for("kb.kb_index", business_id=bid))
