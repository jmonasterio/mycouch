"""
Virtual Tables Module

Provides HTTP endpoints for __users and __tenants collections.
Maps virtual IDs to internal CouchDB document IDs with access control enforcement.

Approach: Thin wrapper over existing documents; no refactoring.
- __users/<id> → user_<id>
- __tenants/<id> → tenant_<id>
"""

import json
import logging
from typing import Optional, Dict, Any, List, Tuple
from fastapi import HTTPException, Request
from datetime import datetime
import uuid
import hashlib

logger = logging.getLogger(__name__)


# Session service will be injected by main.py
_session_service = None


def set_session_service(session_service):
    """Set the session service for use in virtual table handler."""
    global _session_service
    _session_service = session_service


class VirtualTableMapper:
    """Maps virtual IDs to internal CouchDB document IDs"""

    @staticmethod
    def _hash_sub(sub: str) -> str:
        """Hash a sub claim to create the internal user ID"""
        return hashlib.sha256(sub.encode('utf-8')).hexdigest()

    @staticmethod
    def user_virtual_to_internal(virtual_id: str) -> str:
        """Map virtual user ID to internal document ID.
        Frontend has already hashed the Clerk sub, we just add the prefix.
        Example: a3f7c2d9e1b4... -> user_a3f7c2d9e1b4..."""
        return f"user_{virtual_id}"

    @staticmethod
    def user_internal_to_virtual(internal_id: str) -> str:
        """Map internal user document ID to virtual ID.
        Returns the hash portion after removing user_ prefix.
        The hash is unique enough to serve as a virtual ID."""
        if internal_id.startswith("user_"):
            return internal_id[5:]  # Remove "user_" prefix, keep the hash
        return internal_id

    @staticmethod
    def tenant_virtual_to_internal(virtual_id: str) -> str:
        """Map virtual tenant ID to internal document ID"""
        return f"tenant_{virtual_id}"

    @staticmethod
    def tenant_internal_to_virtual(internal_id: str) -> str:
        """Map internal tenant document ID to virtual ID"""
        if internal_id.startswith("tenant_"):
            return internal_id[7:]  # Remove "tenant_" prefix
        return internal_id


