"""
Tenant Access Control Validation

Ensures that:
1. Every document written to app DBs has a 'tenant' field
2. The tenant value belongs to the authenticated user's authorized tenants
3. Users cannot access or modify data from other tenants
"""

import logging
from typing import Dict, List, Any, Optional
from fastapi import HTTPException
import json
import re
from uuid import UUID

logger = logging.getLogger(__name__)


class TenantAccessError(Exception):
    """Raised when document access violates tenant ownership"""
    pass


class TenantIdFormatError(Exception):
    """Raised when tenant ID format is invalid"""
    pass


class UserIdFormatError(Exception):
    """Raised when user ID format is invalid"""
    pass


def validate_user_id_format(user_id: str) -> None:
    """
    Validate that user ID matches the required format: user_<64-char-sha256-hash>
    
    Args:
        user_id: User ID to validate
        
    Raises:
        UserIdFormatError: If format is invalid
    """
    if not user_id:
        raise UserIdFormatError("User ID cannot be empty")
    
    # Must start with "user_"
    if not user_id.startswith("user_"):
        raise UserIdFormatError(
            f"User ID must start with 'user_', got: {user_id}"
        )
    
    # Extract the hash part after "user_"
    hash_part = user_id[5:]  # Skip "user_" prefix
    
    if not hash_part:
        raise UserIdFormatError("User ID must include a hash after 'user_'")
    
    # Validate that hash is exactly 64 characters (SHA256 hex)
    if len(hash_part) != 64:
        raise UserIdFormatError(
            f"User ID hash must be 64 characters (SHA256 hex), got {len(hash_part)}: {hash_part}"
        )
    
    # Validate that hash contains only valid hex characters
    try:
        int(hash_part, 16)
    except ValueError:
        raise UserIdFormatError(
            f"User ID hash must be valid hexadecimal, got: {hash_part}"
        )


def validate_tenant_id_format(tenant_id: str) -> None:
    """
    Validate that tenant ID matches the required format: tenant_{uuid}
    
    Args:
        tenant_id: Tenant ID to validate
        
    Raises:
        TenantIdFormatError: If format is invalid
    """
    if not tenant_id:
        raise TenantIdFormatError("Tenant ID cannot be empty")
    
    # Must start with "tenant_"
    if not tenant_id.startswith("tenant_"):
        raise TenantIdFormatError(
            f"Tenant ID must start with 'tenant_', got: {tenant_id}"
        )
    
    # Extract the UUID part after "tenant_"
    uuid_part = tenant_id[7:]  # Skip "tenant_" prefix
    
    if not uuid_part:
        raise TenantIdFormatError("Tenant ID must include a UUID after 'tenant_'")
    
    # Validate that the UUID part is a valid UUID
    try:
        UUID(uuid_part)
    except ValueError:
        raise TenantIdFormatError(
            f"Tenant ID must have format 'tenant_{{uuid}}', got invalid UUID: {uuid_part}"
        )


class TenantValidator:
    """Validate tenant access for document writes"""
    
    def __init__(self, couch_sitter_service):
        self.couch_sitter_service = couch_sitter_service
    
    async def validate_write(
        self,
        doc: Dict[str, Any],
        user_id: str,
        database: str
    ) -> None:
        """
        Validate that user can write this document to this database.
        
        Rules:
        1. Document must have 'tenant' field (except band-info, which derives from _id)
        2. tenant value must be in user's authorized tenants
        3. Cannot write to couch-sitter (central registry)
        
        Args:
            doc: Document being written
            user_id: Authenticated user ID (from JWT)
            database: Target database (e.g., 'roady', 'roady-staging')
        
        Raises:
            TenantAccessError: If validation fails
        """
        
        # Ensure this is an app database, not couch-sitter
        if database == 'couch-sitter':
            raise TenantAccessError(
                "Cannot write directly to couch-sitter. "
                "Use /api/tenants endpoint to create tenants."
            )
        
        # Get user's authorized tenants from couch-sitter
        try:
            user_tenants, _ = await self.couch_sitter_service.get_user_tenants(user_id)
            tenant_ids = [t.get("_id") for t in user_tenants if t]
        except Exception as e:
            logger.error(f"Failed to get user tenants: {e}")
            raise TenantAccessError("Cannot verify tenant access")
        
        if not tenant_ids:
            raise TenantAccessError(
                "User has no authorized tenants. Create one first via /api/tenants"
            )
        
        # Special handling for band-info documents
        doc_id = doc.get("_id", "")
        doc_type = doc.get("type", "")
        
        if doc_type == "band-info":
            # band-info_{tenantId} documents derive tenant from _id
            if doc_id.startswith("band-info_"):
                tenant_id = doc_id.split("_", 1)[1]
                if tenant_id not in tenant_ids:
                    raise TenantAccessError(
                        f"Cannot create band-info for tenant '{tenant_id}'. "
                        f"You have access to: {tenant_ids}"
                    )
                # band-info is OK - update doc to include tenant field
                doc["tenant"] = tenant_id
                return
            else:
                raise TenantAccessError(
                    "band-info document must follow naming convention: band-info_{tenantId}"
                )
        
        # All other documents must have explicit tenant field
        tenant_id = doc.get("tenant")
        
        if not tenant_id:
            raise TenantAccessError(
                f"Document missing required 'tenant' field. "
                f"Document must belong to one of your tenants: {tenant_ids}"
            )
        
        # Verify tenant ownership
        if tenant_id not in tenant_ids:
            raise TenantAccessError(
                f"Cannot write to tenant '{tenant_id}'. "
                f"You have access to: {tenant_ids}"
            )
        
        logger.info(
            f"✅ Tenant validation passed: user={user_id}, tenant={tenant_id}, db={database}"
        )
    
    async def validate_bulk_docs(
        self,
        docs: List[Dict[str, Any]],
        user_id: str,
        database: str
    ) -> None:
        """
        Validate all documents in a bulk write operation.
        
        All docs must pass validation or entire operation is rejected.
        """
        for i, doc in enumerate(docs):
            try:
                # Skip deleted documents
                if doc.get("_deleted"):
                    continue
                
                await self.validate_write(doc, user_id, database)
            except TenantAccessError as e:
                raise TenantAccessError(
                    f"Document {i} failed validation: {str(e)}"
                )
    
    @staticmethod
    def is_app_database(database: str) -> bool:
        """Check if database is an app database (not couch-sitter)"""
        system_dbs = {
            'couch-sitter',
            '_users',
            '_replicator',
            '_global_changes'
        }
        return database not in system_dbs
