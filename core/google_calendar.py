# core/google_calendar.py — Google Calendar integration for LocusAI
# Handles OAuth2 flow, event sync, and availability checking

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Tuple, Any

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5050/integrations/google/callback")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

GOOGLE_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


# ============================================================================
# OAuth2 Flow
# ============================================================================

def get_oauth_flow(redirect_uri: Optional[str] = None):
    """Create a Google OAuth2 flow object.

    Returns:
        Flow object or None if not configured
    """
    if not GOOGLE_CONFIGURED:
        return None

    try:
        from google_auth_oauthlib.flow import Flow

        client_config = {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri or GOOGLE_REDIRECT_URI],
            }
        }

        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=redirect_uri or GOOGLE_REDIRECT_URI,
        )
        return flow
    except ImportError:
        logger.error("google-auth-oauthlib not installed")
        return None


def get_authorization_url(business_id: int, redirect_uri: Optional[str] = None) -> Optional[str]:
    """Generate the Google OAuth2 authorization URL.

    Args:
        business_id: Business to authorize for (stored in state)
        redirect_uri: Override redirect URI (for tunnel URLs)

    Returns:
        Authorization URL or None if not configured
    """
    flow = get_oauth_flow(redirect_uri)
    if not flow:
        return None

    import secrets
    state = f"{business_id}:{secrets.token_urlsafe(16)}"

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # Force refresh token
        state=state,
    )
    return auth_url


