"""
Authentication Middleware for Tenant/Invitation Endpoints

Extracts user info from JWT for API routes.
"""

from fastapi import Depends, HTTPException, Header
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


# This will be set by the FastAPI app during initialization
clerk_service = None


def set_clerk_service(service):
    """Set the clerk service instance (called by main.py)"""
    global clerk_service
    clerk_service = service


async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Extract user info from JWT token in Authorization header.
    
    Returns:
        Dict with user_id, tenant_id, sub, email, name, application_id
        
    Raises:
        HTTPException: If token is missing or invalid
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization.split(" ", 1)[1]

    try:
        if not clerk_service:
            raise HTTPException(status_code=500, detail="Authentication service not available")

        # Validate JWT and extract user information
        user_info = await clerk_service.get_user_from_jwt(token)
        if not user_info:
            raise HTTPException(status_code=401, detail="Invalid JWT token")

        # Extract required fields
        sub = user_info.get("sub")
        email = user_info.get("email")
        name = user_info.get("name")
        issuer = user_info.get("iss")

        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token: missing sub claim")

        # Convert sub to user_id format used in database
        # Assuming sub is from Clerk and we hash it as user_{hash}
        # This assumes the couch_sitter_service has already created the user
        user_id = f"user_{sub}"  # This will be matched against user docs

        return {
            "user_id": user_id,
            "sub": sub,
            "email": email,
            "name": name,
            "issuer": issuer,
            "application_id": "roady"  # Default app, can be determined from issuer if needed
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting user from token: {e}")
        raise HTTPException(status_code=401, detail="Failed to validate token")
