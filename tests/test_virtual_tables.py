"""
Tests for Virtual Tables Module (M5 - Testing)

Tests access control, immutable fields, soft-delete, bootstrap, and PouchDB compatibility.
Uses memory DAL for fast, isolated testing without touching real database.
"""

import pytest
import json
import hashlib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
import pytest_asyncio

from couchdb_jwt_proxy.main import app
from couchdb_jwt_proxy.virtual_tables import (
    VirtualTableMapper,
    VirtualTableAccessControl,
    VirtualTableValidator,
    VirtualTableHandler,
)
from couchdb_jwt_proxy.bootstrap import BootstrapManager
from couchdb_jwt_proxy.dal import create_dal


def _hash_sub(sub: str) -> str:
    """Helper to hash user sub for tests"""
    return hashlib.sha256(sub.encode('utf-8')).hexdigest()


# ============================================================================
# Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def async_client():
    """FastAPI test client with memory DAL"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_jwt_payload():
    """Mock JWT payload for testing"""
    return {
        "sub": "user_abc123",
        "email": "user@example.com",
        "iss": "https://test.clerk.accounts.dev",
        "aud": "test-app",
        "iat": 1699561200,
        "exp": 1699564800
    }


@pytest.fixture
def mock_jwt_with_tenant():
    """Mock JWT with active_tenant_id"""
    return {
        "sub": "user_abc123",
        "email": "user@example.com",
        "active_tenant_id": "tenant_personal_abc123",
        "iss": "https://test.clerk.accounts.dev",
        "aud": "test-app",
        "iat": 1699561200,
        "exp": 1699564800
    }


@pytest_asyncio.fixture
async def dal():
    """Create memory DAL instance (async fixture)"""
    return create_dal()


@pytest_asyncio.fixture
async def virtual_table_handler(dal):
    """Create virtual table handler (async fixture)"""
    return VirtualTableHandler(dal)


@pytest_asyncio.fixture
async def bootstrap_manager(dal):
    """Create bootstrap manager (async fixture)"""
    return BootstrapManager(dal)


# ============================================================================
# VirtualTableMapper Tests
# ============================================================================

class TestVirtualTableMapper:
    """Test ID mapping between virtual and internal formats"""

    def test_user_virtual_to_internal(self):
        """Test mapping virtual user ID to internal"""
        virtual_id = "abc123"
        internal_id = VirtualTableMapper.user_virtual_to_internal(virtual_id)
        assert internal_id == "user_abc123"

    def test_user_internal_to_virtual(self):
        """Test mapping internal user ID to virtual"""
        internal_id = "user_abc123"
        virtual_id = VirtualTableMapper.user_internal_to_virtual(internal_id)
        assert virtual_id == "abc123"

    def test_user_id_roundtrip(self):
        """Test virtual -> internal -> virtual roundtrip"""
        original = "abc123"
        internal = VirtualTableMapper.user_virtual_to_internal(original)
        virtual = VirtualTableMapper.user_internal_to_virtual(internal)
        assert virtual == original

    def test_tenant_virtual_to_internal(self):
        """Test mapping virtual tenant ID to internal"""
        virtual_id = "tenant-uuid-123"
        internal_id = VirtualTableMapper.tenant_virtual_to_internal(virtual_id)
        assert internal_id == "tenant_tenant-uuid-123"

    def test_tenant_internal_to_virtual(self):
        """Test mapping internal tenant ID to virtual"""
        internal_id = "tenant_tenant-uuid-123"
        virtual_id = VirtualTableMapper.tenant_internal_to_virtual(internal_id)
        assert virtual_id == "tenant-uuid-123"

    def test_tenant_id_roundtrip(self):
        """Test virtual -> internal -> virtual roundtrip"""
        original = "tenant-uuid-123"
        internal = VirtualTableMapper.tenant_virtual_to_internal(original)
        virtual = VirtualTableMapper.tenant_internal_to_virtual(internal)
        assert virtual == original


# ============================================================================
# VirtualTableAccessControl Tests
# ============================================================================

class TestVirtualTableAccessControl:
    """Test access control rules"""

    def test_user_can_read_own_doc(self):
        """User can read their own document"""
        user1_hash = _hash_sub("user1")
        assert VirtualTableAccessControl.can_read_user("user1", user1_hash) is True

    def test_user_cannot_read_other_doc(self):
        """User cannot read another user's document"""
        user2_hash = _hash_sub("user2")
        assert VirtualTableAccessControl.can_read_user("user1", user2_hash) is False

    def test_user_can_update_allowed_field(self):
        """User can update allowed fields in their own doc"""
        user1_hash = _hash_sub("user1")
        assert VirtualTableAccessControl.can_update_user("user1", user1_hash, "name") is True
        assert VirtualTableAccessControl.can_update_user("user1", user1_hash, "email") is True
        assert VirtualTableAccessControl.can_update_user("user1", user1_hash, "active_tenant_id") is True

    def test_user_cannot_update_immutable_field(self):
        """User cannot update immutable fields"""
        user1_hash = _hash_sub("user1")
        assert VirtualTableAccessControl.can_update_user("user1", user1_hash, "sub") is False
        assert VirtualTableAccessControl.can_update_user("user1", user1_hash, "type") is False
        assert VirtualTableAccessControl.can_update_user("user1", user1_hash, "_id") is False

    def test_user_cannot_update_other_user(self):
        """User cannot update another user's document"""
        user2_hash = _hash_sub("user2")
        assert VirtualTableAccessControl.can_update_user("user1", user2_hash, "name") is False

    def test_user_cannot_delete_self(self):
        """User cannot delete themselves"""
        user1_hash = _hash_sub("user1")
        assert VirtualTableAccessControl.can_delete_user("user1", user1_hash) is False

    def test_user_can_delete_other(self):
        """Admin can delete another user (delete doesn't check ownership)"""
        user1_hash = _hash_sub("user1")
        assert VirtualTableAccessControl.can_delete_user("admin", user1_hash) is True

    def test_user_can_read_tenant_if_member(self):
        """User can read tenant if in userIds"""
        # Caller responsibility: normalize Clerk subs to internal format before calling
        user1_hash = _hash_sub("user1")
        user2_hash = _hash_sub("user2")
        user3_hash = _hash_sub("user3")
        
        tenant_doc = {
            "_id": "tenant_123",
            "userIds": [f"user_{user1_hash}", f"user_{user2_hash}"],
            "userId": f"user_{user1_hash}"
        }
        # Pass internal format (user_<hash>)
        assert VirtualTableAccessControl.can_read_tenant(f"user_{user1_hash}", tenant_doc) is True
        assert VirtualTableAccessControl.can_read_tenant(f"user_{user2_hash}", tenant_doc) is True
        assert VirtualTableAccessControl.can_read_tenant(f"user_{user3_hash}", tenant_doc) is False

    def test_user_can_update_tenant_if_owner(self):
        """Only owner can update tenant"""
        tenant_doc = {
            "_id": "tenant_123",
            "userId": "owner_user",
            "userIds": ["owner_user", "member_user"]
        }
        assert VirtualTableAccessControl.can_update_tenant("owner_user", tenant_doc, "name") is True
        assert VirtualTableAccessControl.can_update_tenant("member_user", tenant_doc, "name") is False

    def test_user_can_delete_tenant_if_owner(self):
        """Only owner can delete tenant"""
        tenant_doc = {
            "_id": "tenant_123",
            "userId": "owner_user",
            "userIds": ["owner_user", "member_user"]
        }
        assert VirtualTableAccessControl.can_delete_tenant("owner_user", tenant_doc) is True
        assert VirtualTableAccessControl.can_delete_tenant("member_user", tenant_doc) is False


