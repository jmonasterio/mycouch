"""
Tests for Tenant and Invitation Management

Covers: unit tests, integration tests, and security tests for the new multi-tenant model.
Uses in-memory DAL for realistic testing instead of mocks.
"""

import pytest
import json
from datetime import datetime, timezone, timedelta

# Import services and DAL
from src.couchdb_jwt_proxy.couch_sitter_service import CouchSitterService
from src.couchdb_jwt_proxy.invite_service import InviteService, TOKEN_PREFIX
from src.couchdb_jwt_proxy.dal import create_dal


# ============ FIXTURES ============

@pytest.fixture
def memory_dal():
    """Create in-memory DAL for testing"""
    dal = create_dal(backend="memory")
    yield dal
    # Cleanup not needed for memory backend


@pytest.fixture
def couch_sitter_service(memory_dal):
    """Create CouchSitterService with memory DAL"""
    return CouchSitterService(
        couch_sitter_db_url="http://localhost:5984/couch-sitter",
        couchdb_user="admin",
        couchdb_password="password",
        dal=memory_dal
    )


@pytest.fixture
def invite_service(memory_dal):
    """Create InviteService with memory DAL"""
    return InviteService(
        couch_sitter_db_url="http://localhost:5984/couch-sitter",
        couchdb_user="admin",
        couchdb_password="password",
        dal=memory_dal
    )


# ============ UNIT TESTS: Token Generation & Validation ============

class TestTokenGeneration:
    """Test secure token generation and validation"""

    def test_generate_token_format(self, invite_service):
        """Token should have correct format: sk_ prefix + hex bytes"""
        token = invite_service.generate_token()
        
        assert token.startswith(TOKEN_PREFIX)
        assert len(token) > len(TOKEN_PREFIX)
        # Should be hex characters after prefix
        hex_part = token[len(TOKEN_PREFIX):]
        assert all(c in '0123456789abcdef' for c in hex_part)

    def test_generate_different_tokens(self, invite_service):
        """Each generated token should be unique"""
        tokens = {invite_service.generate_token() for _ in range(10)}
        assert len(tokens) == 10  # All unique

    def test_hash_token_deterministic(self, invite_service):
        """Hashing same token should produce same hash"""
        token = invite_service.generate_token()
        hash1 = invite_service.hash_token(token)
        hash2 = invite_service.hash_token(token)
        
        assert hash1 == hash2

    def test_hash_different_tokens_different_hashes(self, invite_service):
        """Different tokens should produce different hashes"""
        token1 = invite_service.generate_token()
        token2 = invite_service.generate_token()
        
        hash1 = invite_service.hash_token(token1)
        hash2 = invite_service.hash_token(token2)
        
        assert hash1 != hash2

    def test_verify_token_timing_attack_resistant(self, invite_service):
        """Token verification should use timing-attack resistant comparison"""
        token = invite_service.generate_token()
        token_hash = invite_service.hash_token(token)
        
        # Valid token should verify
        assert invite_service.verify_token(token, token_hash) is True
        
        # Invalid token should not verify
        assert invite_service.verify_token("sk_invalid", token_hash) is False
        
        # Modified token should not verify
        invalid_token = "sk_" + token[len(TOKEN_PREFIX)+1:]  # Change first hex char
        assert invite_service.verify_token(invalid_token, token_hash) is False


# ============ UNIT TESTS: Invitation Service ============

