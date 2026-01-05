"""
Bootstrap Module

Handles first-login scenario where user doesn't have an active_tenant_id in JWT.
Creates user and personal tenant on first access; triggers JWT refresh.
"""

import logging
import hashlib
from typing import Optional, Dict, Any
from fastapi import HTTPException
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)


class BootstrapManager:
    """Manage bootstrap flow for new users"""

    def __init__(self, dal):
        """Initialize with DAL (data access layer)"""
        self.dal = dal

    @staticmethod
    def _hash_sub(sub: str) -> str:
        """
        Hash the Clerk sub to create a consistent user ID.

        This matches the hashing done in:
        - virtual_tables.py VirtualTableMapper._hash_sub()
        - tenant-manager.js hashUserId()

        The hash ensures consistent IDs across frontend and backend.
        """
        return hashlib.sha256(sub.encode('utf-8')).hexdigest()

    async def check_active_tenant_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """
        Check if JWT has active_tenant_id claim.
        Returns active_tenant_id if present, None otherwise.
        """
        active_tenant_id = payload.get("active_tenant_id")
        return active_tenant_id

    async def get_user_active_tenant(self, user_id: str) -> Optional[str]:
        """
        Fetch user doc and return their active_tenant_id.
        Returns None if user doesn't exist or has no active tenant.
        """
        try:
            user_doc = await self.dal.get_document("couch-sitter", user_id)
            return user_doc.get("active_tenant_id")
        except HTTPException as e:
            if e.status_code == 404:
                return None
            raise
        except Exception:
            return None

    async def bootstrap_user(self, sub: str, email: str, name: str) -> Dict[str, Any]:
        """
        Bootstrap a new user:
        1. Create user document
        2. Create personal tenant
        3. Link them together
        4. Return active_tenant_id to set in JWT

        Returns dict with:
        - active_tenant_id: tenant ID to set in JWT
        - user_doc: created user document
        - tenant_doc: created personal tenant
        """
        # Normalize sub to remove user_ prefix if present (Clerk may include it)
        sub_normalized = sub[5:] if sub.startswith("user_") else sub
        # Hash the sub to create consistent user ID that matches frontend hashing
        sub_hash = self._hash_sub(sub_normalized)
        user_id = f"user_{sub_hash}"
        logger.info(f"Bootstrap: sub={sub_normalized[:20]}... -> hash={sub_hash[:16]}... -> user_id={user_id[:30]}...")
        
        # Check if user already exists
        user_doc = None
        try:
            user_doc = await self.dal.get_document("couch-sitter", user_id)
            if user_doc and not user_doc.get("deleted"):
                # User exists; use their active_tenant_id
                logger.info(f"User {user_id} already exists, skipping bootstrap")
                active_tenant_id = user_doc.get("active_tenant_id")
                return {
                    "active_tenant_id": active_tenant_id,
                    "user_doc": user_doc,
                    "bootstrapped": False
                }
        except HTTPException as e:
            if e.status_code != 404:
                raise
        
        # Create personal tenant
        now = datetime.utcnow().isoformat() + "Z"
        # Use hashed sub for tenant ID (consistent with user_id format)
        personal_tenant_id = f"tenant_{sub_hash}_personal"
        personal_tenant_id_virtual = f"{sub_hash}_personal"  # Virtual format (no prefix)

        # IMPORTANT: userId stores the internal doc ID (user_{hash})
        # IMPORTANT: userIds stores the Clerk sub for querying (matches POST /__tenants behavior)
        # This is because virtual_tables queries userIds by JWT sub (requesting_user_id = payload.get("sub"))
        tenant_doc = {
            "_id": personal_tenant_id,
            "type": "tenant",
            "name": f"{email.split('@')[0]}'s Workspace",
            "userId": sub_normalized,  # Clerk sub (not hashed) - for owner lookup
            "userIds": [sub_normalized],  # Clerk sub (not hashed) - for membership queries
            "applicationId": "roady",
            "metadata": {
                "isPersonal": True,
                "autoCreated": True
            },
            "createdAt": now,
            "updatedAt": now
        }
        logger.info(f"Bootstrap: Creating tenant {personal_tenant_id} with userIds={tenant_doc['userIds']}")
        
        # Create user document
        user_doc = {
            "_id": user_id,
            "type": "user",
            "sub": sub,
            "email": email,
            "name": name,
            "personalTenantId": personal_tenant_id,
            "tenantIds": [personal_tenant_id],
            "tenants": [
                {
                    "tenantId": personal_tenant_id,
                    "role": "owner",
                    "personal": True,
                    "joinedAt": now
                }
            ],
            "active_tenant_id": personal_tenant_id_virtual,
            "createdAt": now,
            "updatedAt": now
        }
        
        # Save to CouchDB (tenant first, then user)
        try:
            logger.info(f"Creating personal tenant: {personal_tenant_id}")
            put_result = await self.dal.put_document("couch-sitter", personal_tenant_id, tenant_doc)
            # Add the _rev from put result to our tenant_doc for consistency
            tenant_doc["_rev"] = put_result.get("_rev")
            
            logger.info(f"Creating user: {user_id}")
            put_result = await self.dal.put_document("couch-sitter", user_id, user_doc)
            # Add the _rev from put result to our user_doc for consistency
            user_doc["_rev"] = put_result.get("_rev")
            
            logger.info(f"Bootstrapped user {user_id} with personal tenant {personal_tenant_id}")
            
            return {
                "active_tenant_id": personal_tenant_id_virtual,
                "user_doc": user_doc,
                "tenant_doc": tenant_doc,
                "bootstrapped": True
            }
        except Exception as e:
            logger.error(f"Failed to bootstrap user {user_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to bootstrap user")

    async def ensure_user_bootstrap(self, payload: Dict[str, Any]) -> str:
        """
        Ensure user is bootstrapped and return active_tenant_id.
        
        Flow:
        1. Check if JWT has active_tenant_id
           - YES: Use it (skip bootstrap)
           - NO: Continue
        2. Extract user info from JWT (sub, email, name)
        3. Bootstrap user if doesn't exist
        4. Return active_tenant_id from user doc
        
        Returns:
            active_tenant_id to use for this request
            
        Raises:
            HTTPException(401) if active_tenant_id missing (client must refresh JWT)
        """
        # 1. Check JWT claim
        jwt_active_tenant_id = await self.check_active_tenant_id(payload)
        if jwt_active_tenant_id:
            logger.debug(f"JWT has active_tenant_id: {jwt_active_tenant_id}")
            return jwt_active_tenant_id
        
        # 2. Extract user info
        sub = payload.get("sub")
        email = payload.get("email")
        name = payload.get("name")
        
        if not sub:
            raise HTTPException(status_code=400, detail="Missing 'sub' claim in JWT")

        # Normalize sub to remove user_ prefix if present (Clerk may include it)
        sub_normalized = sub[5:] if sub.startswith("user_") else sub
        # Hash the sub to create consistent user ID that matches frontend hashing
        sub_hash = self._hash_sub(sub_normalized)
        user_id = f"user_{sub_hash}"

        # 3. Check if user exists and has active_tenant_id
        existing_active = await self.get_user_active_tenant(user_id)
        if existing_active:
            logger.info(f"User {user_id} exists with active_tenant_id: {existing_active}")
            return existing_active
        
        # 4. Bootstrap if needed
        logger.info(f"Bootstrapping user {user_id} (email={email}, name={name})")
        result = await self.bootstrap_user(sub, email or "unknown@example.com", name or "Unknown")
        
        # 5. Return active_tenant_id
        active_tenant_id = result.get("active_tenant_id")
        
        if not active_tenant_id:
            raise HTTPException(status_code=500, detail="Failed to determine active_tenant_id")
        
        logger.info(f"Bootstrap successful for {user_id}, active_tenant_id={active_tenant_id}")
        return active_tenant_id
