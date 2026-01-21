# chat_bp.py — web chat UI (RBAC-ready) with booking auto-commit
from flask import Blueprint, render_template, request, redirect, url_for, session
from core.db import create_session, get_session_messages, log_message, list_businesses
from core.ai import process_message
from core.booking import maybe_commit_booking

bp = Blueprint("chat", __name__)

def _logged_in():
    return session.get("user") is not None

def _sid_key(bid: int) -> str:
    return f"chat_sid_{bid}"

@bp.route("/chat")
def chat_index():
    if not _logged_in():
        return redirect(url_for("auth.login"))

    try:
        business_id = int(request.args.get("business_id", "0") or 0)
    except ValueError:
        business_id = 0

    businesses = list_businesses(limit=200)
    business = next((b for b in businesses if b["id"] == business_id), None) if business_id else None
    messages = []

    if business:
        sid_key = _sid_key(business_id)
        sid = session.get(sid_key)
        if not sid:
            sid = create_session(business["id"])
            session[sid_key] = sid

        rows = get_session_messages(sid, limit=50)
        messages = [{"role": ("assistant" if r["sender"]=="bot" else "user"), "text": r["text"]}
                    for r in reversed(rows)]

    return render_template("chat.html", businesses=businesses, business=business, messages=messages)

@bp.route("/chat/send", methods=["POST"])
def chat_send():
    if not _logged_in():
        return redirect(url_for("auth.login"))

    business_id = int(request.form.get("business_id", "0") or 0)
    businesses = list_businesses(limit=200)
    business = next((b for b in businesses if b["id"] == business_id), None)
    if not business:
        return redirect(url_for("chat.chat_index"))

    sid_key = _sid_key(business_id)
    sid = session.get(sid_key)
    if not sid:
        sid = create_session(business["id"])
        session[sid_key] = sid

    user_text = (request.form.get("message") or "").strip()
    if user_text:
        log_message(sid, "user", user_text)
        reply = (process_message(user_text, business, {"session_id": sid}) or "").strip()
        # NEW: auto-commit bookings
        reply, _committed = maybe_commit_booking(reply, business, sid)
        log_message(sid, "bot", reply)

    return redirect(url_for("chat.chat_index", business_id=business_id))

@bp.route("/chat/reset", methods=["POST"])
def chat_reset():
    if not _logged_in():
        return redirect(url_for("auth.login"))
    business_id = int(request.form.get("business_id", "0") or 0)
    if business_id:
        sid_key = _sid_key(business_id)
        session.pop(sid_key, None)
    return redirect(url_for("chat.chat_index", business_id=business_id))
