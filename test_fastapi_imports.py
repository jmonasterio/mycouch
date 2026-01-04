#!/usr/bin/env python3
"""
Test: FastAPI with main.py imports but minimal routes.
Goal: Isolate if CrowdStrike triggers on specific imports.
"""
# === IMPORTS FROM main.py ===
import os
import json
import httpx  # Suspicious? Network library
import jwt    # Suspicious? Crypto library
import logging
import base64
import hashlib
from typing import Optional, Dict, Any, List
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Header, Request, Body
from fastapi.responses import Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

import uvicorn

# Load env
load_dotenv()

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
    return {"status": "ok", "server": "fastapi-with-imports"}

@app.get("/test")
def test():
    return {"test": "passed"}

if __name__ == "__main__":
    print("=" * 60)
    print("  FastAPI with main.py imports (minimal routes)")
    print("  Testing if imports trigger CrowdStrike")
    print("=" * 60)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5985,
        http="h11",
        ws="none",
    )
