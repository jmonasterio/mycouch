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
        Initialize the Clerk service with API credentials.

        Args:
            secret_key: Clerk Secret Key for Backend API access
            issuer_url: Clerk Issuer URL for JWT validation
        """
        self.secret_key = secret_key or os.getenv("CLERK_SECRET_KEY")
        self.issuer_url = issuer_url or os.getenv("CLERK_ISSUER_URL")

        if not self.issuer_url:
            raise ValueError("CLERK_ISSUER_URL is required")

        # Check if Clerk Backend API is available
        if not CLERK_API_AVAILABLE:
            logger.warning("Clerk Backend API package not installed - session metadata features disabled")
            self.clerk_client = None
        elif not self.secret_key:
            logger.warning("CLERK_SECRET_KEY not configured - Clerk Backend API features disabled")
            self.clerk_client = None
        else:
            try:
                self.clerk_client = Clerk(bearer_auth=self.secret_key)
                logger.info("ClerkService initialized with Backend API access")
            except Exception as e:
                logger.error(f"Failed to initialize Clerk Backend API client: {e}")
                self.clerk_client = None

    async def verify_session_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify a Clerk session token and return session information.

        Args:
            token: Clerk session token

        Returns:
            Session information dict if valid, None otherwise

        Raises:
            Exception: If token verification fails
        """
        if not self.clerk_client:
            logger.warning("Clerk Backend API not configured - skipping session verification")
            return None

        try:
            # Verify the session token using Clerk Backend API
            session = self.clerk_client.sessions.verify_session_token(token)
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

    async def get_user_session_metadata(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current session metadata for a user.

        Args:
            user_id: Clerk user ID
            session_id: Clerk session ID

        Returns:
            Session metadata dict if found, None otherwise
        """
        if not self.clerk_client:
            return None

        try:
            # Get the session to access metadata
            session = self.clerk_client.sessions.get(session_id=session_id)
            if session and session.public_user_data:
                metadata = session.public_user_data.get("metadata", {})
                logger.debug(f"Retrieved session metadata for user {user_id}: {metadata}")
                return metadata
            return {}
        except Exception as e:
            logger.error(f"Failed to get session metadata for user {user_id}: {e}")
            return None

    async def update_active_tenant_in_session(self, user_id: str, session_id: str, tenant_id: str) -> bool:
        """
        Update the active tenant in a user's session metadata.

        Args:
            user_id: Clerk user ID
            session_id: Clerk session ID
            tenant_id: New active tenant ID

        Returns:
            True if successful, False otherwise
        """
        if not self.clerk_client:
            logger.warning("Clerk Backend API not configured - cannot update session metadata")
            return False

        try:
            # Get current metadata
            current_metadata = await self.get_user_session_metadata(user_id, session_id) or {}

            # Update the active tenant
            updated_metadata = {
                **current_metadata,
                "active_tenant_id": tenant_id,
                "active_tenant_updated_at": json.dumps({"__type__": "datetime", "value": "now"})
            }

            # FIXED: Try to update session metadata first (the correct approach)
            # This ensures each session can have its own active tenant
            try:
                # Update the session's public user data metadata
                self.clerk_client.sessions.update(
                    session_id=session_id,
                    public_user_data={"metadata": updated_metadata}
                )
                logger.info(f"Updated active tenant in session metadata for user {user_id}: {tenant_id}")
                return True
            except Exception as session_error:
                # FIXED: Added proper fallback handling with logging
                logger.warning(f"Failed to update session metadata, falling back to user metadata: {session_error}")

                # FALLBACK: Update user metadata if session metadata fails
                # This ensures compatibility with older Clerk API versions or missing permissions
                self.clerk_client.users.update(
                    user_id=user_id,
                    public_metadata=updated_metadata
                )
                logger.info(f"Updated active tenant in user metadata (fallback) for user {user_id}: {tenant_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to update active tenant for user {user_id}: {e}")
            return False

    async def get_user_active_tenant(self, user_id: str, session_id: str) -> Optional[str]:
        """
        Get the active tenant ID from a user's session metadata.

        Args:
            user_id: Clerk user ID
            session_id: Clerk session ID

        Returns:
            Active tenant ID if found, None otherwise
        """
        if not self.clerk_client:
            return None

        try:
            # Try to get from session metadata first
            session_metadata = await self.get_user_session_metadata(user_id, session_id)
            if session_metadata:
                active_tenant = session_metadata.get("active_tenant_id")
                if active_tenant:
                    logger.debug(f"Found active tenant in session metadata for user {user_id}: {active_tenant}")
                    return active_tenant

            # Fallback to user metadata if session metadata doesn't have it
            user = self.clerk_client.users.get(user_id=user_id)
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

    async def update_user_active_tenant(self, user_id: str, tenant_id: str) -> bool:
        """
        Update the active tenant in a user's metadata (fallback method).

        Args:
            user_id: Clerk user ID
            tenant_id: New active tenant ID

        Returns:
            True if successful, False otherwise
        """
        if not self.clerk_client:
            logger.warning("Clerk Backend API not configured - cannot update user metadata")
            return False

        try:
            # Get current user metadata
            user = self.clerk_client.users.get(user_id=user_id)
            current_metadata = user.public_metadata if user and user.public_metadata else {}

            # Update the active tenant
            updated_metadata = {
                **current_metadata,
                "active_tenant_id": tenant_id,
                "active_tenant_updated_at": json.dumps({"__type__": "datetime", "value": "now"})
            }

            # Update the user metadata
            self.clerk_client.users.update(
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
            # Decode the JWT token without verification first to get the sub
            import jwt
            decoded = jwt.decode(jwt_token, options={"verify_signature": False})

            user_info = {
                "sub": decoded.get("sub"),
                "user_id": decoded.get("sub"),  # In Clerk, sub is the user ID
                "email": decoded.get("email"),
                "name": decoded.get("name"),
                "session_id": decoded.get("sid"),  # Session ID if available
                "tenant_id": decoded.get("tenant_id")  # Tenant ID if available
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
            True if API is available and configured with secret key, False otherwise
        """
        return CLERK_API_AVAILABLE and self.clerk_client is not None