#!/usr/bin/env python3
"""
Test script - run with: uv run python test_with_proxy_uv.py

This tests if 'uv run' is the CrowdStrike trigger.
"""
import uvicorn
import httpx
from fastapi import FastAPI

app = FastAPI()

COUCHDB_URL = "http://localhost:5984"

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/proxy")
def proxy():
    print("Making request to CouchDB...")
    try:
        response = httpx.get(f"{COUCHDB_URL}/", auth=("admin", "admin"), timeout=5.0)
        print(f"CouchDB response: {response.status_code}")
        return {"couchdb_status": response.status_code}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    print("Starting test server via uv run...")
    uvicorn.run(app, host="127.0.0.1", port=5985)
