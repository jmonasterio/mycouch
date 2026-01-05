"""
Tests for User ID Format Validation

Validates that user IDs must follow the format: user_<64-char-sha256-hash>
"""

import pytest
import hashlib
from src.couchdb_jwt_proxy.tenant_validation import (
    validate_user_id_format,
    UserIdFormatError
)


def _hash_sub(sub: str) -> str:
    """Helper to hash Clerk sub like the actual implementation does"""
    return hashlib.sha256(sub.encode('utf-8')).hexdigest()


class TestUserIdValidation:
    """Test user ID format validation"""
    
    def test_valid_user_id(self):
        """Valid user ID should not raise error"""
        sub = "user_34tzJwWB3jaQT6ZKPqZIQoJwsmz"
        user_hash = _hash_sub(sub)
        user_id = f"user_{user_hash}"
        # Should not raise
        validate_user_id_format(user_id)
    
    def test_valid_user_id_any_valid_hash(self):
        """Any valid 64-char hex hash should pass"""
        valid_hash = "a" * 64  # 64 'a' characters
        user_id = f"user_{valid_hash}"
        # Should not raise
        validate_user_id_format(user_id)
    
    def test_valid_user_id_mixed_hex(self):
        """Mixed hex characters (0-9, a-f) should pass"""
        valid_hash = "0123456789abcdef" * 4  # 64 hex chars
        user_id = f"user_{valid_hash}"
        # Should not raise
        validate_user_id_format(user_id)
    
    def test_valid_user_id_uppercase_hex(self):
        """Uppercase hex characters (A-F) should pass"""
        valid_hash = "0123456789ABCDEF" * 4  # 64 hex chars uppercase
        user_id = f"user_{valid_hash}"
        # Should not raise
        validate_user_id_format(user_id)
    
    def test_empty_user_id(self):
        """Empty user ID should raise error"""
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format("")
        assert "cannot be empty" in str(exc_info.value)
    
    def test_missing_user_prefix(self):
        """User ID without user_ prefix should raise error"""
        valid_hash = "a" * 64
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format(valid_hash)
        assert "must start with 'user_'" in str(exc_info.value)
    
    def test_wrong_prefix(self):
        """User ID with wrong prefix should raise error"""
        valid_hash = "a" * 64
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format(f"tenant_{valid_hash}")
        assert "must start with 'user_'" in str(exc_info.value)
    
    def test_prefix_only(self):
        """User ID with only prefix should raise error"""
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format("user_")
        assert "must include a hash" in str(exc_info.value)
    
    def test_hash_too_short(self):
        """Hash shorter than 64 chars should raise error"""
        short_hash = "a" * 63
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format(f"user_{short_hash}")
        assert "must be 64 characters" in str(exc_info.value)
    
    def test_hash_too_long(self):
        """Hash longer than 64 chars should raise error"""
        long_hash = "a" * 65
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format(f"user_{long_hash}")
        assert "must be 64 characters" in str(exc_info.value)
    
    def test_invalid_hex_characters(self):
        """Hash with non-hex characters should raise error"""
        invalid_hash = "z" * 64  # 'z' is not a hex character
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format(f"user_{invalid_hash}")
        assert "valid hexadecimal" in str(exc_info.value)
    
    def test_invalid_hex_special_chars(self):
        """Hash with special characters should raise error"""
        invalid_hash = "a" * 63 + "!"
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format(f"user_{invalid_hash}")
        assert "valid hexadecimal" in str(exc_info.value)
    
    def test_hash_with_spaces(self):
        """Hash with spaces should raise error"""
        with pytest.raises(UserIdFormatError) as exc_info:
            # Create a string that's exactly 64 hex chars with spaces
            invalid_hash = "a" * 31 + " " + "a" * 32  # 31 + 1 space + 32 = 64 chars but contains space
            validate_user_id_format(f"user_{invalid_hash}")
        assert "valid hexadecimal" in str(exc_info.value)
    
    def test_case_insensitive_prefix(self):
        """Prefix must be lowercase"""
        valid_hash = "a" * 64
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format(f"USER_{valid_hash}")
        assert "must start with 'user_'" in str(exc_info.value)
    
    def test_none_user_id(self):
        """None should raise error"""
        with pytest.raises((UserIdFormatError, AttributeError)):
            validate_user_id_format(None)
    
    def test_double_prefix(self):
        """User ID with double prefix should raise error"""
        valid_hash = "a" * 64
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format(f"user_user_{valid_hash}")
        # This creates user_user_aaa... which is 69 chars, too long
        assert "must be 64 characters" in str(exc_info.value)
    
    def test_user_id_with_extra_suffix(self):
        """User ID with extra suffix should raise error"""
        valid_hash = "a" * 64
        with pytest.raises(UserIdFormatError) as exc_info:
            validate_user_id_format(f"user_{valid_hash}_extra")
        # This adds extra chars beyond 64, making it invalid length
        assert "must be 64 characters" in str(exc_info.value)


