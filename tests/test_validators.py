# tests/test_validators.py — Tests for core/validators.py
# Comprehensive validation testing for input sanitization and security

import pytest
from datetime import datetime

from core.validators import (
    validate_email,
    validate_phone,
    validate_name,
    validate_date,
    validate_datetime,
    validate_slug,
    validate_redirect_url,
    validate_password,
    validate_json_config,
    safe_int,
    slugify,
    csv_escape,
    build_csv_row,
    format_datetime,
    format_date,
)


# ============================================================================
# Email Validation Tests
# ============================================================================

class TestValidateEmail:
    """Tests for email validation."""

    def test_valid_email(self):
        is_valid, result = validate_email("user@example.com")
        assert is_valid is True
        assert result == "user@example.com"

    def test_valid_email_with_subdomain(self):
        is_valid, result = validate_email("user@mail.example.co.uk")
        assert is_valid is True
        assert result == "user@mail.example.co.uk"

    def test_valid_email_with_plus(self):
        is_valid, result = validate_email("user+tag@example.com")
        assert is_valid is True
        assert result == "user+tag@example.com"

    def test_email_normalized_to_lowercase(self):
        is_valid, result = validate_email("User@EXAMPLE.COM")
        assert is_valid is True
        assert result == "user@example.com"

    def test_email_whitespace_stripped(self):
        is_valid, result = validate_email("  user@example.com  ")
        assert is_valid is True
        assert result == "user@example.com"

    def test_empty_email_is_valid(self):
        # Empty email is valid (optional field)
        is_valid, result = validate_email("")
        assert is_valid is True
        assert result == ""

    def test_none_email_is_valid(self):
        is_valid, result = validate_email(None)
        assert is_valid is True
        assert result == ""

    def test_invalid_email_no_at(self):
        is_valid, result = validate_email("userexample.com")
        assert is_valid is False
        assert "Invalid email" in result

    def test_invalid_email_no_domain(self):
        is_valid, result = validate_email("user@")
        assert is_valid is False
        assert "Invalid email" in result

    def test_invalid_email_multiple_at(self):
        is_valid, result = validate_email("user@@example.com")
        assert is_valid is False
        assert "Invalid email" in result

    def test_email_too_long(self):
        long_email = "a" * 250 + "@example.com"
        is_valid, result = validate_email(long_email)
        assert is_valid is False
        assert "too long" in result


# ============================================================================
# Phone Validation Tests
# ============================================================================

class TestValidatePhone:
    """Tests for phone number validation."""

    def test_valid_phone_digits_only(self):
        is_valid, result = validate_phone("5551234567")
        assert is_valid is True
        assert result == "5551234567"

    def test_valid_phone_with_formatting(self):
        is_valid, result = validate_phone("(555) 123-4567")
        assert is_valid is True
        assert result == "5551234567"

    def test_valid_phone_international(self):
        is_valid, result = validate_phone("+1-555-123-4567")
        assert is_valid is True
        assert result == "+15551234567"

    def test_valid_phone_with_spaces(self):
        is_valid, result = validate_phone("555 123 4567")
        assert is_valid is True
        assert result == "5551234567"

    def test_empty_phone_is_valid(self):
        # Empty phone is valid (optional field)
        is_valid, result = validate_phone("")
        assert is_valid is True
        assert result == ""

    def test_none_phone_is_valid(self):
        is_valid, result = validate_phone(None)
        assert is_valid is True
        assert result == ""

    def test_phone_too_short(self):
        is_valid, result = validate_phone("12345")
        assert is_valid is False
        assert "7-15 digits" in result

    def test_phone_too_long(self):
        is_valid, result = validate_phone("1234567890123456")
        assert is_valid is False
        assert "7-15 digits" in result

    def test_phone_no_digits(self):
        is_valid, result = validate_phone("abc-def-ghij")
        assert is_valid is False
        assert "no digits" in result


# ============================================================================
# Name Validation Tests
# ============================================================================

class TestValidateName:
    """Tests for name validation."""

    def test_valid_name(self):
        is_valid, result = validate_name("John Doe")
        assert is_valid is True
        assert result == "John Doe"

    def test_name_whitespace_stripped(self):
        is_valid, result = validate_name("  Jane Smith  ")
        assert is_valid is True
        assert result == "Jane Smith"

    def test_empty_name_is_required(self):
        is_valid, result = validate_name("")
        assert is_valid is False
        assert "required" in result

    def test_none_name_is_required(self):
        is_valid, result = validate_name(None)
        assert is_valid is False
        assert "required" in result

    def test_name_too_short(self):
        is_valid, result = validate_name("", min_length=2)
        assert is_valid is False

    def test_name_too_long(self):
        long_name = "A" * 201
        is_valid, result = validate_name(long_name, max_length=200)
        assert is_valid is False
        assert "at most 200" in result

    def test_name_with_control_characters(self):
        is_valid, result = validate_name("John\x00Doe")
        assert is_valid is False
        assert "invalid characters" in result

    def test_custom_field_name(self):
        is_valid, result = validate_name("", field_name="Company Name")
        assert is_valid is False
        assert "Company Name is required" in result


