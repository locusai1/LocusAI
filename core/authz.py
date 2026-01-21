from typing import List
from flask import session
from core.db import get_conn

def get_allowed_business_ids_for_user(user) -> List[int]:
    """Admins see all; owners only see businesses they are mapped to."""
    if not user:
        return []
    if user.get("role") == "admin":
        with get_conn() as con:
            return [r["id"] for r in con.execute("SELECT id FROM businesses").fetchall()]
    with get_conn() as con:
        rows = con.execute("SELECT business_id FROM business_users WHERE user_id=?", (user["id"],)).fetchall()
        return [r["business_id"] for r in rows]

def user_can_access_business(user, business_id:int) -> bool:
    return business_id in get_allowed_business_ids_for_user(user)