class TestNormalizationAndValidation:
    """Test that normalization produces valid user IDs"""
    
    def test_normalize_real_clerk_sub(self):
        """Normalizing a real Clerk sub should produce valid user ID"""
        clerk_sub = "user_34tzJwWB3jaQT6ZKPqZIQoJwsmz"
        user_hash = _hash_sub(clerk_sub)
        user_id = f"user_{user_hash}"
        
        # Normalization should produce valid format
        validate_user_id_format(user_id)
    
    def test_normalize_various_clerk_subs(self):
        """Various Clerk subs should all produce valid user IDs after normalization"""
        test_subs = [
            "user_34tzJwWB3jaQT6ZKPqZIQoJwsmz",
            "user_2xXYZ123",
            "user_abcdefghijklmnopqrstuvwxyz",
            "user_1234567890",
        ]
        
        for sub in test_subs:
            user_hash = _hash_sub(sub)
            user_id = f"user_{user_hash}"
            # All should pass validation
            validate_user_id_format(user_id)
    
    def test_hash_is_always_64_chars(self):
        """SHA256 hex digest should always be 64 characters"""
        test_subs = [
            "short",
            "a" * 100,
            "user_x",
            "user_" + "a" * 500,
        ]
        
        for sub in test_subs:
            user_hash = _hash_sub(sub)
            # SHA256 hex should always be exactly 64 chars
            assert len(user_hash) == 64
            user_id = f"user_{user_hash}"
            validate_user_id_format(user_id)


class TestEdgeCases:
    """Test edge cases for user ID validation"""
    
    def test_lowercase_hex_only(self):
        """Lowercase hex should pass"""
        user_id = "user_" + "abcdef0123456789" * 4
        validate_user_id_format(user_id)
    
    def test_uppercase_hex_only(self):
        """Uppercase hex should pass"""
        user_id = "user_" + "ABCDEF0123456789" * 4
        validate_user_id_format(user_id)
    
    def test_mixed_case_hex(self):
        """Mixed case hex should pass"""
        user_id = "user_" + "AaBbCcDdEeFf0123" * 4
        validate_user_id_format(user_id)
    
    def test_all_zeros(self):
        """All zeros hash should pass (technically valid SHA256)"""
        user_id = "user_" + "0" * 64
        validate_user_id_format(user_id)
    
    def test_all_fs(self):
        """All 'f' hash should pass (technically valid SHA256)"""
        user_id = "user_" + "f" * 64
        validate_user_id_format(user_id)
    
    def test_whitespace_in_prefix(self):
        """Whitespace before user_ should fail"""
        valid_hash = "a" * 64
        with pytest.raises(UserIdFormatError):
            validate_user_id_format(f" user_{valid_hash}")
    
    def test_newline_in_hash(self):
        """Newline characters should fail"""
        with pytest.raises(UserIdFormatError):
            validate_user_id_format("user_" + "a" * 32 + "\n" + "a" * 31)


class TestCommonInvalidPatterns:
    """Test common invalid patterns that might be passed by mistake"""
    
    def test_just_hash_no_prefix(self):
        """Just the hash without prefix should fail"""
        valid_hash = "a" * 64
        with pytest.raises(UserIdFormatError):
            validate_user_id_format(valid_hash)
    
    def test_uuid_format(self):
        """UUID format should fail (wrong type of ID)"""
        with pytest.raises(UserIdFormatError):
            validate_user_id_format("user_550e8400-e29b-41d4-a716-446655440000")
    
    def test_bare_clerk_sub(self):
        """Bare Clerk sub without normalization should fail"""
        with pytest.raises(UserIdFormatError):
            validate_user_id_format("user_34tzJwWB3jaQT6ZKPqZIQoJwsmz")
    
    def test_email_format(self):
        """Email format should fail"""
        with pytest.raises(UserIdFormatError):
            validate_user_id_format("user_alice@example.com")
    
    def test_arbitrary_string(self):
        """Arbitrary string should fail"""
        with pytest.raises(UserIdFormatError):
            validate_user_id_format("user_not-a-valid-hash")
    
    def test_admin_user_id(self):
        """'admin' string should fail"""
        with pytest.raises(UserIdFormatError):
            validate_user_id_format("user_admin")
