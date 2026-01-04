#!/usr/bin/env python3
"""
Test: FastAPI with proxy using urllib instead of httpx.
Goal: See if stdlib urllib avoids CrowdStrike detection.
"""
import sys
import os
import json
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import HTTPError
import base64

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

def get_auth_header():
    creds = f"{COUCHDB_USER}:{COUCHDB_PASSWORD}"
    return f"Basic {base64.b64encode(creds.encode()).decode()}"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4000", "http://localhost:5000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "server": "fastapi-proxy-urllib"}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_to_couchdb(request: Request, path: str):
    """Proxy all requests to CouchDB using urllib (stdlib)"""
    if request.method == "OPTIONS":
        return Response(status_code=200)

    # Build CouchDB URL
    url = f"{COUCHDB_URL}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    # Read body
    body = await request.body()

    # Make request using urllib (stdlib)
    headers = {
        "Authorization": get_auth_header(),
        "Content-Type": "application/json"
    }

    try:
        req = UrlRequest(
            url,
            data=body if body else None,
            headers=headers,
            method=request.method
        )
        with urlopen(req, timeout=30) as resp:
            content = resp.read()
            status = resp.status
            content_type = resp.headers.get("Content-Type", "application/json")
    except HTTPError as e:
        content = e.read() if e.fp else b'{"error": "proxy error"}'
        status = e.code
        content_type = "application/json"

    return Response(
        content=content,
        status_code=status,
        headers={"Content-Type": content_type}
    )

if __name__ == "__main__":
    print("=" * 60)
    print("  FastAPI with CouchDB proxy (urllib, not httpx)")
    print("  Testing if stdlib avoids CrowdStrike")
    print("=" * 60)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5985,
        http="h11",
        ws="none",
    )
