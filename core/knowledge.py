import re
from core.db import get_conn

def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def load_business_from_db(business_name_or_slug: str):
    """
    Robust lookup:
    - Accepts name or slug (any case, any spacing)
    - Trims, normalizes hyphens
    - Exact, slug, partial LIKE, and token-AND fallbacks
    """
    q = (business_name_or_slug or "").strip()
    if not q:
        raise ValueError("Empty business name/slug")

    q_lower = q.lower()
    q_slug  = slugify(q)

    with get_conn() as con:
        # Exact by name (case-insensitive)
        row = con.execute("SELECT * FROM businesses WHERE lower(name)=?", (q_lower,)).fetchone()
        if row: return row

        # Exact by slug
        row = con.execute("SELECT * FROM businesses WHERE lower(slug)=?", (q_slug,)).fetchone()
        if row: return row

        # Partial LIKE (name then slug)
        row = con.execute("SELECT * FROM businesses WHERE lower(name) LIKE ? LIMIT 1", (f"%{q_lower}%",)).fetchone()
        if row: return row
        row = con.execute("SELECT * FROM businesses WHERE lower(slug) LIKE ? LIMIT 1", (f"%{q_slug}%",)).fetchone()
        if row: return row

        # Token AND match across name, then slug
        words = [w for w in re.split(r"[^a-z0-9]+", q_lower) if w]
        if words:
            clause = " AND ".join(["lower(name) LIKE ?"] * len(words))
            params = [f"%{w}%" for w in words]
            row = con.execute(f"SELECT * FROM businesses WHERE {clause} LIMIT 1", params).fetchone()
            if row: return row

            clause = " AND ".join(["lower(slug) LIKE ?"] * len(words))
            row = con.execute(f"SELECT * FROM businesses WHERE {clause} LIMIT 1", params).fetchone()
            if row: return row

    raise ValueError(f"Business '{business_name_or_slug}' not found in DB")
