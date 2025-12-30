"""
Test cascade delete functionality for bands/tenants.

When a band (tenant) is deleted:
1. Soft-delete the tenant document in couch-sitter
2. Hard-delete the band's database (e.g., DELETE /roady)

This ensures no orphaned data remains.
"""

import pytest
import logging
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch

from src.couchdb_jwt_proxy.virtual_tables import VirtualTableHandler
from src.couchdb_jwt_proxy.dal import CouchDAL

logger = logging.getLogger(__name__)


class TestCascadeDelete:
    """Test cascade delete of bands/tenants"""
    
    @pytest.fixture
    def dal(self):
        """Create a memory-backed DAL for testing"""
        return CouchDAL(backend="memory")
    
    @pytest.fixture
    def virtual_table_handler(self, dal):
        """Create a VirtualTableHandler with the test DAL"""
        return VirtualTableHandler(dal=dal, clerk_service=None, applications={})
    
    @pytest.mark.asyncio
    async def test_cascade_delete_tenant_and_database(self, virtual_table_handler, dal):
        """Test that delete_tenant deletes both tenant doc and database"""
        
        tenant_id = "team123"
        internal_id = f"tenant_{tenant_id}"
        
        # Create tenant document with applicationId pointing to roady database
        tenant_doc = {
            "_id": internal_id,
            "type": "tenant",
            "name": "Test Band",
            "userId": "user_owner",
            "userIds": ["user_owner"],
            "applicationId": "roady",  # This is the key - tells us which db to delete
            "createdAt": "2024-01-01T00:00:00Z"
        }
        await dal.put_document("couch-sitter", internal_id, tenant_doc)
        
        # Verify tenant exists
        existing = await dal.get_document("couch-sitter", internal_id)
        assert existing["_id"] == internal_id
        assert existing["applicationId"] == "roady"
        
        # Mock delete_database to track if it's called
        original_delete_db = dal.delete_database
        dal.delete_database = AsyncMock(return_value={"ok": True})
        
        # Delete tenant
        result = await virtual_table_handler.delete_tenant(tenant_id, "user_owner", "")
        
        # Verify result
        assert result["ok"] is True
        assert result["_id"] == internal_id
        
        # Verify tenant was soft-deleted in couch-sitter
        deleted_tenant = await dal.get_document("couch-sitter", internal_id)
        assert deleted_tenant.get("deleted") is True
        assert deleted_tenant.get("updatedAt") is not None
        
        # Verify delete_database was called with roady
        dal.delete_database.assert_called_once_with("roady")
        
        # Restore original method
        dal.delete_database = original_delete_db
    
    @pytest.mark.asyncio
    async def test_cascade_delete_with_database_failure_returns_warning(self, virtual_table_handler, dal):
        """Test that if database deletion fails, we still succeed but include warning"""
        
        tenant_id = "team123"
        internal_id = f"tenant_{tenant_id}"
        
        # Create tenant
        tenant_doc = {
            "_id": internal_id,
            "type": "tenant",
            "name": "Test Band",
            "userId": "user_owner",
            "userIds": ["user_owner"],
            "applicationId": "roady"
        }
        await dal.put_document("couch-sitter", internal_id, tenant_doc)
        
        # Mock delete_database to fail
        dal.delete_database = AsyncMock(side_effect=Exception("Connection timeout"))
        
        # Delete tenant - should still succeed
        result = await virtual_table_handler.delete_tenant(tenant_id, "user_owner", "")
        
        # Verify success with warning
        assert result["ok"] is True
        assert "warnings" in result
        assert any("roady" in w for w in result["warnings"])
        
        # Verify tenant was still deleted
        deleted_tenant = await dal.get_document("couch-sitter", internal_id)
        assert deleted_tenant.get("deleted") is True
    
    @pytest.mark.asyncio
    async def test_cascade_delete_tenant_deletion_failure_fails_completely(self, virtual_table_handler, dal):
        """Test that if tenant deletion fails, we fail even if database deletion would succeed"""
        
        tenant_id = "team123"
        internal_id = f"tenant_{tenant_id}"
        
        # Create tenant
        tenant_doc = {
            "_id": internal_id,
            "type": "tenant",
            "name": "Test Band",
            "userId": "user_owner",
            "userIds": ["user_owner"],
            "applicationId": "roady"
        }
        await dal.put_document("couch-sitter", internal_id, tenant_doc)
        
        # Mock put_document to fail for tenant deletion
        original_put = dal.put_document
        async def failing_put(db, doc_id, doc):
            if db == "couch-sitter" and doc_id == internal_id:
                raise HTTPException(status_code=409, detail="Revision conflict")
            return await original_put(db, doc_id, doc)
        
        dal.put_document = failing_put
        
        # Delete tenant - should fail
        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.delete_tenant(tenant_id, "user_owner", "")
        
        assert exc_info.value.status_code == 500
        assert "Failed to delete tenant document" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_cascade_delete_skips_couch_sitter_database(self, virtual_table_handler, dal):
        """Test that we don't try to delete the couch-sitter system database"""
        
        tenant_id = "team123"
        internal_id = f"tenant_{tenant_id}"
        
        # Create tenant with couch-sitter as applicationId (shouldn't happen, but safety)
        tenant_doc = {
            "_id": internal_id,
            "type": "tenant",
            "name": "Test Band",
            "userId": "user_owner",
            "userIds": ["user_owner"],
            "applicationId": "couch-sitter"  # System database
        }
        await dal.put_document("couch-sitter", internal_id, tenant_doc)
        
        # Mock delete_database to track calls
        dal.delete_database = AsyncMock()
        
        # Delete tenant
        result = await virtual_table_handler.delete_tenant(tenant_id, "user_owner", "")
        
        # Verify success with no database deletion
        assert result["ok"] is True
        
        # Verify delete_database was NOT called (couch-sitter is skipped)
        dal.delete_database.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_cascade_delete_no_application_id(self, virtual_table_handler, dal):
        """Test behavior when tenant has no applicationId"""
        
        tenant_id = "team123"
        internal_id = f"tenant_{tenant_id}"
        
        # Create tenant WITHOUT applicationId
        tenant_doc = {
            "_id": internal_id,
            "type": "tenant",
            "name": "Test Band",
            "userId": "user_owner",
            "userIds": ["user_owner"]
            # No applicationId
        }
        await dal.put_document("couch-sitter", internal_id, tenant_doc)
        
        # Mock delete_database to track calls
        dal.delete_database = AsyncMock()
        
        # Delete tenant
        result = await virtual_table_handler.delete_tenant(tenant_id, "user_owner", "")
        
        # Verify success with no database deletion attempt
        assert result["ok"] is True
        
        # Verify delete_database was NOT called
        dal.delete_database.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_delete_tenant_only_owner_can_delete(self, virtual_table_handler, dal):
        """Test access control: only owner can delete"""
        
        tenant_id = "team123"
        internal_id = f"tenant_{tenant_id}"
        
        # Create tenant
        tenant_doc = {
            "_id": internal_id,
            "type": "tenant",
            "name": "Test Band",
            "userId": "user_owner",
            "userIds": ["user_owner", "user_member"],
            "applicationId": "roady"
        }
        await dal.put_document("couch-sitter", internal_id, tenant_doc)
        
        # Member tries to delete - should fail
        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.delete_tenant(tenant_id, "user_member", "")
        
        assert exc_info.value.status_code == 403
        assert "Only owner" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_delete_tenant_cannot_delete_active_tenant(self, virtual_table_handler, dal):
        """Test that user cannot delete their active/current tenant"""
        
        tenant_id = "team123"
        internal_id = f"tenant_{tenant_id}"
        
        # Create tenant
        tenant_doc = {
            "_id": internal_id,
            "type": "tenant",
            "name": "Test Band",
            "userId": "user_owner",
            "userIds": ["user_owner"],
            "applicationId": "roady"
        }
        await dal.put_document("couch-sitter", internal_id, tenant_doc)
        
        # Try to delete active tenant
        with pytest.raises(HTTPException) as exc_info:
            await virtual_table_handler.delete_tenant(
                tenant_id, 
                "user_owner", 
                internal_id  # This is the active tenant
            )
        
        assert exc_info.value.status_code == 403
        assert "active tenant" in exc_info.value.detail.lower()
