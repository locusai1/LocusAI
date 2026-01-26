# core/validators.py — Input validation utilities for LocusAI
# Provides consistent, secure validation across the application

import re
import logging
from datetime import datetime
from typing import Optional, Tuple, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ============================================================================
# Email Validation
# ============================================================================

# RFC 5322 simplified email regex
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


def validate_email(email: Optional[str]) -> Tuple[bool, str]:
    """Validate an email address.

    Returns:
        (is_valid, cleaned_email_or_error_message)
    """
    if not email:
        return True, ""  # Empty email is OK (optional field)

    email = email.strip().lower()

    if len(email) > 254:  # RFC 5321
        return False, "Email address too long"

    if not EMAIL_REGEX.match(email):
        return False, "Invalid email format"

    return True, email


# ============================================================================
# Phone Validation
# ============================================================================

# Allow digits, spaces, dashes, parentheses, plus sign
PHONE_CLEANUP_REGEX = re.compile(r"[^\d+]")
PHONE_VALID_REGEX = re.compile(r"^\+?\d{7,15}$")


def validate_phone(phone: Optional[str]) -> Tuple[bool, str]:
    """Validate and normalize a phone number.

    Returns:
        (is_valid, cleaned_phone_or_error_message)
    """
    if not phone:
        return True, ""  # Empty phone is OK (optional field)

    phone = phone.strip()

    # Remove formatting characters
    cleaned = PHONE_CLEANUP_REGEX.sub("", phone)

    if not cleaned:
        return False, "Phone number contains no digits"

    if not PHONE_VALID_REGEX.match(cleaned):
        return False, "Phone number must be 7-15 digits"

    return True, cleaned


# ============================================================================
# Name Validation
# ============================================================================

def validate_name(name: Optional[str], field_name: str = "Name",
                  min_length: int = 1, max_length: int = 200) -> Tuple[bool, str]:
    """Validate a person/business name.

    Returns:
        (is_valid, cleaned_name_or_error_message)
    """
    if not name:
        return False, f"{field_name} is required"

    name = name.strip()

    if len(name) < min_length:
        return False, f"{field_name} must be at least {min_length} characters"

    if len(name) > max_length:
        return False, f"{field_name} must be at most {max_length} characters"

    # Check for control characters
    if any(ord(c) < 32 for c in name):
        return False, f"{field_name} contains invalid characters"

    return True, name


# ============================================================================
# Date/Time Validation
# ============================================================================

DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
]

DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
]


def validate_date(date_str: Optional[str]) -> Tuple[bool, Optional[datetime]]:
    """Validate and parse a date string.

    Returns:
        (is_valid, parsed_datetime_or_None)
    """
    if not date_str:
        return False, None

    date_str = date_str.strip()

    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str, fmt)
            return True, dt
        except ValueError:
            continue

    return False, None


def validate_datetime(dt_str: Optional[str]) -> Tuple[bool, Optional[datetime]]:
    """Validate and parse a datetime string.

    Returns:
        (is_valid, parsed_datetime_or_None)
    """
    if not dt_str:
        return False, None

    dt_str = dt_str.strip().replace("Z", "")

    # Try ISO format first
    try:
        dt = datetime.fromisoformat(dt_str)
        return True, dt
    except ValueError:
        pass

    # Try other formats
    for fmt in DATETIME_FORMATS:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return True, dt
        except ValueError:
            continue

    return False, None


def format_datetime(dt: datetime) -> str:
    """Format a datetime to standard format."""
    return dt.strftime("%Y-%m-%d %H:%M")


def format_date(dt: datetime) -> str:
    """Format a datetime to date only."""
    return dt.strftime("%Y-%m-%d")


# ============================================================================
# Slug Validation
# ============================================================================

SLUG_REGEX = re.compile(r"^[a-z0-9][a-z0-9\-_]*[a-z0-9]$|^[a-z0-9]$")
RESERVED_SLUGS = frozenset({
    "admin", "api", "auth", "login", "logout", "dashboard", "health",
    "appointments", "services", "chat", "kb", "integrations", "search",
    "static", "assets", "brand", "business", "new", "edit", "delete",
})


