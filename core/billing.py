# core/billing.py — Stripe billing for LocusAI
#
# Self-contained billing layer. Works without any Stripe keys configured:
# is_configured() returns False and the UI shows "billing not configured yet".
# To go live, set STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET and the STRIPE_PRICE_*
# IDs (see core/settings.py). No code changes needed after that.

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core import settings
from core.db import get_conn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plan catalogue — prices in GBP. Stripe Price IDs come from env (per plan).
# `limits` are used by the feature-gating helpers; -1 means unlimited.
# ---------------------------------------------------------------------------
PLANS: Dict[str, Dict[str, Any]] = {
    "starter": {
        "key": "starter",
        "name": "Starter",
        "price_gbp": 49,
        "price_id_attr": "STRIPE_PRICE_STARTER",
        "tagline": "For solo owners who never want to miss a chat.",
        "features": [
            "AI web chat widget",
            "100 conversations / month",
            "1 business",
            "Booking confirmation flow",
            "Email support",
        ],
        "limits": {"conversations": 100, "users": 1, "businesses": 1, "channels": ["web"]},
    },
    "professional": {
        "key": "professional",
        "name": "Professional",
        "price_gbp": 149,
        "price_id_attr": "STRIPE_PRICE_PROFESSIONAL",
        "tagline": "Voice, SMS and chat — the full receptionist.",
        "features": [
            "Everything in Starter",
            "AI voice + SMS + web chat",
            "500 conversations / month",
            "3 team members",
            "Google Calendar sync",
            "Caller recognition",
        ],
        "limits": {
            "conversations": 500,
            "users": 3,
            "businesses": 1,
            "channels": ["web", "voice", "sms"],
        },
        "popular": True,
    },
    "business": {
        "key": "business",
        "name": "Business",
        "price_gbp": 299,
        "price_id_attr": "STRIPE_PRICE_BUSINESS",
        "tagline": "Unlimited volume and full analytics.",
        "features": [
            "Everything in Professional",
            "Unlimited conversations",
            "10 team members",
            "Full analytics suite",
            "Priority support",
        ],
        "limits": {
            "conversations": -1,
            "users": 10,
            "businesses": -1,
            "channels": ["web", "voice", "sms"],
        },
    },
}

# Statuses that grant access. "past_due" is intentionally included as a grace
# period while Stripe's dunning retries the payment — access is only revoked
# when the subscription becomes "canceled"/"unpaid".
ACTIVE_STATUSES = ("active", "trialing", "past_due")


def plan(plan_key: str) -> Optional[Dict[str, Any]]:
    return PLANS.get((plan_key or "").lower())


def plan_list() -> List[Dict[str, Any]]:
    """Ordered list for rendering the pricing page."""
    return [PLANS["starter"], PLANS["professional"], PLANS["business"]]


def price_id_for(plan_key: str) -> Optional[str]:
    p = plan(plan_key)
    if not p:
        return None
    return getattr(settings, p["price_id_attr"], None)


# ---------------------------------------------------------------------------
# Stripe client (lazy — never import at module load so the app boots without it)
# ---------------------------------------------------------------------------
def is_configured() -> bool:
    """True when Stripe is wired up enough to take a payment."""
    if not settings.STRIPE_SECRET_KEY:
        return False
    try:
        import stripe  # noqa: F401
    except ImportError:
        return False
    return True


