#!/usr/bin/env python3
"""
Minimal MyCouch-like app to find CrowdStrike trigger.

Run with: .venv/Scripts/python test_mycouch_minimal.py

Then access endpoints to see which triggers CrowdStrike.
"""
import os
import sys
import json
import asyncio
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any

# Set up path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import uvicorn
import httpx
import jwt
from fastapi import FastAPI, Header, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Add CORS like MyCouch does
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5000", "http://localhost:4000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["accept", "authorization", "content-type"],
)

COUCHDB_URL = "http://localhost:5984"
JWKS_CACHE_DIR = Path(__file__).parent / "jwks_cache"

# Async HTTP client (like MyCouch uses)
_async_client = None

async def get_async_client():
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(timeout=30.0)
    return _async_client

def load_jwks(issuer_domain):
    cache_file = JWKS_CACHE_DIR / f"{issuer_domain}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)
    return None

def verify_jwt(token: str) -> Optional[Dict]:
    """Verify JWT using local JWKS cache"""
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        issuer = unverified.get("iss", "")
        domain = issuer.replace("https://", "").replace("http://", "").rstrip("/")

        jwks = load_jwks(domain)
        if not jwks:
            return None

        from jwt import PyJWK
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        key_data = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key_data = k
                break

        if not key_data:
            return None

        public_key = PyJWK.from_dict(key_data)
        payload = jwt.decode(
            token,
            public_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False, "verify_exp": False}
        )
        return payload
    except Exception as e:
        print(f"JWT error: {e}")
        return None

# === TEST ENDPOINTS ===

@app.get("/")
def root():
    return {"status": "ok", "test": "mycouch-minimal"}

@app.get("/1-basic")
def test_basic():
    """Just return JSON - no I/O"""
    return {"test": 1, "name": "basic"}

@app.get("/2-sync-couchdb")
def test_sync_couchdb():
    """Sync HTTP to CouchDB"""
    response = httpx.get(f"{COUCHDB_URL}/", auth=("admin", "admin"), timeout=5.0)
    return {"test": 2, "status": response.status_code}

@app.get("/3-async-couchdb")
async def test_async_couchdb():
    """Async HTTP to CouchDB (like MyCouch)"""
    client = await get_async_client()
    response = await client.get(f"{COUCHDB_URL}/", auth=("admin", "admin"))
    return {"test": 3, "status": response.status_code}

@app.get("/4-jwt-only")
def test_jwt_only(authorization: Optional[str] = Header(None)):
    """JWT verification only"""
    if not authorization or not authorization.startswith("Bearer "):
        return {"test": 4, "error": "no token"}
    payload = verify_jwt(authorization[7:])
    return {"test": 4, "verified": payload is not None}

@app.get("/5-jwt-then-couchdb")
async def test_jwt_then_couchdb(authorization: Optional[str] = Header(None)):
    """JWT verification then async CouchDB request"""
    if not authorization or not authorization.startswith("Bearer "):
        return {"test": 5, "error": "no token"}

    payload = verify_jwt(authorization[7:])
    if not payload:
        return {"test": 5, "error": "invalid jwt"}

    client = await get_async_client()
    response = await client.get(f"{COUCHDB_URL}/", auth=("admin", "admin"))
    return {"test": 5, "jwt": True, "couchdb": response.status_code}

@app.get("/6-hash-operation")
def test_hash():
    """Hash operation like MyCouch does for user IDs"""
    sub = "user_34tzJwWB3jaQT6ZKPqZIQoJwsmz"
    hashed = hashlib.sha256(sub.encode()).hexdigest()
    return {"test": 6, "hash": hashed[:16]}

@app.get("/7-couchdb-query")
async def test_couchdb_query():
    """CouchDB Mango query (like MyCouch does)"""
    client = await get_async_client()
    query = {"selector": {"type": "application"}, "limit": 10}
    response = await client.post(
        f"{COUCHDB_URL}/couch-sitter/_find",
        json=query,
        auth=("admin", "admin")
    )
    return {"test": 7, "status": response.status_code}

@app.get("/8-multiple-couchdb")
async def test_multiple_couchdb():
    """Multiple concurrent CouchDB requests"""
    client = await get_async_client()

    async def fetch(path):
        return await client.get(f"{COUCHDB_URL}{path}", auth=("admin", "admin"))

    results = await asyncio.gather(
        fetch("/"),
        fetch("/couch-sitter"),
        fetch("/_all_dbs"),
    )
    return {"test": 8, "statuses": [r.status_code for r in results]}

@app.get("/9-file-read")
def test_file_read():
    """Read file from disk"""
    jwks = load_jwks("enabled-hawk-56.clerk.accounts.dev")
    return {"test": 9, "loaded": jwks is not None}

@app.get("/10-env-vars")
def test_env_vars():
    """Access environment variables"""
    return {
        "test": 10,
        "couchdb_url": os.getenv("COUCHDB_INTERNAL_URL", "not set"),
        "clerk_issuer": os.getenv("CLERK_ISSUER_URL", "not set"),
    }

# Proxy endpoint like MyCouch
@app.api_route("/{db_name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_couchdb(db_name: str, path: str, request: Request, authorization: Optional[str] = Header(None)):
    """Full proxy endpoint like MyCouch"""
    print(f"Proxy: {request.method} /{db_name}/{path}")

    # Verify JWT if present
    if authorization and authorization.startswith("Bearer "):
        payload = verify_jwt(authorization[7:])
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid JWT")
        print(f"JWT verified: {payload.get('sub')}")

    # Proxy to CouchDB
    client = await get_async_client()
    url = f"{COUCHDB_URL}/{db_name}/{path}"

    body = None
    if request.method in ["POST", "PUT"]:
        body = await request.body()

    response = await client.request(
        method=request.method,
        url=url,
        content=body,
        auth=("admin", "admin"),
        headers={"Content-Type": request.headers.get("content-type", "application/json")}
    )

    return {"proxied": True, "status": response.status_code, "path": f"/{db_name}/{path}"}

if __name__ == "__main__":
    print("=" * 60)
    print("MyCouch Minimal Test Server")
    print("=" * 60)
    print()
    print("Test endpoints (hit each to find CrowdStrike trigger):")
    print("  /1-basic          - Just JSON, no I/O")
    print("  /2-sync-couchdb   - Sync HTTP to CouchDB")
    print("  /3-async-couchdb  - Async HTTP to CouchDB")
    print("  /4-jwt-only       - JWT verification (needs Auth header)")
    print("  /5-jwt-then-couchdb - JWT + CouchDB (needs Auth header)")
    print("  /6-hash-operation - SHA256 hash")
    print("  /7-couchdb-query  - CouchDB Mango query")
    print("  /8-multiple-couchdb - Multiple concurrent requests")
    print("  /9-file-read      - Read JWKS from disk")
    print("  /10-env-vars      - Environment variables")
    print()
    print("  /{db}/{path}      - Full proxy (like MyCouch)")
    print()
    uvicorn.run(app, host="127.0.0.1", port=5985)  # Same port as MyCouch
