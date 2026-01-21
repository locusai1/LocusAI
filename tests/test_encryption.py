# tests/test_encryption.py — Tests for core/encryption.py
# Tests for field-level encryption, hashing, and PII protection

import os
import pytest
from unittest.mock import patch


# ============================================================================
# Encryption/Decryption Tests
# ============================================================================

class TestFieldEncryption:
    """Tests for field-level encryption and decryption."""

    def test_encrypt_field_returns_prefixed_string(self):
        """Encrypted values should be prefixed with 'enc:' or 'obf:'."""
        from core.encryption import encrypt_field

        result = encrypt_field("secret data")
        assert result.startswith("enc:") or result.startswith("obf:")

    def test_decrypt_field_returns_original(self):
        """Decryption should return the original value."""
        from core.encryption import encrypt_field, decrypt_field

        original = "My secret information"
        encrypted = encrypt_field(original)
        decrypted = decrypt_field(encrypted)
        assert decrypted == original

    def test_encrypt_empty_string(self):
        """Empty string should return empty string."""
        from core.encryption import encrypt_field

        result = encrypt_field("")
        assert result == ""

    def test_decrypt_empty_string(self):
        """Empty string should return empty string."""
        from core.encryption import decrypt_field

        result = decrypt_field("")
        assert result == ""

    def test_encrypt_none(self):
        """None should return None/empty."""
        from core.encryption import encrypt_field

        result = encrypt_field(None)
        assert result is None or result == ""

    def test_decrypt_none(self):
        """None should return None/empty."""
        from core.encryption import decrypt_field

        result = decrypt_field(None)
        assert result is None or result == ""

    def test_double_encryption_prevented(self):
        """Should not double-encrypt already encrypted values."""
        from core.encryption import encrypt_field

        original = "secret"
        encrypted_once = encrypt_field(original)
        encrypted_twice = encrypt_field(encrypted_once)
        assert encrypted_once == encrypted_twice

    def test_decrypt_unencrypted_value(self):
        """Decrypting unencrypted value should return it unchanged."""
        from core.encryption import decrypt_field

        plaintext = "not encrypted"
        result = decrypt_field(plaintext)
        assert result == plaintext

    def test_encrypt_unicode(self):
        """Unicode characters should be properly encrypted/decrypted."""
        from core.encryption import encrypt_field, decrypt_field

        original = "Hello 世界 🌍 Здравствуй"
        encrypted = encrypt_field(original)
        decrypted = decrypt_field(encrypted)
        assert decrypted == original

    def test_encrypt_special_characters(self):
        """Special characters should be properly handled."""
        from core.encryption import encrypt_field, decrypt_field

        original = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        encrypted = encrypt_field(original)
        decrypted = decrypt_field(encrypted)
        assert decrypted == original

    def test_encrypt_long_string(self):
        """Long strings should be properly encrypted/decrypted."""
        from core.encryption import encrypt_field, decrypt_field

        original = "A" * 10000
        encrypted = encrypt_field(original)
        decrypted = decrypt_field(encrypted)
        assert decrypted == original


class TestIsEncrypted:
    """Tests for is_encrypted utility function."""

    def test_is_encrypted_with_enc_prefix(self):
        from core.encryption import is_encrypted

        assert is_encrypted("enc:somedata") is True

    def test_is_encrypted_with_obf_prefix(self):
        from core.encryption import is_encrypted

        assert is_encrypted("obf:somedata") is True

    def test_is_encrypted_with_plaintext(self):
        from core.encryption import is_encrypted

        assert is_encrypted("plaintext") is False

    def test_is_encrypted_with_empty(self):
        from core.encryption import is_encrypted

        assert is_encrypted("") is False

    def test_is_encrypted_with_none(self):
        from core.encryption import is_encrypted

        assert is_encrypted(None) is False


# ============================================================================
# Dictionary Encryption Tests
# ============================================================================

class TestDictEncryption:
    """Tests for dictionary field encryption utilities."""

    def test_encrypt_dict_fields(self):
        """Should encrypt specified fields in a dictionary."""
        from core.encryption import encrypt_dict_fields, is_encrypted

        data = {
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "555-1234",
            "notes": "Some notes"
        }

        result = encrypt_dict_fields(data, ["email", "phone"])

        # Specified fields should be encrypted
        assert is_encrypted(result["email"])
        assert is_encrypted(result["phone"])

        # Other fields should remain unchanged
        assert result["name"] == "John Doe"
        assert result["notes"] == "Some notes"

    def test_encrypt_dict_fields_missing_field(self):
        """Should handle missing fields gracefully."""
        from core.encryption import encrypt_dict_fields

        data = {"name": "John"}
        result = encrypt_dict_fields(data, ["name", "nonexistent"])

        # Should not raise an error
        assert "nonexistent" not in result

    def test_decrypt_dict_fields(self):
        """Should decrypt specified fields in a dictionary."""
        from core.encryption import encrypt_dict_fields, decrypt_dict_fields

        original = {
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "555-1234"
        }

        encrypted = encrypt_dict_fields(original, ["email", "phone"])
        decrypted = decrypt_dict_fields(encrypted, ["email", "phone"])

        assert decrypted["email"] == original["email"]
        assert decrypted["phone"] == original["phone"]
        assert decrypted["name"] == original["name"]

    def test_encrypt_dict_preserves_original(self):
        """Original dictionary should not be modified."""
        from core.encryption import encrypt_dict_fields

        original = {"email": "test@example.com"}
        original_copy = original.copy()

        encrypt_dict_fields(original, ["email"])

        assert original == original_copy