class VirtualTableAccessControl:
    """Enforce access control rules for virtual tables.
    
    UPGRADE NOTE (Architecture Pattern):
    All tenant-related methods (can_read_tenant, can_update_tenant, can_delete_tenant) require
    user_id in INTERNAL format: user_<64-char-sha256-hash>.
    This is intentional - normalization happens at the CALLER (HTTP endpoint layer in main.py),
    not in the library method. This keeps the library focused on data access control.
    
    If calling from tests or new code:
    1. Hash the Clerk sub: user_hash = sha256(clerk_sub)
    2. Add prefix: internal_id = f"user_{user_hash}"
    3. Pass to method: can_read_tenant(internal_id, tenant_doc)
    
    Never add normalization logic back to these methods - it violates single responsibility.
    """

    @staticmethod
    def _hash_user_id(sub: str) -> str:
        """Hash a Clerk sub to get the virtual user ID (hashed format)"""
        return VirtualTableMapper._hash_sub(sub)

    @staticmethod
    def can_read_user(user_id: str, target_user_id: str) -> bool:
        """User can only read their own doc"""
        # user_id is Clerk sub (e.g., user_34tzJwWB3jaQT6ZKPqZIQoJwsmz)
        # target_user_id is internal format from URL (e.g., user_a3f7c2d...)
        user_hash = VirtualTableAccessControl._hash_user_id(user_id)
        # Extract virtual ID from internal format (strip user_ prefix if present)
        target_virtual_id = target_user_id[5:] if target_user_id.startswith('user_') else target_user_id
        return user_hash == target_virtual_id

    @staticmethod
    def can_update_user(user_id: str, target_user_id: str, field: str) -> bool:
        """User can update allowed fields in their own doc"""
        # user_id is Clerk sub (e.g., user_34tzJwWB3jaQT6ZKPqZIQoJwsmz)
        # target_user_id is internal format from URL (e.g., user_a3f7c2d...)
        user_hash = VirtualTableAccessControl._hash_user_id(user_id)
        # Extract virtual ID from internal format (strip user_ prefix if present)
        target_virtual_id = target_user_id[5:] if target_user_id.startswith('user_') else target_user_id
        if user_hash != target_virtual_id:
            return False
        
        allowed_fields = {"name", "email", "active_tenant_id"}
        return field in allowed_fields

    @staticmethod
    def can_delete_user(user_id: str, target_user_id: str) -> bool:
        """User cannot delete themselves"""
        # user_id is Clerk sub (e.g., user_34tzJwWB3jaQT6ZKPqZIQoJwsmz)
        # target_user_id is internal format from URL (e.g., user_a3f7c2d...)
        user_hash = VirtualTableAccessControl._hash_user_id(user_id)
        # Extract virtual ID from internal format (strip user_ prefix if present)
        target_virtual_id = target_user_id[5:] if target_user_id.startswith('user_') else target_user_id
        # Return False if trying to delete self, True otherwise
        return user_hash != target_virtual_id

    @staticmethod
    def can_read_tenant(user_id: str, tenant_doc: Dict[str, Any]) -> bool:
        """User can read if they're in tenant.userIds.
        CALLER RESPONSIBILITY: user_id MUST be in internal format (user_<64-char-sha256-hash>).
        Caller must normalize Clerk subs before calling this method.
        """
        if not tenant_doc:
            return False
        user_ids = tenant_doc.get("userIds", [])
        return user_id in user_ids

    @staticmethod
    def can_update_tenant(user_id: str, tenant_doc: Dict[str, Any], field: str) -> bool:
        """Only owner can update; allowed fields: name, metadata"""
        if not tenant_doc:
            logger.warning(f"[CAN_UPDATE_TENANT] tenant_doc is None/falsy")
            return False
        
        # Only owner can update
        # Normalize both values to handle whitespace/encoding issues
        tenant_userId = (tenant_doc.get("userId") or "").strip()
        normalized_user_id = (user_id or "").strip()
        is_owner = tenant_userId == normalized_user_id
        
        logger.info(f"[CAN_UPDATE_TENANT] user_id='{normalized_user_id}', tenant_userId='{tenant_userId}', is_owner={is_owner}")
        
        if not is_owner:
            logger.warning(f"[CAN_UPDATE_TENANT] User is not owner of tenant ('{normalized_user_id}' != '{tenant_userId}')")
            return False
        
        # Allowed fields for update
        allowed_fields = {"name", "metadata"}
        return field in allowed_fields

    @staticmethod
    def can_delete_tenant(user_id: str, tenant_doc: Dict[str, Any]) -> bool:
        """Only owner can delete"""
        if not tenant_doc:
            return False
        # Normalize both values to handle whitespace/encoding issues
        tenant_userId = (tenant_doc.get("userId") or "").strip()
        normalized_user_id = (user_id or "").strip()
        return tenant_userId == normalized_user_id


class VirtualTableValidator:
    """Validate document changes"""

    IMMUTABLE_USER_FIELDS = {"sub", "type", "_id", "tenants", "tenantIds"}
    IMMUTABLE_TENANT_FIELDS = {"_id", "type", "userId", "userIds", "applicationId"}

    @staticmethod
    def validate_user_update(old_doc: Dict[str, Any], new_doc: Dict[str, Any]) -> List[str]:
        """
        Validate user document update.
        Returns list of error messages; empty if valid.
        """
        errors = []
        
        for field, new_value in new_doc.items():
            if field in VirtualTableValidator.IMMUTABLE_USER_FIELDS:
                old_value = old_doc.get(field)
                if old_value != new_value:
                    errors.append(f"immutable_field: {field}")
        
        return errors

    @staticmethod
    def validate_tenant_update(old_doc: Dict[str, Any], new_doc: Dict[str, Any]) -> List[str]:
        """
        Validate tenant document update.
        Returns list of error messages; empty if valid.
        """
        errors = []
        
        for field, new_value in new_doc.items():
            if field in VirtualTableValidator.IMMUTABLE_TENANT_FIELDS:
                old_value = old_doc.get(field)
                if old_value != new_value:
                    errors.append(f"immutable_field: {field}")
        
        return errors


