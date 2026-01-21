# core/escalation.py — Human handoff and escalation management
# Production-grade escalation system with notifications

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from core.db import get_conn, transaction
from core.mailer import send_email
from core.sentiment import SentimentResult, summarize_conversation

logger = logging.getLogger(__name__)


# ============================================================================
# Escalation Database Operations
# ============================================================================

def create_escalation(
    business_id: int,
    session_id: Optional[int],
    customer_id: Optional[int],
    reason: str,
    priority: str = "normal",
    conversation_summary: Optional[str] = None,
    customer_info: Optional[Dict] = None
) -> Optional[int]:
    """Create an escalation record."""
    try:
        with transaction() as con:
            cur = con.cursor()

            # Build notes with context
            notes_parts = []
            if conversation_summary:
                notes_parts.append(f"Conversation Summary:\n{conversation_summary}")
            if customer_info:
                info_str = ", ".join(f"{k}: {v}" for k, v in customer_info.items() if v)
                notes_parts.append(f"Customer Info: {info_str}")

            notes = "\n\n".join(notes_parts) if notes_parts else None

            cur.execute("""
                INSERT INTO escalations (
                    business_id, session_id, customer_id, reason,
                    status, priority, notes, created_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, datetime('now'))
            """, (business_id, session_id, customer_id, reason, priority, notes))

            escalation_id = cur.lastrowid

            # Mark session as escalated
            if session_id:
                cur.execute("""
                    UPDATE sessions SET
                        escalated = 1,
                        escalated_at = datetime('now'),
                        escalation_reason = ?
                    WHERE id = ?
                """, (reason, session_id))

            logger.info(f"Created escalation {escalation_id} for business {business_id}: {reason}")
            return escalation_id

    except Exception as e:
        logger.error(f"Failed to create escalation: {e}")
        return None


def get_escalation(escalation_id: int) -> Optional[Dict]:
    """Get an escalation by ID."""
    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM escalations WHERE id = ?", (escalation_id,)
        ).fetchone()
        return dict(row) if row else None