# ============================================================================
# Token Hashing Tests
# ============================================================================

class TestTokenHashing:
    """Tests for secure token hashing."""

    def test_hash_token_returns_hex(self):
        """Hash should return a hex string."""
        from core.encryption import hash_token

        result = hash_token("my-secret-token")
        assert isinstance(result, str)
        assert all(c in '0123456789abcdef' for c in result)

    def test_hash_token_consistent(self):
        """Same input should always produce same hash."""
        from core.encryption import hash_token

        token = "test-token"
        hash1 = hash_token(token)
        hash2 = hash_token(token)
        assert hash1 == hash2

    def test_hash_token_different_inputs(self):
        """Different inputs should produce different hashes."""
        from core.encryption import hash_token

        hash1 = hash_token("token1")
        hash2 = hash_token("token2")
        assert hash1 != hash2

    def test_hash_token_with_salt(self):
        """Salt should change the hash."""
        from core.encryption import hash_token

        token = "my-token"
        hash_no_salt = hash_token(token)
        hash_with_salt = hash_token(token, salt="my-salt")
        assert hash_no_salt != hash_with_salt

    def test_hash_token_empty(self):
        """Empty token should return empty string."""
        from core.encryption import hash_token

        result = hash_token("")
        assert result == ""

    def test_hash_token_none(self):
        """None should return empty string."""
        from core.encryption import hash_token

        result = hash_token(None)
        assert result == ""


class TestVerifyTokenHash:
    """Tests for token hash verification."""

    def test_verify_correct_token(self):
        """Correct token should verify successfully."""
        from core.encryption import hash_token, verify_token_hash

        token = "my-secret-token"
        stored_hash = hash_token(token)
        assert verify_token_hash(token, stored_hash) is True

    def test_verify_incorrect_token(self):
        """Incorrect token should fail verification."""
        from core.encryption import hash_token, verify_token_hash

        stored_hash = hash_token("correct-token")
        assert verify_token_hash("wrong-token", stored_hash) is False

    def test_verify_with_salt(self):
        """Verification should work with salt."""
        from core.encryption import hash_token, verify_token_hash

        token = "my-token"
        salt = "my-salt"
        stored_hash = hash_token(token, salt=salt)
        assert verify_token_hash(token, stored_hash, salt=salt) is True

    def test_verify_wrong_salt(self):
        """Wrong salt should fail verification."""
        from core.encryption import hash_token, verify_token_hash

        token = "my-token"
        stored_hash = hash_token(token, salt="correct-salt")
        assert verify_token_hash(token, stored_hash, salt="wrong-salt") is False

    def test_verify_empty_token(self):
        """Empty token should return False."""
        from core.encryption import verify_token_hash

        assert verify_token_hash("", "somehash") is False

    def test_verify_empty_hash(self):
        """Empty hash should return False."""
        from core.encryption import verify_token_hash

        assert verify_token_hash("token", "") is False


# ============================================================================
# Key Generation Tests
# ============================================================================

class TestKeyGeneration:
    """Tests for encryption key generation."""

    def test_generate_encryption_key_length(self):
        """Generated key should be base64-encoded 32 bytes."""
        from core.encryption import generate_encryption_key
        import base64

        key = generate_encryption_key()

        # Should be a string
        assert isinstance(key, str)

        # Should be valid base64
        decoded = base64.b64decode(key)
        assert len(decoded) == 32

    def test_generate_encryption_key_unique(self):
        """Each generated key should be unique."""
        from core.encryption import generate_encryption_key

        key1 = generate_encryption_key()
        key2 = generate_encryption_key()
        assert key1 != key2


# ============================================================================
# PII Field Constants Tests
# ============================================================================

class TestPiiFieldConstants:
    """Tests for PII field constant definitions."""

    def test_customer_pii_fields_defined(self):
        """Customer PII fields should be defined."""
        from core.encryption import CUSTOMER_PII_FIELDS

        assert "email" in CUSTOMER_PII_FIELDS
        assert "phone" in CUSTOMER_PII_FIELDS
        assert "name" in CUSTOMER_PII_FIELDS

    def test_appointment_pii_fields_defined(self):
        """Appointment PII fields should be defined."""
        from core.encryption import APPOINTMENT_PII_FIELDS

        assert "customer_name" in APPOINTMENT_PII_FIELDS
        assert "phone" in APPOINTMENT_PII_FIELDS
        assert "customer_email" in APPOINTMENT_PII_FIELDS

    def test_session_pii_fields_defined(self):
        """Session PII fields should be defined."""
        from core.encryption import SESSION_PII_FIELDS

        assert "phone" in SESSION_PII_FIELDS


# ============================================================================
# Encryption Availability Tests
# ============================================================================

class TestEncryptionAvailability:
    """Tests for encryption module availability detection."""

    def test_encryption_available_flag_exists(self):
        """ENCRYPTION_AVAILABLE flag should be defined."""
        from core.encryption import ENCRYPTION_AVAILABLE

        assert isinstance(ENCRYPTION_AVAILABLE, bool)

    def test_encryption_works_regardless_of_backend(self):
        """Encryption should work whether using Fernet or fallback."""
        from core.encryption import encrypt_field, decrypt_field

        original = "test data"
        encrypted = encrypt_field(original)
        decrypted = decrypt_field(encrypted)

        assert decrypted == original