def exchange_code_for_tokens(
    code: str,
    redirect_uri: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Exchange authorization code for access + refresh tokens.

    Args:
        code: Authorization code from Google callback
        redirect_uri: Must match the redirect_uri used in authorization

    Returns:
        Token dict with access_token, refresh_token, expiry, etc.
    """
    flow = get_oauth_flow(redirect_uri)
    if not flow:
        return None

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials

        return {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else SCOPES,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        }
    except Exception as e:
        logger.error(f"Failed to exchange code for tokens: {e}")
        return None


def get_credentials_from_tokens(token_dict: Dict[str, Any]):
    """Reconstruct Google Credentials from stored token dict.

    Returns:
        google.oauth2.credentials.Credentials or None
    """
    try:
        from google.oauth2.credentials import Credentials

        expiry = None
        if token_dict.get("expiry"):
            try:
                expiry = datetime.fromisoformat(token_dict["expiry"])
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        creds = Credentials(
            token=token_dict.get("access_token"),
            refresh_token=token_dict.get("refresh_token"),
            token_uri=token_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_dict.get("client_id") or GOOGLE_CLIENT_ID,
            client_secret=token_dict.get("client_secret") or GOOGLE_CLIENT_SECRET,
            scopes=token_dict.get("scopes", SCOPES),
            expiry=expiry,
        )
        return creds
    except ImportError:
        logger.error("google-auth not installed")
        return None


def refresh_credentials_if_needed(creds, token_dict: Dict) -> Tuple[Any, Dict]:
    """Refresh credentials if expired, return updated creds and token dict."""
    try:
        from google.auth.transport.requests import Request
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Update stored tokens
            token_dict["access_token"] = creds.token
            if creds.expiry:
                token_dict["expiry"] = creds.expiry.isoformat()
    except Exception as e:
        logger.warning(f"Failed to refresh Google credentials: {e}")
    return creds, token_dict


# ============================================================================
# Calendar API
# ============================================================================

def get_calendar_service(token_dict: Dict[str, Any]):
    """Build a Google Calendar API service from stored tokens.

    Returns:
        googleapiclient Resource or None
    """
    creds = get_credentials_from_tokens(token_dict)
    if not creds:
        return None, token_dict

    # Refresh if needed
    creds, token_dict = refresh_credentials_if_needed(creds, token_dict)

    try:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return service, token_dict
    except Exception as e:
        logger.error(f"Failed to build Calendar service: {e}")
        return None, token_dict


def list_calendars(token_dict: Dict[str, Any]) -> List[Dict]:
    """List all calendars accessible by the authenticated user.

    Returns:
        List of calendar dicts with id, summary, primary
    """
    service, token_dict = get_calendar_service(token_dict)
    if not service:
        return []

    try:
        result = service.calendarList().list().execute()
        calendars = []
        for item in result.get("items", []):
            calendars.append({
                "id": item["id"],
                "name": item.get("summary", item["id"]),
                "primary": item.get("primary", False),
                "color": item.get("backgroundColor"),
            })
        return calendars
    except Exception as e:
        logger.error(f"Failed to list calendars: {e}")
        return []


def get_busy_slots(
    token_dict: Dict[str, Any],
    calendar_id: str,
    start_date: str,
    end_date: str,
) -> List[Dict[str, str]]:
    """Get busy time slots from Google Calendar.

    Args:
        token_dict: Stored OAuth tokens
        calendar_id: Google Calendar ID (e.g. "primary")
        start_date: ISO date string (YYYY-MM-DD)
        end_date: ISO date string (YYYY-MM-DD)

    Returns:
        List of {'start': ISO, 'end': ISO} dicts
    """
    service, token_dict = get_calendar_service(token_dict)
    if not service:
        return []

    try:
        # Convert to RFC3339 format
        start_dt = datetime.fromisoformat(start_date).replace(
            hour=0, minute=0, second=0, tzinfo=timezone.utc
        )
        end_dt = datetime.fromisoformat(end_date).replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

        body = {
            "timeMin": start_dt.isoformat(),
            "timeMax": end_dt.isoformat(),
            "items": [{"id": calendar_id}],
            "timeZone": "UTC",
        }

        result = service.freebusy().query(body=body).execute()
        busy = result.get("calendars", {}).get(calendar_id, {}).get("busy", [])

        return [{"start": b["start"], "end": b["end"]} for b in busy]

    except Exception as e:
        logger.error(f"Failed to get busy slots: {e}")
        return []


def create_calendar_event(
    token_dict: Dict[str, Any],
    calendar_id: str,
    summary: str,
    start_at: str,
    duration_min: int = 60,
    description: str = "",
    location: str = "",
    attendee_email: Optional[str] = None,
) -> Optional[Dict]:
    """Create an event in Google Calendar.

    Args:
        token_dict: Stored OAuth tokens
        calendar_id: Calendar ID to create event in
        summary: Event title
        start_at: ISO datetime string (YYYY-MM-DD HH:MM or full ISO)
        duration_min: Duration in minutes
        description: Event description
        location: Event location
        attendee_email: Optional attendee email

    Returns:
        Created event dict with id, htmlLink, etc. or None
    """
    service, token_dict = get_calendar_service(token_dict)
    if not service:
        return None

    try:
        # Parse start time
        start_dt = datetime.fromisoformat(start_at.replace("Z", "").replace(" ", "T"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(minutes=duration_min)

        event = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "UTC",
            },
        }

        if attendee_email:
            event["attendees"] = [{"email": attendee_email}]

        result = service.events().insert(calendarId=calendar_id, body=event).execute()
        logger.info(f"Created Google Calendar event: {result.get('id')} — {summary}")
        return result

    except Exception as e:
        logger.error(f"Failed to create calendar event: {e}")
        return None


def delete_calendar_event(
    token_dict: Dict[str, Any],
    calendar_id: str,
    event_id: str,
) -> bool:
    """Delete an event from Google Calendar.

    Args:
        token_dict: Stored OAuth tokens
        calendar_id: Calendar ID containing the event
        event_id: Google Calendar event ID

    Returns:
        True if deleted successfully
    """
    service, token_dict = get_calendar_service(token_dict)
    if not service:
        return False

    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        logger.info(f"Deleted Google Calendar event: {event_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete calendar event {event_id}: {e}")
        return False


def update_calendar_event(
    token_dict: Dict[str, Any],
    calendar_id: str,
    event_id: str,
    start_at: str,
    duration_min: int = 60,
    summary: Optional[str] = None,
) -> bool:
    """Update an existing Google Calendar event.

    Args:
        token_dict: Stored OAuth tokens
        calendar_id: Calendar ID
        event_id: Google Calendar event ID
        start_at: New start time ISO string
        duration_min: New duration

    Returns:
        True if updated successfully
    """
    service, token_dict = get_calendar_service(token_dict)
    if not service:
        return False

    try:
        # Fetch existing event
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

        # Update fields
        start_dt = datetime.fromisoformat(start_at.replace("Z", "").replace(" ", "T"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(minutes=duration_min)

        event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": "UTC"}
        event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": "UTC"}
        if summary:
            event["summary"] = summary

        service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
        logger.info(f"Updated Google Calendar event: {event_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to update calendar event {event_id}: {e}")
        return False


# ============================================================================
# Business-level sync helpers
# ============================================================================

def get_business_gcal_config(business_id: int) -> Optional[Dict]:
    """Get stored Google Calendar config for a business.

    Returns:
        Dict with tokens and calendar_id, or None
    """
    from core.db import get_conn

    with get_conn() as con:
        row = con.execute(
            """SELECT account_json FROM integrations
               WHERE business_id = ? AND provider_key = 'google_calendar'
               AND status = 'active' LIMIT 1""",
            (business_id,)
        ).fetchone()

        if not row or not row["account_json"]:
            return None

        try:
            return json.loads(row["account_json"])
        except Exception:
            return None


def save_business_gcal_config(business_id: int, config: Dict) -> bool:
    """Save Google Calendar config for a business."""
    from core.db import transaction

    try:
        with transaction() as con:
            con.execute(
                """INSERT INTO integrations (business_id, provider_key, status, account_json, updated_at)
                   VALUES (?, 'google_calendar', 'active', ?, datetime('now'))
                   ON CONFLICT(business_id, provider_key)
                   DO UPDATE SET status='active', account_json=excluded.account_json, updated_at=excluded.updated_at""",
                (business_id, json.dumps(config))
            )
        return True
    except Exception as e:
        logger.error(f"Failed to save Google Calendar config: {e}")
        return False


def disconnect_gcal(business_id: int) -> bool:
    """Disconnect Google Calendar for a business."""
    from core.db import transaction

    try:
        with transaction() as con:
            con.execute(
                """UPDATE integrations SET status='inactive', updated_at=datetime('now')
                   WHERE business_id = ? AND provider_key = 'google_calendar'""",
                (business_id,)
            )
        return True
    except Exception as e:
        logger.error(f"Failed to disconnect Google Calendar: {e}")
        return False


def sync_appointment_to_gcal(appointment_id: int) -> Tuple[bool, str]:
    """Push a LocusAI appointment to Google Calendar.

    Called after creating or updating an appointment.

    Returns:
        (success, message)
    """
    from core.db import get_conn, transaction

    with get_conn() as con:
        appt = con.execute(
            """SELECT a.*, b.name as biz_name, b.address as biz_address
               FROM appointments a
               JOIN businesses b ON a.business_id = b.id
               WHERE a.id = ?""",
            (appointment_id,)
        ).fetchone()

    if not appt:
        return False, "Appointment not found"

    appt = dict(appt)
    config = get_business_gcal_config(appt["business_id"])
    if not config:
        return False, "Google Calendar not connected"

    calendar_id = config.get("calendar_id", "primary")
    tokens = config.get("tokens", {})

    # Get service duration
    duration_min = 60
    with get_conn() as con:
        svc = con.execute(
            "SELECT duration_min FROM services WHERE business_id = ? AND name = ?",
            (appt["business_id"], appt.get("service"))
        ).fetchone()
        if svc:
            duration_min = svc["duration_min"]

    summary = f"{appt.get('service', 'Appointment')} — {appt.get('customer_name', 'Client')}"
    description = (
        f"Booked via LocusAI\n"
        f"Service: {appt.get('service', '')}\n"
        f"Customer: {appt.get('customer_name', '')}\n"
        f"Phone: {appt.get('phone', '')}\n"
        f"Email: {appt.get('customer_email', '')}"
    )

    # Check if already synced
    external_id = appt.get("external_id")
    if external_id and external_id.startswith("gcal:"):
        event_id = external_id[5:]
        # Update existing event
        success = update_calendar_event(
            tokens, calendar_id, event_id,
            appt["start_at"], duration_min, summary
        )
        if success:
            return True, f"Google Calendar event updated"
        return False, "Failed to update calendar event"

    # Create new event
    event = create_calendar_event(
        tokens, calendar_id, summary,
        appt["start_at"], duration_min,
        description=description,
        location=appt.get("biz_address", ""),
        attendee_email=appt.get("customer_email"),
    )

    if event:
        # Store the Google Calendar event ID
        gcal_id = f"gcal:{event['id']}"
        try:
            with transaction() as con:
                con.execute(
                    "UPDATE appointments SET external_id = ? WHERE id = ?",
                    (gcal_id, appointment_id)
                )
        except Exception:
            pass
        return True, f"Synced to Google Calendar"

    return False, "Failed to create calendar event"


def delete_appointment_from_gcal(appointment_id: int) -> Tuple[bool, str]:
    """Remove a cancelled appointment from Google Calendar."""
    from core.db import get_conn

    with get_conn() as con:
        appt = con.execute(
            "SELECT * FROM appointments WHERE id = ?",
            (appointment_id,)
        ).fetchone()

    if not appt:
        return False, "Appointment not found"

    appt = dict(appt)
    external_id = appt.get("external_id", "")
    if not external_id or not external_id.startswith("gcal:"):
        return False, "No Google Calendar event linked"

    config = get_business_gcal_config(appt["business_id"])
    if not config:
        return False, "Google Calendar not connected"

    event_id = external_id[5:]
    calendar_id = config.get("calendar_id", "primary")
    tokens = config.get("tokens", {})

    success = delete_calendar_event(tokens, calendar_id, event_id)
    return (True, "Removed from Google Calendar") if success else (False, "Failed to remove from Calendar")


def is_slot_available_gcal(
    business_id: int,
    start_at: str,
    duration_min: int = 60,
) -> bool:
    """Check if a time slot is free in Google Calendar.

    Returns True if available (no conflicts), False if busy.
    If Google Calendar not connected, returns True (don't block booking).
    """
    config = get_business_gcal_config(business_id)
    if not config:
        return True  # Can't check → assume available

    tokens = config.get("tokens", {})
    calendar_id = config.get("calendar_id", "primary")

    try:
        start_dt = datetime.fromisoformat(start_at.replace("Z", "").replace(" ", "T"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(minutes=duration_min)

        date_str = start_dt.date().isoformat()
        busy_slots = get_busy_slots(tokens, calendar_id, date_str, date_str)

        for slot in busy_slots:
            try:
                busy_start = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
                busy_end = datetime.fromisoformat(slot["end"].replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    busy_start = busy_start.replace(tzinfo=None)
                    busy_end = busy_end.replace(tzinfo=None)
                # Check for overlap
                if start_dt < busy_end and end_dt > busy_start:
                    return False
            except Exception:
                continue

        return True

    except Exception as e:
        logger.warning(f"Google Calendar availability check failed: {e}")
        return True  # Fail open
