# core/digest.py — weekly "what your AI receptionist did" performance digest
#
# Aggregates a business's activity over a window and emails the owner a concise
# summary. Dedupes one send per business per ISO week via digest_log.

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core.db import get_conn

logger = logging.getLogger(__name__)


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def build_digest(business_id: int, days: int = 7) -> Dict[str, Any]:
    """Aggregate activity stats for a business over the last `days`."""
    since = _since(days)
    out: Dict[str, Any] = {"days": days}
    with get_conn() as con:

        def n(sql, params=()):
            r = con.execute(sql, params).fetchone()
            return (r[0] if r else 0) or 0

        out["calls"] = n(
            "SELECT COUNT(*) FROM sessions WHERE business_id=? AND channel='voice' AND created_at>=?",
            (business_id, since),
        )
        out["chats"] = n(
            "SELECT COUNT(*) FROM sessions WHERE business_id=? AND channel='web' AND created_at>=?",
            (business_id, since),
        )
        out["sms"] = n(
            "SELECT COUNT(*) FROM sessions WHERE business_id=? AND channel='sms' AND created_at>=?",
            (business_id, since),
        )
        out["bookings"] = n(
            "SELECT COUNT(*) FROM appointments WHERE business_id=? AND created_at>=?",
            (business_id, since),
        )
        out["cancellations"] = n(
            "SELECT COUNT(*) FROM appointments WHERE business_id=? AND status='cancelled' AND created_at>=?",
            (business_id, since),
        )
        out["escalations"] = n(
            "SELECT COUNT(*) FROM escalations WHERE business_id=? AND created_at>=?",
            (business_id, since),
        )

        # Estimated booked revenue: match each booking's service to its price.
        rows = con.execute(
            """
            SELECT a.service, s.price FROM appointments a
            LEFT JOIN services s ON s.business_id=a.business_id AND lower(s.name)=lower(a.service)
            WHERE a.business_id=? AND a.created_at>=? AND a.status IN ('pending','confirmed','completed')
        """,
            (business_id, since),
        ).fetchall()
        revenue = 0.0
        for r in rows:
            try:
                p = str(r["price"] or "").replace("£", "").replace("$", "").replace(",", "").strip()
                revenue += float(p) if p else 0.0
            except (ValueError, TypeError):
                pass
        out["est_revenue"] = round(revenue, 2)

        # Top call intents (voice).
        intents = con.execute(
            """
            SELECT call_intent, COUNT(*) c FROM voice_calls
            WHERE business_id=? AND created_at>=? AND call_intent IS NOT NULL AND call_intent != ''
            GROUP BY call_intent ORDER BY c DESC LIMIT 5
        """,
            (business_id, since),
        ).fetchall()
        out["top_intents"] = [{"intent": r["call_intent"], "count": r["c"]} for r in intents]

        # Containment (calls handled without human transfer).
        total_voice = n(
            "SELECT COUNT(*) FROM voice_calls WHERE business_id=? AND created_at>=?",
            (business_id, since),
        )
        contained = n(
            "SELECT COUNT(*) FROM voice_calls WHERE business_id=? AND created_at>=? AND containment=1",
            (business_id, since),
        )
        out["containment_rate"] = round(contained * 100 / total_voice) if total_voice else None

    out["total_conversations"] = out["calls"] + out["chats"] + out["sms"]
    return out


def render_digest_text(business_name: str, stats: Dict[str, Any]) -> str:
    """Plain-text digest body."""
    lines = [
        f"Here's what your AI receptionist handled for {business_name} "
        f"over the last {stats['days']} days:",
        "",
        f"  • Conversations:   {stats['total_conversations']}  "
        f"({stats['calls']} calls, {stats['chats']} web chats, {stats['sms']} SMS)",
        f"  • Appointments booked: {stats['bookings']}",
    ]
    if stats.get("cancellations"):
        lines.append(f"  • Cancellations:   {stats['cancellations']}")
    if stats.get("est_revenue"):
        lines.append(f"  • Est. booked revenue: £{stats['est_revenue']:.0f}")
    if stats.get("containment_rate") is not None:
        lines.append(f"  • Calls handled without a human: {stats['containment_rate']}%")
    lines.append(f"  • Escalations to your team: {stats['escalations']}")

    if stats.get("top_intents"):
        lines += ["", "Top reasons people got in touch:"]
        for it in stats["top_intents"]:
            lines.append(f"  • {it['intent']} ({it['count']})")

    lines += [
        "",
        "Your AI receptionist is working around the clock so you don't have to.",
        "Log in to your dashboard for full details.",
        "",
        "— LocusAI",
    ]
    return "\n".join(lines)


def _digest_enabled(business: Dict[str, Any]) -> bool:
    raw = business.get("settings_json")
    if not raw:
        return True  # opted-in by default
    try:
        return bool(json.loads(raw).get("weekly_digest_enabled", True))
    except (ValueError, TypeError):
        return True


def _owner_email(business_id: int) -> Optional[str]:
    with get_conn() as con:
        r = con.execute(
            """
            SELECT u.email FROM users u
            JOIN business_users bu ON bu.user_id=u.id
            WHERE bu.business_id=? AND u.email IS NOT NULL
            ORDER BY u.id LIMIT 1
        """,
            (business_id,),
        ).fetchone()
    return r["email"] if r else None


def send_digest(business_id: int, *, force: bool = False) -> bool:
    """Build + email a digest for one business. Returns True if sent.
    Skips when opted out, no owner email, or (unless force) no activity."""
    with get_conn() as con:
        biz = con.execute(
            "SELECT * FROM businesses WHERE id=? AND archived=0", (business_id,)
        ).fetchone()
    if not biz:
        return False
    biz = dict(biz)
    if not _digest_enabled(biz):
        return False
    email = _owner_email(business_id)
    if not email:
        return False

    stats = build_digest(business_id)
    if not force and stats["total_conversations"] == 0 and stats["bookings"] == 0:
        return False  # nothing worth emailing

    body = render_digest_text(biz["name"], stats)
    subject = f"Your weekly LocusAI summary — {biz['name']}"
    try:
        from core.mailer import send_email

        return bool(send_email(email, subject, body))
    except Exception as e:
        logger.warning(f"Digest send failed for business {business_id}: {e}")
        return False


def _week_start() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()  # Monday


def send_weekly_digests() -> int:
    """Send digests to all eligible businesses, once per ISO week (deduped).
    Safe to call repeatedly; returns the number sent this invocation."""
    period = _week_start()
    sent = 0
    with get_conn() as con:
        biz_ids = [
            r["id"] for r in con.execute("SELECT id FROM businesses WHERE archived=0").fetchall()
        ]
    for bid in biz_ids:
        with get_conn() as con:
            already = con.execute(
                "SELECT 1 FROM digest_log WHERE business_id=? AND period_start=?", (bid, period)
            ).fetchone()
        if already:
            continue
        if send_digest(bid):
            with get_conn() as con:
                try:
                    con.execute(
                        "INSERT OR IGNORE INTO digest_log (business_id, period_start) VALUES (?, ?)",
                        (bid, period),
                    )
                    con.commit()
                except Exception:
                    pass
            sent += 1
    return sent
