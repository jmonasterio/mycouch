"""
Local JWKS Client - A PyJWKClient replacement that loads keys from local cache files.

This avoids outbound network calls which can be blocked by security software.
"""

import json
import logging
from typing import Optional, Dict, Any
from jwt import PyJWK
from jwt.api_jwk import PyJWKSet

logger = logging.getLogger(__name__)


class LocalJWKClient:
    """
    A JWT key client that loads JWKS from a local dict/file instead of fetching from network.

    Compatible with PyJWKClient interface for get_signing_key_from_jwt().
    """

    def __init__(self, jwks_data: Dict[str, Any]):
        """
        Initialize with JWKS data.

        Args:
            jwks_data: JWKS dict with "keys" array
        """
        self.jwks_data = jwks_data
        self._keys: Dict[str, PyJWK] = {}
        self._load_keys()

    def _load_keys(self):
        """Load and index all keys by kid."""
        keys = self.jwks_data.get("keys", [])
        for key_data in keys:
            kid = key_data.get("kid")
            if kid:
                try:
                    self._keys[kid] = PyJWK.from_dict(key_data)
                    logger.debug(f"Loaded key: {kid}")
                except Exception as e:
                    logger.warning(f"Failed to load key {kid}: {e}")

        logger.info(f"✓ Loaded {len(self._keys)} signing keys from local cache")

    def get_signing_key_from_jwt(self, token: str) -> PyJWK:
        """
        Get the signing key for a JWT token.

        Args:
            token: The JWT token string

        Returns:
            PyJWK object for the key

        Raises:
            Exception if key not found
        """
        import jwt

        # Decode header to get kid
        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as e:
            raise Exception(f"Failed to decode JWT header: {e}")

        kid = unverified_header.get("kid")
        if not kid:
            raise Exception("JWT header missing 'kid' (key ID)")

        if kid not in self._keys:
            available_kids = list(self._keys.keys())
            raise Exception(f"Key '{kid}' not found in JWKS. Available keys: {available_kids}")

        return self._keys[kid]
