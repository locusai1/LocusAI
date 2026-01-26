# core/encryption.py — Field-level encryption for PII data in LocusAI
# Provides encryption/decryption utilities for sensitive data at rest

import os
import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================================
# Encryption Configuration
# ============================================================================

# Get encryption key from environment or generate a derived key from FLASK_SECRET_KEY
# In production, use a dedicated encryption key stored securely
_ENCRYPTION_KEY: Optional[bytes] = None


def _get_encryption_key() -> bytes:
    """Get or derive the encryption key.

    Priority:
    1. ENCRYPTION_KEY environment variable (recommended for production)
    2. Derived from FLASK_SECRET_KEY (acceptable for development)
    """
    global _ENCRYPTION_KEY

    if _ENCRYPTION_KEY is not None:
        return _ENCRYPTION_KEY

    # Try dedicated encryption key first
    key_env = os.getenv("ENCRYPTION_KEY")
    if key_env:
        # Expect base64-encoded 32-byte key
        try:
            _ENCRYPTION_KEY = base64.b64decode(key_env)
            if len(_ENCRYPTION_KEY) != 32:
                raise ValueError("ENCRYPTION_KEY must be 32 bytes (256 bits)")
            return _ENCRYPTION_KEY
        except Exception as e:
            logger.error(f"Invalid ENCRYPTION_KEY: {e}")
            raise

    # Fall back to deriving from FLASK_SECRET_KEY
    flask_secret = os.getenv("FLASK_SECRET_KEY")
    if not flask_secret:
        raise ValueError(
            "No encryption key configured. Set ENCRYPTION_KEY or FLASK_SECRET_KEY."
        )

    # Derive a 32-byte key using PBKDF2
    # Using a fixed salt is not ideal but necessary for deterministic derivation
    # In production, use a proper ENCRYPTION_KEY
    salt = b"locusai_pii_encryption_v1"
    _ENCRYPTION_KEY = hashlib.pbkdf2_hmac(
        'sha256',
        flask_secret.encode('utf-8'),
        salt,
        iterations=100000,
        dklen=32
    )

    logger.warning(
        "Using derived encryption key from FLASK_SECRET_KEY. "
        "For production, set a dedicated ENCRYPTION_KEY."
    )

    return _ENCRYPTION_KEY


# ============================================================================
# Fernet-like Encryption (using built-in libraries only)
# ============================================================================

# If cryptography library is available, use it; otherwise fall back to simpler method
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    _FERNET: Optional[Fernet] = None

    def _get_fernet() -> Fernet:
        """Get or create Fernet instance."""
        global _FERNET

        if _FERNET is not None:
            return _FERNET

        key = _get_encryption_key()
        # Fernet requires a URL-safe base64-encoded 32-byte key
        fernet_key = base64.urlsafe_b64encode(key)
        _FERNET = Fernet(fernet_key)
        return _FERNET

    def encrypt_field(value: str) -> str:
        """Encrypt a string field value.

        Returns:
            Base64-encoded encrypted value with 'enc:' prefix
        """
        if not value:
            return value

        # Don't double-encrypt
        if value.startswith("enc:"):
            return value

        try:
            fernet = _get_fernet()
            encrypted = fernet.encrypt(value.encode('utf-8'))
            return "enc:" + encrypted.decode('utf-8')
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt_field(value: str) -> str:
        """Decrypt a string field value.

        Returns:
            Decrypted plaintext value
        """
        if not value:
            return value

        # Only decrypt if encrypted
        if not value.startswith("enc:"):
            return value

        try:
            fernet = _get_fernet()
            encrypted_data = value[4:]  # Remove "enc:" prefix
            decrypted = fernet.decrypt(encrypted_data.encode('utf-8'))
            return decrypted.decode('utf-8')
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    ENCRYPTION_AVAILABLE = True

