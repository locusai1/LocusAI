# core/kb_autolearn.py — self-improving knowledge base.
# When the same question keeps coming up and the KB can't answer it, the AI
# teaches itself: it drafts an answer GROUNDED ONLY in the business's existing
# knowledge (KB entries, services, hours) and saves it. Grounding is the safety
# rail — we never auto-publish invented facts; if the answer can't be derived
# from what the business already told us, we skip it (it still surfaces as a
# manual suggestion via the existing /kb flow).

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from core.db import get_conn

logger = logging.getLogger(__name__)

MIN_FREQUENCY = 3  # distinct conversations that asked it
MAX_NEW_PER_RUN = 3  # cap auto-additions per run
AUTOLEARN_TAG = "auto-learned"
_NOT_ANSWERABLE = "NO_ANSWER"

_QUESTION_HINT = re.compile(
    r"\?|\b(how|what|when|where|why|who|can|do|does|are|is|will|would|could|should|"
    r"price|cost|open|hours|available|book)\b",
    re.I,
)


def _normalize(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (q or "").lower()).strip()


def frequent_unanswered_questions(
    business_id: int, *, days: int = 30, min_frequency: int = MIN_FREQUENCY
) -> List[Dict]:
    """Questions asked across >= min_frequency distinct conversations that the KB
    doesn't already cover. Returns [{question, frequency}] most-frequent first."""
    since = f"-{int(days)} days"
    with get_conn() as con:
        rows = con.execute(
            """
            SELECT m.text AS text, m.session_id AS sid FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE s.business_id = ? AND m.sender = 'user'
              AND m.timestamp >= datetime('now', ?)
            """,
            (business_id, since),
        ).fetchall()
        existing = [
            _normalize(r["question"])
            for r in con.execute(
                "SELECT question FROM kb_entries WHERE business_id=? AND active=1", (business_id,)
            ).fetchall()
        ]

    # Count distinct sessions per normalized question.
    buckets: Dict[str, Dict] = {}
    for r in rows:
        text = (r["text"] or "").strip()
        if len(text) < 6 or len(text) > 300 or not _QUESTION_HINT.search(text):
            continue
        key = _normalize(text)
        if not key:
            continue
        b = buckets.setdefault(key, {"question": text, "sessions": set()})
        b["sessions"].add(r["sid"])

    out = []
    for key, b in buckets.items():
        freq = len(b["sessions"])
        if freq < min_frequency:
            continue
        # Skip if already covered (exact or substring overlap with an existing Q).
        if any(key == e or key in e or e in key for e in existing if e):
            continue
        out.append({"question": b["question"], "frequency": freq})
    out.sort(key=lambda x: x["frequency"], reverse=True)
    return out


def _business_context(business_id: int) -> str:
    """Compact factual context the AI may ground answers in."""
    with get_conn() as con:
        kb = con.execute(
            "SELECT question, answer FROM kb_entries WHERE business_id=? AND active=1 LIMIT 50",
            (business_id,),
        ).fetchall()
        svc = con.execute(
            "SELECT name, duration_min, price FROM services WHERE business_id=? AND active=1",
            (business_id,),
        ).fetchall()
        hrs = con.execute(
            "SELECT weekday, open_time, close_time, closed FROM business_hours WHERE business_id=?",
            (business_id,),
        ).fetchall()

    parts = []
    if kb:
        parts.append(
            "Existing Q&A:\n" + "\n".join(f"- Q: {r['question']} A: {r['answer']}" for r in kb)
        )
    if svc:
        parts.append(
            "Services:\n"
            + "\n".join(f"- {r['name']} ({r['duration_min']} min, price {r['price']})" for r in svc)
        )
    if hrs:
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        lines = []
        for r in hrs:
            wd = days[r["weekday"]] if 0 <= r["weekday"] < 7 else str(r["weekday"])
            lines.append(
                f"- {wd}: {'closed' if r['closed'] else (r['open_time'] or '') + '-' + (r['close_time'] or '')}"
            )
        parts.append("Opening hours:\n" + "\n".join(lines))
    return "\n\n".join(parts)


def _ground_answer(business_name: str, question: str, context: str) -> Optional[str]:
    """Draft an answer using ONLY the supplied context. Returns None if it can't."""
    from core.kb_suggestions import _complete

    if not context.strip():
        return None
    prompt = f"""You are configuring an AI receptionist for "{business_name}".
Answer the customer question below using ONLY the facts in CONTEXT. Do not invent
prices, hours, addresses, or policies. If the context does not contain enough
information to answer accurately, reply with exactly {_NOT_ANSWERABLE}.

Return ONLY JSON: {{"answer": "..."}} (or {{"answer": "{_NOT_ANSWERABLE}"}}).

CONTEXT:
{context}

QUESTION: {question}
"""
    try:
        raw = _complete(prompt)
    except Exception:
        logger.warning("autolearn grounding failed", exc_info=True)
        return None

    import json

    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        ans = (json.loads(m.group(0)).get("answer") or "").strip()
    except json.JSONDecodeError:
        return None
    if not ans or _NOT_ANSWERABLE in ans:
        return None
    return ans


def auto_learn_kb(
    business_id: int,
    business_name: str = "",
    *,
    min_frequency: int = MIN_FREQUENCY,
    max_new: int = MAX_NEW_PER_RUN,
) -> List[Dict]:
    """Find recurring unanswered questions, draft grounded answers, and save them
    as active KB entries. Returns the entries added."""
    from core.kb_suggestions import is_configured

    if not is_configured():
        return []

    candidates = frequent_unanswered_questions(business_id, min_frequency=min_frequency)
    if not candidates:
        return []

    context = _business_context(business_id)
    added: List[Dict] = []
    for cand in candidates:
        if len(added) >= max_new:
            break
        answer = _ground_answer(business_name, cand["question"], context)
        if not answer:
            continue
        with get_conn() as con:
            con.execute(
                "INSERT INTO kb_entries(business_id, question, answer, tags, active, updated_at) "
                "VALUES(?, ?, ?, ?, 1, datetime('now','localtime'))",
                (business_id, cand["question"], answer, AUTOLEARN_TAG),
            )
            con.commit()
        added.append(
            {"question": cand["question"], "answer": answer, "frequency": cand["frequency"]}
        )
        logger.info("Auto-learned KB entry for business %s: %s", business_id, cand["question"])

    return added


def run_autolearn_for_enabled() -> int:
    """Background entry point: auto-learn for every business that opted in.
    Returns total entries added."""
    with get_conn() as con:
        rows = con.execute(
            "SELECT id, name FROM businesses WHERE archived=0 AND kb_autolearn_enabled=1"
        ).fetchall()
    total = 0
    for r in rows:
        try:
            total += len(auto_learn_kb(r["id"], r["name"] or ""))
        except Exception:
            logger.warning("autolearn run failed for business %s", r["id"], exc_info=True)
    return total
