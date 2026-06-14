import uuid
from datetime import datetime, timedelta
from typing import List


def _fmt(dt: datetime) -> str:
    # naive local time; many calendars accept this; for prod you may want TZ handling
    return dt.strftime("%Y%m%dT%H%M%S")


def _esc(text: str) -> str:
    """Escape an ICS text value per RFC 5545 (commas, semicolons, newlines)."""
    return (
        str(text or "")
        .replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def make_feed_ics(calendar_name: str, events: List[dict]) -> bytes:
    """Build a multi-event subscription feed (VCALENDAR with many VEVENTs).

    Each event dict: {uid, summary, description, location, start: datetime,
    duration_min: int}. Used for the per-business iCal subscription URL that
    Google / Outlook / Apple Calendar can subscribe to."""
    dtstamp = _fmt(datetime.utcnow())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LocusAI//Appointments//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(calendar_name)}",
    ]
    for ev in events:
        start = ev["start"]
        end = start + timedelta(minutes=ev.get("duration_min") or 30)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{ev.get('uid') or uuid.uuid4()}@locusai",
            f"DTSTAMP:{dtstamp}Z",
            f"DTSTART:{_fmt(start)}",
            f"DTEND:{_fmt(end)}",
            f"SUMMARY:{_esc(ev.get('summary', 'Appointment'))}",
            f"DESCRIPTION:{_esc(ev.get('description', ''))}",
            f"LOCATION:{_esc(ev.get('location', ''))}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def make_ics(
    summary: str, description: str, start: datetime, duration_min: int = 60, location: str = ""
) -> bytes:
    uid = f"{uuid.uuid4()}@locusai"
    dtstamp = _fmt(datetime.utcnow())
    dtstart = _fmt(start)
    dtend = _fmt(start + timedelta(minutes=duration_min))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LocusAI//Appointments//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}Z",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{description}".replace("\n", "\\n"),
        f"LOCATION:{location}".replace("\n", " "),
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")
