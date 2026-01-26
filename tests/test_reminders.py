# tests/test_reminders.py — Tests for core/reminders.py (Appointment Reminders)

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


class TestReminderTypes:
    """Tests for reminder type enums."""

    def test_reminder_type_values(self):
        """Should have correct reminder type values."""
        from core.reminders import ReminderType
        assert ReminderType.TWENTY_FOUR_HOURS.value == "24h"
        assert ReminderType.ONE_HOUR.value == "1h"
        assert ReminderType.FIFTEEN_MINUTES.value == "15m"

    def test_reminder_channel_values(self):
        """Should have correct channel values."""
        from core.reminders import ReminderChannel
        assert ReminderChannel.EMAIL.value == "email"
        assert ReminderChannel.SMS.value == "sms"

    def test_reminder_status_values(self):
        """Should have correct status values."""
        from core.reminders import ReminderStatus
        assert ReminderStatus.PENDING.value == "pending"
        assert ReminderStatus.SENT.value == "sent"
        assert ReminderStatus.FAILED.value == "failed"
        assert ReminderStatus.CANCELLED.value == "cancelled"


class TestReminderConfiguration:
    """Tests for reminder configuration."""

    def test_default_schedule_defined(self):
        """Should have default reminder schedule."""
        from core.reminders import DEFAULT_REMINDER_SCHEDULE
        assert len(DEFAULT_REMINDER_SCHEDULE) >= 1
        # Each item should be (ReminderType, ReminderChannel) tuple
        for item in DEFAULT_REMINDER_SCHEDULE:
            assert len(item) == 2

    def test_reminder_deltas_defined(self):
        """Should have time deltas for each type."""
        from core.reminders import REMINDER_DELTAS, ReminderType
        assert ReminderType.TWENTY_FOUR_HOURS in REMINDER_DELTAS
        assert ReminderType.ONE_HOUR in REMINDER_DELTAS
        assert ReminderType.FIFTEEN_MINUTES in REMINDER_DELTAS

    def test_reminder_deltas_correct(self):
        """Should have correct time deltas."""
        from core.reminders import REMINDER_DELTAS, ReminderType
        assert REMINDER_DELTAS[ReminderType.TWENTY_FOUR_HOURS] == timedelta(hours=24)
        assert REMINDER_DELTAS[ReminderType.ONE_HOUR] == timedelta(hours=1)
        assert REMINDER_DELTAS[ReminderType.FIFTEEN_MINUTES] == timedelta(minutes=15)