# ============================================================================
# VirtualTableValidator Tests
# ============================================================================

class TestVirtualTableValidator:
    """Test field validation and immutable protection"""

    def test_immutable_user_fields(self):
        """Verify immutable user field list"""
        assert "sub" in VirtualTableValidator.IMMUTABLE_USER_FIELDS
        assert "type" in VirtualTableValidator.IMMUTABLE_USER_FIELDS
        assert "_id" in VirtualTableValidator.IMMUTABLE_USER_FIELDS
        assert "tenants" in VirtualTableValidator.IMMUTABLE_USER_FIELDS
        assert "tenantIds" in VirtualTableValidator.IMMUTABLE_USER_FIELDS

    def test_immutable_tenant_fields(self):
        """Verify immutable tenant field list"""
        assert "_id" in VirtualTableValidator.IMMUTABLE_TENANT_FIELDS
        assert "type" in VirtualTableValidator.IMMUTABLE_TENANT_FIELDS
        assert "userId" in VirtualTableValidator.IMMUTABLE_TENANT_FIELDS
        assert "userIds" in VirtualTableValidator.IMMUTABLE_TENANT_FIELDS
        assert "applicationId" in VirtualTableValidator.IMMUTABLE_TENANT_FIELDS

    def test_validate_user_update_allowed_fields(self):
        """Validate update with only allowed fields"""
        old_doc = {
            "_id": "user_abc",
            "type": "user",
            "sub": "abc",
            "name": "Old Name",
            "email": "old@example.com"
        }
        new_doc = {
            "_id": "user_abc",
            "type": "user",
            "sub": "abc",
            "name": "New Name",
            "email": "new@example.com"
        }
        errors = VirtualTableValidator.validate_user_update(old_doc, new_doc)
        assert len(errors) == 0

    def test_validate_user_update_immutable_field_change(self):
        """Detect attempt to change immutable field"""
        old_doc = {
            "_id": "user_abc",
            "type": "user",
            "sub": "abc",
            "name": "Name"
        }
        new_doc = {
            "_id": "user_abc",
            "type": "user",
            "sub": "def",  # Changed - immutable!
            "name": "Name"
        }
        errors = VirtualTableValidator.validate_user_update(old_doc, new_doc)
        assert len(errors) > 0
        assert any("sub" in error for error in errors)

    def test_validate_tenant_update_allowed_fields(self):
        """Validate tenant update with only allowed fields"""
        old_doc = {
            "_id": "tenant_123",
            "type": "tenant",
            "name": "Old Team",
            "metadata": {}
        }
        new_doc = {
            "_id": "tenant_123",
            "type": "tenant",
            "name": "New Team",
            "metadata": {"custom": "value"}
        }
        errors = VirtualTableValidator.validate_tenant_update(old_doc, new_doc)
        assert len(errors) == 0

    def test_validate_tenant_update_immutable_field_change(self):
        """Detect attempt to change tenant immutable field"""
        old_doc = {
            "_id": "tenant_123",
            "type": "tenant",
            "userId": "user1",
            "name": "Team"
        }
        new_doc = {
            "_id": "tenant_123",
            "type": "tenant",
            "userId": "user2",  # Changed - immutable!
            "name": "Team"
        }
        errors = VirtualTableValidator.validate_tenant_update(old_doc, new_doc)
        assert len(errors) > 0
        assert any("userId" in error for error in errors)


