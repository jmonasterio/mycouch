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

# Pure-Python BIP-340 secp256k1 Schnorr verification (no native deps)
_P  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _point_add(P1, P2):
    if P1 is None: return P2
    if P2 is None: return P1
    if P1[0] == P2[0] and P1[1] != P2[1]: return None
    if P1 == P2:
        lam = (3 * P1[0] * P1[0] * pow(2 * P1[1], _P - 2, _P)) % _P
    else:
        lam = ((P2[1] - P1[1]) * pow(P2[0] - P1[0], _P - 2, _P)) % _P
    x3 = (lam * lam - P1[0] - P2[0]) % _P
    return x3, (lam * (P1[0] - x3) - P1[1]) % _P


def _point_mul(P, n):
    R, Q = None, P
    while n:
        if n & 1: R = _point_add(R, Q)
        Q = _point_add(Q, Q)
        n >>= 1
    return R


def _lift_x(x):
    if x >= _P: return None
    y_sq = (pow(x, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != y_sq: return None
    return x, (y if y % 2 == 0 else _P - y)


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    h = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(h + h + msg).digest()


def _verify_schnorr(pubkey_bytes: bytes, msg: bytes, sig_bytes: bytes) -> bool:
    """BIP-340 Schnorr signature verification (pure Python, no native deps)."""
    if len(pubkey_bytes) != 32 or len(sig_bytes) != 64 or len(msg) != 32:
        return False
    P = _lift_x(int.from_bytes(pubkey_bytes, 'big'))
    if P is None:
        return False
    r = int.from_bytes(sig_bytes[:32], 'big')
    s = int.from_bytes(sig_bytes[32:], 'big')
    if r >= _P or s >= _N:
        return False
    e = int.from_bytes(
        _tagged_hash('BIP0340/challenge', sig_bytes[:32] + pubkey_bytes + msg), 'big'
    ) % _N
    R = _point_add(_point_mul((_Gx, _Gy), s), _point_mul(P, _N - e))
    return R is not None and R[1] % 2 == 0 and R[0] == r
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
        valid = _verify_schnorr(pubkey_bytes, event_id_bytes, sig_bytes)
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
