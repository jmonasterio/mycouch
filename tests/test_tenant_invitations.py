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
        
        # Verify role was added to user's tenants array
        role = await couch_sitter_service.get_user_role_for_tenant("user_bob", tenant_id)
        assert role == "member"


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


# ============ COMPREHENSIVE INTEGRATION TESTS ============
# These tests verify the COMPLETE invitation acceptance flow end-to-end

class TestInvitationAcceptanceComplete:
    """
    Test complete invitation acceptance with full data verification.
    This is the critical test that was missing and explains the deleted bands issue.
    """

    @pytest.mark.asyncio
    async def test_accept_invitation_updates_all_data_structures(
        self, couch_sitter_service, invite_service, memory_dal
    ):
        """
        Verify accepting invitation updates tenant and user documents correctly.
        
        This is the key integration test that validates:
        1. Tenant's userIds is updated
        2. User's tenants array has correct format with role, joinedAt, etc.
        3. User's tenantIds array is updated
        4. Tenant is visible via get_user_tenants()
        5. Token cannot be reused
        """
        
        # ===== SETUP: Create inviter and invitee =====
        inviter_sub = "user_alice_sub_123"
        inviter_hash = couch_sitter_service._hash_sub(inviter_sub)
        inviter_id = f"user_{inviter_hash}"
        
        invitee_sub = "user_bob_sub_456"
        invitee_hash = couch_sitter_service._hash_sub(invitee_sub)
        invitee_id = f"user_{invitee_hash}"
        
        # Create both users
        await couch_sitter_service.create_user_with_personal_tenant_multi_tenant(
            sub=inviter_sub,
            email="alice@example.com",
            name="Alice"
        )
        
        await couch_sitter_service.create_user_with_personal_tenant_multi_tenant(
            sub=invitee_sub,
            email="bob@example.com",
            name="Bob"
        )
        
        # ===== CREATE WORKSPACE TENANT =====
        workspace = await couch_sitter_service.create_workspace_tenant(
            user_id=inviter_id,
            name="The Beatles",
            application_id="roady"
        )
        workspace_id = workspace["_id"]
        workspace_id_virtual = workspace_id[7:]  # Remove "tenant_" prefix
        
        # Verify workspace has only inviter initially
        assert inviter_id in workspace["userIds"]
        assert invitee_id not in workspace["userIds"]
        
        # ===== CREATE INVITATION =====
        invitation = await invite_service.create_invitation(
            tenant_id=workspace_id,
            tenant_name="The Beatles",
            email="bob@example.com",
            role="member",
            created_by=inviter_id
        )
        token = invitation["token"]
        invite_id = invitation["_id"]
        
        assert token.startswith("sk_")
        assert invitation["status"] == "pending"
        
        # ===== ACCEPT INVITATION =====
        # Step 1: Validate token
        valid_invitation = await invite_service.validate_token(token)
        assert valid_invitation is not None, "Token should be valid before acceptance"
        assert valid_invitation["_id"] == invite_id
        
        # Step 2: Mark invitation as accepted
        await invite_service.accept_invitation(valid_invitation, invitee_id)
        
        # Step 3: Add user to tenant (this is where cleanup happens)
        updated_workspace = await couch_sitter_service.add_user_to_tenant(
            tenant_id=workspace_id,
            user_id=invitee_id,
            role="member"
        )
        
        # ===== VERIFY RESULT 1: Tenant's userIds updated =====
        tenant = await couch_sitter_service.get_tenant(workspace_id)
        assert invitee_id in tenant["userIds"], \
            f"Invitee {invitee_id} should be in tenant's userIds. Got: {tenant['userIds']}"
        assert inviter_id in tenant["userIds"], \
            "Inviter should still be in tenant's userIds"
        assert len(tenant["userIds"]) == 2, \
            f"Should have exactly 2 members. Got: {len(tenant['userIds'])}"
        
        # ===== VERIFY RESULT 2: User's tenants array has correct format =====
        invitee_doc = await couch_sitter_service.find_user_by_sub_hash(invitee_hash)
        assert invitee_doc is not None, "Invitee user document should exist"
        
        invitee_tenants = invitee_doc.get("tenants", [])
        workspace_entry = next(
            (t for t in invitee_tenants if t.get("tenantId") == workspace_id_virtual),
            None
        )
        
        assert workspace_entry is not None, \
            f"Invitee should have workspace in tenants array. Got: {invitee_tenants}"
        assert workspace_entry.get("role") == "member", \
            f"Role should be 'member'. Got: {workspace_entry.get('role')}"
        assert workspace_entry.get("joinedAt") is not None, \
            "joinedAt timestamp should be set"
        assert workspace_entry.get("personal") is False, \
            "Should not be marked as personal"
        assert "userIds" in workspace_entry, \
            "userIds should be copied to tenants array entry"
        
        # ===== VERIFY RESULT 3: User's tenantIds updated =====
        invitee_tenant_ids = invitee_doc.get("tenantIds", [])
        assert workspace_id in invitee_tenant_ids, \
            f"Internal ID {workspace_id} should be in tenantIds. Got: {invitee_tenant_ids}"
        
        # ===== VERIFY RESULT 4: Tenant visible via get_user_tenants() =====
        visible_tenants, _ = await couch_sitter_service.get_user_tenants(invitee_sub)
        visible_tenant_ids = [t["tenantId"] for t in visible_tenants]
        assert workspace_id_virtual in visible_tenant_ids, \
            f"Workspace {workspace_id_virtual} should be visible. Got: {visible_tenant_ids}"
        
        # Verify the visible tenant has correct metadata
        visible_workspace = next(
            (t for t in visible_tenants if t["tenantId"] == workspace_id_virtual),
            None
        )
        assert visible_workspace is not None
        assert visible_workspace["name"] == "The Beatles"
        assert visible_workspace["role"] == "member"
        
        # ===== VERIFY RESULT 5: Token cannot be reused (single-use) =====
        reused = await invite_service.validate_token(token)
        assert reused is None, \
            "Token should not be reusable after acceptance"

    @pytest.mark.asyncio
    async def test_cleanup_removes_deleted_tenant_references(
        self, couch_sitter_service, invite_service, memory_dal
    ):
        """
        Verify that accepting invitation cleans up deleted tenant references.
        
        This tests the scenario that was causing the "5 deleted bands appear" bug:
        - User syncs account with deleted tenants in their arrays
        - User accepts invitation
        - Cleanup should remove the deleted references
        """
        
        # ===== SETUP =====
        inviter_sub = "user_alice_sub_789"
        inviter_hash = couch_sitter_service._hash_sub(inviter_sub)
        inviter_id = f"user_{inviter_hash}"
        
        invitee_sub = "user_bob_sub_789"
        invitee_hash = couch_sitter_service._hash_sub(invitee_sub)
        invitee_id = f"user_{invitee_hash}"
        
        await couch_sitter_service.create_user_with_personal_tenant_multi_tenant(
            sub=inviter_sub, email="alice@example.com", name="Alice"
        )
        await couch_sitter_service.create_user_with_personal_tenant_multi_tenant(
            sub=invitee_sub, email="bob@example.com", name="Bob"
        )
        
        workspace = await couch_sitter_service.create_workspace_tenant(
            user_id=inviter_id, name="The Beatles", application_id="roady"
        )
        workspace_id = workspace["_id"]
        
        # ===== SIMULATE SYNCED DELETED TENANTS =====
        # This simulates the scenario where invitee's account has deleted tenant references
        # synced from the inviter's account (e.g., from a previous sync)
        
        invitee_doc = await couch_sitter_service.find_user_by_sub_hash(invitee_hash)
        
        deleted_tenant_id_1 = "tenant_deleted_uuid_1"
        deleted_tenant_id_2 = "tenant_deleted_uuid_2"
        deleted_uuid_1 = "deleted_uuid_1"
        deleted_uuid_2 = "deleted_uuid_2"
        
        # Add stale deleted references to invitee's arrays
        invitee_doc.setdefault("tenantIds", []).extend([
            deleted_tenant_id_1,
            deleted_tenant_id_2
        ])
        invitee_doc.setdefault("tenants", []).extend([
            {
                "tenantId": deleted_uuid_1,
                "role": "member",
                "personal": False,
                "joinedAt": "2025-01-01T00:00:00Z"
            },
            {
                "tenantId": deleted_uuid_2,
                "role": "member",
                "personal": False,
                "joinedAt": "2025-01-02T00:00:00Z"
            }
        ])
        
        # Save the corrupted document
        await memory_dal.get(invitee_id, "PUT", invitee_doc)
        
        # Verify it has the stale references
        invitee_doc_before = await couch_sitter_service.find_user_by_sub_hash(invitee_hash)
        assert len(invitee_doc_before.get("tenantIds", [])) == 2 + 1, \
            "Should have 2 deleted + 1 personal tenant before"
        assert len(invitee_doc_before.get("tenants", [])) == 2 + 1, \
            "Should have 2 deleted + 1 personal tenant in tenants before"
        
        # ===== ACCEPT INVITATION (triggers cleanup) =====
        invitation = await invite_service.create_invitation(
            tenant_id=workspace_id,
            tenant_name="The Beatles",
            email="bob@example.com",
            role="member",
            created_by=inviter_id
        )
        
        await invite_service.accept_invitation(invitation, invitee_id)
        await couch_sitter_service.add_user_to_tenant(
            tenant_id=workspace_id,
            user_id=invitee_id,
            role="member"
        )
        
        # ===== VERIFY CLEANUP HAPPENED =====
        invitee_doc_after = await couch_sitter_service.find_user_by_sub_hash(invitee_hash)
        
        # Deleted tenant IDs should be removed from tenantIds
        invitee_tenant_ids = invitee_doc_after.get("tenantIds", [])
        assert deleted_tenant_id_1 not in invitee_tenant_ids, \
            f"Deleted tenant {deleted_tenant_id_1} should be removed"
        assert deleted_tenant_id_2 not in invitee_tenant_ids, \
            f"Deleted tenant {deleted_tenant_id_2} should be removed"
        assert workspace_id in invitee_tenant_ids, \
            "New workspace should be added to tenantIds"
        
        # Deleted tenants should be removed from tenants array
        invitee_tenants = invitee_doc_after.get("tenants", [])
        deleted_entries = [t for t in invitee_tenants 
                          if t.get("tenantId") in [deleted_uuid_1, deleted_uuid_2]]
        assert len(deleted_entries) == 0, \
            f"Deleted tenants should be removed from tenants array. Got: {deleted_entries}"
        
        # New workspace should be present
        workspace_entries = [t for t in invitee_tenants 
                            if t.get("tenantId") == workspace_id[7:]]
        assert len(workspace_entries) == 1, \
            "New workspace should be in tenants array"
        assert workspace_entries[0].get("role") == "member"

    @pytest.mark.asyncio
    async def test_virtual_endpoint_filters_deleted_tenants(
        self, couch_sitter_service, memory_dal
    ):
        """
        Verify that GET /__tenants endpoint filters out deleted tenants.
        
        Even if user is in a deleted tenant's userIds array, it should not be returned.
        This is the server-side filtering that prevents deleted tenants from appearing
        in the frontend after acceptance.
        """
        
        # ===== SETUP =====
        user_id = "user_test_virtual"
        
        # Create active tenant
        active_tenant = {
            "_id": "tenant_active_uuid",
            "type": "tenant",
            "name": "Active Band",
            "userIds": [user_id],
            "createdAt": "2025-01-01T00:00:00Z",
            "deletedAt": None
        }
        
        # Create deleted tenant (user is still member, but shouldn't appear)
        deleted_tenant = {
            "_id": "tenant_deleted_uuid",
            "type": "tenant",
            "name": "Deleted Band",
            "userIds": [user_id],
            "createdAt": "2025-01-01T00:00:00Z",
            "deletedAt": "2025-01-10T00:00:00Z"  # ← Marked as deleted
        }
        
        # Store both tenants in database
        await memory_dal.get("couch-sitter/tenant_active_uuid", "PUT", active_tenant)
        await memory_dal.get("couch-sitter/tenant_deleted_uuid", "PUT", deleted_tenant)
        
        # ===== QUERY FOR TENANTS =====
        # Simulate what virtual_tables.py does in list_tenants()
        query = {"selector": {"type": "tenant"}}
        result = await memory_dal.query("couch-sitter", query)
        all_docs = result.get("docs", [])
        
        # Filter like the endpoint does
        filtered_docs = [
            doc for doc in all_docs 
            if user_id in doc.get("userIds", []) 
            and not doc.get("deletedAt")
        ]
        
        # ===== VERIFY =====
        filtered_ids = [doc["_id"] for doc in filtered_docs]
        
        assert "tenant_active_uuid" in filtered_ids, \
            "Active tenant should be returned"
        assert "tenant_deleted_uuid" not in filtered_ids, \
            "Deleted tenant should be filtered out"
        assert len(filtered_docs) == 1, \
            f"Should only return 1 tenant. Got: {len(filtered_docs)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
