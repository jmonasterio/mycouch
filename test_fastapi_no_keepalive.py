#!/usr/bin/env python3
"""
Test: FastAPI with keep-alive DISABLED on both inbound and outbound.

Hypothesis: CrowdStrike detects async socket multiplexing + keep-alive patterns.
Disabling keep-alive makes uvicorn behave more like stdlib http.server.

Key changes:
1. timeout_keep_alive=0 on uvicorn
2. max_keepalive_connections=0 on httpx client
3. Connection: close header on responses
"""
import sys
import os
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

load_dotenv()

COUCHDB_URL = os.getenv("COUCHDB_INTERNAL_URL", "http://localhost:5984")
COUCHDB_USER = os.getenv("COUCHDB_USER", "admin")
COUCHDB_PASSWORD = os.getenv("COUCHDB_PASSWORD", "admin")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4000", "http://localhost:5000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create client with keep-alive DISABLED
# This forces new TCP connection per request (like stdlib http.server)
http_client = httpx.AsyncClient(
    auth=(COUCHDB_USER, COUCHDB_PASSWORD),
    timeout=30.0,
    limits=httpx.Limits(
        max_keepalive_connections=0,  # DISABLE keep-alive pooling
        max_connections=100,
    ),
)


@app.get("/")
async def root():
    return {"status": "ok", "server": "fastapi-no-keepalive"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_to_couchdb(request: Request, path: str):
    """Proxy all requests to CouchDB with keep-alive disabled"""
    if request.method == "OPTIONS":
        return Response(status_code=200, headers={"Connection": "close"})

    # Build CouchDB URL
    url = f"{COUCHDB_URL}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    # Read body
    body = await request.body()

    # Make request to CouchDB (client has keep-alive disabled)
    resp = await http_client.request(
        method=request.method,
        url=url,
        content=body if body else None,
        headers={"Content-Type": "application/json"},
    )

    # Return response with Connection: close header
    # This tells browser not to reuse the connection
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={
            "Content-Type": resp.headers.get("Content-Type", "application/json"),
            "Connection": "close",  # FORCE connection close
        },
    )


@app.on_event("shutdown")
async def shutdown():
    await http_client.aclose()


if __name__ == "__main__":
    print("=" * 60)
    print("  FastAPI with KEEP-ALIVE DISABLED")
    print("  Testing if disabling keep-alive avoids CrowdStrike")
    print("=" * 60)
    print("  Changes from normal uvicorn:")
    print("    - timeout_keep_alive=0 (server)")
    print("    - max_keepalive_connections=0 (httpx client)")
    print("    - Connection: close header (responses)")
    print("=" * 60)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5985,
        http="h11",
        ws="none",
        timeout_keep_alive=0,  # DISABLE keep-alive on inbound connections
    )
