"""
JWT authentication - sync-compatible for both FastAPI and stdlib servers.
"""
import logging
from typing import Dict, Any, Optional, Tuple

import jwt
from jwt import PyJWKClient

from .config import Config

logger = logging.getLogger(__name__)

# JWKS client cache (module-level singleton)
_jwks_clients: Dict[str, PyJWKClient] = {}


def decode_token_unsafe(token: str) -> Optional[Dict[str, Any]]:
    """Decode JWT without verification (for extracting issuer)."""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception as e:
        logger.warning(f"Failed to decode token: {e}")
        return None


def get_jwks_client(issuer: str) -> Optional[PyJWKClient]:
    """Get or create JWKS client for issuer."""
    if issuer in _jwks_clients:
        return _jwks_clients[issuer]

    jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
    logger.info(f"Fetching JWKS from: {jwks_url}")

    try:
        client = PyJWKClient(jwks_url, cache_keys=True)
        _jwks_clients[issuer] = client
        return client
    except Exception as e:
        logger.error(f"Failed to create JWKS client for {issuer}: {e}")
        return None


def verify_jwt(
    token: str,
    applications: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Verify JWT token.

    Args:
        token: The JWT token string
        applications: Optional dict of registered applications (issuer -> config)

    Returns:
        Tuple of (payload, error_reason). If successful, error_reason is None.
    """
    try:
        # Extract issuer from unverified token
        unverified = decode_token_unsafe(token)
        if not unverified:
            return None, "invalid_token_format"

        issuer = unverified.get("iss")
        if not issuer:
            return None, "missing_issuer"

        # Check if issuer is registered (if we have applications loaded)
        if applications and issuer not in applications:
            logger.warning(f"Unknown issuer: {issuer}")
            logger.warning(f"Registered issuers: {list(applications.keys())}")
            # Allow anyway - we may not have loaded apps yet

        # Get JWKS client
        jwks_client = get_jwks_client(issuer)
        if not jwks_client:
            return None, "jwks_unavailable"

        # Get signing key and verify
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={
                "verify_aud": False,
                "verify_iss": True,
                "verify_exp": not Config.SKIP_JWT_EXPIRATION_CHECK,
                "leeway": 300
            }
        )

        if Config.SKIP_JWT_EXPIRATION_CHECK:
            logger.warning("JWT expiration check DISABLED")

        return payload, None

    except jwt.ExpiredSignatureError:
        return None, "token_expired"
    except jwt.InvalidTokenError as e:
        return None, f"invalid_token: {e}"
    except Exception as e:
        logger.error(f"JWT verification error: {e}")
        return None, f"verification_error: {e}"


def extract_bearer_token(auth_header: str) -> Optional[str]:
    """Extract token from Authorization header."""
    if not auth_header:
        return None
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:]
