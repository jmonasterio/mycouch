#!/usr/bin/env python3
"""
Test: FastAPI with FULL main.py imports including internal modules.
Goal: Isolate if internal module imports trigger CrowdStrike.
"""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# === ALL IMPORTS FROM main.py ===
import json
import httpx
import jwt
import logging
import base64
import hashlib
from typing import Optional, Dict, Any, List
from functools import lru_cache
from jwt import PyJWKClient

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header, Request, Body
from fastapi.responses import Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn
from dotenv import load_dotenv
from urllib.parse import parse_qsl

# === INTERNAL MODULE IMPORTS ===
from couchdb_jwt_proxy.user_tenant_cache import get_cache
from couchdb_jwt_proxy.couch_sitter_service import CouchSitterService, ADMIN_TENANT_ID
from couchdb_jwt_proxy.clerk_service import ClerkService
from couchdb_jwt_proxy.dal import create_dal
from couchdb_jwt_proxy.auth_log_service import AuthLogService
from couchdb_jwt_proxy.invite_service import InviteService
from couchdb_jwt_proxy.tenant_routes import create_tenant_router
from couchdb_jwt_proxy.virtual_tables import VirtualTableHandler, VirtualTableMapper
from couchdb_jwt_proxy.session_service import SessionService
from couchdb_jwt_proxy.cleanup_service import CleanupService
from couchdb_jwt_proxy.bootstrap import BootstrapManager
from couchdb_jwt_proxy.index_bootstrap import IndexBootstrap
from couchdb_jwt_proxy.tenant_service import TenantService
from couchdb_jwt_proxy import auth_middleware

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
    return {"status": "ok", "server": "fastapi-full-imports"}

@app.get("/test")
def test():
    return {"test": "passed"}

if __name__ == "__main__":
    print("=" * 60)
    print("  FastAPI with FULL main.py imports")
    print("  Testing if internal modules trigger CrowdStrike")
    print("=" * 60)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5985,
        http="h11",
        ws="none",
    )
