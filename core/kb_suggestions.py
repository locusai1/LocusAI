# core/kb_suggestions.py — AI knowledge-gap suggestions
#
# Looks at recent customer questions (web/SMS messages + voice transcripts),
# clusters the recurring ones NOT already covered by the knowledge base, and
# proposes ready-to-add KB entries (question + answer). Owner reviews + adds.
# Degrades gracefully (returns []) when no OpenAI key is configured.

import json
import logging
import re
from typing import Dict, List

from core.db import get_conn
from core.settings import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

_QUESTION_HINT = re.compile(
    r"\?|^(do|does|can|could|are|is|how|what|when|where|why|which|who|will|would|should)\b",
    re.IGNORECASE,
)


def gather_recent_questions(business_id: int, days: int = 30, limit: int = 80) -> List[str]:
    """Recent customer (user) messages + voice caller messages that look like questions."""
    since = f"-{int(days)} days"
    qs: List[str] = []
    with get_conn() as con:
        rows = con.execute(
            """
            SELECT m.text FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE s.business_id = ? AND m.sender = 'user'
              AND m.timestamp >= datetime('now', ?)
            ORDER BY m.timestamp DESC LIMIT ?
        """,
            (business_id, since, limit),
        ).fetchall()
        qs.extend((r["text"] or "").strip() for r in rows)

        vrows = con.execute(
            """
            SELECT caller_message FROM voice_calls
            WHERE business_id = ? AND caller_message IS NOT NULL AND caller_message != ''
              AND created_at >= datetime('now', ?)
            ORDER BY created_at DESC LIMIT ?
        """,
            (business_id, since, limit),
        ).fetchall()
        qs.extend((r["caller_message"] or "").strip() for r in vrows)

    # Keep question-like, de-duplicate, trim.
    seen, out = set(), []
    for q in qs:
        if not q or len(q) < 6 or len(q) > 300:
            continue
        if not _QUESTION_HINT.search(q):
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def existing_questions(business_id: int) -> List[str]:
    with get_conn() as con:
        rows = con.execute(
            "SELECT question FROM kb_entries WHERE business_id=?", (business_id,)
        ).fetchall()
    return [(r["question"] or "").strip().lower() for r in rows]


def is_configured() -> bool:
    return bool(OPENAI_API_KEY)


def _complete(prompt: str) -> str:
    """Single LLM completion returning text. Isolated for easy testing."""
    from core.ai import client

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant that returns only valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def _build_prompt(business_name: str, questions: List[str], existing: List[str]) -> str:
    q_block = "\n".join(f"- {q}" for q in questions[:60])
    e_block = "\n".join(f"- {q}" for q in existing[:60]) or "(none yet)"
    return f"""A business called "{business_name}" uses an AI receptionist. Below are recent
questions real customers asked. Identify the most common/important questions that the
business should have a saved answer for, and that are NOT already covered by the
existing knowledge base.

For each, write a concise, professional draft answer the business can edit. Keep answers
generic and safe — do not invent specific prices, addresses, or policies; instead use a
placeholder like "[add your …]" when a specific detail is needed.

Return ONLY JSON in this exact shape, max 5 items, no commentary:
{{"suggestions": [{{"question": "...", "answer": "..."}}]}}

EXISTING KNOWLEDGE BASE QUESTIONS:
{e_block}

RECENT CUSTOMER QUESTIONS:
{q_block}
"""


def _parse(raw: str) -> List[Dict[str, str]]:
    if not raw:
        return []
    # Strip code fences if present.
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    items = data.get("suggestions") if isinstance(data, dict) else data
    out = []
    for it in items or []:
        q = (it.get("question") or "").strip()
        a = (it.get("answer") or "").strip()
        if q and a:
            out.append({"question": q, "answer": a})
    return out[:5]


def suggest_kb_entries(
    business_id: int, business_name: str = "the business"
) -> List[Dict[str, str]]:
    """Return suggested KB entries, or [] when not configured / not enough data."""
    if not is_configured():
        return []
    questions = gather_recent_questions(business_id)
    if len(questions) < 3:
        return []  # not enough signal to be useful
    existing = set(existing_questions(business_id))
    try:
        raw = _complete(_build_prompt(business_name, questions, list(existing)))
    except Exception as e:
        logger.warning(f"KB suggestion LLM call failed: {e}")
        return []
    suggestions = _parse(raw)
    # Drop anything that essentially duplicates an existing KB question.
    return [s for s in suggestions if s["question"].strip().lower() not in existing]