class TestScheduleReminders:
    """Tests for schedule_reminders_for_appointment."""

    def test_schedule_reminders_creates_records(self, sample_business):
        """Should create reminder records."""
        from core.reminders import schedule_reminders_for_appointment
        from core.db import transaction

        # Create a test appointment
        future = datetime.now() + timedelta(days=2)
        with transaction() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO appointments (business_id, customer_name, start_at, status)
                VALUES (?, ?, ?, 'confirmed')
            """, (sample_business["id"], "Test Customer", future.isoformat()))
            appt_id = cur.lastrowid

        reminder_ids = schedule_reminders_for_appointment(
            appointment_id=appt_id,
            start_at=future.isoformat(),
            customer_email="test@example.com",
            customer_phone="555-1234"
        )
        assert len(reminder_ids) >= 1

    def test_schedule_reminders_skips_email_without_address(self, sample_business):
        """Should skip email reminders if no email provided."""
        from core.reminders import schedule_reminders_for_appointment, ReminderType, ReminderChannel
        from core.db import transaction, get_conn

        future = datetime.now() + timedelta(days=2)
        with transaction() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO appointments (business_id, customer_name, start_at, status)
                VALUES (?, ?, ?, 'confirmed')
            """, (sample_business["id"], "Test", future.isoformat()))
            appt_id = cur.lastrowid

        # Only provide phone, not email
        reminder_ids = schedule_reminders_for_appointment(
            appointment_id=appt_id,
            start_at=future.isoformat(),
            customer_email=None,
            customer_phone="555-1234",
            reminder_schedule=[(ReminderType.TWENTY_FOUR_HOURS, ReminderChannel.EMAIL)]
        )
        assert len(reminder_ids) == 0

    def test_schedule_reminders_skips_past_times(self, sample_business):
        """Should skip reminders scheduled in the past."""
        from core.reminders import schedule_reminders_for_appointment, ReminderType, ReminderChannel
        from core.db import transaction

        # Appointment in 30 minutes - 24h reminder would be in the past
        soon = datetime.now() + timedelta(minutes=30)
        with transaction() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO appointments (business_id, customer_name, start_at, status)
                VALUES (?, ?, ?, 'confirmed')
            """, (sample_business["id"], "Test", soon.isoformat()))
            appt_id = cur.lastrowid

        reminder_ids = schedule_reminders_for_appointment(
            appointment_id=appt_id,
            start_at=soon.isoformat(),
            customer_email="test@example.com",
            reminder_schedule=[(ReminderType.TWENTY_FOUR_HOURS, ReminderChannel.EMAIL)]
        )
        assert len(reminder_ids) == 0

    def test_schedule_reminders_invalid_datetime(self, sample_business):
        """Should handle invalid datetime gracefully."""
        from core.reminders import schedule_reminders_for_appointment

        result = schedule_reminders_for_appointment(
            appointment_id=999,
            start_at="invalid-datetime",
            customer_email="test@example.com"
        )
        assert result == []


class TestCancelReminders:
    """Tests for cancel_reminders_for_appointment."""

    def test_cancel_reminders(self, sample_business):
        """Should cancel all reminders for appointment."""
        from core.reminders import schedule_reminders_for_appointment, cancel_reminders_for_appointment
        from core.db import transaction, get_conn

        future = datetime.now() + timedelta(days=2)
        with transaction() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO appointments (business_id, customer_name, start_at, status)
                VALUES (?, ?, ?, 'confirmed')
            """, (sample_business["id"], "Test", future.isoformat()))
            appt_id = cur.lastrowid

        schedule_reminders_for_appointment(
            appointment_id=appt_id,
            start_at=future.isoformat(),
            customer_email="test@example.com",
            customer_phone="555-1234"
        )

        cancelled_count = cancel_reminders_for_appointment(appt_id)
        assert cancelled_count >= 1

        # Verify status changed
        with get_conn() as con:
            rows = con.execute(
                "SELECT status FROM reminders WHERE appointment_id = ?",
                (appt_id,)
            ).fetchall()
            for row in rows:
                assert row["status"] == "cancelled"


