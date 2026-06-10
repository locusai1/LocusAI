# core/webhooks.py — outbound webhooks / event bus for LocusAI
#
# Businesses register endpoint URLs; on events (booking.created, etc.) we POST a
# signed JSON payload with at-least-once delivery (queued in webhook_deliveries,
# retried with backoff by a supervised dispatcher). SSRF-guarded + HMAC-signed.

import json
import hmac
import hashlib
import ipaddress
import logging
import secrets
import socket
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

from core.db import get_conn

logger = logging.getLogger(__name__)

# Canonical event names emitted by the app.
EVENT_TYPES = [
    "booking.created",
    "appointment.rescheduled",
    "appointment.cancelled",
    "escalation.created",
    "call.completed",
]

MAX_ATTEMPTS = 5
_BACKOFF_SECONDS = [0, 60, 300, 1800, 7200]  # per attempt index


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Security: SSRF guard + signing
# ---------------------------------------------------------------------------
def is_safe_url(url: str) -> bool:
    """Reject non-http(s) and URLs resolving to private/loopback/link-local IPs
    to prevent SSRF against internal services."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = p.hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False
    return True


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 signature, returned as 'sha256=<hex>' (Stripe/GitHub style)."""
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def generate_secret() -> str:
    return "whsec_" + secrets.token_hex(24)


# ---------------------------------------------------------------------------
# Endpoint management
# ---------------------------------------------------------------------------
def list_endpoints(business_id: int) -> List[Dict[str, Any]]:
    with get_conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM webhook_endpoints WHERE business_id=? ORDER BY id DESC",
            (business_id,)).fetchall()]


def create_endpoint(business_id: int, url: str, events: str = "all",
                    description: Optional[str] = None) -> Dict[str, Any]:
    secret = generate_secret()
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO webhook_endpoints (business_id, url, secret, events, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (business_id, url, secret, events or "all", description),
        )
        con.commit()
        eid = cur.lastrowid
    return {"id": eid, "secret": secret}


def delete_endpoint(business_id: int, endpoint_id: int) -> bool:
    with get_conn() as con:
        cur = con.execute(
            "DELETE FROM webhook_endpoints WHERE id=? AND business_id=?",
            (endpoint_id, business_id))
        con.commit()
        return cur.rowcount > 0


def recent_deliveries(business_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    with get_conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT id, endpoint_id, event_type, status, attempts, response_code, "
            "last_error, created_at, delivered_at FROM webhook_deliveries "
            "WHERE business_id=? ORDER BY id DESC LIMIT ?", (business_id, limit)).fetchall()]


# ---------------------------------------------------------------------------
# Emit + dispatch
# ---------------------------------------------------------------------------
def _endpoint_wants(events_field: str, event_type: str) -> bool:
    if not events_field or events_field.strip().lower() == "all":
        return True
    wanted = {e.strip() for e in events_field.split(",") if e.strip()}
    return event_type in wanted


def emit_event(business_id: int, event_type: str, data: Dict[str, Any]) -> int:
    """Queue a delivery for each matching active endpoint. Returns count queued.
    Never raises — webhook failures must not break the originating action."""
    try:
        endpoints = [e for e in list_endpoints(business_id)
                     if e["active"] and _endpoint_wants(e["events"], event_type)]
        if not endpoints:
            return 0
        envelope = {
            "event": event_type,
            "business_id": business_id,
            "created_at": _now().isoformat(),
            "data": data,
        }
        payload = json.dumps(envelope, default=str)
        with get_conn() as con:
            for e in endpoints:
                con.execute(
                    "INSERT INTO webhook_deliveries "
                    "(endpoint_id, business_id, event_type, payload, status, next_attempt_at) "
                    "VALUES (?, ?, ?, ?, 'pending', ?)",
                    (e["id"], business_id, event_type, payload, _now().isoformat()),
                )
            con.commit()
        return len(endpoints)
    except Exception:
        logger.exception("emit_event failed for %s (business %s)", event_type, business_id)
        return 0


