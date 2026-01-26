# core/reminders.py — Automated appointment reminder system for LocusAI
# Schedules and sends email/SMS reminders before appointments

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

from core.db import get_conn, transaction

logger = logging.getLogger(__name__)

# ============================================================================
# Reminder Types
# ============================================================================

class ReminderType(Enum):
    """Types of appointment reminders."""
    TWENTY_FOUR_HOURS = "24h"  # 24 hours before
    ONE_HOUR = "1h"           # 1 hour before
    FIFTEEN_MINUTES = "15m"   # 15 minutes before


class ReminderChannel(Enum):
    """Channels for sending reminders."""
    EMAIL = "email"
    SMS = "sms"


class ReminderStatus(Enum):
    """Status of a reminder."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================================
# Reminder Configuration
# ============================================================================

# Default reminder schedule (can be overridden per business)
DEFAULT_REMINDER_SCHEDULE = [
    (ReminderType.TWENTY_FOUR_HOURS, ReminderChannel.EMAIL),
    (ReminderType.ONE_HOUR, ReminderChannel.SMS),
]

# Time deltas for each reminder type
REMINDER_DELTAS = {
    ReminderType.TWENTY_FOUR_HOURS: timedelta(hours=24),
    ReminderType.ONE_HOUR: timedelta(hours=1),
    ReminderType.FIFTEEN_MINUTES: timedelta(minutes=15),
}


# ============================================================================
# Reminder Scheduling
# ============================================================================

def schedule_reminders_for_appointment(
    appointment_id: int,
    start_at: str,
    customer_email: Optional[str] = None,
    customer_phone: Optional[str] = None,
    reminder_schedule: Optional[List[Tuple[ReminderType, ReminderChannel]]] = None
) -> List[int]:
    """Schedule reminders for a new appointment.

    Args:
        appointment_id: ID of the appointment
        start_at: Appointment start time (ISO format)
        customer_email: Customer email (required for email reminders)
        customer_phone: Customer phone (required for SMS reminders)
        reminder_schedule: Custom reminder schedule, or uses default

    Returns:
        List of created reminder IDs
    """
    schedule = reminder_schedule or DEFAULT_REMINDER_SCHEDULE

    try:
        appt_time = datetime.fromisoformat(start_at.replace(" ", "T"))
    except ValueError as e:
        logger.error(f"Invalid appointment time: {start_at} - {e}")
        return []

    created_ids = []
    now = datetime.now()

    with transaction() as con:
        for reminder_type, channel in schedule:
            # Check if we have the required contact info
            if channel == ReminderChannel.EMAIL and not customer_email:
                continue
            if channel == ReminderChannel.SMS and not customer_phone:
                continue

            # Calculate scheduled time
            delta = REMINDER_DELTAS.get(reminder_type, timedelta(hours=24))
            scheduled_for = appt_time - delta

            # Don't schedule reminders in the past
            if scheduled_for <= now:
                logger.debug(
                    f"Skipping {reminder_type.value} reminder for appointment {appointment_id}: "
                    f"scheduled time {scheduled_for} is in the past"
                )
                continue

            # Check if reminder already exists
            existing = con.execute(
                """SELECT id FROM reminders
                   WHERE appointment_id = ? AND type = ? AND channel = ?
                   AND status NOT IN ('cancelled')""",
                (appointment_id, reminder_type.value, channel.value)
            ).fetchone()

            if existing:
                logger.debug(
                    f"Reminder {reminder_type.value}/{channel.value} already exists for "
                    f"appointment {appointment_id}"
                )
                continue

            # Create the reminder
            cur = con.cursor()
            cur.execute(
                """INSERT INTO reminders(appointment_id, type, channel, scheduled_for, status)
                   VALUES(?, ?, ?, ?, ?)""",
                (
                    appointment_id,
                    reminder_type.value,
                    channel.value,
                    scheduled_for.isoformat(),
                    ReminderStatus.PENDING.value
                )
            )
            reminder_id = cur.lastrowid
            created_ids.append(reminder_id)

            logger.info(
                f"Scheduled {reminder_type.value} {channel.value} reminder (ID: {reminder_id}) "
                f"for appointment {appointment_id} at {scheduled_for}"
            )

    return created_ids


def cancel_reminders_for_appointment(appointment_id: int) -> int:
    """Cancel all pending reminders for an appointment.

    Args:
        appointment_id: ID of the appointment

    Returns:
        Number of reminders cancelled
    """
    with transaction() as con:
        cur = con.execute(
            """UPDATE reminders SET status = ? WHERE appointment_id = ? AND status = ?""",
            (ReminderStatus.CANCELLED.value, appointment_id, ReminderStatus.PENDING.value)
        )
        count = cur.rowcount

    if count > 0:
        logger.info(f"Cancelled {count} reminders for appointment {appointment_id}")

    return count


def reschedule_reminders_for_appointment(
    appointment_id: int,
    new_start_at: str,
    customer_email: Optional[str] = None,
    customer_phone: Optional[str] = None
) -> List[int]:
    """Reschedule reminders when appointment time changes.

    Cancels existing reminders and creates new ones.

    Args:
        appointment_id: ID of the appointment
        new_start_at: New appointment start time
        customer_email: Customer email
        customer_phone: Customer phone

    Returns:
        List of new reminder IDs
    """
    # Cancel existing reminders
    cancel_reminders_for_appointment(appointment_id)

    # Schedule new reminders
    return schedule_reminders_for_appointment(
        appointment_id=appointment_id,
        start_at=new_start_at,
        customer_email=customer_email,
        customer_phone=customer_phone
    )


# ============================================================================
# Reminder Processing
# ============================================================================

def get_due_reminders(limit: int = 100) -> List[Dict[str, Any]]:
    """Get reminders that are due to be sent.

    Args:
        limit: Maximum number of reminders to return

    Returns:
        List of reminder dicts with appointment and business info
    """
    now = datetime.now().isoformat()

    with get_conn() as con:
        rows = con.execute(
            """SELECT
                r.id as reminder_id,
                r.appointment_id,
                r.type,
                r.channel,
                r.scheduled_for,
                a.customer_name,
                a.phone as customer_phone,
                a.customer_email,
                a.service,
                a.start_at as appointment_time,
                b.id as business_id,
                b.name as business_name,
                b.escalation_phone as business_phone,
                b.escalation_email as business_email
               FROM reminders r
               JOIN appointments a ON r.appointment_id = a.id
               JOIN businesses b ON a.business_id = b.id
               WHERE r.status = ?
                 AND r.scheduled_for <= ?
                 AND a.status NOT IN ('cancelled', 'completed')
               ORDER BY r.scheduled_for ASC
               LIMIT ?""",
            (ReminderStatus.PENDING.value, now, limit)
        ).fetchall()

        return [dict(r) for r in rows]


def mark_reminder_sent(reminder_id: int) -> bool:
    """Mark a reminder as sent.

    Args:
        reminder_id: ID of the reminder

    Returns:
        True if updated successfully
    """
    try:
        with transaction() as con:
            con.execute(
                """UPDATE reminders SET status = ?, sent_at = ? WHERE id = ?""",
                (ReminderStatus.SENT.value, datetime.now().isoformat(), reminder_id)
            )
        return True
    except Exception as e:
        logger.error(f"Failed to mark reminder {reminder_id} as sent: {e}")
        return False


def mark_reminder_failed(reminder_id: int, error_message: str) -> bool:
    """Mark a reminder as failed.

    Args:
        reminder_id: ID of the reminder
        error_message: Error description

    Returns:
        True if updated successfully
    """
    try:
        with transaction() as con:
            con.execute(
                """UPDATE reminders SET status = ?, error_message = ? WHERE id = ?""",
                (ReminderStatus.FAILED.value, error_message[:500], reminder_id)
            )
        return True
    except Exception as e:
        logger.error(f"Failed to mark reminder {reminder_id} as failed: {e}")
        return False


# ============================================================================
# Reminder Content Generation
# ============================================================================

def generate_email_reminder(reminder: Dict[str, Any]) -> Dict[str, str]:
    """Generate email reminder content.

    Args:
        reminder: Reminder dict with appointment info

    Returns:
        Dict with 'subject', 'body' keys
    """
    business_name = reminder.get("business_name", "Our Business")
    customer_name = reminder.get("customer_name", "Valued Customer")
    service = reminder.get("service", "your appointment")
    appointment_time = reminder.get("appointment_time", "")

    # Parse and format the appointment time
    try:
        dt = datetime.fromisoformat(appointment_time.replace(" ", "T"))
        formatted_time = dt.strftime("%A, %B %d at %I:%M %p")
    except Exception:
        formatted_time = appointment_time

    reminder_type = reminder.get("type", "24h")

    if reminder_type == "24h":
        time_desc = "tomorrow"
    elif reminder_type == "1h":
        time_desc = "in 1 hour"
    elif reminder_type == "15m":
        time_desc = "in 15 minutes"
    else:
        time_desc = "soon"

    subject = f"Reminder: Your appointment {time_desc} - {business_name}"

    body = f"""Hello {customer_name},