class VirtualTableChangesFilter:
    """Filter _changes responses by access control"""

    @staticmethod
    async def filter_user_changes(
        changes: Dict[str, Any],
        requesting_user_id: str
    ) -> Dict[str, Any]:
        """
        Filter _changes for __users endpoint.
        Only return the requesting user's own doc.
        """
        filtered_results = []
        
        for change in changes.get("results", []):
            change_id = change.get("id", "")
            
            # Check if this is the user's own doc
            expected_id = f"user_{requesting_user_id}"
            if change_id == expected_id:
                # Include in results
                if "doc" in change:
                    # Filter out soft-deleted
                    if not change["doc"].get("deleted"):
                        filtered_results.append(change)
                else:
                    # Change without doc (deleted); still include if it's the user's doc
                    filtered_results.append(change)
        
        changes["results"] = filtered_results
        return changes

    @staticmethod
    async def filter_tenant_changes(
        changes: Dict[str, Any],
        requesting_user_id: str,
        dal
    ) -> Dict[str, Any]:
        """
        Filter _changes for __tenants endpoint.
        Only return tenants user is member of.
        """
        filtered_results = []
        
        for change in changes.get("results", []):
            change_id = change.get("id", "")
            
            if "doc" in change:
                doc = change["doc"]
                # Filter out soft-deleted
                if doc.get("deleted"):
                    continue
                
                # Check if user is member
                user_ids = doc.get("userIds", [])
                if requesting_user_id in user_ids:
                    filtered_results.append(change)
            else:
                # Change without doc (deleted); check doc_id pattern
                # For now, skip deleted changes to avoid exposing ids
                pass
        
        changes["results"] = filtered_results
        return changes


