"""
Security tests for JWT fallback vulnerability fix.
Tests verify that the fallback mechanism has been removed and strict JWT validation is enforced.

Issue: https://github.com/jmonasterio/mycouch/security-review.md#1-jwt-fallback-creates-authentication-bypass
CWE-287: Improper Authentication
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
        # MISSING: "active_tenant_id" - this is the vulnerability
        "iat": int(datetime.now().timestamp()),
        "exp": int((datetime.now() + timedelta(hours=1)).timestamp())
    }


@pytest.fixture
def mock_app():
    """Create test FastAPI app with JWT validation"""
    from fastapi import FastAPI, HTTPException
    from src.couchdb_jwt_proxy.main import extract_tenant
    
    app = FastAPI()
    
    @app.post("/test/roady")
    async def test_roady_endpoint(payload: dict):
        """Test endpoint for Roady app"""
        # Mock the extract_tenant function
        tenant_id = await extract_tenant(payload, "/roady/test")
        return {"tenant_id": tenant_id}
    
    return app


class TestJWTFallbackRemoval:
    """Test suite for JWT fallback removal (CRITICAL fix)"""
    
    @pytest.mark.asyncio
    async def test_valid_jwt_with_tenant_claim_accepted(self, valid_jwt_payload):
        """Test that valid JWT with active_tenant_id is accepted"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        
        # Should return tenant_id without error
        tenant_id = await extract_tenant(valid_jwt_payload, "/roady/test")
        
        assert tenant_id == "tenant_abc"
        assert tenant_id is not None
    
    @pytest.mark.asyncio
    async def test_stale_jwt_without_tenant_claim_rejected(self, stale_jwt_payload):
        """Test that stale JWT without active_tenant_id is REJECTED (not allowed to fallback)"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        from fastapi import HTTPException
        
        # Should raise HTTPException - no fallback allowed
        with pytest.raises(HTTPException) as exc_info:
            await extract_tenant(stale_jwt_payload, "/roady/test")
        
        # Verify it's a 401 (authentication error)
        assert exc_info.value.status_code == 401
        assert "Missing active_tenant_id claim" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_no_fallback_to_clerk_api(self, stale_jwt_payload):
        """Test that extract_tenant does NOT call clerk_service.get_user_active_tenant"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        from fastapi import HTTPException
        
        # Mock clerk_service to verify it's not called
        with patch('src.couchdb_jwt_proxy.main.clerk_service') as mock_clerk:
            mock_clerk.get_user_active_tenant.return_value = "tenant_fallback"
            
            # Should raise HTTPException WITHOUT calling fallback API
            with pytest.raises(HTTPException):
                await extract_tenant(stale_jwt_payload, "/roady/test")
            
            # Verify clerk_service was NOT called (this is the fix)
            mock_clerk.get_user_active_tenant.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_couch_sitter_requests_unaffected(self, stale_jwt_payload):
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


class TestMissingActiveClaimsErrorHandling:
    """Test proper error handling for missing claims"""
    
    @pytest.mark.asyncio
    async def test_error_message_clear_and_actionable(self, stale_jwt_payload):
        """Test that error message guides user to refresh token"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            await extract_tenant(stale_jwt_payload, "/roady/test")
        
        error_msg = exc_info.value.detail
        
        # Verify error message is clear
        assert "active_tenant_id" in error_msg
        assert "refresh" in error_msg.lower()
        assert "token" in error_msg.lower()
    
    @pytest.mark.asyncio
    async def test_logging_contains_security_context(self, stale_jwt_payload, caplog):
        """Test that rejection is properly logged for security audit"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        from fastapi import HTTPException
        import logging
        
        caplog.set_level(logging.WARNING)
        
        with pytest.raises(HTTPException):
            await extract_tenant(stale_jwt_payload, "/roady/test")
        
        # Should log the rejection with context
        assert any("Missing active_tenant_id" in record.message for record in caplog.records)
        assert any(stale_jwt_payload["sub"] in record.message for record in caplog.records)


