import os
import secrets
from pathlib import Path

# Load .env file from project root
from dotenv import load_dotenv
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path, override=True)

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

# ===== Retell AI (Voice Calls) =====
# Required for voice AI functionality
RETELL_API_KEY = os.getenv("RETELL_API_KEY")
RETELL_WEBHOOK_SECRET = os.getenv("RETELL_WEBHOOK_SECRET")
RETELL_DEFAULT_AGENT_ID = os.getenv("RETELL_DEFAULT_AGENT_ID")
# Voice call limits
VOICE_TRANSFER_TIMEOUT = int(os.getenv("VOICE_TRANSFER_TIMEOUT", "300"))  # seconds
VOICE_MAX_DURATION = int(os.getenv("VOICE_MAX_DURATION", "600"))  # seconds (10 min)
VOICE_RECORDING_ENABLED = os.getenv("VOICE_RECORDING_ENABLED", "true").lower() == "true"

# ===== Email (optional; used for appointment confirmations) =====
SMTP_HOST = os.getenv("SMTP_HOST")            # e.g. "smtp.gmail.com"
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_FROM", "no-reply@axisai.local")
SMTP_TLS  = os.getenv("SMTP_TLS", "true").lower() == "true"