class VirtualTableHandler:
    """Handle virtual table HTTP operations"""

    def __init__(self, dal, clerk_service=None, applications=None, session_service=None):
        """Initialize with DAL (data access layer), Clerk service, application config, and session service"""
        self.dal = dal
        self.clerk_service = clerk_service
        self.applications = applications or {}  # App configs from couch-sitter
        self.session_service = session_service  # Session service for per-device tenant mapping

    async def get_user(self, user_id: str, requesting_user_id: str) -> Dict[str, Any]:
        """
        GET /__users/<id>
        Returns user document; user can only read their own doc.
        """
        # Access control
        if not VirtualTableAccessControl.can_read_user(requesting_user_id, user_id):
            raise HTTPException(status_code=403, detail="Cannot read other users' documents")
        
        # Map virtual to internal ID
        internal_id = VirtualTableMapper.user_virtual_to_internal(user_id)
        
        # Fetch from CouchDB
        try:
            doc = await self.dal.get_document("couch-sitter", internal_id)
        except HTTPException as e:
            if e.status_code == 404:
                raise HTTPException(status_code=404, detail="User not found")
            raise
        
        # Filter out soft-deleted docs
        if doc.get("deleted"):
            raise HTTPException(status_code=404, detail="User not found")
        
        return doc

    async def _track_session_tenant_switch(
        self,
        sid: Optional[str],
        user_id_hash: str,
        active_tenant_id: str,
        app_id: Optional[str] = None
    ) -> None:
        """
        Track a tenant switch in the session document.
        Called when user updates their active_tenant_id.
        
        Args:
            sid: Session ID from JWT (optional)
            user_id_hash: Hashed user ID
            active_tenant_id: The new active tenant ID
            app_id: Clerk issuer/app identifier (optional)
        """
        if not sid or not self.session_service:
            logger.debug(f"[VIRTUAL] Skipping session tracking: sid={sid}, session_service={bool(self.session_service)}")
            return
        
        try:
            await self.session_service.create_session(
                sid=sid,
                user_id=user_id_hash,
                active_tenant_id=active_tenant_id,
                app_id=app_id
            )
            logger.info(f"[VIRTUAL] ✓ Tracked tenant switch in session: {sid} → {active_tenant_id}")
        except Exception as e:
            logger.warning(f"[VIRTUAL] Failed to track session tenant switch: {e}")
            # Don't fail the user update if session tracking fails

    async def update_user(
        self,
        user_id: str,
        requesting_user_id: str,
        updates: Dict[str, Any],
        issuer: Optional[str] = None,
        sid: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        PUT /__users/<id>
        Update user document; allowed fields only; user can only update self.
        
        Args:
            user_id: Virtual user ID
            requesting_user_id: JWT 'sub' claim
            updates: Fields to update
            issuer: JWT 'iss' claim; used to find correct Clerk secret key
        """
        # Access control
        if not VirtualTableAccessControl.can_read_user(requesting_user_id, user_id):
            raise HTTPException(status_code=403, detail="Cannot update other users' documents")
        
        # Map virtual to internal ID
        internal_id = VirtualTableMapper.user_virtual_to_internal(user_id)
        
        # Fetch current doc (or create new one if doesn't exist)
        try:
            current_doc = await self.dal.get_document("couch-sitter", internal_id)
        except HTTPException as e:
            if e.status_code == 404:
                # First update - create new user document
                current_doc = {
                    "_id": internal_id,
                    "type": "user",
                    "sub": requesting_user_id,
                    "createdAt": datetime.utcnow().isoformat()
                }
                logger.info(f"Creating new user document: {internal_id}")
            else:
                raise
        
        # Validate immutable fields
        errors = VirtualTableValidator.validate_user_update(current_doc, updates)
        if errors:
            for error in errors:
                field = error.split(": ")[1] if ": " in error else error
                raise HTTPException(
                    status_code=400,
                    detail=f"immutable_field: {field}"
                )
        
        # Validate allowed fields for update
        for field in updates:
            if field.startswith("_"):
                continue  # Allow CouchDB metadata fields
            if not VirtualTableAccessControl.can_update_user(requesting_user_id, user_id, field):
                raise HTTPException(
                    status_code=400,
                    detail=f"field_not_allowed: {field}"
                )
        
        # Perform update with retry on conflict
        max_retries = 3
        for attempt in range(max_retries):
            # Fetch current doc (in case it changed)
            try:
                current_doc = await self.dal.get_document("couch-sitter", internal_id)
            except HTTPException as e:
                if e.status_code == 404:
                    # Document may have been deleted, create new one
                    current_doc = {
                        "_id": internal_id,
                        "type": "user",
                        "sub": requesting_user_id,
                        "createdAt": datetime.utcnow().isoformat()
                    }
                    logger.info(f"Creating new user document in retry: {internal_id}")
                else:
                    raise
            
            # Merge updates with current doc to preserve _rev and other fields
            merged_doc = {**current_doc}
            for key, value in updates.items():
                if key not in {"_id", "_rev", "type", "sub"}:  # Don't override system fields
                    merged_doc[key] = value
            
            # Attempt update
            try:
                put_result = await self.dal.put_document("couch-sitter", internal_id, merged_doc)
                # Add the _rev from put result to our merged_doc and return it
                merged_doc["_rev"] = put_result.get("_rev")
                
                # If active_tenant_id was updated, track in session document
                if "active_tenant_id" in updates:
                    await self._track_session_tenant_switch(
                        sid=sid,
                        user_id_hash=user_id,  # This is the hashed user ID from virtual URL
                        active_tenant_id=updates["active_tenant_id"],
                        app_id=issuer
                    )
                
                return merged_doc
            except HTTPException as e:
                if "conflict" in str(e.detail).lower():
                    if attempt < max_retries - 1:
                        logger.info(f"Revision conflict on attempt {attempt + 1}, retrying...")
                        continue
                    else:
                        raise HTTPException(status_code=409, detail="Revision conflict after retries")
                raise

    async def delete_user(self, user_id: str, requesting_user_id: str) -> Dict[str, Any]:
        """
        DELETE /__users/<id>
        Soft-delete user document; cannot delete self.
        """
        # Access control: cannot delete self
        if not VirtualTableAccessControl.can_delete_user(requesting_user_id, user_id):
            raise HTTPException(status_code=403, detail="Users cannot delete themselves")
        
        # Map virtual to internal ID
        internal_id = VirtualTableMapper.user_virtual_to_internal(user_id)
        
        # Fetch current doc
        try:
            current_doc = await self.dal.get_document("couch-sitter", internal_id)
        except HTTPException as e:
            if e.status_code == 404:
                raise HTTPException(status_code=404, detail="User not found")
            raise
        
        # Soft-delete
        current_doc["deleted"] = True
        current_doc["updatedAt"] = datetime.utcnow().isoformat() + "Z"
        
        try:
            put_result = await self.dal.put_document("couch-sitter", internal_id, current_doc)
        except HTTPException as e:
            if "conflict" in str(e.detail).lower():
                raise HTTPException(status_code=409, detail="Revision conflict")
            raise
        
        # Return response with ok=true and rev info
        return {"ok": True, "_id": put_result.get("id"), "_rev": put_result.get("_rev")}

    async def get_tenant(self, tenant_id: str, requesting_user_id: str) -> Dict[str, Any]:
        """
        GET /__tenants/<id>
        Returns tenant document; user must be member.
        Converts internal ID to virtual format in response.
        """
        # Map virtual to internal ID
        internal_id = VirtualTableMapper.tenant_virtual_to_internal(tenant_id)
        
        # Fetch from CouchDB
        try:
            doc = await self.dal.get_document("couch-sitter", internal_id)
        except HTTPException as e:
            if e.status_code == 404:
                raise HTTPException(status_code=404, detail="Tenant not found")
            raise
        
        # Filter out soft-deleted docs (check both deletedAt for new format and deleted for legacy)
        if doc.get("deletedAt") or doc.get("deleted"):
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Access control: user must be member
        if not VirtualTableAccessControl.can_read_tenant(requesting_user_id, doc):
            raise HTTPException(status_code=403, detail="You are not a member of this tenant")
        
        # Convert internal _id to virtual format for response
        if doc.get("_id", "").startswith("tenant_"):
            doc["_id"] = VirtualTableMapper.tenant_internal_to_virtual(doc["_id"])
        
        return doc

    async def list_tenants(self, user_id: str) -> List[Dict[str, Any]]:
        """
        GET /__tenants
        Returns all tenants user is member of. Converts internal IDs to virtual format for API response.
        
        CALLER RESPONSIBILITY: user_id MUST be in internal format (user_<64-char-sha256-hash>).
        Normalization from Clerk sub happens at the HTTP endpoint layer (main.py).
        See VirtualTableAccessControl class docstring for upgrade notes.
        """
        # Query all tenant docs for this user (exclude soft-deleted documents)
        # Filter out docs where either deletedAt or deleted fields are set (for both new and legacy formats)
        query = {
            "selector": {
                "type": "tenant",
                "userIds": {"$elemMatch": {"$eq": user_id}},
                "$and": [
                    {"deletedAt": {"$exists": False}},
                    {"deleted": {"$ne": True}}
                ]
            }
        }
        
        try:
            result = await self.dal.query_documents("couch-sitter", query)
        except Exception as e:
            logger.error(f"Error querying tenants: {e}")
            raise HTTPException(status_code=500, detail="Error querying tenants")
        
        docs = result.get("docs", [])
        
        # Filter out soft-deleted (in-memory fallback filter) and convert _id to virtual format
        docs = [doc for doc in docs if not doc.get("deletedAt") and not doc.get("deleted")]
        for doc in docs:
            if doc.get("_id", "").startswith("tenant_"):
                doc["_id"] = VirtualTableMapper.tenant_internal_to_virtual(doc["_id"])
            
            # Populate members array from userIds
            try:
                user_ids = doc.get("userIds", [])
                members = []
                tenant_id_internal = doc.get("_id", "")
                logger.info(f"[MEMBERS] Populating members for tenant {tenant_id_internal}: userIds={user_ids}")
                
                for uid in user_ids:
                    try:
                        user_response = await self.dal.get(f"couch-sitter/{uid}", "GET", None)
                        if user_response and isinstance(user_response, dict) and "error" not in user_response:
                            # Get role from user's tenants array
                            role = "member"
                            user_tenants = user_response.get("tenants", [])
                            for ut in user_tenants:
                                if ut.get("tenantId") == tenant_id_internal:
                                    role = ut.get("role", "member")
                                    break
                            
                            members.append({
                                "userId": uid,
                                "name": user_response.get("name", "Unknown"),
                                "email": user_response.get("email", ""),
                                "role": role
                            })
                    except Exception as e:
                        logger.info(f"[MEMBERS] Could not load user {uid} for tenant members: {e}")
                        members.append({
                            "userId": uid,
                            "name": "Unknown",
                            "email": "",
                            "role": "member"
                        })
                doc["members"] = members
                logger.info(f"[MEMBERS] Added {len(members)} members to tenant {tenant_id_internal}")
            except Exception as e:
                logger.error(f"[MEMBERS] Error populating members for tenant {doc.get('_id')}: {e}", exc_info=True)
                doc["members"] = []
        
        return docs

    async def create_tenant(
        self,
        requesting_user_id: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        POST /__tenants
        Create new tenant; user becomes owner.
        Returns virtual ID (without "tenant_" prefix) for use in subsequent requests.
        
        CALLER RESPONSIBILITY: requesting_user_id MUST be in internal format (user_<64-char-sha256-hash>).
        Normalization from Clerk sub happens at the HTTP endpoint layer (main.py).
        See VirtualTableAccessControl class docstring for upgrade notes.
        """
        # Generate tenant ID
        tenant_id = str(uuid.uuid4())
        internal_id = VirtualTableMapper.tenant_virtual_to_internal(tenant_id)
        
        # Create tenant doc
        now = datetime.utcnow().isoformat() + "Z"
        logger.info(f"[VIRTUAL] Creating tenant with owner: {requesting_user_id}")
        
        tenant_doc = {
            "_id": internal_id,
            "type": "tenant",
            "name": data.get("name", "Untitled Tenant"),
            "userId": requesting_user_id,
            "userIds": [requesting_user_id],
            "applicationId": data.get("applicationId", "roady"),
            "metadata": data.get("metadata", {}),
            "createdAt": now,
            "updatedAt": now
        }
        
        # Save to CouchDB
        try:
            put_result = await self.dal.put_document("couch-sitter", internal_id, tenant_doc)
            # Add the _rev from put result and convert _id to virtual format for response
            tenant_doc["_rev"] = put_result.get("_rev")
            # Return with virtual ID (without "tenant_" prefix)
            tenant_doc["_id"] = tenant_id
        except Exception as e:
            logger.error(f"Error creating tenant: {e}")
            raise HTTPException(status_code=500, detail="Error creating tenant")
        
        return tenant_doc

    async def update_tenant(
        self,
        tenant_id: str,
        requesting_user_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        PUT /__tenants/<id>
        Update tenant document; only owner can update; allowed fields only.
        """
        # Validate requesting_user_id
        if not requesting_user_id:
            logger.error(f"[VIRTUAL] update_tenant called with empty requesting_user_id")
            raise HTTPException(status_code=400, detail="Missing user authentication")
        
        # Map virtual to internal ID
        internal_id = VirtualTableMapper.tenant_virtual_to_internal(tenant_id)
        
        # Fetch current doc
        try:
            current_doc = await self.dal.get_document("couch-sitter", internal_id)
        except HTTPException as e:
            if e.status_code == 404:
                raise HTTPException(status_code=404, detail="Tenant not found")
            raise
        
        # Access control: only owner
        tenant_owner = current_doc.get('userId')
        logger.info(f"[VIRTUAL] Update tenant access check: tenant_id={tenant_id}, requesting_user_id='{requesting_user_id}', tenant_userId='{tenant_owner}'")
        
        if not VirtualTableAccessControl.can_update_tenant(requesting_user_id, current_doc, "_"):
            logger.error(f"[VIRTUAL] ✗ Update tenant REJECTED: '{requesting_user_id}' is not owner '{tenant_owner}'")
            raise HTTPException(status_code=403, detail="Only owner can update this tenant")
        
        # Validate immutable fields
        errors = VirtualTableValidator.validate_tenant_update(current_doc, updates)
        if errors:
            for error in errors:
                field = error.split(": ")[1] if ": " in error else error
                raise HTTPException(
                    status_code=400,
                    detail=f"immutable_field: {field}"
                )
        
        # Validate allowed fields for update
        for field in updates:
            if field.startswith("_"):
                continue  # Allow CouchDB metadata fields
            if not VirtualTableAccessControl.can_update_tenant(requesting_user_id, current_doc, field):
                raise HTTPException(
                    status_code=400,
                    detail=f"field_not_allowed: {field}"
                )
        
        # Perform update with retry on conflict
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Merge updates with current doc
                merged_doc = {**current_doc}
                for key, value in updates.items():
                    if key not in {"_id", "_rev", "type", "userId", "userIds"}:
                        merged_doc[key] = value
                
                # Attempt update
                put_result = await self.dal.put_document("couch-sitter", internal_id, merged_doc)
                # Convert _id to virtual format for response
                merged_doc["_rev"] = put_result.get("_rev")
                merged_doc["_id"] = tenant_id
                return merged_doc
            except HTTPException as e:
                if "conflict" in str(e.detail).lower():
                    if attempt < max_retries - 1:
                        logger.info(f"Revision conflict on attempt {attempt + 1}, retrying...")
                        # Fetch fresh copy
                        current_doc = await self.dal.get_document("couch-sitter", internal_id)
                        continue
                    else:
                        raise HTTPException(status_code=409, detail="Revision conflict after retries")
                raise

    async def delete_tenant(
        self,
        tenant_id: str,
        requesting_user_id: str,
        user_active_tenant_id: str
    ) -> Dict[str, Any]:
        """
        DELETE /__tenants/<id>
        Soft-delete tenant in couch-sitter AND cascade-delete the tenant's database (e.g., roady).
        Only owner can delete; cannot delete active tenant.
        """
        # Map virtual to internal ID
        internal_id = VirtualTableMapper.tenant_virtual_to_internal(tenant_id)
        
        # Fetch current doc
        try:
            current_doc = await self.dal.get_document("couch-sitter", internal_id)
        except HTTPException as e:
            if e.status_code == 404:
                raise HTTPException(status_code=404, detail="Tenant not found")
            raise
        
        # Access control: only owner
        if not VirtualTableAccessControl.can_delete_tenant(requesting_user_id, current_doc):
            raise HTTPException(status_code=403, detail="Only owner can delete this tenant")
        
        # Check if active tenant
        if user_active_tenant_id == internal_id or user_active_tenant_id == tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Cannot delete active tenant. Switch to another tenant first."
            )
        
        # Get the database name from the tenant's applicationId
        # This tells us which database to delete (e.g., "roady")
        db_name = current_doc.get("applicationId", "").strip()
        
        warnings = []
        tenant_deleted = False
        db_deleted = False
        put_result = None
        
        # STEP 1: Soft-delete tenant in couch-sitter
        # Use deletedAt field to match client-side soft-delete field and enable sync consistency
        current_doc["deletedAt"] = datetime.utcnow().isoformat() + "Z"
        current_doc["updatedAt"] = datetime.utcnow().isoformat() + "Z"
        
        try:
            put_result = await self.dal.put_document("couch-sitter", internal_id, current_doc)
            tenant_deleted = True
            logger.info(f"[VIRTUAL] ✓ Soft-deleted tenant in couch-sitter: {tenant_id}")
        except HTTPException as e:
            tenant_error = "Revision conflict" if "conflict" in str(e.detail).lower() else str(e.detail)
            logger.error(f"[VIRTUAL] ✗ Failed to delete tenant doc: {tenant_error}")
            warnings.append(f"Failed to delete tenant document: {tenant_error}")
        except Exception as e:
            tenant_error = str(e)
            logger.error(f"[VIRTUAL] ✗ Failed to delete tenant doc: {tenant_error}")
            warnings.append(f"Failed to delete tenant document: {tenant_error}")
        
        # STEP 2: Cascade-delete the tenant's database (e.g., DELETE /roady)
        # This removes all equipment, gigs, and other data for this band
        if db_name and db_name != "couch-sitter":
            try:
                logger.info(f"[VIRTUAL] Cascade-deleting database: {db_name} for tenant: {tenant_id}")
                await self.dal.delete_database(db_name)
                db_deleted = True
                logger.info(f"[VIRTUAL] ✓ Successfully deleted database: {db_name}")
            except Exception as e:
                db_error = str(e)
                logger.error(f"[VIRTUAL] ✗ Failed to delete database {db_name}: {db_error}")
                warnings.append(f"Failed to delete database '{db_name}': {db_error}")
        elif db_name == "couch-sitter":
            logger.warning(f"[VIRTUAL] Skipping database deletion for couch-sitter (system database)")
        else:
            logger.warning(f"[VIRTUAL] No applicationId found for tenant {tenant_id}")
        
        # BOTH STEPS MUST SUCCEED - fail if both failed or if tenant deletion failed
        if not tenant_deleted:
            raise HTTPException(
                status_code=500,
                detail=warnings[0] if warnings else "Failed to delete tenant"
            )
        
        response = {
            "ok": True,
            "_id": put_result.get("id") if put_result else tenant_id,
            "_rev": put_result.get("_rev") if put_result else None
        }
        
        # Add warnings if database deletion failed
        if warnings:
            response["warnings"] = warnings
            logger.warning(f"[VIRTUAL] Tenant deleted with warnings: {warnings}")
        
        return response

    async def get_user_changes(
        self,
        requesting_user_id: str,
        since: str = "0",
        limit: Optional[int] = None,
        include_docs: bool = False
    ) -> Dict[str, Any]:
        """
        GET /__users/_changes
        Return change feed filtered to requesting user's own doc.
        Virtual table handler: queries couch-sitter internally, no database permission needed.
        """
        try:
            # requesting_user_id is Clerk sub (e.g., user_34tzJwWB3jaQT6ZKPqZIQoJwsmz)
            # Hash it to get virtual ID, then add prefix for internal ID
            user_hash = VirtualTableAccessControl._hash_user_id(requesting_user_id)
            internal_id = VirtualTableMapper.user_virtual_to_internal(user_hash)
            doc = await self.dal.get_document("couch-sitter", internal_id)
            
            # Filter out soft-deleted docs
            if doc.get("deleted"):
                return {
                    "results": [],
                    "last_seq": since or "0",
                    "pending": 0
                }
            
            # Convert to _changes format
            # Simple seq based on presence: if since=0 or no since, include the doc
            results = []
            if since == "0" or not since:
                results.append({
                    "seq": "1-abc",
                    "id": doc.get("_id"),
                    "changes": [{"rev": doc.get("_rev")}],
                    "doc": doc if include_docs else None
                })
            
            return {
                "results": results,
                "last_seq": "1-abc" if results else since or "0",
                "pending": 0
            }
            
        except HTTPException as e:
            if e.status_code == 404:
                # User doc doesn't exist yet - return empty changes
                return {
                    "results": [],
                    "last_seq": since or "0",
                    "pending": 0
                }
            raise
        except Exception as e:
            logger.error(f"Error querying user changes: {e}")
            raise HTTPException(status_code=500, detail="Error querying changes")

    async def get_tenant_changes(
        self,
        requesting_user_id: str,
        since: str = "0",
        limit: Optional[int] = None,
        include_docs: bool = False
    ) -> Dict[str, Any]:
        """
        GET /__tenants/_changes
        Return change feed filtered to tenants user is member of.
        Virtual table handler: queries couch-sitter internally, no database permission needed.
        """
        try:
            # Query couch-sitter for tenants this user is member of (exclude soft-deleted)
            # Filter out docs where either deletedAt (new format) or deleted (legacy) fields are set
            result = await self.dal.query_documents("couch-sitter", {
                "selector": {
                    "type": "tenant",
                    "userIds": {"$elemMatch": {"$eq": requesting_user_id}},
                    "$and": [
                        {"deletedAt": {"$exists": False}},
                        {"deleted": {"$ne": True}}
                    ]
                }
            })
        except Exception as e:
            logger.error(f"Error querying tenant changes: {e}")
            raise HTTPException(status_code=500, detail="Error querying changes")
        
        # Convert to _changes format
        docs = result.get("docs", [])
        results = []
        
        # Simple seq-based filtering: include all docs if since=0, otherwise check seq
        since_num = int(since) if since and since != "0" else 0
        
        for i, doc in enumerate(docs):
            seq_num = i + 1
            # Include doc if seq > since
            if seq_num > since_num:
                results.append({
                    "seq": f"{seq_num}-abc",
                    "id": doc.get("_id"),
                    "changes": [{"rev": doc.get("_rev")}],
                    "doc": doc if include_docs else None
                })
        
        return {
            "results": results,
            "last_seq": f"{len(docs)}-abc" if docs else since or "0-abc",
            "pending": 0
        }

    async def bulk_docs_users(
        self,
        requesting_user_id: str,
        docs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        POST /__users/_bulk_docs
        Bulk operations on user docs; validate each.
        """
        results = []
        
        for doc in docs:
            doc_id = doc.get("_id")
            
            # Extract virtual ID from doc_id if it has "user_" prefix
            if doc_id and doc_id.startswith("user_"):
                virtual_id = VirtualTableMapper.user_internal_to_virtual(doc_id)
            else:
                virtual_id = doc_id
            
            try:
                if doc.get("_deleted"):
                    # Delete operation
                    result = await self.delete_user(virtual_id, requesting_user_id)
                else:
                    # Update operation
                    result = await self.update_user(virtual_id, requesting_user_id, doc)
                
                results.append({
                    "ok": True,
                    "_id": result.get("_id"),
                    "_rev": result.get("_rev")
                })
            except HTTPException as e:
                results.append({
                    "error": e.detail,
                    "_id": doc_id or virtual_id
                })
            except Exception as e:
                results.append({
                    "error": str(e),
                    "_id": doc_id or virtual_id
                })
        
        return results

    async def bulk_docs_tenants(
        self,
        requesting_user_id: str,
        user_active_tenant_id: str,
        docs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        POST /__tenants/_bulk_docs
        Bulk operations on tenant docs; validate each.
        """
        results = []
        
        for doc in docs:
            doc_id = doc.get("_id")
            
            # Extract virtual ID from doc_id if it has "tenant_" prefix
            if doc_id and doc_id.startswith("tenant_"):
                virtual_id = VirtualTableMapper.tenant_internal_to_virtual(doc_id)
            else:
                virtual_id = doc_id
            
            try:
                if doc.get("_deleted"):
                    # Delete operation
                    result = await self.delete_tenant(virtual_id, requesting_user_id, user_active_tenant_id)
                else:
                    # Update operation
                    result = await self.update_tenant(virtual_id, requesting_user_id, doc)
                
                results.append({
                    "ok": True,
                    "_id": result.get("_id"),
                    "_rev": result.get("_rev")
                })
            except HTTPException as e:
                results.append({
                    "error": e.detail,
                    "_id": doc_id or virtual_id
                })
            except Exception as e:
                results.append({
                    "error": str(e),
                    "_id": doc_id or virtual_id
                })
        
        return results