# ============================================================================
# Date/Time Validation Tests
# ============================================================================

class TestValidateDate:
    """Tests for date validation."""

    def test_valid_date_iso(self):
        is_valid, result = validate_date("2026-01-15")
        assert is_valid is True
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 15

    def test_valid_date_slash_format(self):
        is_valid, result = validate_date("01/15/2026")
        assert is_valid is True
        assert result.month == 1 or result.day == 1  # Could be US or EU format

    def test_invalid_date(self):
        is_valid, result = validate_date("not-a-date")
        assert is_valid is False
        assert result is None

    def test_empty_date(self):
        is_valid, result = validate_date("")
        assert is_valid is False
        assert result is None


class TestValidateDatetime:
    """Tests for datetime validation."""

    def test_valid_datetime_space(self):
        is_valid, result = validate_datetime("2026-01-15 10:30")
        assert is_valid is True
        assert result.hour == 10
        assert result.minute == 30

    def test_valid_datetime_t_separator(self):
        is_valid, result = validate_datetime("2026-01-15T10:30")
        assert is_valid is True
        assert result.hour == 10

    def test_valid_datetime_with_seconds(self):
        is_valid, result = validate_datetime("2026-01-15 10:30:45")
        assert is_valid is True
        assert result.second == 45

    def test_valid_datetime_iso_z(self):
        is_valid, result = validate_datetime("2026-01-15T10:30:00Z")
        assert is_valid is True

    def test_invalid_datetime(self):
        is_valid, result = validate_datetime("not-a-datetime")
        assert is_valid is False
        assert result is None


class TestFormatDatetime:
    """Tests for datetime formatting."""

    def test_format_datetime(self):
        dt = datetime(2026, 1, 15, 10, 30, 0)
        result = format_datetime(dt)
        assert result == "2026-01-15 10:30"

    def test_format_date(self):
        dt = datetime(2026, 1, 15, 10, 30, 0)
        result = format_date(dt)
        assert result == "2026-01-15"


# ============================================================================
# Slug Validation Tests
# ============================================================================

class TestValidateSlug:
    """Tests for URL slug validation."""

    def test_valid_slug(self):
        is_valid, result = validate_slug("my-business")
        assert is_valid is True
        assert result == "my-business"

    def test_slug_normalized_to_lowercase(self):
        is_valid, result = validate_slug("My-Business")
        assert is_valid is True
        assert result == "my-business"

    def test_slug_with_underscores(self):
        is_valid, result = validate_slug("my_business")
        assert is_valid is True
        assert result == "my_business"

    def test_empty_slug(self):
        is_valid, result = validate_slug("")
        assert is_valid is False
        assert "required" in result

    def test_slug_too_short(self):
        is_valid, result = validate_slug("a")
        assert is_valid is False
        assert "at least 2" in result

    def test_slug_too_long(self):
        long_slug = "a" * 51
        is_valid, result = validate_slug(long_slug, max_length=50)
        assert is_valid is False
        assert "at most 50" in result

    def test_slug_invalid_characters(self):
        is_valid, result = validate_slug("my business!")
        assert is_valid is False
        assert "can only contain" in result

    def test_reserved_slug(self):
        is_valid, result = validate_slug("admin")
        assert is_valid is False
        assert "reserved" in result

    def test_reserved_slug_login(self):
        is_valid, result = validate_slug("login")
        assert is_valid is False
        assert "reserved" in result


class TestSlugify:
    """Tests for slugify function."""

    def test_slugify_simple(self):
        result = slugify("My Business Name")
        assert result == "my-business-name"

    def test_slugify_special_characters(self):
        result = slugify("John's Café & Bar!")
        assert result == "johns-caf-bar"

    def test_slugify_underscores(self):
        result = slugify("my_business_name")
        assert result == "my-business-name"

    def test_slugify_multiple_spaces(self):
        result = slugify("my   business   name")
        assert result == "my-business-name"

    def test_slugify_empty(self):
        result = slugify("")
        assert result == ""

    def test_slugify_only_special_chars(self):
        result = slugify("!!!@@@###")
        assert result == "unnamed"


# ============================================================================
# URL Redirect Validation Tests (Security Critical)
# ============================================================================

class TestValidateRedirectUrl:
    """Tests for redirect URL validation (prevents open redirect attacks)."""

    def test_valid_relative_url(self):
        result = validate_redirect_url("/dashboard")
        assert result == "/dashboard"

    def test_valid_relative_url_with_params(self):
        result = validate_redirect_url("/search?q=test")
        assert result == "/search?q=test"

    def test_empty_url_returns_default(self):
        result = validate_redirect_url("")
        assert result == "/dashboard"

    def test_none_url_returns_default(self):
        result = validate_redirect_url(None)
        assert result == "/dashboard"

    def test_absolute_url_blocked(self):
        result = validate_redirect_url("https://evil.com/steal")
        assert result == "/dashboard"

    def test_protocol_relative_url_blocked(self):
        result = validate_redirect_url("//evil.com/steal")
        assert result == "/dashboard"

    def test_javascript_url_blocked(self):
        result = validate_redirect_url("javascript:alert(1)")
        assert result == "/dashboard"

    def test_custom_default(self):
        result = validate_redirect_url(None, default="/home")
        assert result == "/home"


