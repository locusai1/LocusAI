# core/feedback.py — owner thumbs up/down on handled conversations.
# A 👎 with a note is the strongest tuning signal there is: it tells you exactly
# which calls the AI got wrong, so they can be reviewed and fed back into the
# prompt / knowledge base. Every rated call makes the next one better.

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from core.db import get_conn

logger = logging.getLogger(__name__)


def record_feedback(
    business_id: int,
    rating: str,
    *,
    voice_call_id: Optional[int] = None,
    session_id: Optional[int] = None,
    note: Optional[str] = None,
    created_by: Optional[int] = None,
) -> bool:
    """Upsert a rating for one call or chat session. Re-rating overwrites."""
    if rating not in ("up", "down"):
        return False
    if not voice_call_id and not session_id:
        return False

    key_col = "voice_call_id" if voice_call_id else "session_id"
    key_val = voice_call_id or session_id
    with get_conn() as con:
        con.execute(
            f"""
            INSERT INTO conversation_feedback (business_id, {key_col}, rating, note, created_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT({key_col}) DO UPDATE SET
                rating=excluded.rating, note=excluded.note, created_at=CURRENT_TIMESTAMP
            """,
            (business_id, key_val, rating, (note or "").strip() or None, created_by),
        )
        con.commit()
    return True


def feedback_summary(business_id: int, *, days: int = 30) -> Dict:
    """Counts + recent 👎 (with notes) for review — the tuning queue."""
    with get_conn() as con:
        counts = con.execute(
            """
            SELECT
                COUNT(CASE WHEN rating='up' THEN 1 END) AS up,
                COUNT(CASE WHEN rating='down' THEN 1 END) AS down
            FROM conversation_feedback
            WHERE business_id = ? AND date(created_at) >= date('now', ?)
            """,
            (business_id, f"-{int(days)} days"),
        ).fetchone()
        downs = con.execute(
            """
            SELECT voice_call_id, session_id, note, created_at
            FROM conversation_feedback
            WHERE business_id = ? AND rating = 'down'
            ORDER BY created_at DESC LIMIT 20
            """,
            (business_id,),
        ).fetchall()

    up, down = counts["up"] or 0, counts["down"] or 0
    total = up + down
    return {
        "up": up,
        "down": down,
        "total": total,
        "satisfaction": round(up / total * 100, 1) if total else None,
        "needs_review": [dict(r) for r in downs],
    }


def get_ratings(business_id: int, *, voice_call_ids: List[int] = None) -> Dict[int, str]:
    """Map voice_call_id -> rating, for rendering current state in the UI."""
    if not voice_call_ids:
        return {}
    placeholders = ",".join("?" for _ in voice_call_ids)
    with get_conn() as con:
        rows = con.execute(
            f"SELECT voice_call_id, rating FROM conversation_feedback "
            f"WHERE business_id = ? AND voice_call_id IN ({placeholders})",
            (business_id, *voice_call_ids),
        ).fetchall()
    return {r["voice_call_id"]: r["rating"] for r in rows if r["voice_call_id"]}