except ImportError:
    # Fallback: Use simple XOR-based obfuscation (NOT recommended for production)
    # This is only for development/testing when cryptography isn't installed

    logger.warning(
        "cryptography library not available. Using basic obfuscation only. "
        "Install cryptography for proper encryption: pip install cryptography"
    )

    def encrypt_field(value: str) -> str:
        """Obfuscate a string field value (NOT secure encryption).

        Returns:
            Base64-encoded obfuscated value with 'obf:' prefix
        """
        if not value:
            return value

        if value.startswith("obf:") or value.startswith("enc:"):
            return value

        try:
            key = _get_encryption_key()
            # Simple XOR obfuscation (NOT cryptographically secure)
            data = value.encode('utf-8')
            result = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
            return "obf:" + base64.b64encode(result).decode('utf-8')
        except Exception as e:
            logger.error(f"Obfuscation failed: {e}")
            raise

    def decrypt_field(value: str) -> str:
        """De-obfuscate a string field value.

        Returns:
            Original plaintext value
        """
        if not value:
            return value

        if not (value.startswith("obf:") or value.startswith("enc:")):
            return value

        try:
            key = _get_encryption_key()
            prefix = "obf:" if value.startswith("obf:") else "enc:"
            data = base64.b64decode(value[len(prefix):])
            result = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
            return result.decode('utf-8')
        except Exception as e:
            logger.error(f"De-obfuscation failed: {e}")
            raise

    ENCRYPTION_AVAILABLE = False


# ============================================================================
# Utility Functions
# ============================================================================

def is_encrypted(value: str) -> bool:
    """Check if a value is encrypted."""
    if not value:
        return False
    return value.startswith("enc:") or value.startswith("obf:")


def encrypt_dict_fields(data: dict, fields: list) -> dict:
    """Encrypt specified fields in a dictionary.

    Args:
        data: Dictionary containing data
        fields: List of field names to encrypt

    Returns:
        Dictionary with specified fields encrypted
    """
    result = data.copy()
    for field in fields:
        if field in result and result[field]:
            result[field] = encrypt_field(str(result[field]))
    return result


def decrypt_dict_fields(data: dict, fields: list) -> dict:
    """Decrypt specified fields in a dictionary.

    Args:
        data: Dictionary containing data
        fields: List of field names to decrypt

    Returns:
        Dictionary with specified fields decrypted
    """
    result = data.copy()
    for field in fields:
        if field in result and result[field]:
            result[field] = decrypt_field(str(result[field]))
    return result


# ============================================================================
# Hashing Utilities (for non-reversible data like tokens)
# ============================================================================

def hash_token(token: str, salt: Optional[str] = None) -> str:
    """Create a secure hash of a token for storage.

    Use this for API keys, reset tokens, etc. where you don't need to
    retrieve the original value.

    Args:
        token: The token to hash
        salt: Optional salt (use a unique value per token type)

    Returns:
        Hex-encoded SHA-256 hash
    """
    if not token:
        return ""

    data = token.encode('utf-8')
    if salt:
        data = salt.encode('utf-8') + data

    return hashlib.sha256(data).hexdigest()


def verify_token_hash(token: str, stored_hash: str, salt: Optional[str] = None) -> bool:
    """Verify a token against its stored hash.

    Args:
        token: The token to verify
        stored_hash: The stored hash to compare against
        salt: The same salt used when hashing

    Returns:
        True if token matches the hash
    """
    if not token or not stored_hash:
        return False

    import hmac
    computed = hash_token(token, salt)
    return hmac.compare_digest(computed, stored_hash)


# ============================================================================
# PII Field Lists (for use with encrypt_dict_fields/decrypt_dict_fields)
# ============================================================================

# Fields that should be encrypted in the customers table
CUSTOMER_PII_FIELDS = ["email", "phone", "name"]

# Fields that should be encrypted in the appointments table
APPOINTMENT_PII_FIELDS = ["customer_name", "phone", "customer_email"]

# Fields that should be encrypted in the messages table (if storing PII)
MESSAGE_PII_FIELDS = []  # Messages may contain PII but are generally not encrypted

# Fields that should be encrypted in the sessions table
SESSION_PII_FIELDS = ["phone"]


# ============================================================================
# Key Generation Utility (for deployment setup)
# ============================================================================

def generate_encryption_key() -> str:
    """Generate a new random encryption key.

    Returns:
        Base64-encoded 32-byte key suitable for ENCRYPTION_KEY env var
    """
    import secrets
    key = secrets.token_bytes(32)
    return base64.b64encode(key).decode('utf-8')


if __name__ == "__main__":
    # When run directly, generate a new key
    print("Generated Encryption Key:")
    print(generate_encryption_key())
    print("\nSet this as your ENCRYPTION_KEY environment variable.")
