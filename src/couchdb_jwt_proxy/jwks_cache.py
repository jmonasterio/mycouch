"""
JWKS File Cache - Load JWKS keys from local files to avoid outbound network calls.

This helps avoid issues with security software (like CrowdStrike) that may block
outbound HTTPS connections to Clerk's JWKS endpoints.

Usage:
    1. Place JWKS files in the `jwks_cache/` directory
    2. Name them by issuer domain: `enabled-hawk-56.clerk.accounts.dev.json`
    3. MyCouch will load from file instead of fetching from network

To download JWKS files:
    python -m couchdb_jwt_proxy.jwks_cache download
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Cache directory relative to this file's location
CACHE_DIR = Path(__file__).parent.parent.parent / "jwks_cache"


def get_cache_filename(issuer: str) -> Path:
    """Convert issuer URL to cache filename."""
    # Extract domain from issuer URL
    # https://enabled-hawk-56.clerk.accounts.dev -> enabled-hawk-56.clerk.accounts.dev.json
    parsed = urlparse(issuer)
    domain = parsed.netloc or parsed.path.strip("/")
    return CACHE_DIR / f"{domain}.json"


def load_jwks_from_cache(issuer: str) -> Optional[Dict[str, Any]]:
    """
    Load JWKS from local cache file if it exists.

    Returns:
        JWKS dict if file exists, None otherwise
    """
    cache_file = get_cache_filename(issuer)
    logger.info(f"[JWKS_CACHE] Looking for cache file: {cache_file} (exists: {cache_file.exists()})")

    if not cache_file.exists():
        logger.warning(f"[JWKS_CACHE] No cache file found for {issuer}: {cache_file}")
        return None

    try:
        with open(cache_file, "r") as f:
            jwks = json.load(f)
        logger.info(f"✓ Loaded JWKS from cache: {cache_file}")
        return jwks
    except Exception as e:
        logger.error(f"Failed to load JWKS cache file {cache_file}: {e}")
        return None


def save_jwks_to_cache(issuer: str, jwks: Dict[str, Any]) -> bool:
    """
    Save JWKS to local cache file.

    Returns:
        True if saved successfully, False otherwise
    """
    cache_file = get_cache_filename(issuer)

    try:
        # Create cache directory if it doesn't exist
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        with open(cache_file, "w") as f:
            json.dump(jwks, f, indent=2)
        logger.info(f"✓ Saved JWKS to cache: {cache_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to save JWKS cache file {cache_file}: {e}")
        return False


def download_and_cache_jwks(issuer: str) -> Optional[Dict[str, Any]]:
    """
    Download JWKS from issuer and save to cache.

    This is meant to be run once manually to populate the cache.
    """
    import httpx

    jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"

    try:
        print(f"Downloading JWKS from {jwks_url}...")
        response = httpx.get(jwks_url, timeout=30.0)
        response.raise_for_status()
        jwks = response.json()

        if save_jwks_to_cache(issuer, jwks):
            print(f"✓ Cached JWKS for {issuer}")
            return jwks
        else:
            print(f"✗ Failed to cache JWKS for {issuer}")
            return None
    except Exception as e:
        print(f"✗ Failed to download JWKS from {jwks_url}: {e}")
        return None


def main():
    """CLI to download and cache JWKS files."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m couchdb_jwt_proxy.jwks_cache download [issuer1] [issuer2] ...")
        print("       python -m couchdb_jwt_proxy.jwks_cache download  # downloads default issuers")
        sys.exit(1)

    command = sys.argv[1]

    if command == "download":
        # Default issuers if none specified
        issuers = sys.argv[2:] if len(sys.argv) > 2 else [
            "https://enabled-hawk-56.clerk.accounts.dev",
            "https://desired-lab-27.clerk.accounts.dev"
        ]

        print(f"Downloading JWKS for {len(issuers)} issuer(s)...")
        print(f"Cache directory: {CACHE_DIR}")
        print()

        for issuer in issuers:
            download_and_cache_jwks(issuer)

        print()
        print("Done! Restart MyCouch to use cached JWKS.")
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