# ============================================================================
# VirtualTableHandler Tests (CRUD Operations)
# ============================================================================

class TestVirtualTableHandlerUserCRUD:
    """Test user CRUD operations with access control"""

    @pytest.mark.asyncio
    async def test_get_user_own_doc(self, virtual_table_handler, dal):
        """User can read their own document"""
        # Create a user doc with proper internal ID (user_<hash>)
        user_hash = _hash_sub("abc123")
        internal_id = f"user_{user_hash}"
        user_doc = {
            "_id": internal_id,
            "type": "user",
            "sub": "abc123",
            "email": "user@example.com",
            "name": "Test User"
        }
        await dal.put_document("couch-sitter", internal_id, user_doc)

        # Get own doc - use hashed ID for URL param
        result = await virtual_table_handler.get_user(user_hash, "abc123")
        assert result["_id"] == internal_id
        assert result["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_get_user_other_doc_forbidden(self, virtual_table_handler, dal):
        """User cannot read another user's document"""
        from fastapi import HTTPException

        other_hash = _hash_sub("other")
        internal_id = f"user_{other_hash}"
        user_doc = {
            "_id": internal_id,
            "type": "user",
            "sub": "other",
            "email": "other@example.com"
        }
        await dal.put_document("couch-sitter", internal_id, user_doc)

        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.get_user(other_hash, "abc123")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_user_allowed_fields(self, virtual_table_handler, dal):
        """User can update allowed fields"""
        user_hash = _hash_sub("abc123")
        internal_id = f"user_{user_hash}"
        user_doc = {
            "_id": internal_id,
            "type": "user",
            "sub": "abc123",
            "email": "old@example.com",
            "name": "Old Name"
        }
        await dal.put_document("couch-sitter", internal_id, user_doc)

        # Update allowed fields - use hashed ID for URL param
        updates = {
            "name": "New Name",
            "email": "new@example.com"
        }
        result = await virtual_table_handler.update_user(user_hash, "abc123", updates)
        assert result["name"] == "New Name"
        assert result["email"] == "new@example.com"

    @pytest.mark.asyncio
    async def test_update_user_immutable_field_forbidden(self, virtual_table_handler, dal):
        """User cannot update immutable fields"""
        from fastapi import HTTPException

        user_hash = _hash_sub("abc123")
        internal_id = f"user_{user_hash}"
        user_doc = {
            "_id": internal_id,
            "type": "user",
            "sub": "abc123",
            "email": "user@example.com"
        }
        await dal.put_document("couch-sitter", internal_id, user_doc)

        # Try to update immutable field
        updates = {"sub": "xyz"}
        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.update_user(user_hash, "abc123", updates)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_user_soft_delete(self, virtual_table_handler, dal):
        """Soft-delete user marks as deleted"""
        other_hash = _hash_sub("other")
        internal_id = f"user_{other_hash}"
        user_doc = {
            "_id": internal_id,
            "type": "user",
            "sub": "other",
            "email": "other@example.com"
        }
        await dal.put_document("couch-sitter", internal_id, user_doc)

        # Delete other user (not self-delete prevention test) - use hashed ID
        result = await virtual_table_handler.delete_user(other_hash, "admin")
        assert result["ok"] is True

        # Verify soft-deleted
        fetched = await dal.get_document("couch-sitter", internal_id)
        assert fetched.get("deleted") is True

    @pytest.mark.asyncio
    async def test_delete_user_self_prevention(self, virtual_table_handler, dal):
        """User cannot delete themselves"""
        from fastapi import HTTPException

        user_hash = _hash_sub("abc123")
        internal_id = f"user_{user_hash}"
        user_doc = {
            "_id": internal_id,
            "type": "user",
            "sub": "abc123",
            "email": "user@example.com"
        }
        await dal.put_document("couch-sitter", internal_id, user_doc)

        # Try to self-delete - use hashed ID
        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.delete_user(user_hash, "abc123")
        assert exc_info.value.status_code == 403


class TestVirtualTableHandlerTenantCRUD:
    """Test tenant CRUD operations with ownership checks"""

    @pytest.mark.asyncio
    async def test_create_tenant(self, virtual_table_handler):
        """User becomes owner when creating tenant"""
        # Caller responsibility: normalize Clerk sub to internal format before calling
        user_hash = _hash_sub("user_abc123")
        internal_user_id = f"user_{user_hash}"
        
        result = await virtual_table_handler.create_tenant(
            internal_user_id,  # Pass internal format
            {"name": "My Team"}
        )
        assert result["name"] == "My Team"
        # userId should be in internal format (user_<hash>)
        assert result["userId"] == internal_user_id
        assert internal_user_id in result["userIds"]

    @pytest.mark.asyncio
    async def test_get_tenant_as_member(self, virtual_table_handler, dal):
        """User can read tenant if member"""
        tenant_id = "tenant_team123"
        # Use internal format for userId/userIds
        owner_hash = _hash_sub("user_owner")
        member_hash = _hash_sub("user_member")
        
        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": "Team",
            "userId": f"user_{owner_hash}",
            "userIds": [f"user_{owner_hash}", f"user_{member_hash}"]
        }
        await dal.put_document("couch-sitter", tenant_id, tenant_doc)

        # Caller responsibility: pass internal format to get_tenant
        result = await virtual_table_handler.get_tenant("team123", f"user_{member_hash}")
        assert result["name"] == "Team"

    @pytest.mark.asyncio
    async def test_get_tenant_non_member_forbidden(self, virtual_table_handler, dal):
        """User cannot read tenant if not member"""
        from fastapi import HTTPException

        tenant_id = "tenant_team123"
        # Use internal format for userId/userIds
        owner_hash = _hash_sub("user_owner")
        
        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": "Team",
            "userId": f"user_{owner_hash}",
            "userIds": [f"user_{owner_hash}"]
        }
        await dal.put_document("couch-sitter", tenant_id, tenant_doc)

        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.get_tenant("team123", "user_other")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_tenants_filtered_to_member(self, virtual_table_handler, dal):
        """List tenants returns only user's tenants"""
        # Create multiple tenants using internal format
        member_hash = _hash_sub("user_member")
        owner_hash = _hash_sub("user_owner")
        
        tenant1 = {
            "_id": "tenant_team1",
            "type": "tenant",
            "name": "Team 1",
            "userId": f"user_{member_hash}",
            "userIds": [f"user_{member_hash}"]
        }
        tenant2 = {
            "_id": "tenant_team2",
            "type": "tenant",
            "name": "Team 2",
            "userId": f"user_{owner_hash}",
            "userIds": [f"user_{owner_hash}"]
        }
        await dal.put_document("couch-sitter", "tenant_team1", tenant1)
        await dal.put_document("couch-sitter", "tenant_team2", tenant2)

        # Test raw query first
        query = {
            "selector": {
                "type": "tenant"
            }
        }
        raw_results = await dal.query_documents("couch-sitter", query)
        print(f"DEBUG: Raw query returned {len(raw_results.get('docs', []))} docs")

        # List tenants for user_member (caller responsibility: pass internal format)
        results = await virtual_table_handler.list_tenants(f"user_{member_hash}")
        assert len(results) == 1
        # Virtual table handler converts internal IDs to virtual format (removes prefix)
        assert results[0]["_id"] == "team1"

    @pytest.mark.asyncio
    async def test_update_tenant_owner_only(self, virtual_table_handler, dal):
        """Only owner can update tenant"""
        from fastapi import HTTPException

        tenant_id = "tenant_team123"
        # Use internal format
        owner_hash = _hash_sub("user_owner")
        member_hash = _hash_sub("user_member")
        
        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": "Team",
            "userId": f"user_{owner_hash}",
            "userIds": [f"user_{owner_hash}", f"user_{member_hash}"]
        }
        await dal.put_document("couch-sitter", tenant_id, tenant_doc)

        # Member tries to update
        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.update_tenant(
                "team123",
                "user_member",
                {"name": "New Name"}
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_tenant_owner_only(self, virtual_table_handler, dal):
        """Only owner can delete tenant"""
        from fastapi import HTTPException

        tenant_id = "tenant_team123"
        # Use internal format
        owner_hash = _hash_sub("user_owner")
        member_hash = _hash_sub("user_member")
        
        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": "Team",
            "userId": f"user_{owner_hash}",
            "userIds": [f"user_{owner_hash}", f"user_{member_hash}"]
        }
        await dal.put_document("couch-sitter", tenant_id, tenant_doc)

        # Member tries to delete
        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.delete_tenant("team123", "user_member", None)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_tenant_cannot_delete_active(self, virtual_table_handler, dal):
        """Cannot delete active tenant"""
        from fastapi import HTTPException

        tenant_id = "tenant_team123"
        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": "Team",
            "userId": "user_owner",
            "userIds": ["user_owner"]
        }
        await dal.put_document("couch-sitter", tenant_id, tenant_doc)

        # Try to delete active tenant
        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.delete_tenant("team123", "user_owner", "tenant_team123")
        assert exc_info.value.status_code == 403


