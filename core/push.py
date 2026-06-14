# core/push.py — Web Push (PWA) notifications for business owners.
#
# Lets owners install LocusAI to their phone home screen and receive push alerts
# (e.g. a frustrated caller escalated, a missed call) even when the dashboard is
# closed. Uses the standard Web Push protocol with VAPID.
#
# Graceful degradation:
#   - No VAPID keys configured  -> subscribe endpoint returns "not configured";
#     the PWA still installs, just no push.
#   - pywebpush not installed    -> sends are no-ops (logged). Add it to go live.
#
# Generate keys once with:  python -m core.push genkeys
# then set VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_CLAIM_EMAIL in the env.

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

from core.db import get_conn, transaction

logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "mailto:hello@locusai.co.uk")


def is_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def _private_key_pem() -> str:
    """Return the private key as a PEM string.

    Accepts either a raw PEM (multi-line) or, for env-var friendliness, a
    single-line base64 of the PEM."""
    key = VAPID_PRIVATE_KEY.strip()
    if "BEGIN" in key:
        return key
    try:
        return base64.b64decode(key).decode()
    except Exception:
        return key


def public_key() -> str:
    """The applicationServerKey the browser needs to subscribe."""
    return VAPID_PUBLIC_KEY


def save_subscription(
    user_id: int,
    subscription: Dict[str, Any],
    *,
    business_id: Optional[int] = None,
    user_agent: Optional[str] = None,
) -> bool:
    """Persist a PushSubscription JSON (endpoint + keys.p256dh + keys.auth)."""
    try:
        endpoint = subscription.get("endpoint")
        keys = subscription.get("keys", {}) or {}
        p256dh = keys.get("p256dh")
        auth = keys.get("auth")
        if not (endpoint and p256dh and auth):
            return False
        with transaction() as con:
            con.execute(
                """INSERT INTO push_subscriptions (user_id, business_id, endpoint, p256dh, auth, user_agent)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(endpoint) DO UPDATE SET
                       user_id=excluded.user_id, business_id=excluded.business_id,
                       p256dh=excluded.p256dh, auth=excluded.auth""",
                (user_id, business_id, endpoint, p256dh, auth, user_agent),
            )
        return True
    except Exception as e:
        logger.warning("save_subscription failed: %s", e)
        return False


def remove_subscription(endpoint: str) -> None:
    try:
        with transaction() as con:
            con.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
    except Exception:
        pass


def _subscriptions_for_business(business_id: int) -> List[Dict[str, Any]]:
    """All push subscriptions belonging to users linked to this business."""
    with get_conn() as con:
        rows = con.execute(
            """SELECT ps.* FROM push_subscriptions ps
               JOIN business_users bu ON bu.user_id = ps.user_id
               WHERE bu.business_id = ?""",
            (business_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def send_push_to_business(business_id: int, title: str, body: str, url: str = "/") -> int:
    """Send a push notification to every owner of a business. Returns # delivered.

    No-op (returns 0) when VAPID keys or pywebpush are absent."""
    if not is_configured():
        logger.debug("Web push not configured; skipping notification")
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.info("pywebpush not installed; skipping push (pip install pywebpush)")
        return 0

    payload = json.dumps({"title": title, "body": body, "url": url})
    priv = _private_key_pem()
    subs = _subscriptions_for_business(business_id)
    sent = 0
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s["endpoint"],
                    "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
                },
                data=payload,
                vapid_private_key=priv,
                vapid_claims={"sub": VAPID_CLAIM_EMAIL},
            )
            sent += 1
        except WebPushException as e:
            # 404/410 -> subscription is dead, prune it.
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                remove_subscription(s["endpoint"])
            else:
                logger.warning("webpush failed: %s", e)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("webpush error: %s", e)
    return sent


# ============================================================================
# Key generation (CLI)
# ============================================================================


def generate_vapid_keys() -> Dict[str, str]:
    """Generate a VAPID keypair. Returns dict with public_key, private_key (PEM)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key()
    raw_pub = pub.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()
    private_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return {"public_key": public_b64, "private_key": private_pem}


if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "genkeys":
        keys = generate_vapid_keys()
        priv_b64 = base64.b64encode(keys["private_key"].encode()).decode()
        print("VAPID_PUBLIC_KEY=" + keys["public_key"])
        print("VAPID_PRIVATE_KEY=" + priv_b64)
        print("VAPID_CLAIM_EMAIL=mailto:hello@locusai.co.uk")
    else:
        print("Usage: python -m core.push genkeys")