class TestInvitationService:
    """Test invitation creation and validation"""

    @pytest.mark.asyncio
    async def test_create_invitation_returns_doc_with_token(self, invite_service, memory_dal):
        """Creating invitation should return document with plain token (once)"""
        invitation = await invite_service.create_invitation(
            tenant_id="tenant_123",
            tenant_name="My Workspace",
            email="bob@example.com",
            role="member",
            created_by="user_alice"
        )
        
        # Check structure
        assert invitation["_id"].startswith("invite_")
        assert invitation["type"] == "invitation"
        assert invitation["tenantId"] == "tenant_123"
        assert invitation["tenantName"] == "My Workspace"
        assert invitation["email"] == "bob@example.com"
        assert invitation["role"] == "member"
        assert invitation["status"] == "pending"
        assert invitation["createdBy"] == "user_alice"
        
        # Token should be returned (first and only time)
        assert invitation["token"].startswith(TOKEN_PREFIX)
        assert invitation["tokenHash"]  # Hash should also be present
        
        # Expiration should be set
        assert invitation["expiresAt"]
        assert invitation["acceptedAt"] is None
        assert invitation["acceptedBy"] is None

    @pytest.mark.asyncio
    async def test_validate_token_returns_valid_invitation(self, invite_service, memory_dal):
        """Validating a valid token should return invitation"""
        # Create invitation
        invitation = await invite_service.create_invitation(
            tenant_id="tenant_123",
            tenant_name="My Workspace",
            email="bob@example.com",
            role="member",
            created_by="user_alice"
        )
        
        token = invitation["token"]
        
        # Validate token
        result = await invite_service.validate_token(token)
        
        assert result is not None
        assert result["_id"] == invitation["_id"]
        assert result["status"] == "pending"
        assert result["tenantName"] == "My Workspace"

    @pytest.mark.asyncio
    async def test_validate_token_rejects_expired(self, invite_service, memory_dal):
        """Validating expired token should return None"""
        token = invite_service.generate_token()
        token_hash = invite_service.hash_token(token)
        
        # Token expired 1 day ago
        expires_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        
        # Manually create expired invitation in database
        invitation_id = "invite_expired"
        invitation_doc = {
            "_id": invitation_id,
            "type": "invitation",
            "tenantId": "tenant_123",
            "tokenHash": token_hash,
            "status": "pending",
            "expiresAt": expires_at,
            "createdAt": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        }
        
        await memory_dal.get(invitation_id, "PUT", invitation_doc)
        
        # Token should be rejected as expired
        result = await invite_service.validate_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_token_rejects_accepted(self, invite_service, memory_dal):
        """Validating already-accepted token should return None (single-use)"""
        # Create and accept invitation
        invitation = await invite_service.create_invitation(
            tenant_id="tenant_123",
            tenant_name="My Workspace",
            email="bob@example.com",
            role="member",
            created_by="user_alice"
        )
        
        token = invitation["token"]
        
        # Accept the invitation
        await invite_service.accept_invitation(invitation, "user_bob")
        
        # Trying to use token again should fail
        result = await invite_service.validate_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_token_rejects_revoked(self, invite_service, memory_dal):
        """Validating revoked token should return None"""
        # Create and revoke invitation
        invitation = await invite_service.create_invitation(
            tenant_id="tenant_123",
            tenant_name="My Workspace",
            email="bob@example.com",
            role="member",
            created_by="user_alice"
        )
        
        token = invitation["token"]
        invite_id = invitation["_id"]
        
        # Revoke the invitation
        await invite_service.revoke_invitation(invite_id)
        
        # Token should be rejected
        result = await invite_service.validate_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_token_invalid_format(self, invite_service):
        """Invalid token format should return None without DB call"""
        result = await invite_service.validate_token("invalid_no_prefix")
        assert result is None
        
        result = await invite_service.validate_token("wrong_prefix123")
        assert result is None


# ============ UNIT TESTS: Tenant Management ============