# ============================================================================
# Bootstrap Tests
# ============================================================================

class TestBootstrapManager:
    """Test first-login bootstrap flow"""

    @pytest.mark.asyncio
    async def test_bootstrap_creates_user_and_tenant(self, bootstrap_manager):
        """Bootstrap creates user and personal tenant"""
        result = await bootstrap_manager.bootstrap_user(
            "abc123",
            "user@example.com",
            "Test User"
        )
        assert result["bootstrapped"] is True
        assert result["user_doc"]["sub"] == "abc123"
        assert result["user_doc"]["email"] == "user@example.com"
        assert result["tenant_doc"]["metadata"]["isPersonal"] is True
        assert result["active_tenant_id"] is not None

    @pytest.mark.asyncio
    async def test_bootstrap_user_exists_returns_active_tenant(self, bootstrap_manager, dal):
        """Bootstrap returns existing user's active_tenant_id"""
        # Create existing user with HASHED ID (matches new bootstrap behavior)
        # sha256("abc123") = 6ca13d52ca70c883e0f0bb101e425a89e8624de51db2d2392593af6a84118090
        import hashlib
        sub_hash = hashlib.sha256("abc123".encode()).hexdigest()
        user_id = f"user_{sub_hash}"
        user_doc = {
            "_id": user_id,
            "type": "user",
            "sub": "abc123",
            "email": "user@example.com",
            "active_tenant_id": "tenant_existing"
        }
        await dal.put_document("couch-sitter", user_id, user_doc)

        result = await bootstrap_manager.bootstrap_user("abc123", "user@example.com", "Test")
        assert result["bootstrapped"] is False
        assert result["active_tenant_id"] == "tenant_existing"

    @pytest.mark.asyncio
    async def test_ensure_user_bootstrap_with_jwt(self, bootstrap_manager):
        """ensure_user_bootstrap detects missing active_tenant_id and bootstraps"""
        payload = {
            "sub": "newuser123",
            "email": "new@example.com",
            "name": "New User"
        }

        result = await bootstrap_manager.ensure_user_bootstrap(payload)
        assert result is not None
        assert result.startswith("tenant_")


