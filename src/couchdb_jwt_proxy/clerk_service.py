"""
Clerk Backend API Service for Session Metadata Management

Handles all Clerk Backend API operations for managing user sessions
and active tenant information in Clerk session metadata.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
import httpx

# Try to import Clerk Backend API, but don't fail if not available
try:
    from clerk_backend_api import Clerk
    CLERK_API_AVAILABLE = True
except ImportError:
    CLERK_API_AVAILABLE = False
    logging.warning("Clerk Backend API not available - session metadata features disabled")

logger = logging.getLogger(__name__)


class ClerkService:
    """
    Service for managing Clerk sessions and active tenant metadata.

    Features:
    - Session metadata management for active tenant
    - User verification and session validation
    - Integration with user cache and tenant management
    """

    def __init__(self, secret_key: str = None, issuer_url: str = None):
        """
        Initialize the Clerk service.
        
        Args:
            secret_key: Default Clerk Secret Key (optional - will come from app config)
            issuer_url: Default Clerk Issuer URL (optional)
        """
        self.clients: Dict[str, Clerk] = {}
        self.default_issuer = issuer_url or os.getenv("CLERK_ISSUER_URL")
        
        # Only register default client if BOTH issuer and secret are provided
        # Otherwise, secrets come from app config in couch-sitter database
        default_key = secret_key or os.getenv("CLERK_SECRET_KEY")
        if self.default_issuer and default_key:
            logger.info(f"Registering default Clerk app: {self.default_issuer}")
            self.register_app(self.default_issuer, default_key)
        elif self.default_issuer:
            logger.info(f"Clerk Issuer configured: {self.default_issuer} (secrets from app config)")
        else:
            logger.warning("No Clerk configuration - metadata updates will be skipped")

    def register_app(self, issuer: str, secret_key: str):
        """
        Register a Clerk application with its secret key.
        
        Args:
            issuer: Clerk Issuer URL
            secret_key: Clerk Secret Key
        """
        if not CLERK_API_AVAILABLE:
            logger.warning("Clerk Backend API package not installed - cannot register app")
            return

        try:
            client = Clerk(bearer_auth=secret_key)
            self.clients[issuer] = client
            logger.info(f"Registered Clerk client for issuer: {issuer}")
        except Exception as e:
            logger.error(f"Failed to initialize Clerk client for {issuer}: {e}")

    def get_client(self, issuer: str = None) -> Optional[Clerk]:
        """
        Get the Clerk client for a specific issuer.
        
        Loads client from cache if available, otherwise tries to load from APPLICATIONS if configured.
        
        Args:
            issuer: Clerk Issuer URL (optional, defaults to self.default_issuer)
            
        Returns:
            Clerk client instance or None
        """
        target_issuer = issuer or self.default_issuer
        logger.debug(f"[CLERK] get_client() called: issuer={issuer}, default_issuer={self.default_issuer}, target_issuer={target_issuer}")
        
        if not target_issuer:
            logger.warning("[CLERK] get_client() - no target issuer")
            return None
            
        # Normalize issuer (remove trailing slash)
        target_issuer = target_issuer.rstrip('/')
        
        # Check cache first
        if target_issuer in self.clients:
            logger.debug(f"[CLERK] Found client in cache for {target_issuer}")
            return self.clients[target_issuer]
        
        logger.debug(f"[CLERK] Client not in cache for {target_issuer}, trying APPLICATIONS")
        
        # Try to load from APPLICATIONS if available (live loading)
        try:
            from .main import APPLICATIONS
            logger.debug(f"[CLERK] APPLICATIONS keys: {list(APPLICATIONS.keys())}")
            
            if target_issuer in APPLICATIONS:
                app_config = APPLICATIONS[target_issuer]
                logger.debug(f"[CLERK] Found config in APPLICATIONS for {target_issuer}")
                
                if isinstance(app_config, dict):
                    secret_key = app_config.get("clerkSecretKey")
                    if secret_key:
                        logger.info(f"[CLERK] Registering Clerk client from APPLICATIONS: {target_issuer}")
                        self.register_app(target_issuer, secret_key)
                        logger.info(f"[CLERK] Loaded and registered Clerk client from APPLICATIONS: {target_issuer}")
                        return self.clients.get(target_issuer)
                    else:
                        logger.warning(f"[CLERK] No clerkSecretKey in APPLICATIONS for {target_issuer}")
                else:
                    logger.warning(f"[CLERK] APPLICATIONS[{target_issuer}] is not a dict: {type(app_config)}")
            else:
                logger.warning(f"[CLERK] {target_issuer} not in APPLICATIONS")
                
        except ImportError as e:
            logger.warning(f"[CLERK] Failed to import APPLICATIONS: {e}")
            pass
        except Exception as e:
            logger.error(f"[CLERK] Failed to load Clerk client from APPLICATIONS for {target_issuer}: {e}", exc_info=True)
        
        logger.warning(f"[CLERK] No Clerk client available for {target_issuer}")
        return None

    async def verify_session_token(self, token: str, issuer: str = None) -> Optional[Dict[str, Any]]:
        """
        Verify a Clerk session token and return session information.

        Args:
            token: Clerk session token
            issuer: Clerk Issuer URL

        Returns:
            Session information dict if valid, None otherwise
        """
        client = self.get_client(issuer)
        if not client:
            logger.warning(f"No Clerk client found for issuer: {issuer}")
            return None

        try:
            # Verify the session token using Clerk Backend API
            session = client.sessions.verify_session_token(token)
            if session:
                logger.debug(f"Verified session for user: {session.user_id}")
                return {
                    "session_id": session.id,
                    "user_id": session.user_id,
                    "expires_at": session.expire_at,
                    "status": session.status
                }
            return None
        except Exception as e:
            logger.error(f"Failed to verify session token: {e}")
            return None

    async def update_active_tenant_in_session(self, user_id: str, tenant_id: str, issuer: str = None) -> bool:
        """
        Update the active tenant in a user's metadata.

        Args:
            user_id: Clerk user ID
            tenant_id: New active tenant ID
            issuer: Clerk Issuer URL

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"[CLERK] Attempting to update active tenant for user {user_id} to {tenant_id}, issuer={issuer}")
        
        client = self.get_client(issuer)
        if not client:
            logger.warning(f"[CLERK] Clerk Backend API not configured for issuer {issuer} - cannot update user metadata")
            return False

        logger.debug(f"[CLERK] Got Clerk client for issuer {issuer}")

        try:
            # Get current user metadata
            logger.debug(f"[CLERK] Fetching current user data for {user_id}")
            user = client.users.get(user_id=user_id)
            
            if not user:
                logger.error(f"[CLERK] User {user_id} not found in Clerk")
                return False
            
            current_metadata = user.public_metadata if user.public_metadata else {}
            logger.debug(f"[CLERK] Current user metadata: {current_metadata}")

            # Update the active tenant
            updated_metadata = {
                **current_metadata,
                "active_tenant_id": tenant_id
            }
            logger.debug(f"[CLERK] Updated metadata to send: {updated_metadata}")

            # Update user's public metadata (JWT claim comes from {{user.public_metadata.active_tenant_id}})
            logger.info(f"[CLERK] Calling client.users.update for user {user_id} with metadata: {updated_metadata}")
            client.users.update(
                user_id=user_id,
                public_metadata=updated_metadata
            )
            logger.info(f"[CLERK] Successfully updated active tenant in user metadata for user {user_id}: {tenant_id}")
            return True

        except Exception as e:
            logger.error(f"[CLERK] Failed to update active tenant for user {user_id}: {e}", exc_info=True)
            return False

    async def get_user_active_tenant(self, user_id: str, issuer: str = None) -> Optional[str]:
        """
        Get the active tenant ID from a user's metadata.

        Args:
            user_id: Clerk user ID
            issuer: Clerk Issuer URL

        Returns:
            Active tenant ID if found, None otherwise
        """
        client = self.get_client(issuer)
        if not client:
            return None

        try:
            user = client.users.get(user_id=user_id)
            if user and user.public_metadata:
                active_tenant = user.public_metadata.get("active_tenant_id")
                if active_tenant:
                    logger.debug(f"Found active tenant in user metadata for user {user_id}: {active_tenant}")
                    return active_tenant

            logger.debug(f"No active tenant found for user {user_id}")
            return None

        except Exception as e:
            logger.error(f"Failed to get active tenant for user {user_id}: {e}")
            return None

    async def update_user_active_tenant(self, user_id: str, tenant_id: str, issuer: str = None) -> bool:
        """
        Update the active tenant in a user's metadata (fallback method).

        Args:
            user_id: Clerk user ID
            tenant_id: New active tenant ID
            issuer: Clerk Issuer URL

        Returns:
            True if successful, False otherwise
        """
        client = self.get_client(issuer)
        if not client:
            logger.warning("Clerk Backend API not configured - cannot update user metadata")
            return False

        try:
            # Get current user metadata
            user = client.users.get(user_id=user_id)
            current_metadata = user.public_metadata if user and user.public_metadata else {}

            # Update the active tenant
            updated_metadata = {
                **current_metadata,
                "active_tenant_id": tenant_id,
                "active_tenant_updated_at": json.dumps({"__type__": "datetime", "value": "now"})
            }

            # Update the user metadata
            client.users.update(
                user_id=user_id,
                public_metadata=updated_metadata
            )

            logger.info(f"Updated active tenant in user metadata for user {user_id}: {tenant_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to update active tenant in user metadata for user {user_id}: {e}")
            return False

    async def get_user_from_jwt(self, jwt_token: str) -> Optional[Dict[str, Any]]:
        """
        Extract user information from JWT token.

        Args:
            jwt_token: Clerk JWT token

        Returns:
            User information dict if valid, None otherwise
        """
        try:
            # Decode the JWT token without verification first to get the sub and iss
            import jwt
            decoded = jwt.decode(jwt_token, options={"verify_signature": False})

            # Clerk's unique user ID can be in 'id' (custom claim) or 'sub' (standard claim)
            user_id = decoded.get("id") or decoded.get("sub")

            user_info = {
                "sub": user_id,  # Use id or sub as the primary identifier
                "user_id": user_id,
                "email": decoded.get("email"),
                "name": decoded.get("name"),
                "session_id": decoded.get("sid"),  # Session ID if available
                "tenant_id": decoded.get("tenant_id"),  # Tenant ID if available
                "iss": decoded.get("iss")  # Issuer
            }

            logger.debug(f"Extracted user info from JWT: {user_info}")
            return user_info

        except Exception as e:
            logger.error(f"Failed to extract user info from JWT: {e}")
            return None

    def is_configured(self) -> bool:
        """
        Check if the Clerk Backend API is properly configured.

        Returns:
            True if API is available and at least one client is registered
        """
        return CLERK_API_AVAILABLE and len(self.clients) > 0

    async def fetch_user_details(self, user_id: str, issuer: str = None) -> Optional[Dict[str, Any]]:
        """
        Fetch user details (email, name) directly from Clerk Backend API.
        Useful when JWT claims are missing this information.

        Args:
            user_id: Clerk user ID
            issuer: Clerk Issuer URL

        Returns:
            Dict with 'email' and 'name' if found, None otherwise
        """
        client = self.get_client(issuer)
        if not client:
            return None

        try:
            logger.info(f"Fetching user details from Clerk API for {user_id}")
            user = client.users.get(user_id=user_id)
            
            email = None
            if user.email_addresses:
                # Use primary email if available, otherwise first one
                primary = next((e for e in user.email_addresses if e.id == user.primary_email_address_id), None)
                if primary:
                    email = primary.email_address
                elif len(user.email_addresses) > 0:
                    email = user.email_addresses[0].email_address

            name = None
            if user.first_name or user.last_name:
                name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            
            return {
                "email": email,
                "name": name
            }

        except Exception as e:
            logger.error(f"Failed to fetch user details for {user_id}: {e}", exc_info=True)
            return None