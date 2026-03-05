"""
Unit tests for Nostr NIP-98 HTTP Auth verification and session token management.

Uses pure-Python secp256k1 signing (no native deps) for test key material.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from unittest.mock import patch

import pytest

from couchdb_jwt_proxy.core.auth import (
    _Gx,
    _Gy,
    _N,
    _P,
    _lift_x,
    _point_add,
    _point_mul,
    _serialize_event,
    _tagged_hash,
    issue_session_token,
    verify_nip98,
    verify_session_token,
)


# ---------------------------------------------------------------------------
# Pure-Python BIP-340 signer (for tests only — not used in production)
# ---------------------------------------------------------------------------

def _sign_schnorr(privkey_bytes: bytes, msg: bytes) -> bytes:
    """BIP-340 Schnorr signing with aux_rand = 0x00…00 (deterministic for tests)."""
    d = int.from_bytes(privkey_bytes, "big")
    if d == 0 or d >= _N:
        raise ValueError("invalid private key")

    P = _point_mul((_Gx, _Gy), d)
    # Negate d if P.y is odd (even-y convention)
    if P[1] % 2 != 0:
        d = _N - d
    P_x = P[0].to_bytes(32, "big")

    aux = b"\x00" * 32
    t = bytes(a ^ b for a, b in zip(privkey_bytes, _tagged_hash("BIP0340/aux", aux)))
    k0 = int.from_bytes(_tagged_hash("BIP0340/nonce", t + P_x + msg), "big") % _N
    if k0 == 0:
        raise ValueError("nonce is zero")

    R = _point_mul((_Gx, _Gy), k0)
    k = k0 if R[1] % 2 == 0 else _N - k0
    R_x = R[0].to_bytes(32, "big")

    e = int.from_bytes(_tagged_hash("BIP0340/challenge", R_x + P_x + msg), "big") % _N
    s = (k + e * d) % _N
    return R_x + s.to_bytes(32, "big")


class _PrivKey:
    """Thin wrapper around a raw private key, mirroring the coincurve API."""

    def __init__(self, privkey_bytes: bytes):
        self._priv = privkey_bytes
        d = int.from_bytes(privkey_bytes, "big")
        P = _point_mul((_Gx, _Gy), d)
        self._pubkey_hex = P[0].to_bytes(32, "big").hex()

    @property
    def public_key_xonly_hex(self) -> str:
        return self._pubkey_hex

    def sign_schnorr(self, msg: bytes) -> bytes:
        return _sign_schnorr(self._priv, msg)


# ---------------------------------------------------------------------------
# Test fixtures — real key material
# ---------------------------------------------------------------------------

TEST_PRIVKEY_HEX = "b94f5374fce5edbc8e2a8697c15331677e6ebf0b262f70f82af3ef28e4ef9fc9"
TEST_PRIVKEY = _PrivKey(bytes.fromhex(TEST_PRIVKEY_HEX))
TEST_PUBKEY_HEX = TEST_PRIVKEY.public_key_xonly_hex

SESSION_SECRET = "test-secret-that-is-at-least-32-chars-long"


def make_nip98_event(
    url: str,
    method: str,
    body: bytes = b"",
    privkey: _PrivKey = None,
    created_at: int = None,
    override_kind: int = 27235,
    override_u: str = None,
    override_method: str = None,
    include_payload: bool = True,
) -> str:
    """Build a valid NIP-98 Authorization header."""
    if privkey is None:
        privkey = TEST_PRIVKEY
    pubkey = privkey.public_key_xonly_hex
    ts = created_at if created_at is not None else int(time.time())

    tags = [
        ["u", override_u if override_u is not None else url],
        ["method", override_method if override_method is not None else method],
    ]
    if include_payload and method.upper() in ("POST", "PUT", "PATCH") and body:
        payload_hash = hashlib.sha256(body).hexdigest()
        tags.append(["payload", payload_hash])

    serialized = _serialize_event(pubkey, ts, override_kind, tags, "")
    event_id = hashlib.sha256(serialized).hexdigest()
    sig = privkey.sign_schnorr(bytes.fromhex(event_id)).hex()

    event = {
        "id": event_id,
        "pubkey": pubkey,
        "created_at": ts,
        "kind": override_kind,
        "tags": tags,
        "content": "",
        "sig": sig,
    }
    return "Nostr " + base64.b64encode(json.dumps(event).encode()).decode()


# ---------------------------------------------------------------------------
# verify_nip98 — happy path
# ---------------------------------------------------------------------------

class TestVerifyNip98Happy:
    def test_get_request_returns_pubkey(self):
        url = "http://localhost:5985/auth/session"
        auth = make_nip98_event(url, "GET")
        result = verify_nip98(auth, url, "GET")
        assert result == TEST_PUBKEY_HEX

    def test_post_request_with_body(self):
        url = "http://localhost:5985/auth/session"
        body = b'{"hello": "world"}'
        auth = make_nip98_event(url, "POST", body)
        result = verify_nip98(auth, url, "POST", body)
        assert result == TEST_PUBKEY_HEX

    def test_post_without_payload_tag_succeeds(self):
        """payload tag is optional — server only checks it if present."""
        url = "http://localhost:5985/auth/session"
        body = b"some body"
        auth = make_nip98_event(url, "POST", body, include_payload=False)
        result = verify_nip98(auth, url, "POST", body)
        assert result == TEST_PUBKEY_HEX

    def test_different_private_key(self):
        sk2 = _PrivKey(bytes.fromhex("a" * 64))
        url = "http://localhost:5985/test"
        auth = make_nip98_event(url, "GET", privkey=sk2)
        result = verify_nip98(auth, url, "GET")
        assert result == sk2.public_key_xonly_hex


# ---------------------------------------------------------------------------
# verify_nip98 — validation failures
# ---------------------------------------------------------------------------

class TestVerifyNip98Failures:
    def test_missing_authorization(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_nip98(None, "http://localhost/", "GET")
        assert exc.value.status_code == 401

    def test_wrong_scheme(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_nip98("Bearer sometoken", "http://localhost/", "GET")
        assert exc.value.status_code == 401

    def test_malformed_base64(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_nip98("Nostr notbase64!!!", "http://localhost/", "GET")
        assert exc.value.status_code == 401

    def test_wrong_kind(self):
        from fastapi import HTTPException
        url = "http://localhost:5985/auth/session"
        auth = make_nip98_event(url, "GET", override_kind=1)
        with pytest.raises(HTTPException) as exc:
            verify_nip98(auth, url, "GET")
        assert exc.value.status_code == 401
        assert "kind" in exc.value.detail

    def test_stale_timestamp(self):
        from fastapi import HTTPException
        url = "http://localhost:5985/auth/session"
        old_ts = int(time.time()) - 120
        auth = make_nip98_event(url, "GET", created_at=old_ts)
        with pytest.raises(HTTPException) as exc:
            verify_nip98(auth, url, "GET", time_tolerance=60)
        assert exc.value.status_code == 401
        assert "timestamp" in exc.value.detail

    def test_future_timestamp(self):
        from fastapi import HTTPException
        url = "http://localhost:5985/auth/session"
        future_ts = int(time.time()) + 120
        auth = make_nip98_event(url, "GET", created_at=future_ts)
        with pytest.raises(HTTPException) as exc:
            verify_nip98(auth, url, "GET", time_tolerance=60)
        assert exc.value.status_code == 401

    def test_url_mismatch(self):
        from fastapi import HTTPException
        url = "http://localhost:5985/auth/session"
        auth = make_nip98_event(url, "GET", override_u="http://localhost:5985/other")
        with pytest.raises(HTTPException) as exc:
            verify_nip98(auth, url, "GET")
        assert exc.value.status_code == 401
        assert "URL" in exc.value.detail

    def test_method_mismatch(self):
        from fastapi import HTTPException
        url = "http://localhost:5985/auth/session"
        auth = make_nip98_event(url, "GET", override_method="POST")
        with pytest.raises(HTTPException) as exc:
            verify_nip98(auth, url, "GET")
        assert exc.value.status_code == 401
        assert "method" in exc.value.detail

    def test_payload_hash_mismatch(self):
        from fastapi import HTTPException
        url = "http://localhost:5985/auth/session"
        body = b"real body"
        auth = make_nip98_event(url, "POST", b"different body")
        with pytest.raises(HTTPException) as exc:
            verify_nip98(auth, url, "POST", body)
        assert exc.value.status_code == 401
        assert "payload" in exc.value.detail

    def test_bad_signature(self):
        from fastapi import HTTPException
        url = "http://localhost:5985/auth/session"
        auth_header = make_nip98_event(url, "GET")

        # Tamper with the sig
        raw = base64.b64decode(auth_header[6:])
        event = json.loads(raw)
        event["sig"] = "00" * 64
        tampered = "Nostr " + base64.b64encode(json.dumps(event).encode()).decode()

        with pytest.raises(HTTPException) as exc:
            verify_nip98(tampered, url, "GET")
        assert exc.value.status_code == 401
        assert "signature" in exc.value.detail

    def test_tampered_id(self):
        from fastapi import HTTPException
        url = "http://localhost:5985/auth/session"
        auth_header = make_nip98_event(url, "GET")

        raw = base64.b64decode(auth_header[6:])
        event = json.loads(raw)
        event["id"] = "00" * 32
        tampered = "Nostr " + base64.b64encode(json.dumps(event).encode()).decode()

        with pytest.raises(HTTPException) as exc:
            verify_nip98(tampered, url, "GET")
        assert exc.value.status_code == 401
        assert "id" in exc.value.detail


# ---------------------------------------------------------------------------
# Session token — issue and verify
# ---------------------------------------------------------------------------

class TestSessionToken:
    def test_roundtrip(self):
        with patch.dict(os.environ, {"SESSION_SECRET": SESSION_SECRET}):
            data = issue_session_token("deadbeef" * 8, "user_abc123", ttl=3600)
            assert "token" in data
            assert data["expires_in"] == 3600

            payload = verify_session_token(f"Bearer {data['token']}")
            assert payload["pubkey"] == "deadbeef" * 8
            assert payload["user_id"] == "user_abc123"

    def test_expired_token(self):
        from fastapi import HTTPException
        with patch.dict(os.environ, {"SESSION_SECRET": SESSION_SECRET}):
            data = issue_session_token("aabbccdd" * 8, "user_xyz", ttl=-1)
            with pytest.raises(HTTPException) as exc:
                verify_session_token(f"Bearer {data['token']}")
            assert exc.value.status_code == 401
            assert "expired" in exc.value.detail

    def test_tampered_payload(self):
        from fastapi import HTTPException
        with patch.dict(os.environ, {"SESSION_SECRET": SESSION_SECRET}):
            data = issue_session_token("deadbeef" * 8, "user_abc", ttl=3600)
            token = data["token"]
            payload_b64, sig = token.rsplit(".", 1)

            # Tamper with the payload
            original = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
            original["user_id"] = "user_evil"
            tampered_b64 = base64.urlsafe_b64encode(json.dumps(original).encode()).decode().rstrip("=")
            tampered_token = f"{tampered_b64}.{sig}"

            with pytest.raises(HTTPException) as exc:
                verify_session_token(f"Bearer {tampered_token}")
            assert exc.value.status_code == 401
            assert "signature" in exc.value.detail

    def test_missing_bearer(self):
        from fastapi import HTTPException
        with patch.dict(os.environ, {"SESSION_SECRET": SESSION_SECRET}):
            with pytest.raises(HTTPException) as exc:
                verify_session_token(None)
            assert exc.value.status_code == 401

    def test_wrong_scheme(self):
        from fastapi import HTTPException
        with patch.dict(os.environ, {"SESSION_SECRET": SESSION_SECRET}):
            with pytest.raises(HTTPException) as exc:
                verify_session_token("Nostr sometoken")
            assert exc.value.status_code == 401

    def test_short_secret_raises(self):
        with patch.dict(os.environ, {"SESSION_SECRET": "short"}):
            with pytest.raises(RuntimeError, match="SESSION_SECRET"):
                issue_session_token("pubkey", "user", ttl=3600)