def validate_slug(slug: Optional[str], max_length: int = 50) -> Tuple[bool, str]:
    """Validate a URL slug.

    Returns:
        (is_valid, cleaned_slug_or_error_message)
    """
    if not slug:
        return False, "Slug is required"

    slug = slug.strip().lower()

    if len(slug) > max_length:
        return False, f"Slug must be at most {max_length} characters"

    if len(slug) < 2:
        return False, "Slug must be at least 2 characters"

    if not SLUG_REGEX.match(slug):
        return False, "Slug can only contain lowercase letters, numbers, hyphens, and underscores"

    if slug in RESERVED_SLUGS:
        return False, f"'{slug}' is a reserved word"

    return True, slug


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    if not text:
        return ""

    # Convert to lowercase
    slug = text.lower().strip()

    # Replace spaces and underscores with hyphens
    slug = re.sub(r"[\s_]+", "-", slug)

    # Remove non-alphanumeric characters (except hyphens)
    slug = re.sub(r"[^a-z0-9\-]", "", slug)

    # Remove multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)

    # Remove leading/trailing hyphens
    slug = slug.strip("-")

    return slug or "unnamed"


# ============================================================================
# URL Validation
# ============================================================================

ALLOWED_REDIRECT_PREFIXES = ("/",)


def validate_redirect_url(url: Optional[str], default: str = "/dashboard") -> str:
    """Validate a redirect URL to prevent open redirect attacks.

    Only allows relative URLs starting with /

    Returns:
        Safe redirect URL
    """
    if not url:
        return default

    url = url.strip()

    # Parse the URL
    try:
        parsed = urlparse(url)
    except Exception:
        return default

    # Must be a relative URL (no scheme or netloc)
    if parsed.scheme or parsed.netloc:
        logger.warning(f"Blocked potential open redirect: {url}")
        return default

    # Must start with allowed prefix
    if not any(url.startswith(prefix) for prefix in ALLOWED_REDIRECT_PREFIXES):
        return default

    # No double slashes (could be protocol-relative URL)
    if url.startswith("//"):
        return default

    return url


# ============================================================================
# Integer Validation
# ============================================================================

def safe_int(value: Optional[str], default: int = 0,
             min_val: Optional[int] = None,
             max_val: Optional[int] = None) -> int:
    """Safely parse an integer with optional bounds.

    Returns:
        Parsed integer, clamped to bounds if specified
    """
    if value is None:
        return default

    try:
        result = int(value)
    except (ValueError, TypeError):
        return default

    if min_val is not None and result < min_val:
        return min_val

    if max_val is not None and result > max_val:
        return max_val

    return result


# ============================================================================
# CSV Escaping
# ============================================================================

def csv_escape(value) -> str:
    """Escape a value for safe CSV output.

    Prevents formula injection and handles special characters.
    """
    if value is None:
        return ""

    value = str(value)

    # Prevent formula injection (Excel/Google Sheets)
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        value = "'" + value

    # Escape quotes and wrap in quotes if contains special chars
    if '"' in value or "," in value or "\n" in value or "\r" in value:
        value = '"' + value.replace('"', '""') + '"'

    return value


def build_csv_row(values: List) -> str:
    """Build a CSV row from a list of values."""
    return ",".join(csv_escape(v) for v in values) + "\n"


# ============================================================================
# Password Validation
# ============================================================================

def validate_password(password: Optional[str]) -> Tuple[bool, str]:
    """Validate password strength.

    Returns:
        (is_valid, error_message_or_empty)
    """
    if not password:
        return False, "Password is required"

    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    if len(password) > 128:
        return False, "Password must be at most 128 characters"

    # Check for at least one letter and one number
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)

    if not has_letter or not has_digit:
        return False, "Password must contain at least one letter and one number"

    return True, ""


# ============================================================================
# JSON Config Validation
# ============================================================================

def validate_json_config(json_str: Optional[str],
                        required_keys: Optional[List[str]] = None) -> Tuple[bool, dict, str]:
    """Validate a JSON configuration string.

    Returns:
        (is_valid, parsed_dict, error_message)
    """
    import json

    if not json_str:
        return True, {}, ""

    json_str = json_str.strip()
    if not json_str:
        return True, {}, ""

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return False, {}, f"Invalid JSON: {e}"

    if not isinstance(data, dict):
        return False, {}, "Config must be a JSON object"

    if required_keys:
        missing = [k for k in required_keys if k not in data]
        if missing:
            return False, {}, f"Missing required keys: {', '.join(missing)}"

    return True, data, ""
