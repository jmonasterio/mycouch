"""
Authentication middleware for tenant/invitation endpoints.

Verifies Bearer session tokens issued by POST /auth/session.
The session token is obtained by authenticating once with NIP-98.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request

from .core.auth import verify_session_token

logger = logging.getLogger(__name__)


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Extract and verify the current user from a Bearer session token.

    Returns:
        Dict with user_id, sub (pubkey), email, name, issuer, azp

    Raises:
        HTTPException(401): If token is missing or invalid
    """
    payload = verify_session_token(authorization)

    return {
        "user_id": payload["user_id"],
        "sub": payload["pubkey"],   # pubkey is the stable Nostr identity
        "email": None,              # not available in NIP-98
        "name": None,               # not available in NIP-98
        "issuer": "nostr",
        "azp": None,
    }
