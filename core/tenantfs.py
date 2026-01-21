import os, json
from core.db import get_business_by_id

def business_paths(slug:str):
    data_dir   = os.path.join("businesses", slug)             # non-public
    static_dir = os.path.join("static", "tenants", slug)      # public assets
    return data_dir, static_dir

def write_meta_from_db(business_id:int):
    b = get_business_by_id(business_id)
    if not b: return
    slug = b["slug"]
    data_dir, _ = business_paths(slug)
    os.makedirs(data_dir, exist_ok=True)
    meta = {
        "id": b["id"],
        "tenant_key": b.get("tenant_key"),
        "name": b["name"],
        "slug": b["slug"],
        "hours": b.get("hours"),
        "address": b.get("address"),
        "tone": b.get("tone"),
        "accent_color": b.get("accent_color"),
        "logo_path": b.get("logo_path"),
        "created_at": b.get("created_at"),
    }
    with open(os.path.join(data_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