def _stripe():
    """Return the configured stripe module, or None if unavailable."""
    if not settings.STRIPE_SECRET_KEY:
        return None
    try:
        import stripe
    except ImportError:
        logger.warning("stripe package not installed; billing disabled")
        return None
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_subscription(user_id: int) -> Optional[Dict[str, Any]]:
    """Most recent subscription row for a user (any status)."""
    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM subscriptions WHERE user_id=? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def has_active_subscription(user_id: int) -> bool:
    """True if the user has a subscription in a paid/working state that has not
    lapsed past its current period."""
    sub = get_subscription(user_id)
    if not sub:
        return False
    if sub["status"] not in ACTIVE_STATUSES:
        return False
    # If we know the period end, make sure it hasn't passed (grace handled by Stripe).
    cpe = sub.get("current_period_end")
    if cpe:
        try:
            end = datetime.fromisoformat(cpe.replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end < datetime.now(timezone.utc):
                return False
        except (ValueError, AttributeError):
            pass
    return True


def current_plan_key(user_id: int) -> Optional[str]:
    """The plan the user is actively paying for, or None."""
    if not has_active_subscription(user_id):
        return None
    sub = get_subscription(user_id)
    return sub.get("plan") if sub else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_subscription(
    user_id: int,
    *,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    plan_key: Optional[str] = None,
    status: Optional[str] = None,
    current_period_end: Optional[str] = None,
    cancel_at_period_end: Optional[bool] = None,
) -> None:
    """Insert or update the user's subscription row, keyed by stripe_subscription_id
    when available, otherwise by user_id. Only provided fields are written."""
    with get_conn() as con:
        existing = None
        if stripe_subscription_id:
            existing = con.execute(
                "SELECT * FROM subscriptions WHERE stripe_subscription_id=?",
                (stripe_subscription_id,),
            ).fetchone()
        if existing is None:
            existing = con.execute(
                "SELECT * FROM subscriptions WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()

        fields = {
            "stripe_customer_id": stripe_customer_id,
            "stripe_subscription_id": stripe_subscription_id,
            "plan": plan_key,
            "status": status,
            "current_period_end": current_period_end,
            "cancel_at_period_end": (
                None if cancel_at_period_end is None else int(cancel_at_period_end)
            ),
        }
        provided = {k: v for k, v in fields.items() if v is not None}

        if existing:
            if not provided:
                return
            sets = ", ".join(f"{k}=?" for k in provided)
            params = list(provided.values()) + [_now(), existing["id"]]
            con.execute(f"UPDATE subscriptions SET {sets}, updated_at=? WHERE id=?", params)
        else:
            cols = ["user_id"] + list(provided.keys())
            placeholders = ", ".join("?" * len(cols))
            con.execute(
                f"INSERT INTO subscriptions ({', '.join(cols)}) VALUES ({placeholders})",
                [user_id] + list(provided.values()),
            )
        con.commit()


# ---------------------------------------------------------------------------
# Checkout & Customer Portal
# ---------------------------------------------------------------------------
def create_checkout_session(
    user: Dict[str, Any], plan_key: str, success_url: str, cancel_url: str
) -> Optional[str]:
    """Create a Stripe Checkout Session and return its URL, or None on failure."""
    s = _stripe()
    if s is None:
        return None
    price_id = price_id_for(plan_key)
    if not price_id:
        logger.warning("No Stripe price ID configured for plan '%s'", plan_key)
        return None

    # Reuse an existing customer if we have one.
    customer_id = None
    sub = get_subscription(user["id"])
    if sub:
        customer_id = sub.get("stripe_customer_id")

    kwargs = dict(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(user["id"]),
        metadata={"user_id": str(user["id"]), "plan": plan_key},
        subscription_data={"metadata": {"user_id": str(user["id"]), "plan": plan_key}},
        allow_promotion_codes=True,
    )
    if customer_id:
        kwargs["customer"] = customer_id
    elif user.get("email"):
        kwargs["customer_email"] = user["email"]

    try:
        cs = s.checkout.Session.create(**kwargs)
        return cs.url
    except Exception:
        logger.exception("Failed to create Stripe checkout session")
        return None


def create_billing_portal_session(user_id: int, return_url: str) -> Optional[str]:
    """Create a Customer Portal session so the user can manage/cancel."""
    s = _stripe()
    if s is None:
        return None
    sub = get_subscription(user_id)
    if not sub or not sub.get("stripe_customer_id"):
        return None
    try:
        ps = s.billing_portal.Session.create(
            customer=sub["stripe_customer_id"], return_url=return_url
        )
        return ps.url
    except Exception:
        logger.exception("Failed to create Stripe billing portal session")
        return None


# ---------------------------------------------------------------------------
# Webhook handling
# ---------------------------------------------------------------------------
def verify_webhook(payload: bytes, sig_header: str):
    """Verify a webhook signature and return the parsed event, or None."""
    s = _stripe()
    if s is None or not settings.STRIPE_WEBHOOK_SECRET:
        return None
    try:
        return s.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except Exception:
        logger.warning("Stripe webhook signature verification failed")
        return None


def _ts_to_iso(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _user_id_from_metadata(obj: Dict[str, Any]) -> Optional[int]:
    meta = obj.get("metadata") or {}
    uid = meta.get("user_id") or obj.get("client_reference_id")
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None


def apply_event(event: Dict[str, Any]) -> bool:
    """Apply a verified Stripe event to the subscriptions table.
    Returns True if handled. Safe to call repeatedly (idempotent upserts)."""
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        user_id = _user_id_from_metadata(obj)
        if not user_id:
            return False
        plan_key = (obj.get("metadata") or {}).get("plan", "starter")
        # Only mark active if payment actually went through; otherwise record the
        # link and let customer.subscription.* / invoice.paid confirm status.
        paid = obj.get("payment_status") in ("paid", "no_payment_required")
        upsert_subscription(
            user_id,
            stripe_customer_id=obj.get("customer"),
            stripe_subscription_id=obj.get("subscription"),
            plan_key=plan_key,
            status="active" if paid else "incomplete",
        )
        return True

    if etype in (
        "customer.subscription.updated",
        "customer.subscription.created",
        "customer.subscription.deleted",
    ):
        user_id = _user_id_from_metadata(obj)
        # Fall back to matching by stripe customer/subscription id.
        if not user_id:
            sub_row = None
            with get_conn() as con:
                if obj.get("id"):
                    sub_row = con.execute(
                        "SELECT user_id FROM subscriptions WHERE stripe_subscription_id=?",
                        (obj.get("id"),),
                    ).fetchone()
                if sub_row is None and obj.get("customer"):
                    sub_row = con.execute(
                        "SELECT user_id FROM subscriptions WHERE stripe_customer_id=?",
                        (obj.get("customer"),),
                    ).fetchone()
            if sub_row:
                user_id = sub_row["user_id"]
        if not user_id:
            return False

        status = "canceled" if etype.endswith("deleted") else obj.get("status")
        plan_key = (obj.get("metadata") or {}).get("plan")
        # Derive plan from the price if metadata is absent.
        if not plan_key:
            try:
                price_id = obj["items"]["data"][0]["price"]["id"]
                for pk in PLANS:
                    if price_id_for(pk) == price_id:
                        plan_key = pk
                        break
            except (KeyError, IndexError, TypeError):
                pass
        upsert_subscription(
            user_id,
            stripe_customer_id=obj.get("customer"),
            stripe_subscription_id=obj.get("id"),
            plan_key=plan_key,
            status=status,
            current_period_end=_ts_to_iso(obj.get("current_period_end")),
            cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
        )
        return True

    if etype == "invoice.paid":
        customer = obj.get("customer")
        if customer:
            with get_conn() as con:
                con.execute(
                    "UPDATE subscriptions SET status='active', updated_at=? "
                    "WHERE stripe_customer_id=?",
                    (_now(), customer),
                )
                con.commit()
        return True

    if etype == "invoice.payment_failed":
        customer = obj.get("customer")
        if customer:
            with get_conn() as con:
                con.execute(
                    "UPDATE subscriptions SET status='past_due', updated_at=? "
                    "WHERE stripe_customer_id=?",
                    (_now(), customer),
                )
                con.commit()
        return True

    logger.info("Unhandled Stripe event type: %s", etype)
    return False
