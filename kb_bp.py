# kb_bp.py — Knowledge Base management (RBAC-ready)
import re
import csv
import io
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from core.db import get_conn, list_businesses
from core.authz import user_can_access_business

bp = Blueprint("kb", __name__)


def _sanitize_fts5_query(q: str) -> str:
    """
    Sanitize input for FTS5 MATCH to prevent query injection.
    Escapes special FTS5 operators by wrapping the query in double quotes.
    """
    if not q:
        return ""
    # Escape double quotes by doubling them
    escaped = q.replace('"', '""')
    # Wrap in double quotes to treat as a literal phrase
    return f'"{escaped}"'

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
                    # Sanitize query to prevent FTS5 injection
                    safe_q = _sanitize_fts5_query(q)
                    entries = con.execute("""
                      SELECT e.id, e.question, e.answer, e.tags, e.active, e.updated_at
                      FROM kb_entries_fts f
                      JOIN kb_entries e ON e.id=f.rowid
                      WHERE e.business_id=? AND e.active IN (0,1) AND f MATCH ?
                      ORDER BY e.updated_at DESC LIMIT 200;
                    """,(business_id, safe_q)).fetchall()
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

@bp.route("/kb/import/<int:business_id>", methods=["POST"])
def kb_import(business_id: int):
    """Bulk import KB entries from pasted CSV data."""
    if not _logged_in():
        return redirect(url_for("auth.login"))
    if not _can_access(business_id):
        flash("Access denied.", "err")
        return redirect(url_for("kb.kb_index"))

    csv_data = (request.form.get("csv_data") or "").strip()
    if not csv_data:
        flash("No CSV data provided.", "err")
        return redirect(url_for("kb.kb_index", business_id=business_id))

    try:
        reader = csv.DictReader(io.StringIO(csv_data))
        # Normalize field names to lowercase stripped
        imported = 0
        errors = 0
        with get_conn() as con:
            for row in reader:
                row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
                question = row.get("question", "")
                answer = row.get("answer", "")
                tags = row.get("tags", "")
                if not question or not answer:
                    errors += 1
                    continue
                con.execute("""
                    INSERT INTO kb_entries (business_id, question, answer, tags, active, updated_at)
                    VALUES (?, ?, ?, ?, 1, datetime('now', 'localtime'))
                """, (business_id, question, answer, tags))
                imported += 1

        if imported:
            flash(f"Imported {imported} KB entr{'y' if imported == 1 else 'ies'}" +
                  (f" ({errors} skipped due to missing fields)" if errors else "") + ".", "ok")
        else:
            flash("No entries imported. Check your CSV format — columns must be: question, answer, tags.", "err")
    except Exception as e:
        flash(f"Import failed: {e}", "err")

    return redirect(url_for("kb.kb_index", business_id=business_id))


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