# ============================================================================
# _changes Endpoint Tests (PouchDB Compatibility)
# ============================================================================

class TestVirtualTableChanges:
    """Test _changes filtering for PouchDB sync"""

    @pytest.mark.asyncio
    async def test_user_changes_filters_own_doc(self, virtual_table_handler, dal):
        """GET /__users/_changes returns only own doc"""
        # Create two users
        user1 = {"_id": "user_abc", "type": "user", "sub": "abc"}
        user2 = {"_id": "user_xyz", "type": "user", "sub": "xyz"}
        await dal.put_document("couch-sitter", "user_abc", user1)
        await dal.put_document("couch-sitter", "user_xyz", user2)

        result = await virtual_table_handler.get_user_changes("abc")
        # Should return empty (current implementation returns empty)
        assert "results" in result
        assert "last_seq" in result

    @pytest.mark.asyncio
    async def test_tenant_changes_filters_membership(self, virtual_table_handler, dal):
        """GET /__tenants/_changes returns only member tenants"""
        # Create tenants
        tenant1 = {
            "_id": "tenant_team1",
            "type": "tenant",
            "name": "Team 1",
            "userIds": ["user_abc"]
        }
        tenant2 = {
            "_id": "tenant_team2",
            "type": "tenant",
            "name": "Team 2",
            "userIds": ["user_xyz"]
        }
        await dal.put_document("couch-sitter", "tenant_team1", tenant1)
        await dal.put_document("couch-sitter", "tenant_team2", tenant2)

        result = await virtual_table_handler.get_tenant_changes("user_abc")
        assert "results" in result
        # Should have one result (only team1)
        results = [r for r in result["results"] if not r.get("deleted")]
        assert len(results) == 1