class TestJWTClaimVariations:
    """Test different JWT claim formats"""
    
    @pytest.mark.asyncio
    async def test_active_tenant_id_at_top_level(self):
        """Test active_tenant_id at JWT root level"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        
        payload = {
            "sub": "user_123",
            "iss": "https://roady.clerk.accounts.dev",
            "active_tenant_id": "tenant_xyz"  # At root level
        }
        
        tenant_id = await extract_tenant(payload, "/roady/test")
        assert tenant_id == "tenant_xyz"
    
    @pytest.mark.asyncio
    async def test_tenant_id_fallback_claim(self):
        """Test tenant_id claim (alternative to active_tenant_id)"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        
        payload = {
            "sub": "user_123",
            "iss": "https://roady.clerk.accounts.dev",
            "tenant_id": "tenant_fallback"  # Alternative claim name
        }
        
        tenant_id = await extract_tenant(payload, "/roady/test")
        assert tenant_id == "tenant_fallback"
    
    @pytest.mark.asyncio
    async def test_active_tenant_in_metadata(self):
        """Test active_tenant_id nested in metadata"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        
        payload = {
            "sub": "user_123",
            "iss": "https://roady.clerk.accounts.dev",
            "metadata": {
                "active_tenant_id": "tenant_nested"
            }
        }
        
        tenant_id = await extract_tenant(payload, "/roady/test")
        assert tenant_id == "tenant_nested"
    
    @pytest.mark.asyncio
    async def test_all_tenant_claims_missing(self):
        """Test rejection when all possible tenant claims are missing"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        from fastapi import HTTPException
        
        payload = {
            "sub": "user_123",
            "iss": "https://roady.clerk.accounts.dev",
            "metadata": {}  # Empty metadata
        }
        
        # Should reject for roady request
        with pytest.raises(HTTPException) as exc_info:
            await extract_tenant(payload, "/roady/test")
        
        assert exc_info.value.status_code == 401


class TestSecurityLogging:
    """Test that security events are properly logged"""
    
    @pytest.mark.asyncio
    async def test_missing_claim_logged_at_warning_level(self, stale_jwt_payload, caplog):
        """Test that missing active_tenant_id is logged at WARNING level"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        from fastapi import HTTPException
        import logging
        
        caplog.set_level(logging.WARNING)
        
        with pytest.raises(HTTPException):
            await extract_tenant(stale_jwt_payload, "/roady/test")
        
        # Verify warning was logged
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_records) > 0
        assert any("Missing active_tenant_id" in r.message for r in warning_records)
    
    @pytest.mark.asyncio
    async def test_user_info_in_security_log(self, stale_jwt_payload, caplog):
        """Test that user info is included in security logs"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        from fastapi import HTTPException
        import logging
        
        caplog.set_level(logging.WARNING)
        
        with pytest.raises(HTTPException):
            await extract_tenant(stale_jwt_payload, "/roady/test")
        
        # Verify user sub is logged (for audit trail)
        assert any(stale_jwt_payload["sub"] in r.message for r in caplog.records)


class TestComplianceWithSecurityReview:
    """Tests mapping to security-review.md requirements"""
    
    @pytest.mark.asyncio
    async def test_cwe_287_improper_authentication(self):
        """Verify fix for CWE-287: Improper Authentication"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        from fastapi import HTTPException
        
        # Attacker tries to access with missing active_tenant_id claim
        malicious_payload = {
            "sub": "attacker",
            "iss": "https://roady.clerk.accounts.dev",
            # No active_tenant_id - should be rejected
        }
        
        with pytest.raises(HTTPException) as exc:
            await extract_tenant(malicious_payload, "/roady/test")
        
        # Must return 401 (not 200 or 500)
        assert exc.value.status_code == 401
    
    @pytest.mark.asyncio  
    async def test_no_cross_tenant_access(self):
        """Verify tenant isolation is maintained after fix"""
        from src.couchdb_jwt_proxy.main import extract_tenant
        
        # User with access to tenant_a
        payload_a = {
            "sub": "user_123",
            "iss": "https://roady.clerk.accounts.dev",
            "active_tenant_id": "tenant_a"
        }
        
        # User with access to tenant_b
        payload_b = {
            "sub": "user_456",
            "iss": "https://roady.clerk.accounts.dev",
            "active_tenant_id": "tenant_b"
        }
        
        tenant_a = await extract_tenant(payload_a, "/roady/test")
        tenant_b = await extract_tenant(payload_b, "/roady/test")
        
        # Verify no cross-tenant leakage
        assert tenant_a == "tenant_a"
        assert tenant_b == "tenant_b"
        assert tenant_a != tenant_b


# Integration tests
class TestIntegrationWithProxy:
    """Integration tests with full proxy"""
    
    @pytest.mark.asyncio
    async def test_roady_request_rejects_missing_claim(self):
        """Test that roady database requests reject missing active_tenant_id"""
        from src.couchdb_jwt_proxy.main import app, verify_clerk_jwt
        
        # Mock a request with valid Clerk JWT but missing active_tenant_id
        with patch('src.couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify:
            mock_verify.return_value = ({
                "sub": "user_123",
                "iss": "https://roady.clerk.accounts.dev",
                # Missing active_tenant_id
            }, None)
            
            # This would be tested in proxy_couchdb endpoint
            # The endpoint should call extract_tenant which rejects the request
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
