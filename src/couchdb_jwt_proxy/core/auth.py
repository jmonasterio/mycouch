"""
Nostr NIP-98 HTTP Auth — verification and session token management.

NIP-98 replaces Clerk RS256 JWT. The client signs a kind-27235 Nostr event
bound to the exact URL + HTTP method, base64-encodes it, and sends it as:
    Authorization: Nostr <base64(JSON event)>

The server verifies once at POST /auth/session and issues a short-lived
HMAC-SHA256 session token. All subsequent requests use Bearer <token>.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import coincurve
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nostr canonical event serialization
# ---------------------------------------------------------------------------

def _serialize_event(pubkey: str, created_at: int, kind: int,
                     tags: list, content: str) -> bytes:
    """Produce the canonical Nostr event serialization for hashing.

    [0, pubkey, created_at, kind, tags, content]
    """
    return json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _get_tag(tags: list, name: str) -> Optional[str]:
    """Return the first value of the first tag matching name, or None."""
    for tag in tags:
        if isinstance(tag, list) and len(tag) >= 2 and tag[0] == name:
            return tag[1]
    return None


# ---------------------------------------------------------------------------
# NIP-98 verification
# ---------------------------------------------------------------------------

def verify_nip98(
    authorization: Optional[str],
    url: str,
    method: str,
    body: bytes = b"",
    time_tolerance: int = 60,
) -> str:
    """Verify a NIP-98 Authorization header and return the pubkey hex.

    Raises HTTPException(401) on any failure.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Nostr "):
        raise HTTPException(status_code=401, detail="Authorization must use Nostr scheme")

    # 1. Decode base64 → JSON
    try:
        event_json = base64.b64decode(authorization[6:])
        event: Dict[str, Any] = json.loads(event_json)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: malformed base64/JSON")

    # 2. kind must be 27235
    if event.get("kind") != 27235:
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: kind must be 27235")

    # 3. Timestamp within tolerance
    created_at = event.get("created_at")
    if not isinstance(created_at, int):
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: missing created_at")
    if abs(time.time() - created_at) > time_tolerance:
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: timestamp out of range")

    # 4. u tag must match request URL exactly
    tags = event.get("tags", [])
    u_tag = _get_tag(tags, "u")
    if u_tag != url:
        logger.warning(f"NIP-98 URL mismatch: event has '{u_tag}', request is '{url}'")
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: URL mismatch")

    # 5. method tag must match HTTP method
    method_tag = _get_tag(tags, "method")
    if not method_tag or method_tag.upper() != method.upper():
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: method mismatch")

    # 6. payload tag: if present on POST/PUT/PATCH, verify SHA256 of body
    payload_tag = _get_tag(tags, "payload")
    if method.upper() in ("POST", "PUT", "PATCH") and payload_tag is not None:
        expected = hashlib.sha256(body).hexdigest()
        if payload_tag != expected:
            raise HTTPException(status_code=401, detail="Invalid NIP-98 token: payload hash mismatch")

    # 7. Verify event id = SHA256(canonical serialization)
    pubkey = event.get("pubkey", "")
    content = event.get("content", "")
    try:
        canonical = _serialize_event(pubkey, created_at, 27235, tags, content)
        expected_id = hashlib.sha256(canonical).hexdigest()
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: cannot serialize event")

    if event.get("id") != expected_id:
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: id mismatch")

    # 8. Verify Schnorr signature (BIP-340) via coincurve
    sig_hex = event.get("sig", "")
    try:
        pubkey_bytes = bytes.fromhex(pubkey)
        sig_bytes = bytes.fromhex(sig_hex)
        event_id_bytes = bytes.fromhex(expected_id)
        pk = coincurve.PublicKeyXOnly(pubkey_bytes)
        valid = pk.verify(sig_bytes, event_id_bytes)
    except Exception as e:
        logger.warning(f"NIP-98 signature verification error: {e}")
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: signature verification failed")

    if not valid:
        raise HTTPException(status_code=401, detail="Invalid NIP-98 token: invalid signature")

    return pubkey


# ---------------------------------------------------------------------------
# Session token (HMAC-SHA256, stateless)
# ---------------------------------------------------------------------------

def _get_session_secret() -> bytes:
    """Return SESSION_SECRET as bytes. Raises on missing/short secret."""
    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError(
            "SESSION_SECRET must be set to at least 32 characters. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return secret.encode("utf-8")


def issue_session_token(
    pubkey: str,
    user_id: str,
    ttl: Optional[int] = None,
) -> Dict[str, Any]:
    """Issue a short-lived HMAC-SHA256 session token.

    Returns { token, expires_in } where expires_in is seconds.
    """
    if ttl is None:
        ttl = int(os.environ.get("SESSION_TTL_SECONDS", str(8 * 3600)))

    now = int(time.time())
    payload = json.dumps({
        "pubkey": pubkey,
        "user_id": user_id,
        "iat": now,
        "exp": now + ttl,
    }, separators=(",", ":"))

    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_get_session_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
    token = f"{payload_b64}.{sig}"

    return {"token": token, "expires_in": ttl}


def verify_session_token(authorization: Optional[str]) -> Dict[str, Any]:
    """Verify a Bearer session token and return {"pubkey", "user_id"}.

    Raises HTTPException(401) on any failure.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization must use Bearer scheme")

    token = authorization[7:]

    try:
        payload_b64, sig = token.rsplit(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid session token format")

    # Verify HMAC
    expected_sig = hmac.new(_get_session_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid session token: signature mismatch")

    # Decode payload
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session token: malformed payload")

    # Check expiry
    if int(time.time()) > payload.get("exp", 0):
        raise HTTPException(status_code=401, detail="Session token expired")

    return {
        "pubkey": payload["pubkey"],
        "user_id": payload["user_id"],
    }
