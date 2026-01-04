#!/usr/bin/env python3
"""
Test: FastAPI with actual HTTP proxy route.
Goal: Isolate if proxying requests triggers CrowdStrike.
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

@app.get("/")
async def root():
    return {"status": "ok", "server": "fastapi-proxy-test"}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_to_couchdb(request: Request, path: str):
    """Proxy all requests to CouchDB"""
    if request.method == "OPTIONS":
        return Response(status_code=200)

    # Build CouchDB URL
    url = f"{COUCHDB_URL}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    # Read body
    body = await request.body()

    # Make request to CouchDB
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method=request.method,
            url=url,
            content=body if body else None,
            headers={"Content-Type": "application/json"},
            auth=(COUCHDB_USER, COUCHDB_PASSWORD),
            timeout=30.0
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")}
    )

if __name__ == "__main__":
    print("=" * 60)
    print("  FastAPI with CouchDB proxy route")
    print("  Testing if proxying triggers CrowdStrike")
    print("=" * 60)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5985,
        http="h11",
        ws="none",
    )
