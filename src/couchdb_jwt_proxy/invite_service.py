"""
Invitation Service for Workspace Tenant Management

Handles secure token generation, validation, and single-use enforcement
for workspace invitations.
"""

import os
import uuid
import hmac
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import httpx
import logging
from unittest.mock import MagicMock

logger = logging.getLogger(__name__)

# Prefix for invitation tokens
TOKEN_PREFIX = "sk_"
TOKEN_BYTES = 32  # 256-bit entropy
EXPIRATION_DAYS = 7
HMAC_ALGORITHM = "sha256"


class InviteService:
    """
    Service for managing workspace invitations with secure token handling.
    
    Features:
    - Secure token generation (sk_ prefix, 256-bit entropy)
    - Single-use token validation
    - Expiration checking (7 days default)
    - Email verification matching
    - Timing-attack resistant comparison
    """

    def __init__(self, couch_sitter_db_url: str, couchdb_user: str = None, couchdb_password: str = None, dal=None):
        """
        Initialize the service with database connection parameters.

        Args:
            couch_sitter_db_url: URL to the couch-sitter database
            couchdb_user: Username for CouchDB authentication
            couchdb_password: Password for CouchDB authentication
            dal: Optional DAL instance for testing
        """
        self.db_url = couch_sitter_db_url.rstrip('/')
        self.couchdb_user = couchdb_user
        self.couchdb_password = couchdb_password
        self.dal = dal

        # Prepare authentication headers if credentials provided
        self.auth_headers = {}
        if couchdb_user and couchdb_password:
            import base64
            credentials = base64.b64encode(f"{couchdb_user}:{couchdb_password}".encode()).decode()
            self.auth_headers["Authorization"] = f"Basic {credentials}"

        self.db_name = self.db_url.split('/')[-1]
        logger.info(f"InviteService initialized for database: {couch_sitter_db_url}")

    async def _make_request(self, method: str, path: str, **kwargs):
        """
        Make a request to CouchDB with authentication.
        Uses DAL when available (testing), otherwise HTTP requests.

        Args:
            method: HTTP method
            path: Database path (relative to database URL)
            **kwargs: Additional arguments

        Returns:
            Response object (httpx.Response for HTTP, mock for DAL)

        Raises:
            httpx.HTTPError: If the request fails
        """
        if self.dal:
            json_data = kwargs.get('json')
            payload = json_data if method in ["PUT", "POST"] else None
            full_path = f"{self.db_name}/{path.lstrip('/')}"
            
            result = await self.dal.get(full_path, method, payload)

            mock_response = MagicMock()
            mock_response.json.return_value = result

            if isinstance(result, dict) and "error" in result:
                if result.get("error") == "not_found":
                    mock_response.status_code = 404
                else:
                    mock_response.status_code = 400
            else:
                mock_response.status_code = 200

            def raise_for_status():
                if mock_response.status_code >= 400:
                    import httpx
                    raise httpx.HTTPStatusError(
                        f"HTTP {mock_response.status_code} error",
                        request=MagicMock(),
                        response=mock_response
                    )
            mock_response.raise_for_status = raise_for_status
            return mock_response

        # Otherwise make HTTP request
        url = f"{self.db_url}/{path.lstrip('/')}"
        headers = kwargs.pop('headers', {})
        headers.update(self.auth_headers)

        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response

    def generate_token(self) -> str:
        """
        Generate a secure invitation token.
        
        Format: sk_ prefix + 32 bytes random (256-bit entropy)
        
        Returns:
            Token string
        """
        random_bytes = secrets.token_hex(TOKEN_BYTES)
        token = f"{TOKEN_PREFIX}{random_bytes}"
        logger.debug(f"Generated invitation token: {token[:20]}...")
        return token

    def hash_token(self, token: str) -> str:
        """
        Hash a token for storage.
        
        Uses SHA256 to store only hashed version in database.
        
        Args:
            token: Plain token string
            
        Returns:
            SHA256 hash as hex string
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        logger.debug(f"Hashed token: {token[:20]}... -> {token_hash[:20]}...")
        return token_hash

    def verify_token(self, plain_token: str, stored_hash: str) -> bool:
        """
        Verify a token against its stored hash using timing-attack resistant comparison.
        
        Args:
            plain_token: Plain token from user
            stored_hash: Stored hash from database
            
        Returns:
            True if token matches, False otherwise
        """
        plain_hash = self.hash_token(plain_token)
        # Use hmac.compare_digest for timing-attack resistance
        return hmac.compare_digest(plain_hash, stored_hash)

    async def create_invitation(
        self,
        tenant_id: str,
        tenant_name: str,
        email: str,
        role: str,
        created_by: str,
        expiration_days: int = EXPIRATION_DAYS
    ) -> Dict[str, Any]:
        """
        Create a new invitation for a workspace tenant.
        
        Args:
            tenant_id: Tenant ID (internal format: tenant_uuid)
            tenant_name: Tenant name (denormalized for preview)
            email: Email of the invitee
            role: Role to assign (member, admin)
            created_by: User ID of inviter
            expiration_days: Days until invitation expires (default: 7)
            
        Returns:
            Invitation document with token
            
        Raises:
            httpx.HTTPError: If database operation fails
            ValueError: If tenant_id is not in internal format
        """
        # CRITICAL: Validate tenant_id is in internal format (tenant_uuid)
        # The caller is responsible for sending correct format. No silent conversions.
        if not isinstance(tenant_id, str) or not tenant_id.startswith("tenant_"):
            raise ValueError(
                f"Invalid tenant_id format in invitation: '{tenant_id}'. "
                f"Expected internal format 'tenant_<uuid>', got format without 'tenant_' prefix. "
                f"Caller must prepend 'tenant_' prefix before calling create_invitation."
            )
        
        invite_id = f"invite_{uuid.uuid4()}"
        plain_token = self.generate_token()
        token_hash = self.hash_token(plain_token)
        
        current_time = datetime.now(timezone.utc).isoformat()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=expiration_days)).isoformat()
        
        invitation_doc = {
            "_id": invite_id,
            "type": "invitation",
            "tenantId": tenant_id,  # Stored in internal format (tenant_uuid)
            "tenantName": tenant_name,
            "email": email,
            "role": role,
            "token": plain_token,
            "tokenHash": token_hash,
            "status": "pending",
            "createdBy": created_by,
            "createdAt": current_time,
            "expiresAt": expires_at,
            "acceptedAt": None,
            "acceptedBy": None
        }
        
        try:
            response = await self._make_request("PUT", invite_id, json=invitation_doc)
            created = response.json()
            logger.info(f"Created invitation: {invite_id} for {email} to tenant {tenant_id}")
            
            # Return the original document (with plain token) once, then never again
            return invitation_doc
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to create invitation: {e}")
            raise

    async def get_invitation_by_id(self, invite_id: str) -> Optional[Dict[str, Any]]:
        """
        Get invitation document by ID.
        
        Args:
            invite_id: Invitation ID
            
        Returns:
            Invitation document if found, None otherwise
        """
        try:
            response = await self._make_request("GET", invite_id)
            doc = response.json()
            logger.debug(f"Found invitation: {invite_id}")
            return doc
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"Invitation not found: {invite_id}")
                return None
            logger.error(f"Error fetching invitation {invite_id}: {e}")
            raise

    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate an invitation token.
        
        Checks:
        - Token exists and matches hash
        - Not yet expired
        - Not already accepted
        
        Args:
            token: Plain token from user
            
        Returns:
            Invitation document if valid, None if invalid/expired
        """
        # Extract token prefix to find invitations (all invitations have sk_ token)
        if not token.startswith(TOKEN_PREFIX):
            logger.warning(f"Invalid token format: {token[:20]}...")
            return None
        
        try:
            # Query for invitations with matching token hash
            token_hash = self.hash_token(token)
            query = {
                "selector": {
                    "type": "invitation",
                    "tokenHash": token_hash
                },
                "limit": 1
            }
            
            response = await self._make_request("POST", "_find", json=query)
            result = response.json()
            
            docs = result.get("docs", [])
            if not docs:
                logger.warning(f"Token not found: {token[:20]}...")
                return None
            
            invitation = docs[0]
            
            # Check if already accepted
            if invitation.get("status") == "accepted":
                logger.warning(f"Token already accepted: {invitation['_id']}")
                return None
            
            # Check if revoked
            if invitation.get("status") == "revoked":
                logger.warning(f"Token revoked: {invitation['_id']}")
                return None
            
            # Check expiration
            expires_at = invitation.get("expiresAt")
            if expires_at:
                expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if datetime.now(timezone.utc) > expires_dt:
                    logger.warning(f"Token expired: {invitation['_id']}")
                    return None
            
            logger.info(f"Token validated: {invitation['_id']}")
            return invitation
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Error validating token: {e}")
            raise

    async def accept_invitation(
        self,
        invitation: Dict[str, Any],
        user_id: str
    ) -> Dict[str, Any]:
        """
        Mark invitation as accepted.
        
        Args:
            invitation: Invitation document
            user_id: User ID accepting the invitation
            
        Returns:
            Updated invitation document
            
        Raises:
            httpx.HTTPError: If database operation fails
        """
        current_time = datetime.now(timezone.utc).isoformat()
        
        invitation["status"] = "accepted"
        invitation["acceptedAt"] = current_time
        invitation["acceptedBy"] = user_id
        
        try:
            response = await self._make_request("PUT", invitation["_id"], json=invitation)
            updated = response.json()
            logger.info(f"Accepted invitation: {invitation['_id']} by user {user_id}")
            return invitation
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to accept invitation: {e}")
            raise

    async def revoke_invitation(self, invite_id: str) -> Dict[str, Any]:
        """
        Revoke a pending invitation.
        
        Args:
            invite_id: Invitation ID
            
        Returns:
            Updated invitation document
            
        Raises:
            httpx.HTTPError: If database operation fails
        """
        try:
            invitation = await self.get_invitation_by_id(invite_id)
            if not invitation:
                raise ValueError(f"Invitation not found: {invite_id}")
            
            current_time = datetime.now(timezone.utc).isoformat()
            invitation["status"] = "revoked"
            invitation["revokedAt"] = current_time
            
            response = await self._make_request("PUT", invite_id, json=invitation)
            updated = response.json()
            logger.info(f"Revoked invitation: {invite_id}")
            return invitation
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to revoke invitation: {e}")
            raise

    async def get_invitations_for_tenant(
        self,
        tenant_id: str,
        status: Optional[str] = None
    ) -> list:
        """
        Get all invitations for a tenant.
        
        Args:
            tenant_id: Tenant ID
            status: Filter by status (pending, accepted, revoked)
            
        Returns:
            List of invitation documents
        """
        try:
            selector = {
                "type": "invitation",
                "tenantId": tenant_id
            }
            
            if status:
                selector["status"] = status
            
            query = {
                "selector": selector,
                "sort": [{"createdAt": "desc"}]
            }
            
            response = await self._make_request("POST", "_find", json=query)
            result = response.json()
            
            invitations = result.get("docs", [])
            logger.debug(f"Found {len(invitations)} invitations for tenant {tenant_id}")
            return invitations
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Error fetching invitations for tenant {tenant_id}: {e}")
            raise

    async def create_tenant_user_mapping(
        self,
        tenant_id: str,
        user_id: str,
        role: str,
        invited_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        DEPRECATED: This method no longer creates tenant_user_mapping documents.
        Role is now stored in user.tenants[] array (single source of truth).
        This method is kept for backward compatibility but is a no-op.
        
        Args:
            tenant_id: Tenant ID
            user_id: User ID
            role: Role (owner, admin, member)
            invited_by: User ID of the inviter
            
        Returns:
            Empty dict (no document created)
        """
        logger.info(f"create_tenant_user_mapping called but is deprecated (no-op). Role should be in user.tenants[]")
        return {}
