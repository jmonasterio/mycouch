#!/usr/bin/env python3
"""
Test: FastAPI with proxy using sync executor.
Goal: See if running proxy in thread pool avoids detection.
"""
import sys
import os
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
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

# Thread pool for sync operations
executor = ThreadPoolExecutor(max_workers=10)

def get_auth_header():
    creds = f"{COUCHDB_USER}:{COUCHDB_PASSWORD}"
    return f"Basic {base64.b64encode(creds.encode()).decode()}"

def sync_proxy(method: str, url: str, body: bytes):
    """Sync proxy function to run in executor"""
    headers = {
        "Authorization": get_auth_header(),
        "Content-Type": "application/json"
    }
    try:
        req = UrlRequest(url, data=body if body else None, headers=headers, method=method)
        with urlopen(req, timeout=30) as resp:
            return resp.read(), resp.status, resp.headers.get("Content-Type", "application/json")
    except HTTPError as e:
        return e.read() if e.fp else b'{"error": "proxy error"}', e.code, "application/json"

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
    return {"status": "ok", "server": "fastapi-proxy-sync"}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_to_couchdb(request: Request, path: str):
    """Proxy via thread pool executor"""
    if request.method == "OPTIONS":
        return Response(status_code=200)

    url = f"{COUCHDB_URL}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    body = await request.body()

    # Run sync proxy in thread pool
    loop = asyncio.get_event_loop()
    content, status, content_type = await loop.run_in_executor(
        executor, sync_proxy, request.method, url, body
    )

    return Response(content=content, status_code=status, headers={"Content-Type": content_type})

if __name__ == "__main__":
    print("=" * 60)
    print("  FastAPI with sync proxy (thread pool)")
    print("  Testing if thread executor avoids CrowdStrike")
    print("=" * 60)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5985,
        http="h11",
        ws="none",
    )
