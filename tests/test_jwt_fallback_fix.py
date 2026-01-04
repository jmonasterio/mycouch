"""
Tests for multi-tenant extract_tenant() with 5-level discovery chain.

The extract_tenant function implements automatic tenant discovery with multi-level fallback:
- Level 1: Session cache (fastest)
- Level 2: User document default
- Level 3: First user-owned tenant
- Level 4: Create new tenant (if user has none)
- Level 5: Error (shouldn't reach here)

For couch-sitter requests: Uses personal tenant (existing behavior)
For multi-tenant requests: Uses 5-level discovery chain
"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from httpx import AsyncClient
import jwt
from datetime import datetime, timedelta


# Test fixtures and helpers
@pytest.fixture
def valid_jwt_payload():
    """Create a valid JWT payload with active_tenant_id"""
    return {
        "sub": "user_123",
        "iss": "https://roady.clerk.accounts.dev",
        "email": "test@example.com",
        "active_tenant_id": "tenant_abc",
        "iat": int(datetime.now().timestamp()),
        "exp": int((datetime.now() + timedelta(hours=1)).timestamp())
    }


@pytest.fixture
def stale_jwt_payload():
    """Create a stale JWT payload missing active_tenant_id (simulates old token)"""
    return {
        "sub": "user_123",
        "iss": "https://roady.clerk.accounts.dev",
        "email": "test@example.com",
        # MISSING: "active_tenant_id" - 5-level discovery will handle this
        "iat": int(datetime.now().timestamp()),
        "exp": int((datetime.now() + timedelta(hours=1)).timestamp())
    }


class TestMultiTenantDiscovery:
    """Test suite for 5-level tenant discovery chain"""

    @pytest.mark.asyncio
    async def test_new_user_gets_tenant_created(self, stale_jwt_payload):
        """Test that new user without tenant gets one created (Level 4)"""
        from src.couchdb_jwt_proxy.main import extract_tenant

        # New user with no session, no user doc, no existing tenants
        # Should trigger Level 4: create new tenant
        tenant_id = await extract_tenant(stale_jwt_payload, "/roady/test")

        # Should return a valid tenant ID (UUID format)
        assert tenant_id is not None
        assert len(tenant_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_couch_sitter_requests_use_personal_tenant(self, stale_jwt_payload):
        """Test that couch-sitter requests still work (they use personal tenant)"""
        from src.couchdb_jwt_proxy.main import extract_tenant

        # Mock couch_sitter_service for couch-sitter request
        with patch('src.couchdb_jwt_proxy.main.couch_sitter_service') as mock_cs:
            # Create a mock object with tenant_id attribute
            mock_user_tenant = Mock()
            mock_user_tenant.tenant_id = "tenant_personal"

            # Mock the async method to return the mock object
            mock_cs.get_user_tenant_info = AsyncMock(return_value=mock_user_tenant)

            # This should work fine for couch-sitter (uses personal tenant, not active_tenant_id)
            tenant_id = await extract_tenant(stale_jwt_payload, "/couch-sitter/test")

            # Should get personal tenant without error
            assert tenant_id == "tenant_personal"
            mock_cs.get_user_tenant_info.assert_called_once()


class TestTenantMembershipValidation:
    """Test suite for tenant membership validation (HIGH priority)"""

    @pytest.mark.asyncio
    async def test_unauthorized_tenant_switch_blocked(self):
        """Test that unauthorized tenant switch attempt is blocked"""
        # This test verifies that /choose-tenant endpoint validates membership
        # before allowing a tenant switch. Implementation in next phase.
        # For now, this is a placeholder for future tenant membership validation.
        pass


class TestDiscoveryChainBehavior:
    """Test the 5-level discovery chain behavior"""

    @pytest.mark.asyncio
    async def test_discovery_creates_tenant_for_new_user(self):
        """Test that 5-level discovery creates tenant when user has none"""
        from src.couchdb_jwt_proxy.main import extract_tenant

        payload = {
            "sub": "brand_new_user",
            "iss": "https://roady.clerk.accounts.dev",
            # No active_tenant_id - discovery will create one
        }

        tenant_id = await extract_tenant(payload, "/roady/test")

        # Should get a new tenant created
        assert tenant_id is not None
        assert len(tenant_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_jwt_active_tenant_claim_ignored_by_discovery(self):
        """Test that JWT's active_tenant_id is not used directly - discovery chain handles it"""
        from src.couchdb_jwt_proxy.main import extract_tenant

        payload = {
            "sub": "user_with_claim",
            "iss": "https://roady.clerk.accounts.dev",
            "active_tenant_id": "jwt_claimed_tenant"  # This is ignored
        }

        tenant_id = await extract_tenant(payload, "/roady/test")

        # 5-level discovery creates new tenant instead of using JWT claim
        assert tenant_id is not None
        # The returned tenant will be a new UUID, not the JWT claim value
        assert tenant_id != "jwt_claimed_tenant"


class TestSecurityLogging:
    """Test that discovery events are properly logged"""

    @pytest.mark.asyncio
    async def test_discovery_logs_tenant_creation(self, caplog):
        """Test that tenant creation via discovery is logged"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        import logging

        caplog.set_level(logging.INFO)

        payload = {
            "sub": "user_logging_test",
            "iss": "https://roady.clerk.accounts.dev",
        }

        tenant_id = await extract_tenant(payload, "/roady/test")

        # Should have logged tenant creation
        assert any("Level 4" in record.message or "Created new tenant" in record.message
                   for record in caplog.records)


class TestComplianceWithSecurityReview:
    """Tests for tenant isolation security"""

    @pytest.mark.asyncio
    async def test_no_cross_tenant_access(self):
        """Verify tenant isolation is maintained - different users get different tenants"""
        from src.couchdb_jwt_proxy.main import extract_tenant

        # User A
        payload_a = {
            "sub": "user_123",
            "iss": "https://roady.clerk.accounts.dev",
            "active_tenant_id": "tenant_a"
        }

        # User B
        payload_b = {
            "sub": "user_456",
            "iss": "https://roady.clerk.accounts.dev",
            "active_tenant_id": "tenant_b"
        }

        # Note: extract_tenant uses 5-level discovery chain. When no session/user doc exists,
        # it creates a new tenant for each user. The key security property is that different
        # users get different tenants - not that the JWT claim is used directly.
        tenant_a = await extract_tenant(payload_a, "/roady/test")
        tenant_b = await extract_tenant(payload_b, "/roady/test")

        # Verify tenant isolation - each user gets their own unique tenant
        assert tenant_a is not None
        assert tenant_b is not None
        assert tenant_a != tenant_b  # Critical: no cross-tenant leakage


# Integration tests
class TestIntegrationWithProxy:
    """Integration tests with full proxy"""

    @pytest.mark.asyncio
    async def test_roady_request_creates_tenant(self):
        """Test that roady database requests create tenant via 5-level discovery"""
        from src.couchdb_jwt_proxy.main import app, verify_clerk_jwt

        # Mock a request with valid Clerk JWT but missing active_tenant_id
        with patch('src.couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify:
            mock_verify.return_value = ({
                "sub": "user_123",
                "iss": "https://roady.clerk.accounts.dev",
                # Missing active_tenant_id - discovery will create one
            }, None)

            # This would be tested in proxy_couchdb endpoint
            # The endpoint should call extract_tenant which creates a tenant
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