This is a friendly reminder that you have an appointment {time_desc}:

Service: {service}
When: {formatted_time}
Where: {business_name}

If you need to reschedule or cancel, please contact us as soon as possible.

We look forward to seeing you!

Best regards,
{business_name}
"""

    return {"subject": subject, "body": body}


def generate_sms_reminder(reminder: Dict[str, Any]) -> str:
    """Generate SMS reminder content.

    Args:
        reminder: Reminder dict with appointment info

    Returns:
        SMS message text (limited to ~160 chars)
    """
    business_name = reminder.get("business_name", "")
    service = reminder.get("service", "appt")
    appointment_time = reminder.get("appointment_time", "")
    reminder_type = reminder.get("type", "1h")

    # Parse and format the appointment time
    try:
        dt = datetime.fromisoformat(appointment_time.replace(" ", "T"))
        formatted_time = dt.strftime("%m/%d %I:%M%p")
    except Exception:
        formatted_time = appointment_time

    if reminder_type == "24h":
        time_desc = "tomorrow"
    elif reminder_type == "1h":
        time_desc = "in 1hr"
    elif reminder_type == "15m":
        time_desc = "in 15min"
    else:
        time_desc = "soon"

    # Keep under 160 chars
    msg = f"Reminder: {service} {time_desc} ({formatted_time}) at {business_name}. Reply CANCEL to cancel."

    if len(msg) > 160:
        msg = f"Appt reminder: {time_desc} at {business_name}. Reply CANCEL to cancel."

    return msg[:160]


# ============================================================================
# Reminder Sending (requires sms.py and mailer.py)
# ============================================================================

def send_reminder(reminder: Dict[str, Any]) -> Tuple[bool, str]:
    """Send a reminder via the appropriate channel.

    Args:
        reminder: Reminder dict with all info

    Returns:
        Tuple of (success, error_message)
    """
    channel = reminder.get("channel", "email")

    try:
        if channel == "email":
            return _send_email_reminder(reminder)
        elif channel == "sms":
            return _send_sms_reminder(reminder)
        else:
            return False, f"Unknown channel: {channel}"
    except Exception as e:
        logger.error(f"Failed to send reminder {reminder.get('reminder_id')}: {e}")
        return False, str(e)


def _send_email_reminder(reminder: Dict[str, Any]) -> Tuple[bool, str]:
    """Send an email reminder."""
    customer_email = reminder.get("customer_email")
    if not customer_email:
        return False, "No customer email"

    content = generate_email_reminder(reminder)

    try:
        from core.mailer import send_email
        send_email(
            to=customer_email,
            subject=content["subject"],
            body=content["body"]
        )
        logger.info(f"Sent email reminder to {customer_email}")
        return True, ""
    except ImportError:
        logger.warning("Email sending not available (core.mailer not configured)")
        return False, "Email not configured"
    except Exception as e:
        logger.error(f"Failed to send email reminder: {e}")
        return False, str(e)


def _send_sms_reminder(reminder: Dict[str, Any]) -> Tuple[bool, str]:
    """Send an SMS reminder."""
    customer_phone = reminder.get("customer_phone")
    if not customer_phone:
        return False, "No customer phone"

    message = generate_sms_reminder(reminder)

    try:
        from core.sms import send_sms
        send_sms(
            to=customer_phone,
            message=message
        )
        logger.info(f"Sent SMS reminder to {customer_phone}")
        return True, ""
    except ImportError:
        logger.warning("SMS sending not available (core.sms not configured)")
        return False, "SMS not configured"
    except Exception as e:
        logger.error(f"Failed to send SMS reminder: {e}")
        return False, str(e)


# ============================================================================
# Reminder Processing Loop (called by worker)
# ============================================================================

def process_due_reminders(batch_size: int = 50) -> Dict[str, int]:
    """Process all due reminders.

    This should be called periodically by a background worker.

    Args:
        batch_size: Maximum reminders to process in one batch

    Returns:
        Dict with counts: {'sent': N, 'failed': N, 'total': N}
    """
    stats = {"sent": 0, "failed": 0, "total": 0}

    reminders = get_due_reminders(limit=batch_size)
    stats["total"] = len(reminders)

    for reminder in reminders:
        reminder_id = reminder.get("reminder_id")

        success, error = send_reminder(reminder)

        if success:
            mark_reminder_sent(reminder_id)
            stats["sent"] += 1
        else:
            mark_reminder_failed(reminder_id, error)
            stats["failed"] += 1

    if stats["total"] > 0:
        logger.info(
            f"Processed {stats['total']} reminders: "
            f"{stats['sent']} sent, {stats['failed']} failed"
        )

    return stats


# ============================================================================
# Reminder Statistics
# ============================================================================

def get_reminder_stats(business_id: Optional[int] = None, days: int = 30) -> Dict[str, Any]:
    """Get reminder statistics.

    Args:
        business_id: Filter to specific business (optional)
        days: Number of days to look back

    Returns:
        Dict with stats
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    with get_conn() as con:
        if business_id:
            rows = con.execute(
                """SELECT r.status, r.channel, COUNT(*) as count
                   FROM reminders r
                   JOIN appointments a ON r.appointment_id = a.id
                   WHERE a.business_id = ?
                     AND r.created_at >= ?
                   GROUP BY r.status, r.channel""",
                (business_id, cutoff)
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT status, channel, COUNT(*) as count
                   FROM reminders
                   WHERE created_at >= ?
                   GROUP BY status, channel""",
                (cutoff,)
            ).fetchall()

    stats = {
        "by_status": {},
        "by_channel": {},
        "total": 0
    }

    for row in rows:
        status = row["status"]
        channel = row["channel"]
        count = row["count"]

        stats["total"] += count
        stats["by_status"][status] = stats["by_status"].get(status, 0) + count
        stats["by_channel"][channel] = stats["by_channel"].get(channel, 0) + count

    return stats
