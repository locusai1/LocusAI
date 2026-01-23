# core/integrations.py — provider interface + registry (lazy auto-register)
from __future__ import annotations
from typing import List, Dict, Optional
from core.db import get_conn

class Provider:
    key: str = "base"
    def __init__(self, business_id: int, config: dict):
        self.business_id = business_id
        self.config = config or {}
    def fetch_services(self) -> List[Dict]: raise NotImplementedError
    def fetch_slots(self, service_id: Optional[int], date_str: str) -> List[str]: raise NotImplementedError
    def create_booking(self, payload: Dict) -> Dict: raise NotImplementedError
    def cancel_booking(self, external_id: str) -> bool: raise NotImplementedError

# ---- Registry ----
_REGISTRY: Dict[str, type] = {}

def register(provider_cls):
    _REGISTRY[provider_cls.key] = provider_cls
    return provider_cls

def _ensure_default_providers_loaded():
    """Import default providers once so their @register runs."""
    # If already loaded, do nothing
    if "local" in _REGISTRY and "dummy" in _REGISTRY and "retell" in _REGISTRY:
        return
    try:
        import providers.local_provider  # noqa: F401
    except Exception:
        pass
    try:
        import providers.dummy_provider  # noqa: F401
    except Exception:
        pass
    try:
        import providers.retell_provider  # noqa: F401
    except Exception:
        pass

def get_business_provider_key(business_id:int) -> str:
    with get_conn() as con:
        row = con.execute("""
          SELECT provider_key FROM integrations
          WHERE business_id=? AND status='active'
          ORDER BY id DESC LIMIT 1
        """, (business_id,)).fetchone()
    return row["provider_key"] if row else "local"

def get_business_provider(business_id:int) -> Provider:
    _ensure_default_providers_loaded()
    key = get_business_provider_key(business_id)
    with get_conn() as con:
        row = con.execute("""
          SELECT account_json FROM integrations
          WHERE business_id=? AND provider_key=? AND status='active'
          ORDER BY id DESC LIMIT 1
        """, (business_id, key)).fetchone()
    import json
    cfg = {}
    if row and row["account_json"]:
        try: cfg = json.loads(row["account_json"])
        except Exception: cfg = {}
    cls = _REGISTRY.get(key)
    if not cls:
        # Fallback to local if available
        if key != "local" and "local" in _REGISTRY:
            cls = _REGISTRY["local"]
        else:
            raise RuntimeError(f"No provider registered for key '{key}'")
    return cls(business_id, cfg)
