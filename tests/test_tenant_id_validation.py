"""
Tests for Tenant ID Format Validation

Validates that tenant IDs must follow the format: tenant_{uuid}
"""

import pytest
from uuid import uuid4
from src.couchdb_jwt_proxy.tenant_validation import (
    validate_tenant_id_format,
    TenantIdFormatError
)


class TestTenantIdValidation:
    """Test tenant ID format validation"""
    
    def test_valid_tenant_id(self):
        """Valid tenant ID should not raise error"""
        tenant_uuid = uuid4()
        tenant_id = f"tenant_{tenant_uuid}"
        # Should not raise
        validate_tenant_id_format(tenant_id)
    
    def test_valid_tenant_id_lowercase_uuid(self):
        """Valid tenant ID with lowercase UUID should not raise error"""
        tenant_id = "tenant_550e8400-e29b-41d4-a716-446655440000"
        # Should not raise
        validate_tenant_id_format(tenant_id)
    
    def test_valid_tenant_id_uppercase_uuid(self):
        """Valid tenant ID with uppercase UUID should not raise error"""
        tenant_id = "tenant_550E8400-E29B-41D4-A716-446655440000"
        # Should not raise
        validate_tenant_id_format(tenant_id)
    
    def test_empty_tenant_id(self):
        """Empty tenant ID should raise error"""
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format("")
        assert "cannot be empty" in str(exc_info.value)
    
    def test_missing_tenant_prefix(self):
        """Tenant ID without tenant_ prefix should raise error"""
        tenant_uuid = uuid4()
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format(str(tenant_uuid))
        assert "must start with 'tenant_'" in str(exc_info.value)
    
    def test_wrong_prefix(self):
        """Tenant ID with wrong prefix should raise error"""
        tenant_uuid = uuid4()
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format(f"band_{tenant_uuid}")
        assert "must start with 'tenant_'" in str(exc_info.value)
    
    def test_prefix_only(self):
        """Tenant ID with only prefix should raise error"""
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format("tenant_")
        assert "must include a UUID" in str(exc_info.value)
    
    def test_invalid_uuid_part(self):
        """Tenant ID with invalid UUID part should raise error"""
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format("tenant_not-a-uuid")
        assert "invalid UUID" in str(exc_info.value)
    
    def test_uuid_without_dashes(self):
        """UUID without dashes is valid (Python accepts both formats)"""
        # UUID without dashes is valid in Python
        tenant_id = "tenant_550e8400e29b41d4a716446655440000"
        # Should not raise
        validate_tenant_id_format(tenant_id)
    
    def test_double_prefix(self):
        """Tenant ID with double prefix should raise error"""
        tenant_uuid = uuid4()
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format(f"tenant_tenant_{tenant_uuid}")
        assert "invalid UUID" in str(exc_info.value)
    
    def test_case_insensitive_prefix(self):
        """Prefix must be lowercase"""
        tenant_uuid = uuid4()
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format(f"TENANT_{tenant_uuid}")
        assert "must start with 'tenant_'" in str(exc_info.value)
    
    def test_none_tenant_id(self):
        """None should raise error"""
        with pytest.raises((TenantIdFormatError, AttributeError)):
            validate_tenant_id_format(None)
    
    def test_short_invalid_uuid(self):
        """Too-short UUID should raise error"""
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format("tenant_12345")
        assert "invalid UUID" in str(exc_info.value)
    
    def test_tenant_id_with_extra_suffix(self):
        """Tenant ID with extra suffix should raise error"""
        tenant_uuid = uuid4()
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format(f"tenant_{tenant_uuid}_extra")
        assert "invalid UUID" in str(exc_info.value)
    
    def test_spaces_in_tenant_id(self):
        """Tenant ID with spaces should raise error"""
        with pytest.raises(TenantIdFormatError) as exc_info:
            validate_tenant_id_format("tenant_ 550e8400-e29b-41d4-a716-446655440000")
        assert "invalid UUID" in str(exc_info.value)


class TestTenantIdValidationEdgeCases:
    """Test edge cases for tenant ID validation"""
    
    def test_very_long_uuid(self):
        """Standard UUID should work"""
        # Python uuid4 always produces valid format
        tenant_id = f"tenant_{uuid4()}"
        validate_tenant_id_format(tenant_id)
    
    def test_multiple_dashes_in_uuid(self):
        """Multiple dashes in wrong places - Python's UUID is lenient with dash positions"""
        # Python's UUID() constructor is actually lenient with dashes
        # This actually parses successfully, so it's valid
        validate_tenant_id_format("tenant_550-e8400-e29b-41d4-a716-446655440000")
    
    def test_special_characters(self):
        """Special characters should fail"""
        with pytest.raises(TenantIdFormatError):
            validate_tenant_id_format("tenant_550e8400-e29b-41d4-a716-446655440@00")
    
    def test_whitespace_prefix(self):
        """Whitespace before tenant_ should fail"""
        tenant_uuid = uuid4()
        with pytest.raises(TenantIdFormatError):
            validate_tenant_id_format(f" tenant_{tenant_uuid}")


class TestValidationIntegration:
    """Integration tests showing how validation works with real UUIDs"""
    
    def test_validate_multiple_valid_tenant_ids(self):
        """Multiple valid tenant IDs should all pass"""
        for _ in range(5):
            tenant_id = f"tenant_{uuid4()}"
            # Should not raise
            validate_tenant_id_format(tenant_id)
    
    def test_common_invalid_patterns(self):
        """Common invalid patterns should all fail"""
        invalid_patterns = [
            "550e8400-e29b-41d4-a716-446655440000",  # Missing prefix
            "band_550e8400-e29b-41d4-a716-446655440000",  # Wrong prefix
            "tenant_",  # Missing UUID
            "tenant_invalid",  # Invalid UUID
            "",  # Empty
            "tenant",  # Only prefix, no underscore
        ]
        
        for pattern in invalid_patterns:
            with pytest.raises(TenantIdFormatError):
                validate_tenant_id_format(pattern)
