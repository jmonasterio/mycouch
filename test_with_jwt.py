#!/usr/bin/env python3
"""
Test script - WITH JWT validation and proxy behavior.

Usage:
    .venv/Scripts/python test_with_jwt.py
"""
import uvicorn
import httpx
import json
import jwt
from pathlib import Path
from fastapi import FastAPI, Header
from typing import Optional

app = FastAPI()

COUCHDB_URL = "http://localhost:5984"
JWKS_CACHE_DIR = Path(__file__).parent / "jwks_cache"

# Load JWKS from cache
def load_jwks(issuer_domain):
    cache_file = JWKS_CACHE_DIR / f"{issuer_domain}.json"
    print(f"Loading JWKS from: {cache_file}")
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)
    return None

@app.get("/")
def root():
    return {"status": "ok", "message": "JWT + Proxy test"}

@app.get("/jwt-decode")
def jwt_decode(authorization: Optional[str] = Header(None)):
    """Decode JWT without verification"""
    if not authorization or not authorization.startswith("Bearer "):
        return {"error": "No token"}

    token = authorization[7:]
    try:
        # Decode without verification
        payload = jwt.decode(token, options={"verify_signature": False})
        print(f"Decoded JWT: sub={payload.get('sub')}, iss={payload.get('iss')}")
        return {"decoded": True, "sub": payload.get("sub"), "iss": payload.get("iss")}
    except Exception as e:
        return {"error": str(e)}

@app.get("/jwt-verify")
def jwt_verify(authorization: Optional[str] = Header(None)):
    """Full JWT verification with JWKS"""
    if not authorization or not authorization.startswith("Bearer "):
        return {"error": "No token"}

    token = authorization[7:]
    try:
        # Decode without verification first
        unverified = jwt.decode(token, options={"verify_signature": False})
        issuer = unverified.get("iss", "")
        print(f"JWT issuer: {issuer}")

        # Extract domain from issuer
        domain = issuer.replace("https://", "").replace("http://", "").rstrip("/")
        print(f"Looking for JWKS for domain: {domain}")

        # Load JWKS
        jwks = load_jwks(domain)
        if not jwks:
            return {"error": f"No JWKS cache for {domain}"}

        print(f"Loaded JWKS with {len(jwks.get('keys', []))} keys")

        # Get the key
        from jwt import PyJWK
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        print(f"Token kid: {kid}")

        key_data = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key_data = k
                break

        if not key_data:
            return {"error": f"Key {kid} not found in JWKS"}

        # Verify
        public_key = PyJWK.from_dict(key_data)
        payload = jwt.decode(
            token,
            public_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False, "verify_exp": False}
        )
        print(f"JWT verified! sub={payload.get('sub')}")
        return {"verified": True, "sub": payload.get("sub")}

    except Exception as e:
        print(f"JWT error: {e}")
        return {"error": str(e)}

@app.get("/jwt-and-proxy")
def jwt_and_proxy(authorization: Optional[str] = Header(None)):
    """JWT verification + CouchDB proxy - the full flow"""
    # First verify JWT
    result = jwt_verify(authorization)
    if "error" in result:
        return result

    # Then proxy to CouchDB
    print("Making request to CouchDB...")
    try:
        response = httpx.get(f"{COUCHDB_URL}/", auth=("admin", "admin"), timeout=5.0)
        print(f"CouchDB response: {response.status_code}")
        return {
            "jwt": result,
            "couchdb_status": response.status_code
        }
    except Exception as e:
        return {"jwt": result, "couchdb_error": str(e)}

if __name__ == "__main__":
    print("Starting JWT + Proxy test server...")
    print()
    print("Test endpoints:")
    print("  /jwt-decode    - Decode JWT without verification")
    print("  /jwt-verify    - Full JWT verification with local JWKS")
    print("  /jwt-and-proxy - JWT + CouchDB proxy (full flow)")
    print()
    print("Use with: curl -H 'Authorization: Bearer <token>' http://localhost:5985/jwt-verify")
    print()
    uvicorn.run(app, host="127.0.0.1", port=5985)
