# tests/test_ics.py — Tests for core/ics.py (iCalendar Generation)

import pytest
from datetime import datetime, timedelta


class TestMakeIcs:
    """Tests for make_ics function."""

    def test_make_ics_returns_bytes(self):
        """Should return bytes."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test Appointment",
            description="Test description",
            start=datetime.now() + timedelta(days=1)
        )
        assert isinstance(result, bytes)

    def test_make_ics_utf8_encoded(self):
        """Should be UTF-8 encoded."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test Appointment",
            description="Test description",
            start=datetime.now() + timedelta(days=1)
        )
        # Should decode without errors
        text = result.decode("utf-8")
        assert isinstance(text, str)

    def test_make_ics_vcalendar_format(self):
        """Should have proper VCALENDAR structure."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Desc",
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        assert "BEGIN:VCALENDAR" in result
        assert "END:VCALENDAR" in result
        assert "BEGIN:VEVENT" in result
        assert "END:VEVENT" in result

    def test_make_ics_contains_summary(self):
        """Should include the summary."""
        from core.ics import make_ics
        result = make_ics(
            summary="My Haircut Appointment",
            description="Desc",
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        assert "SUMMARY:My Haircut Appointment" in result

    def test_make_ics_contains_description(self):
        """Should include the description."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Appointment at Test Salon for haircut",
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        assert "DESCRIPTION:" in result
        assert "Test Salon" in result

    def test_make_ics_contains_location(self):
        """Should include location when provided."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Desc",
            start=datetime.now() + timedelta(days=1),
            location="123 Main Street, City"
        ).decode("utf-8")

        assert "LOCATION:123 Main Street" in result

    def test_make_ics_default_duration(self):
        """Should use default 60 minute duration."""
        from core.ics import make_ics
        start = datetime(2026, 3, 15, 14, 0)  # 2:00 PM
        result = make_ics(
            summary="Test",
            description="Desc",
            start=start
        ).decode("utf-8")

        # DTSTART should be 14:00, DTEND should be 15:00
        assert "DTSTART:20260315T140000" in result
        assert "DTEND:20260315T150000" in result

    def test_make_ics_custom_duration(self):
        """Should respect custom duration."""
        from core.ics import make_ics
        start = datetime(2026, 3, 15, 14, 0)  # 2:00 PM
        result = make_ics(
            summary="Test",
            description="Desc",
            start=start,
            duration_min=30
        ).decode("utf-8")

        # DTSTART should be 14:00, DTEND should be 14:30
        assert "DTSTART:20260315T140000" in result
        assert "DTEND:20260315T143000" in result

    def test_make_ics_contains_uid(self):
        """Should contain unique identifier."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Desc",
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        assert "UID:" in result

    def test_make_ics_unique_uids(self):
        """Should generate unique UIDs for each call."""
        from core.ics import make_ics
        start = datetime.now() + timedelta(days=1)

        result1 = make_ics(summary="Test1", description="Desc", start=start).decode("utf-8")
        result2 = make_ics(summary="Test2", description="Desc", start=start).decode("utf-8")

        # Extract UIDs
        uid1 = [line for line in result1.split("\r\n") if line.startswith("UID:")][0]
        uid2 = [line for line in result2.split("\r\n") if line.startswith("UID:")][0]

        assert uid1 != uid2

    def test_make_ics_contains_dtstamp(self):
        """Should contain timestamp of creation."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Desc",
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        assert "DTSTAMP:" in result

    def test_make_ics_version_2(self):
        """Should specify VERSION:2.0."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Desc",
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        assert "VERSION:2.0" in result

    def test_make_ics_prodid(self):
        """Should include PRODID."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Desc",
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        assert "PRODID:" in result

    def test_make_ics_crlf_line_endings(self):
        """Should use CRLF line endings per iCalendar spec."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Desc",
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        assert "\r\n" in result

    def test_make_ics_escapes_newlines_in_description(self):
        """Should escape newlines in description."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Line one\nLine two\nLine three",
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        # Newlines in content should be escaped as \n
        assert "Line one\\nLine two" in result

    def test_make_ics_handles_unicode(self):
        """Should handle unicode characters."""
        from core.ics import make_ics
        result = make_ics(
            summary="Appointment at Café René",
            description="Meeting with José García",
            start=datetime.now() + timedelta(days=1),
            location="München, Germany"
        ).decode("utf-8")

        assert "Café" in result
        assert "José" in result
        assert "München" in result


class TestDateFormatting:
    """Tests for _fmt helper function."""

    def test_fmt_basic_date(self):
        """Should format datetime correctly."""
        from core.ics import _fmt
        dt = datetime(2026, 1, 15, 9, 30, 0)
        result = _fmt(dt)
        assert result == "20260115T093000"

    def test_fmt_midnight(self):
        """Should format midnight correctly."""
        from core.ics import _fmt
        dt = datetime(2026, 12, 31, 0, 0, 0)
        result = _fmt(dt)
        assert result == "20261231T000000"

    def test_fmt_end_of_day(self):
        """Should format end of day correctly."""
        from core.ics import _fmt
        dt = datetime(2026, 6, 15, 23, 59, 59)
        result = _fmt(dt)
        assert result == "20260615T235959"


class TestEdgeCases:
    """Tests for edge cases."""

    def test_make_ics_empty_location(self):
        """Should handle empty location."""
        from core.ics import make_ics
        result = make_ics(
            summary="Test",
            description="Desc",
            start=datetime.now() + timedelta(days=1),
            location=""
        ).decode("utf-8")

        assert "LOCATION:" in result

    def test_make_ics_long_description(self):
        """Should handle long description."""
        from core.ics import make_ics
        long_desc = "This is a very long description. " * 50
        result = make_ics(
            summary="Test",
            description=long_desc,
            start=datetime.now() + timedelta(days=1)
        ).decode("utf-8")

        assert "DESCRIPTION:" in result

    def test_make_ics_zero_duration(self):
        """Should handle zero duration (event with no duration)."""
        from core.ics import make_ics
        start = datetime(2026, 3, 15, 14, 0)
        result = make_ics(
            summary="Test",
            description="Desc",
            start=start,
            duration_min=0
        ).decode("utf-8")

        # DTSTART and DTEND should be the same
        assert "DTSTART:20260315T140000" in result
        assert "DTEND:20260315T140000" in result

    def test_make_ics_multi_hour_duration(self):
        """Should handle multi-hour duration."""
        from core.ics import make_ics
        start = datetime(2026, 3, 15, 10, 0)
        result = make_ics(
            summary="Test",
            description="Desc",
            start=start,
            duration_min=180  # 3 hours
        ).decode("utf-8")

        assert "DTSTART:20260315T100000" in result
        assert "DTEND:20260315T130000" in result
