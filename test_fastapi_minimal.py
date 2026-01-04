#!/usr/bin/env python3
"""
Minimal FastAPI test to isolate CrowdStrike detection.

Test 1: FastAPI + uvicorn with h11/no-ws
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4000", "http://localhost:5000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "server": "fastapi-minimal"}

@app.get("/test")
def test():
    return {"test": "passed"}

if __name__ == "__main__":
    print("=" * 60)
    print("  Minimal FastAPI test")
    print("  Options: http=h11, ws=none")
    print("=" * 60)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5985,
        http="h11",
        ws="none",
    )
