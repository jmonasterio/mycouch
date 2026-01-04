#!/usr/bin/env python3
"""
Test: FastAPI with lifespan that makes HTTP calls and background tasks.
Goal: Isolate if startup HTTP calls or background tasks trigger CrowdStrike.
"""
import sys
import os
import asyncio
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

load_dotenv()

COUCHDB_URL = os.getenv("COUCHDB_INTERNAL_URL", "http://localhost:5984")

# Background task simulation
background_task = None

async def periodic_task():
    """Simulate cleanup service background task"""
    while True:
        print("[Background] Running periodic task...")
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global background_task
    print("[Lifespan] Startup - making HTTP call to CouchDB...")

    # Simulate loading apps from database
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{COUCHDB_URL}/")
            print(f"[Lifespan] CouchDB response: {resp.status_code}")
        except Exception as e:
            print(f"[Lifespan] CouchDB error: {e}")

    # Start background task
    print("[Lifespan] Starting background task...")
    background_task = asyncio.create_task(periodic_task())

    yield

    # Shutdown
    print("[Lifespan] Shutdown")
    if background_task:
        background_task.cancel()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4000", "http://localhost:5000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "server": "fastapi-lifespan-test"}

@app.get("/test")
def test():
    return {"test": "passed"}

if __name__ == "__main__":
    print("=" * 60)
    print("  FastAPI with lifespan (HTTP + background task)")
    print("  Testing if startup behavior triggers CrowdStrike")
    print("=" * 60)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5985,
        http="h11",
        ws="none",
    )
