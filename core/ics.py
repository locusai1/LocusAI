from datetime import datetime, timedelta
import uuid

def _fmt(dt: datetime) -> str:
    # naive local time; many calendars accept this; for prod you may want TZ handling
    return dt.strftime("%Y%m%dT%H%M%S")

def make_ics(summary: str, description: str, start: datetime, duration_min: int = 60, location: str = "") -> bytes:
    uid = f"{uuid.uuid4()}@locusai"
    dtstamp = _fmt(datetime.utcnow())
    dtstart = _fmt(start)
    dtend   = _fmt(start + timedelta(minutes=duration_min))
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