def get_pending_escalations(business_id: int, limit: int = 50) -> List[Dict]:
    """Get pending escalations for a business."""
    with get_conn() as con:
        rows = con.execute("""
            SELECT e.*, s.phone as session_phone, c.name as customer_name,
                   c.email as customer_email, c.phone as customer_phone
            FROM escalations e
            LEFT JOIN sessions s ON e.session_id = s.id
            LEFT JOIN customers c ON e.customer_id = c.id
            WHERE e.business_id = ? AND e.status = 'pending'
            ORDER BY
                CASE e.priority
                    WHEN 'urgent' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'normal' THEN 3
                    ELSE 4
                END,
                e.created_at DESC
            LIMIT ?
        """, (business_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_all_escalations(business_id: int, status: Optional[str] = None, limit: int = 100) -> List[Dict]:
    """Get all escalations for a business."""
    with get_conn() as con:
        if status:
            rows = con.execute("""
                SELECT e.*, c.name as customer_name
                FROM escalations e
                LEFT JOIN customers c ON e.customer_id = c.id
                WHERE e.business_id = ? AND e.status = ?
                ORDER BY e.created_at DESC LIMIT ?
            """, (business_id, status, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT e.*, c.name as customer_name
                FROM escalations e
                LEFT JOIN customers c ON e.customer_id = c.id
                WHERE e.business_id = ?
                ORDER BY e.created_at DESC LIMIT ?
            """, (business_id, limit)).fetchall()
        return [dict(r) for r in rows]


def update_escalation_status(
    escalation_id: int,
    status: str,
    resolved_by: Optional[str] = None,
    resolution_notes: Optional[str] = None
) -> bool:
    """Update escalation status."""
    valid_statuses = ('pending', 'acknowledged', 'resolved')
    if status not in valid_statuses:
        return False

    try:
        with transaction() as con:
            if status == 'resolved':
                con.execute("""
                    UPDATE escalations SET
                        status = ?,
                        resolved_at = datetime('now'),
                        resolved_by = ?,
                        notes = COALESCE(notes || '\n\nResolution: ' || ?, notes)
                    WHERE id = ?
                """, (status, resolved_by, resolution_notes or 'Resolved', escalation_id))
            else:
                con.execute(
                    "UPDATE escalations SET status = ? WHERE id = ?",
                    (status, escalation_id)
                )
        return True
    except Exception as e:
        logger.error(f"Failed to update escalation {escalation_id}: {e}")
        return False


# ============================================================================
# Notification System
# ============================================================================

def notify_escalation(
    escalation_id: int,
    business: Dict,
    customer_info: Optional[Dict] = None,
    conversation_summary: Optional[str] = None
) -> bool:
    """Send notification to business owner about escalation."""
    email = business.get('escalation_email') or business.get('email')
    if not email:
        logger.warning(f"No escalation email for business {business.get('id')}")
        return False

    escalation = get_escalation(escalation_id)
    if not escalation:
        return False

    # Build email
    subject = f"[AxisAI] Customer Escalation - {business.get('name', 'Your Business')}"

    body_parts = [
        f"A customer interaction requires your attention.",
        f"",
        f"Priority: {escalation.get('priority', 'normal').upper()}",
        f"Reason: {escalation.get('reason', 'Unknown')}",
        f"Time: {escalation.get('created_at', 'Unknown')}",
    ]

    if customer_info:
        body_parts.append("")
        body_parts.append("Customer Information:")
        if customer_info.get('name'):
            body_parts.append(f"  Name: {customer_info['name']}")
        if customer_info.get('phone'):
            body_parts.append(f"  Phone: {customer_info['phone']}")
        if customer_info.get('email'):
            body_parts.append(f"  Email: {customer_info['email']}")

    if conversation_summary:
        body_parts.append("")
        body_parts.append("Conversation Summary:")
        body_parts.append(conversation_summary)

    body_parts.extend([
        "",
        "Please log into your AxisAI dashboard to review and respond.",
        "",
        "—",
        "AxisAI Automated Notification"
    ])

    body = "\n".join(body_parts)

    try:
        send_email(email, subject, body)

        # Mark as notified
        with get_conn() as con:
            con.execute(
                "UPDATE escalations SET notified_at = datetime('now') WHERE id = ?",
                (escalation_id,)
            )
            con.commit()

        logger.info(f"Sent escalation notification for {escalation_id} to {email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send escalation notification: {e}")
        return False


# ============================================================================
# Main Escalation Handler
# ============================================================================

def handle_escalation(
    sentiment_result: SentimentResult,
    business: Dict,
    session_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    customer_info: Optional[Dict] = None,
    conversation_history: Optional[List[Dict]] = None
) -> Optional[int]:
    """
    Handle an escalation triggered by sentiment analysis.

    Returns escalation_id if created, None otherwise.
    """
    if not sentiment_result.triggers_escalation:
        return None

    business_id = business.get('id')
    if not business_id:
        logger.error("Cannot create escalation: missing business_id")
        return None

    # Determine priority
    priority = "normal"
    if sentiment_result.sentiment.value == "angry":
        priority = "high"
    elif sentiment_result.details.get('pattern_matches', {}).get('urgency', 0) > 0:
        priority = "urgent"
    elif sentiment_result.intent.value == "complaint":
        priority = "high"

    # Generate conversation summary
    summary = None
    if conversation_history:
        summary = summarize_conversation(conversation_history)

    # Create escalation
    escalation_id = create_escalation(
        business_id=business_id,
        session_id=session_id,
        customer_id=customer_id,
        reason=sentiment_result.escalation_reason or "Escalation triggered",
        priority=priority,
        conversation_summary=summary,
        customer_info=customer_info
    )

    if escalation_id:
        # Send notification (async in production)
        notify_escalation(
            escalation_id=escalation_id,
            business=business,
            customer_info=customer_info,
            conversation_summary=summary
        )

    return escalation_id


def get_escalation_response() -> str:
    """Get the AI response when escalating to human."""
    return (
        "I understand you'd like to speak with someone directly. "
        "I've notified our team and someone will reach out to you shortly. "
        "If you provided your phone number, expect a call back soon. "
        "Is there anything else I can help you with in the meantime?"
    )
