#!/usr/bin/env python3
"""
Test script to isolate CrowdStrike trigger.

This runs a minimal FastAPI server WITHOUT any CouchDB connections.
If CrowdStrike kills this, the trigger is the listening socket or basic HTTP handling.
If this survives but MyCouch doesn't, the trigger is the CouchDB proxy behavior.

Usage:
    .venv/Scripts/python test_no_couchdb.py
"""
import uvicorn
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok", "message": "No CouchDB connections"}

@app.get("/test")
def test():
    return {"test": "passed", "couchdb": "disabled"}

@app.get("/health")
def health():
    return {"healthy": True}

if __name__ == "__main__":
    print("Starting test server (no CouchDB connections)...")
    print("If this survives, CouchDB proxy behavior is the CrowdStrike trigger.")
    print("If this dies, it's the listening socket or basic HTTP handling.")
    print()
    uvicorn.run(app, host="127.0.0.1", port=5985)