# ============================================================================
# Password Validation Tests
# ============================================================================

class TestValidatePassword:
    """Tests for password strength validation."""

    def test_valid_password(self):
        is_valid, error = validate_password("SecurePass123")
        assert is_valid is True
        assert error == ""

    def test_password_with_special_chars(self):
        is_valid, error = validate_password("P@ssw0rd!#$")
        assert is_valid is True

    def test_empty_password(self):
        is_valid, error = validate_password("")
        assert is_valid is False
        assert "required" in error

    def test_none_password(self):
        is_valid, error = validate_password(None)
        assert is_valid is False
        assert "required" in error

    def test_password_too_short(self):
        is_valid, error = validate_password("Pass1")
        assert is_valid is False
        assert "at least 8" in error

    def test_password_too_long(self):
        long_pass = "A1" * 65
        is_valid, error = validate_password(long_pass)
        assert is_valid is False
        assert "at most 128" in error

    def test_password_no_letter(self):
        is_valid, error = validate_password("12345678")
        assert is_valid is False
        assert "letter" in error

    def test_password_no_number(self):
        is_valid, error = validate_password("abcdefgh")
        assert is_valid is False
        assert "number" in error


# ============================================================================
# Safe Integer Tests
# ============================================================================

class TestSafeInt:
    """Tests for safe integer parsing."""

    def test_valid_int(self):
        result = safe_int("42")
        assert result == 42

    def test_valid_negative_int(self):
        result = safe_int("-10")
        assert result == -10

    def test_invalid_int_returns_default(self):
        result = safe_int("not_a_number", default=0)
        assert result == 0

    def test_none_returns_default(self):
        result = safe_int(None, default=5)
        assert result == 5

    def test_min_value_clamping(self):
        result = safe_int("-100", min_val=0)
        assert result == 0

    def test_max_value_clamping(self):
        result = safe_int("1000", max_val=100)
        assert result == 100

    def test_min_and_max_clamping(self):
        result = safe_int("50", min_val=1, max_val=100)
        assert result == 50


# ============================================================================
# CSV Escape Tests (Security Critical)
# ============================================================================

class TestCsvEscape:
    """Tests for CSV escaping (prevents formula injection)."""

    def test_normal_string(self):
        result = csv_escape("Hello World")
        assert result == "Hello World"

    def test_escape_formula_equals(self):
        result = csv_escape("=SUM(A1:A10)")
        assert result.startswith("'")
        assert "=SUM" in result

    def test_escape_formula_plus(self):
        result = csv_escape("+1234567890")
        assert result.startswith("'")

    def test_escape_formula_minus(self):
        result = csv_escape("-1+2")
        assert result.startswith("'")

    def test_escape_formula_at(self):
        result = csv_escape("@SUM(A1)")
        assert result.startswith("'")

    def test_escape_quotes(self):
        result = csv_escape('Hello "World"')
        assert '""' in result
        assert result.startswith('"')
        assert result.endswith('"')

    def test_escape_comma(self):
        result = csv_escape("Hello, World")
        assert result.startswith('"')
        assert result.endswith('"')

    def test_escape_newline(self):
        result = csv_escape("Hello\nWorld")
        assert result.startswith('"')
        assert result.endswith('"')

    def test_none_value(self):
        result = csv_escape(None)
        assert result == ""


class TestBuildCsvRow:
    """Tests for CSV row building."""

    def test_simple_row(self):
        result = build_csv_row(["a", "b", "c"])
        assert result == "a,b,c\n"

    def test_row_with_special_chars(self):
        result = build_csv_row(["Hello, World", "Test"])
        assert '"Hello, World"' in result
        assert "Test" in result


# ============================================================================
# JSON Config Validation Tests
# ============================================================================

class TestValidateJsonConfig:
    """Tests for JSON configuration validation."""

    def test_valid_json(self):
        is_valid, data, error = validate_json_config('{"key": "value"}')
        assert is_valid is True
        assert data == {"key": "value"}
        assert error == ""

    def test_empty_string_is_valid(self):
        is_valid, data, error = validate_json_config("")
        assert is_valid is True
        assert data == {}

    def test_none_is_valid(self):
        is_valid, data, error = validate_json_config(None)
        assert is_valid is True
        assert data == {}

    def test_invalid_json(self):
        is_valid, data, error = validate_json_config("{invalid json}")
        assert is_valid is False
        assert "Invalid JSON" in error

    def test_non_object_json(self):
        is_valid, data, error = validate_json_config('["array"]')
        assert is_valid is False
        assert "object" in error

    def test_missing_required_keys(self):
        is_valid, data, error = validate_json_config(
            '{"a": 1}',
            required_keys=["a", "b"]
        )
        assert is_valid is False
        assert "Missing required keys" in error
        assert "b" in error

    def test_all_required_keys_present(self):
        is_valid, data, error = validate_json_config(
            '{"a": 1, "b": 2}',
            required_keys=["a", "b"]
        )
        assert is_valid is True
