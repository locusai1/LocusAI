# core/kb.py — KB search (FTS + fallback)
from typing import List, Dict
from core.db import get_conn

def search_kb(query: str, business_id: int, limit: int = 5) -> List[Dict]:
    q = (query or "").strip()
    if not q or not business_id:
        return []
    with get_conn() as con:
        # Prefer FTS if available
        try:
            rows = con.execute("""
                SELECT e.id, e.question, e.answer, e.tags
                FROM kb_entries_fts f
                JOIN kb_entries e ON e.id = f.rowid
                WHERE e.active=1 AND e.business_id=?
                  AND f MATCH ?
                LIMIT ?;
            """, (business_id, q, limit)).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except Exception:
            pass

        # Fallback: simple LIKE match on question+answer
        rows = con.execute("""
            SELECT id, question, answer, tags
            FROM kb_entries
            WHERE active=1 AND business_id=?
              AND (question LIKE '%'||?||'%' OR answer LIKE '%'||?||'%')
            LIMIT ?;
        """, (business_id, q, q, limit)).fetchall()
        return [dict(r) for r in rows]
