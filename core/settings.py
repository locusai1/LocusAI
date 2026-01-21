import os
import secrets

# ===== Flask / App =====
# Generate a secure random key if not provided via environment variable
# WARNING: In production, always set FLASK_SECRET_KEY in your environment!
_env_secret = os.getenv("FLASK_SECRET_KEY")
if _env_secret and _env_secret not in ("dev-secret-change-me", "ksks9k3kehejed"):
    FLASK_SECRET_KEY = _env_secret
else:
    # Generate a cryptographically secure random key
    # Note: This changes on restart, so sessions will be invalidated
    FLASK_SECRET_KEY = secrets.token_hex(32)
    import sys
    print("WARNING: No secure FLASK_SECRET_KEY set. Generated temporary key.", file=sys.stderr)
    print("Set FLASK_SECRET_KEY environment variable for persistent sessions.", file=sys.stderr)
APP_BASE_URL     = os.getenv("APP_BASE_URL", "http://127.0.0.1:5050")

# ===== OpenAI =====
# Required for AI to run. Keep it out of source control.
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
# Optional: set if you use a proxy or Azure endpoint
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
# Model selector so you can switch without code changes
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ===== Email (optional; used for appointment confirmations) =====
SMTP_HOST = os.getenv("SMTP_HOST")            # e.g. "smtp.gmail.com"
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_FROM", "no-reply@axisai.local")
SMTP_TLS  = os.getenv("SMTP_TLS", "true").lower() == "true"