class TestRescheduleReminders:
    """Tests for reschedule_reminders_for_appointment."""

    def test_reschedule_reminders(self, sample_business):
        """Should cancel old and create new reminders."""
        from core.reminders import schedule_reminders_for_appointment, reschedule_reminders_for_appointment
        from core.db import transaction

        future = datetime.now() + timedelta(days=2)
        with transaction() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO appointments (business_id, customer_name, start_at, status)
                VALUES (?, ?, ?, 'confirmed')
            """, (sample_business["id"], "Test", future.isoformat()))
            appt_id = cur.lastrowid

        schedule_reminders_for_appointment(
            appointment_id=appt_id,
            start_at=future.isoformat(),
            customer_email="test@example.com"
        )

        # Reschedule to a different time
        new_time = datetime.now() + timedelta(days=3)
        new_ids = reschedule_reminders_for_appointment(
            appointment_id=appt_id,
            new_start_at=new_time.isoformat(),
            customer_email="test@example.com"
        )
        assert len(new_ids) >= 1


class TestGetDueReminders:
    """Tests for get_due_reminders."""

    def test_get_due_reminders_empty(self):
        """Should return empty list when none due."""
        from core.reminders import get_due_reminders
        # Clear any existing due reminders
        from core.db import get_conn
        with get_conn() as con:
            con.execute("DELETE FROM reminders WHERE status = 'pending'")
            con.commit()

        result = get_due_reminders()
        assert isinstance(result, list)

    def test_get_due_reminders_returns_pending(self, sample_business):
        """Should return reminders scheduled for now or past."""
        from core.reminders import get_due_reminders
        from core.db import transaction

        # Create a reminder scheduled in the past
        past = datetime.now() - timedelta(minutes=5)
        with transaction() as con:
            cur = con.cursor()
            # First create appointment
            cur.execute("""
                INSERT INTO appointments (business_id, customer_name, start_at, status)
                VALUES (?, ?, ?, 'confirmed')
            """, (sample_business["id"], "Test", (past + timedelta(hours=1)).isoformat()))
            appt_id = cur.lastrowid

            # Create due reminder
            cur.execute("""
                INSERT INTO reminders (appointment_id, type, channel, scheduled_for, status)
                VALUES (?, '24h', 'email', ?, 'pending')
            """, (appt_id, past.isoformat()))

        due = get_due_reminders()
        assert len(due) >= 1


class TestGenerateReminderContent:
    """Tests for reminder content generation."""

    def test_generate_email_reminder(self):
        """Should generate email subject and body."""
        from core.reminders import generate_email_reminder

        reminder = {
            "appointment_id": 1,
            "type": "24h",
            "customer_name": "John Doe",
            "service": "Haircut",
            "start_at": (datetime.now() + timedelta(days=1)).isoformat(),
            "business_name": "Test Salon"
        }

        result = generate_email_reminder(reminder)
        assert "subject" in result
        assert "body" in result
        assert "John" in result["body"] or "appointment" in result["body"].lower()

    def test_generate_sms_reminder(self):
        """Should generate SMS text under 160 chars."""
        from core.reminders import generate_sms_reminder

        reminder = {
            "appointment_id": 1,
            "type": "1h",
            "customer_name": "John Doe",
            "service": "Haircut",
            "start_at": (datetime.now() + timedelta(hours=1)).isoformat(),
            "business_name": "Test Salon"
        }

        result = generate_sms_reminder(reminder)
        assert isinstance(result, str)
        assert len(result) <= 160


class TestSendReminder:
    """Tests for send_reminder function."""

    def test_send_email_reminder(self):
        """Should attempt to send email for email channel."""
        from core.reminders import send_reminder

        reminder = {
            "id": 1,
            "channel": "email",
            "appointment_id": 1,
            "type": "24h",
            "customer_email": "test@example.com",
            "customer_name": "John",
            "service": "Haircut",
            "start_at": datetime.now().isoformat(),
            "business_name": "Test"
        }

        # Will return success or failure based on email config
        success, error = send_reminder(reminder)
        # Returns tuple of (bool, str)
        assert isinstance(success, bool)
        assert isinstance(error, str)

    def test_send_sms_reminder(self):
        """Should attempt to send SMS for SMS channel."""
        from core.reminders import send_reminder

        reminder = {
            "id": 1,
            "channel": "sms",
            "appointment_id": 1,
            "type": "1h",
            "customer_phone": "555-1234",
            "customer_name": "John",
            "service": "Haircut",
            "start_at": datetime.now().isoformat(),
            "business_name": "Test"
        }

        success, error = send_reminder(reminder)
        # Returns tuple of (bool, str)
        assert isinstance(success, bool)
        assert isinstance(error, str)


class TestProcessDueReminders:
    """Tests for process_due_reminders function."""

    @patch("core.reminders.send_reminder")
    def test_process_due_reminders(self, mock_send):
        """Should process batch of due reminders."""
        from core.reminders import process_due_reminders

        mock_send.return_value = (True, None)
        result = process_due_reminders(batch_size=10)

        assert isinstance(result, dict)
        assert "processed" in result or "sent" in result or isinstance(result.get("sent"), int)