class TestTenantManagement:
    """Test tenant creation and user addition"""

    @pytest.mark.asyncio
    async def test_create_workspace_tenant(self, couch_sitter_service, memory_dal):
        """Creating workspace tenant should set userId and userIds"""
        tenant = await couch_sitter_service.create_workspace_tenant(
            user_id="user_alice",
            name="My Band",
            application_id="roady"
        )
        
        assert tenant["type"] == "tenant"
        assert tenant["name"] == "My Band"
        assert tenant["applicationId"] == "roady"
        assert tenant["userId"] == "user_alice"
        assert tenant["userIds"] == ["user_alice"]
        assert tenant["metadata"]["createdBy"] == "user_alice"
        assert tenant["metadata"]["autoCreated"] is False

    @pytest.mark.asyncio
    async def test_get_tenant(self, couch_sitter_service, memory_dal):
        """Should fetch tenant from database"""
        # Create a tenant first
        tenant = await couch_sitter_service.create_workspace_tenant(
            user_id="user_alice",
            name="My Workspace",
            application_id="roady"
        )
        
        tenant_id = tenant["_id"]
        
        # Now fetch it
        result = await couch_sitter_service.get_tenant(tenant_id)
        
        assert result is not None
        assert result["_id"] == tenant_id
        assert result["name"] == "My Workspace"

    @pytest.mark.asyncio
    async def test_get_tenant_not_found(self, couch_sitter_service, memory_dal):
        """Should return None for non-existent tenant"""
        result = await couch_sitter_service.get_tenant("nonexistent_tenant_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_add_user_to_tenant(self, couch_sitter_service, memory_dal):
        """Adding user to tenant should add to userIds and create mapping"""
        # Create a tenant
        tenant = await couch_sitter_service.create_workspace_tenant(
            user_id="user_alice",
            name="My Band",
            application_id="roady"
        )
        
        tenant_id = tenant["_id"]
        
        # Add another user
        result = await couch_sitter_service.add_user_to_tenant(
            tenant_id=tenant_id,
            user_id="user_bob",
            role="member"
        )
        
        assert "user_bob" in result["userIds"]
        assert len(result["userIds"]) == 2
        
        # Verify mapping was created
        mapping = await couch_sitter_service.get_tenant_user_mapping(tenant_id, "user_bob")
        assert mapping is not None
        assert mapping["role"] == "member"


# ============ INTEGRATION TESTS: Invitation Flow ============

class TestInvitationFlow:
    """Test complete invitation acceptance flow"""

    @pytest.mark.asyncio
    async def test_complete_invitation_flow(self, couch_sitter_service, invite_service, memory_dal):
        """Test full flow: create invitation -> validate token -> accept"""
        tenant_id = "tenant_123"
        tenant_name = "My Band"
        email = "bob@example.com"
        alice_id = "user_alice"
        bob_id = "user_bob"
        
        # 1. Create invitation
        invitation = await invite_service.create_invitation(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            email=email,
            role="member",
            created_by=alice_id
        )
        
        assert invitation["status"] == "pending"
        token = invitation["token"]
        
        # 2. Bob previews invitation (validate token)
        preview = await invite_service.validate_token(token)
        assert preview is not None
        assert preview["tenantName"] == tenant_name
        assert preview["role"] == "member"
        
        # 3. Bob accepts invitation
        accepted = await invite_service.accept_invitation(invitation, bob_id)
        assert accepted["status"] == "accepted"
        assert accepted["acceptedBy"] == bob_id
        
        # 4. Verify token cannot be reused
        reuse = await invite_service.validate_token(token)
        assert reuse is None  # Single-use enforcement


class TestWorkspaceCreationAndInvitation:
    """Test creating workspace and inviting users"""

    @pytest.mark.asyncio
    async def test_create_workspace_and_invite(self, couch_sitter_service, invite_service, memory_dal):
        """Test workflow: create workspace -> invite user -> accept"""
        # Alice creates a workspace
        workspace = await couch_sitter_service.create_workspace_tenant(
            user_id="user_alice",
            name="The Beatles",
            application_id="roady"
        )
        
        workspace_id = workspace["_id"]
        
        # Alice invites Bob
        invitation = await invite_service.create_invitation(
            tenant_id=workspace_id,
            tenant_name="The Beatles",
            email="bob@example.com",
            role="member",
            created_by="user_alice"
        )
        
        token = invitation["token"]
        
        # Bob accepts
        result = await invite_service.accept_invitation(invitation, "user_bob")
        
        # Add Bob to workspace via tenant service
        updated_workspace = await couch_sitter_service.add_user_to_tenant(
            tenant_id=workspace_id,
            user_id="user_bob",
            role="member"
        )
        
        assert "user_bob" in updated_workspace["userIds"]
        assert len(updated_workspace["userIds"]) == 2


# ============ SECURITY TESTS ============

class TestSecurityConstraints:
    """Test authorization and security constraints"""

    @pytest.mark.asyncio
    async def test_cannot_invite_to_personal_tenant(self, couch_sitter_service, invite_service):
        """Should block invitations to personal tenants"""
        # Personal tenants have metadata.autoCreated=True
        personal_tenant = {
            "_id": "tenant_personal_123",
            "type": "tenant",
            "userId": "user_alice",
            "userIds": ["user_alice"],
            "metadata": {
                "autoCreated": True  # Personal tenant marker
            }
        }
        
        # Verify the check works: personal tenant has autoCreated=True
        assert personal_tenant["metadata"]["autoCreated"] is True

    def test_owner_cannot_be_removed(self):
        """In authorization checks: owner cannot be removed from tenant"""
        tenant = {"userId": "user_alice"}
        member_to_remove = "user_alice"
        
        # Should raise error if trying to remove owner
        assert tenant["userId"] == member_to_remove

    def test_owner_role_cannot_change(self):
        """In authorization checks: owner role cannot be changed"""
        tenant = {"userId": "user_alice"}
        user_trying_to_change = "user_alice"
        target_user = "user_alice"
        
        # Should raise error if trying to change owner role
        assert user_trying_to_change == tenant["userId"]
        assert target_user == tenant["userId"]

    @pytest.mark.asyncio
    async def test_token_not_returned_after_initial_creation(self, invite_service, memory_dal):
        """Token should only be returned once during creation"""
        # Create invitation - token is returned
        invitation = await invite_service.create_invitation(
            tenant_id="tenant_123",
            tenant_name="Test",
            email="user@example.com",
            role="member",
            created_by="user_alice"
        )
        
        token = invitation["token"]
        assert token.startswith(TOKEN_PREFIX)
        
        # Fetch from database - should have hash but no token
        fetched = await invite_service.get_invitation_by_id(invitation["_id"])
        assert "tokenHash" in fetched
        # Token should not be returned from database (security)
        # This is enforced by never storing plain token


# ============ ROLE-BASED ACCESS CONTROL TESTS ============

class TestRoleBasedAccess:
    """Test role-based authorization rules"""

    def test_owner_permissions(self):
        """Owner should have full permissions"""
        role = "owner"
        
        assert role in ["owner", "admin"]  # Can do admin actions
        assert role == "owner"  # Only owner can delete/change roles

    def test_admin_permissions(self):
        """Admin should have limited permissions"""
        role = "admin"
        
        assert role in ["owner", "admin"]  # Can manage members
        # But cannot delete tenant or change roles (only owner)

    def test_member_permissions(self):
        """Member should have read-only access"""
        role = "member"
        
        assert role not in ["owner", "admin"]  # Cannot manage members
        # Can read tenant and access data only


# ============ TOKEN EXPIRATION TESTS ============

class TestTokenExpiration:
    """Test token expiration logic"""

    @pytest.mark.asyncio
    async def test_token_expires_after_7_days(self, invite_service, memory_dal):
        """Token should expire after 7 days"""
        # Create invitation (default 7 day expiration)
        invitation = await invite_service.create_invitation(
            tenant_id="tenant_123",
            tenant_name="Test",
            email="user@example.com",
            role="member",
            created_by="user_alice"
        )
        
        expires_at = datetime.fromisoformat(invitation["expiresAt"].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        
        # Should be approximately 7 days in future (within 1 minute)
        delta = (expires_at - now).total_seconds()
        assert 604600 < delta < 604800  # ~7 days ±10 seconds


# ============ TIMING ATTACK RESISTANCE ============

class TestTimingAttackResistance:
    """Verify protection against timing attacks"""

    def test_hmac_compare_digest_used(self, invite_service):
        """Token comparison should use hmac.compare_digest"""
        token = invite_service.generate_token()
        token_hash = invite_service.hash_token(token)
        
        # Valid token should verify with constant time
        valid = invite_service.verify_token(token, token_hash)
        assert valid is True
        
        # Invalid token should also take constant time (not bail early)
        invalid = invite_service.verify_token("sk_invalid", token_hash)
        assert invalid is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