def _deliver_one(delivery: Dict[str, Any]) -> None:
    """Attempt a single delivery; update its row with the outcome + next retry."""
    import httpx
    with get_conn() as con:
        ep = con.execute("SELECT * FROM webhook_endpoints WHERE id=?",
                         (delivery["endpoint_id"],)).fetchone()
    if not ep or not ep["active"]:
        _finalize(delivery["id"], "failed", None, "Endpoint missing or inactive")
        return

    body = delivery["payload"].encode()
    attempt = delivery["attempts"] + 1
    if not is_safe_url(ep["url"]):
        _finalize(delivery["id"], "failed", None, "Endpoint URL failed SSRF safety check")
        return
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "LocusAI-Webhooks/1.0",
        "X-LocusAI-Event": delivery["event_type"],
        "X-LocusAI-Delivery": str(delivery["id"]),
        "X-LocusAI-Signature": sign_payload(ep["secret"], body),
    }
    try:
        resp = httpx.post(ep["url"], content=body, headers=headers, timeout=10)
        code = resp.status_code
        if 200 <= code < 300:
            _finalize(delivery["id"], "success", code, None, attempt)
        else:
            _retry_or_fail(delivery["id"], attempt, code, f"HTTP {code}")
    except Exception as e:
        _retry_or_fail(delivery["id"], attempt, None, str(e)[:200])


def _finalize(delivery_id, status, code, error, attempts=None):
    with get_conn() as con:
        if attempts is not None:
            con.execute(
                "UPDATE webhook_deliveries SET status=?, response_code=?, last_error=?, "
                "attempts=?, delivered_at=? WHERE id=?",
                (status, code, error, attempts, _now().isoformat(), delivery_id))
        else:
            con.execute(
                "UPDATE webhook_deliveries SET status=?, response_code=?, last_error=?, "
                "delivered_at=? WHERE id=?",
                (status, code, error, _now().isoformat(), delivery_id))
        con.commit()


def _retry_or_fail(delivery_id, attempt, code, error):
    if attempt >= MAX_ATTEMPTS:
        _finalize(delivery_id, "failed", code, error, attempt)
        return
    delay = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
    next_at = (_now() + timedelta(seconds=delay)).isoformat()
    with get_conn() as con:
        con.execute(
            "UPDATE webhook_deliveries SET status='pending', attempts=?, response_code=?, "
            "last_error=?, next_attempt_at=? WHERE id=?",
            (attempt, code, error, next_at, delivery_id))
        con.commit()


def send_test_event(business_id: int, endpoint_id: int) -> bool:
    """Queue a 'test.ping' delivery to a single endpoint (for the UI test button)."""
    with get_conn() as con:
        ep = con.execute(
            "SELECT id FROM webhook_endpoints WHERE id=? AND business_id=?",
            (endpoint_id, business_id)).fetchone()
        if not ep:
            return False
        envelope = {"event": "test.ping", "business_id": business_id,
                    "created_at": _now().isoformat(),
                    "data": {"message": "This is a test event from LocusAI."}}
        con.execute(
            "INSERT INTO webhook_deliveries "
            "(endpoint_id, business_id, event_type, payload, status, next_attempt_at) "
            "VALUES (?, ?, 'test.ping', ?, 'pending', ?)",
            (endpoint_id, business_id, json.dumps(envelope), _now().isoformat()))
        con.commit()
    return True


def dispatch_pending(limit: int = 25) -> int:
    """Deliver due pending deliveries. Returns the number attempted.
    Designed to be called repeatedly by a supervised worker."""
    with get_conn() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM webhook_deliveries WHERE status='pending' "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY id ASC LIMIT ?", (_now().isoformat(), limit)).fetchall()]
    for d in rows:
        _deliver_one(d)
    return len(rows)
