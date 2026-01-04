#!/usr/bin/env python3
"""
Test script to isolate CrowdStrike trigger - WITH proxy behavior.

This makes HTTP connections to localhost:5984 (CouchDB) when requests come in.
If CrowdStrike kills this, the trigger is the proxy/relay behavior.

Usage:
    .venv/Scripts/python test_with_proxy.py
"""
import uvicorn
import httpx
from fastapi import FastAPI

app = FastAPI()

COUCHDB_URL = "http://localhost:5984"

@app.get("/")
def root():
    return {"status": "ok", "message": "Proxy test server"}

@app.get("/no-proxy")
def no_proxy():
    """No CouchDB connection - should survive"""
    return {"test": "no proxy", "couchdb": "not called"}

@app.get("/proxy")
def proxy():
    """Makes HTTP connection to CouchDB - might trigger CrowdStrike"""
    print("Making request to CouchDB...")
    try:
        response = httpx.get(f"{COUCHDB_URL}/", auth=("admin", "admin"), timeout=5.0)
        print(f"CouchDB response: {response.status_code}")
        return {"test": "proxy", "couchdb_status": response.status_code, "couchdb_response": response.json()}
    except Exception as e:
        print(f"CouchDB error: {e}")
        return {"test": "proxy", "error": str(e)}

@app.get("/proxy-loop")
def proxy_loop():
    """Makes multiple HTTP connections - more likely to trigger"""
    print("Making 5 requests to CouchDB...")
    results = []
    for i in range(5):
        try:
            response = httpx.get(f"{COUCHDB_URL}/", auth=("admin", "admin"), timeout=5.0)
            results.append({"i": i, "status": response.status_code})
            print(f"Request {i}: {response.status_code}")
        except Exception as e:
            results.append({"i": i, "error": str(e)})
            print(f"Request {i} error: {e}")
    return {"test": "proxy-loop", "results": results}

if __name__ == "__main__":
    print("Starting proxy test server...")
    print()
    print("Test endpoints:")
    print("  /no-proxy   - No CouchDB connection (should survive)")
    print("  /proxy      - Single CouchDB connection (might die)")
    print("  /proxy-loop - Multiple CouchDB connections (more likely to die)")
    print()
    uvicorn.run(app, host="127.0.0.1", port=5985)