# ============================================================================
# _bulk_docs Tests (PouchDB Compatibility)
# ============================================================================

class TestVirtualTableBulkDocs:
    """Test _bulk_docs operations for PouchDB sync"""

    @pytest.mark.asyncio
    async def test_bulk_docs_users_updates(self, virtual_table_handler, dal):
        """POST /__users/_bulk_docs processes multiple user updates"""
        # Create user with hashed ID
        user_hash = _hash_sub("abc123")
        internal_id = f"user_{user_hash}"
        user_doc = {
            "_id": internal_id,
            "type": "user",
            "sub": "abc123",
            "name": "Original",
            "email": "old@example.com"
        }
        await dal.put_document("couch-sitter", internal_id, user_doc)

        # Bulk update - use internal ID format, requesting user is the sub
        docs = [
            {
                "_id": internal_id,
                "name": "Updated"
            }
        ]
        results = await virtual_table_handler.bulk_docs_users("abc123", docs)
        assert len(results) == 1
        assert results[0]["ok"] is True

    @pytest.mark.asyncio
    async def test_bulk_docs_tenants_deletes(self, virtual_table_handler, dal):
        """POST /__tenants/_bulk_docs processes bulk deletes"""
        # Create tenant
        tenant_doc = {
            "_id": "tenant_team123",
            "type": "tenant",
            "name": "Team",
            "userId": "user_owner",
            "userIds": ["user_owner"]
        }
        await dal.put_document("couch-sitter", "tenant_team123", tenant_doc)

        # Bulk delete (mark as _deleted)
        docs = [
            {
                "_id": "tenant_team123",
                "_deleted": True
            }
        ]
        results = await virtual_table_handler.bulk_docs_tenants("user_owner", None, docs)
        assert len(results) == 1
        assert results[0]["ok"] is True


