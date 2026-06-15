# core/semantic_kb.py — meaning-based knowledge base search via embeddings.
#
# Upgrades KB retrieval from keyword matching (FTS5) to *semantic* matching:
# "can I bring my dog?" finds a "Do you allow pets?" entry even with no shared
# words. Embeddings are stored per kb_entry in the kb_embeddings table; search
# embeds the query and ranks by cosine similarity.
#
# Fully degradable: with no OpenAI key (or no embeddings yet) semantic_search
# returns [] and callers fall back to FTS. Indexing happens on KB write and a
# background backfill catches any entries that predate this feature.

import json
import logging
import math
import threading
from typing import Dict, List, Optional

from core.db import get_conn, transaction

logger = logging.getLogger(__name__)

EMBED_MODEL = "text-embedding-3-small"
MIN_SCORE = 0.30  # ignore weak matches so we don't inject irrelevant snippets

# Businesses we've already kicked a backfill for this process (avoid repeats).
_backfilled: set = set()
_backfill_lock = threading.Lock()


def is_available() -> bool:
    from core.settings import OPENAI_API_KEY

    return bool(OPENAI_API_KEY)


def embed_text(text: str) -> Optional[List[float]]:
    """Return an embedding vector for `text`, or None if unavailable/failed."""
    if not text or not is_available():
        return None
    try:
        from core.ai import client

        resp = client.embeddings.create(model=EMBED_MODEL, input=text[:8000])
        return list(resp.data[0].embedding)
    except Exception as e:
        logger.info("embed_text failed: %s", e)
        return None


def _entry_text(question: str, answer: str) -> str:
    return f"Q: {question or ''}\nA: {answer or ''}".strip()


def index_entry(kb_entry_id: int, business_id: int, question: str, answer: str) -> bool:
    """Compute + store the embedding for one KB entry (upsert). Best-effort."""
    vec = embed_text(_entry_text(question, answer))
    if vec is None:
        return False
    try:
        with transaction() as con:
            con.execute(
                """INSERT INTO kb_embeddings (kb_entry_id, business_id, vector, model, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(kb_entry_id) DO UPDATE SET
                       vector=excluded.vector, model=excluded.model, updated_at=datetime('now')""",
                (kb_entry_id, business_id, json.dumps(vec), EMBED_MODEL),
            )
        return True
    except Exception as e:
        logger.warning("index_entry failed for %s: %s", kb_entry_id, e)
        return False


def index_entry_async(kb_entry_id: int, business_id: int, question: str, answer: str) -> None:
    """Fire-and-forget indexing so KB writes don't block on the embedding call."""
    threading.Thread(
        target=index_entry,
        args=(kb_entry_id, business_id, question, answer),
        daemon=True,
    ).start()


def remove_entry(kb_entry_id: int) -> None:
    try:
        with transaction() as con:
            con.execute("DELETE FROM kb_embeddings WHERE kb_entry_id=?", (kb_entry_id,))
    except Exception:
        pass


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def backfill_pending(business_id: Optional[int] = None, limit: int = 100) -> int:
    """Embed active KB entries that don't yet have an embedding. Returns count."""
    if not is_available():
        return 0
    with get_conn() as con:
        params: list = []
        scope = ""
        if business_id is not None:
            scope = "AND e.business_id = ?"
            params.append(business_id)
        rows = con.execute(
            f"""SELECT e.id, e.business_id, e.question, e.answer
                FROM kb_entries e
                LEFT JOIN kb_embeddings k ON k.kb_entry_id = e.id
                WHERE e.active = 1 AND k.kb_entry_id IS NULL {scope}
                LIMIT ?""",
            (*params, limit),
        ).fetchall()
    done = 0
    for r in rows:
        if index_entry(r["id"], r["business_id"], r["question"], r["answer"]):
            done += 1
    if done:
        logger.info("Semantic KB backfill embedded %d entries", done)
    return done


def _maybe_kick_backfill(business_id: int) -> None:
    """Once per process per business, backfill missing embeddings in the background."""
    with _backfill_lock:
        if business_id in _backfilled:
            return
        _backfilled.add(business_id)
    threading.Thread(target=backfill_pending, args=(business_id,), daemon=True).start()


def semantic_search(query: str, business_id: int, limit: int = 5) -> List[Dict]:
    """Rank active KB entries by semantic similarity to `query`.

    Returns [] when embeddings/key are unavailable so callers fall back to FTS."""
    if not (query and business_id) or not is_available():
        return []
    qvec = embed_text(query)
    if qvec is None:
        return []

    with get_conn() as con:
        rows = con.execute(
            """SELECT e.id, e.question, e.answer, e.tags, k.vector
               FROM kb_embeddings k
               JOIN kb_entries e ON e.id = k.kb_entry_id
               WHERE k.business_id = ? AND e.active = 1""",
            (business_id,),
        ).fetchall()

    if not rows:
        # Nothing indexed yet — index in the background for next time, fall back now.
        _maybe_kick_backfill(business_id)
        return []

    scored = []
    for r in rows:
        try:
            vec = json.loads(r["vector"])
        except (ValueError, TypeError):
            continue
        score = _cosine(qvec, vec)
        if score >= MIN_SCORE:
            scored.append(
                {
                    "id": r["id"],
                    "question": r["question"],
                    "answer": r["answer"],
                    "tags": r["tags"],
                    "score": round(score, 4),
                }
            )
    scored.sort(key=lambda d: d["score"], reverse=True)

    # Opportunistically backfill any unindexed entries for this business.
    _maybe_kick_backfill(business_id)
    return scored[:limit]
