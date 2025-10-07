from core.db import get_conn

def load_business_from_db(business_name_or_slug):
    """Load a business by name or slug, with FAQs + info."""
    with get_conn() as con:
        business = con.execute(
            "SELECT * FROM businesses WHERE slug = ? OR name = ?",
            (business_name_or_slug, business_name_or_slug)
        ).fetchone()
        if not business:
            raise ValueError(f"Business '{business_name_or_slug}' not found in DB")

        faqs = con.execute(
            "SELECT question, answer FROM faqs WHERE business_id = ?",
            (business["id"],)
        ).fetchall()

        info = con.execute(
            "SELECT key, value FROM business_info WHERE business_id = ?",
            (business["id"],)
        ).fetchall()

    return {
        "id": business["id"],
        "name": business["name"],
        "faqs": {row["question"]: row["answer"] for row in faqs},
        "info": {row["key"]: row["value"] for row in info}
    }