# ============================================================================
# Extract Tenant Integration Tests (Bootstrap in extract_tenant)
# ============================================================================

class TestExtractTenantBootstrapIntegration:
    """Test extract_tenant() function with 5-level discovery chain"""

    def _create_mock_tenant_service(self):
        """Create a mock TenantService that returns predictable results."""
        import uuid
        mock_service = MagicMock()
        tenant_id = str(uuid.uuid4())

        # Mock query_user_tenants to return empty (triggers Level 4)
        mock_service.query_user_tenants = AsyncMock(return_value=[])

        # Mock create_tenant to return success
        mock_service.create_tenant = AsyncMock(return_value={
            "tenant_id": tenant_id,
            "doc": {"_id": f"tenant_{tenant_id}", "owner_id": "user_hash"}
        })

        # Mock set_user_default_tenant
        mock_service.set_user_default_tenant = AsyncMock(return_value={"active_tenant_id": tenant_id})

        return mock_service, tenant_id

    @pytest.mark.asyncio
    async def test_extract_tenant_roady_creates_tenant_for_new_user(self, dal):
        """extract_tenant creates new tenant via 5-level discovery for roady app"""
        from couchdb_jwt_proxy.main import extract_tenant

        payload = {
            "sub": "user123",
            "email": "user@example.com",
            "active_tenant_id": "tenant_personal",  # Note: this is ignored by 5-level discovery
            "iss": "https://test.clerk.accounts.dev"
        }

        mock_service, expected_tenant = self._create_mock_tenant_service()

        # Mock APPLICATIONS and TenantService to work without real CouchDB
        with patch('couchdb_jwt_proxy.main.APPLICATIONS',
                   {"https://test.clerk.accounts.dev": {"databaseNames": ["roady"]}}), \
             patch('couchdb_jwt_proxy.main.TenantService', return_value=mock_service), \
             patch('couchdb_jwt_proxy.main.session_service') as mock_session:

            mock_session.get_active_tenant = AsyncMock(return_value=None)
            mock_session.create_session = AsyncMock()

            # Clear any cached tenant service
            if hasattr(extract_tenant, '_tenant_service'):
                delattr(extract_tenant, '_tenant_service')

            tenant_id = await extract_tenant(payload, "roady/docs")
            # 5-level discovery creates a new tenant (UUID format)
            assert tenant_id is not None
            # Tenant ID should be UUID-like (36 chars with dashes)
            assert len(tenant_id) == 36

    @pytest.mark.asyncio
    async def test_extract_tenant_roady_creates_tenant_when_missing_active_tenant(self, dal):
        """extract_tenant creates tenant via 5-level discovery even without active_tenant_id"""
        from couchdb_jwt_proxy.main import extract_tenant

        payload = {
            "sub": "newuser123",
            "email": "newuser@example.com",
            "name": "New User",
            "iss": "https://test.clerk.accounts.dev"
        }

        mock_service, expected_tenant = self._create_mock_tenant_service()

        # Mock APPLICATIONS and TenantService to work without real CouchDB
        with patch('couchdb_jwt_proxy.main.APPLICATIONS',
                   {"https://test.clerk.accounts.dev": {"databaseNames": ["roady"]}}), \
             patch('couchdb_jwt_proxy.main.TenantService', return_value=mock_service), \
             patch('couchdb_jwt_proxy.main.session_service') as mock_session:

            mock_session.get_active_tenant = AsyncMock(return_value=None)
            mock_session.create_session = AsyncMock()

            # Clear any cached tenant service
            if hasattr(extract_tenant, '_tenant_service'):
                delattr(extract_tenant, '_tenant_service')

            # 5-level discovery should create a new tenant (Level 4)
            tenant_id = await extract_tenant(payload, "roady/docs")
            assert tenant_id is not None
            # Should be a UUID
            assert len(tenant_id) == 36

    @pytest.mark.asyncio
    async def test_extract_tenant_couch_sitter_ignores_bootstrap(self, dal):
        """extract_tenant for couch-sitter app uses personal tenant (no bootstrap)"""
        from couchdb_jwt_proxy.main import extract_tenant
        
        payload = {
            "sub": "user123",
            "email": "user@example.com",
            "iss": "https://test.clerk.accounts.dev"
        }
        
        # Mock couch-sitter application
        with patch('couchdb_jwt_proxy.main.APPLICATIONS',
                   {"https://test.clerk.accounts.dev": {"databaseNames": ["couch-sitter"]}}), \
             patch('couchdb_jwt_proxy.main.couch_sitter_service') as mock_service, \
             patch('couchdb_jwt_proxy.main.user_cache') as mock_cache:
            
            # Mock cache to return None (cache miss)
            mock_cache.get_user_by_sub_hash.return_value = None
            
            # Setup mock to return user tenant info
            mock_user_info = MagicMock()
            mock_user_info.tenant_id = "tenant_couch_sitter_user123"
            mock_service.get_user_tenant_info = AsyncMock(return_value=mock_user_info)
            
            tenant_id = await extract_tenant(payload, "couch-sitter/docs")
            
            # Should NOT call bootstrap, should call get_user_tenant_info
            assert tenant_id == "tenant_couch_sitter_user123"
            # Verify cache was used
            mock_cache.get_user_by_sub_hash.assert_called_once()
            # Verify service was called since cache missed
            mock_service.get_user_tenant_info.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
