import os
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

# Import user/tenant management modules
from .user_tenant_cache import get_cache
from .couch_sitter_service import CouchSitterService, ADMIN_TENANT_ID
from .clerk_service import ClerkService
from .dal import create_dal
from .auth_log_service import AuthLogService
from .invite_service import InviteService
from .tenant_routes import create_tenant_router
from .virtual_tables import VirtualTableHandler, VirtualTableMapper
from .session_service import SessionService
from .cleanup_service import CleanupService
from .bootstrap import BootstrapManager
from .index_bootstrap import IndexBootstrap
from .tenant_service import TenantService
from . import auth_middleware

# Load environment variables
load_dotenv()

# Configuration
COUCHDB_INTERNAL_URL = os.getenv("COUCHDB_INTERNAL_URL")
COUCHDB_USER = os.getenv("COUCHDB_USER")
COUCHDB_PASSWORD = os.getenv("COUCHDB_PASSWORD")
PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = os.getenv("PROXY_PORT")
LOG_LEVEL = os.getenv("LOG_LEVEL")
COUCH_SITTER_LOG_DB_URL = os.getenv("COUCH_SITTER_LOG_DB_URL")

# Default application configuration (will be loaded from database at startup)
APPLICATIONS: Dict[str, Dict[str, Any]] = {}

# NOTE: DEFAULT_APPLICATIONS has been removed. All application configuration
# must come from the database. Add application documents to the couch-sitter
# database with the following structure:
# {
#   "_id": "app_<issuer>",
#   "type": "application",
#   "issuer": "https://your-clerk-instance.clerk.accounts.dev",
#   "databaseNames": ["roady", "roady-staging", "couch-sitter"],
#   "clerkSecretKey": "sk_...",
#   "createdAt": "...",
#   "updatedAt": "..."
# }

# Clerk configuration (for RS256 JWT validation)
CLERK_ISSUER_URL = os.getenv("CLERK_ISSUER_URL")

# Clerk Backend API configuration (for session metadata management)
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")

# ... (imports and other setup)

# ... (imports and other setup)

# Tenant configuration (always enabled)
TENANT_FIELD = os.getenv("TENANT_FIELD")

# Couch-sitter database configuration for user/tenant management
COUCH_SITTER_DB_URL = os.getenv("COUCH_SITTER_DB_URL")
USER_CACHE_TTL_SECONDS = os.getenv("USER_CACHE_TTL_SECONDS")

# Allowed CouchDB endpoints for PouchDB
# Note: '/' removed because it was matching all document IDs as a prefix
ALLOWED_ENDPOINTS = {
    "/_local/": ["GET", "PUT", "DELETE"],  # PouchDB replication checkpoints
    "/_all_docs": ["GET"],
    "/_all_dbs": ["GET"],  # List all databases
    "/_find": ["POST"],
    "/_bulk_docs": ["POST"],
    "/_changes": ["GET", "POST"],
    "/_revs_diff": ["POST"],
    "/_bulk_get": ["POST"],
    "/_session": ["GET", "POST"],
}

# Validation: Ensure required configuration is set
missing_vars = []

# CLERK_ISSUER_URL is optional - can come from app config in couch-sitter
# if not CLERK_ISSUER_URL:
#     missing_vars.append("CLERK_ISSUER_URL")

if not COUCHDB_INTERNAL_URL:
    missing_vars.append("COUCHDB_INTERNAL_URL")

if not COUCHDB_USER:
    missing_vars.append("COUCHDB_USER")

if not COUCHDB_PASSWORD:
    missing_vars.append("COUCHDB_PASSWORD")

if not PROXY_HOST:
    missing_vars.append("PROXY_HOST")

if not PROXY_PORT:
    missing_vars.append("PROXY_PORT")

if not LOG_LEVEL:
    missing_vars.append("LOG_LEVEL")

# CLERK_SECRET_KEY is now optional - comes from app config in couch-sitter
# if not CLERK_SECRET_KEY:
#     missing_vars.append("CLERK_SECRET_KEY")

if not TENANT_FIELD:
    missing_vars.append("TENANT_FIELD")

if not COUCH_SITTER_DB_URL:
    missing_vars.append("COUCH_SITTER_DB_URL")

if not USER_CACHE_TTL_SECONDS:
    missing_vars.append("USER_CACHE_TTL_SECONDS")

if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}. Configure these in your .env file.")

# Convert string variables to proper types after validation
try:
    PROXY_PORT = int(PROXY_PORT)
except ValueError:
    raise ValueError("PROXY_PORT must be a valid integer. Configure this in your .env file.")

try:
    USER_CACHE_TTL_SECONDS = int(USER_CACHE_TTL_SECONDS)
except ValueError:
    raise ValueError("USER_CACHE_TTL_SECONDS must be a valid integer. Configure this in your .env file.")

# Clean up URLs after validation
if CLERK_ISSUER_URL:
    CLERK_ISSUER_URL = CLERK_ISSUER_URL.rstrip("/")
    CLERK_JWKS_URL = f"{CLERK_ISSUER_URL}/.well-known/jwks.json"
else:
    CLERK_JWKS_URL = None

COUCH_SITTER_DB_URL = COUCH_SITTER_DB_URL.rstrip("/")

# Setup logging with timing
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(relativeCreated)5dms %(name)s:%(levelname)s:%(message)s'
)
logger = logging.getLogger(__name__)

# Reduce httpx logging verbosity
logging.getLogger("httpx").setLevel(logging.WARNING)

# Initialize DAL
dal = create_dal(
    base_url=COUCHDB_INTERNAL_URL,
    username=COUCHDB_USER,
    password=COUCHDB_PASSWORD
)

# Initialize user/tenant management
user_cache = get_cache()
couch_sitter_service = CouchSitterService(
    couch_sitter_db_url=COUCH_SITTER_DB_URL,
    couchdb_user=COUCHDB_USER,
    couchdb_password=COUCHDB_PASSWORD,
    dal=dal
)

# Initialize Invitation Service
invite_service = InviteService(
    couch_sitter_db_url=COUCH_SITTER_DB_URL,
    couchdb_user=COUCHDB_USER,
    couchdb_password=COUCHDB_PASSWORD,
    dal=dal
)

# Initialize Clerk Backend API service
clerk_service = ClerkService(
    secret_key=CLERK_SECRET_KEY,
    issuer_url=CLERK_ISSUER_URL
)

# Set clerk_service for auth_middleware
auth_middleware.set_clerk_service(clerk_service)

# Initialize Session Service (for per-device/per-session tenant mapping)
session_service = SessionService(dal)
logger.info("✓ Initialized session service")

# Initialize Cleanup Service (for periodic cleanup of expired sessions)
cleanup_service = CleanupService(dal, cleanup_interval_hours=24)
logger.info("✓ Initialized cleanup service")

# Initialize Virtual Tables and Bootstrap managers
virtual_table_handler = VirtualTableHandler(dal, clerk_service, APPLICATIONS, session_service)
bootstrap_manager = BootstrapManager(dal)
logger.info("✓ Initialized virtual tables and bootstrap managers")

# Initialize Auth Log Service (optional - only if log database URL is configured)
auth_log_service = None
if COUCH_SITTER_LOG_DB_URL:
    auth_log_service = AuthLogService(
        log_db_url=COUCH_SITTER_LOG_DB_URL,
        couchdb_user=COUCHDB_USER,
        couchdb_password=COUCHDB_PASSWORD
    )
    logger.info(f"Initialized AuthLogService for: {COUCH_SITTER_LOG_DB_URL}")
    # Note: Database will be created automatically on first log write
else:
    logger.warning("COUCH_SITTER_LOG_DB_URL not configured - auth logging disabled")

logger.info(f"Initialized user cache (TTL: {USER_CACHE_TTL_SECONDS}s)")
logger.info(f"Initialized CouchSitter service for: {COUCH_SITTER_DB_URL}")
if clerk_service.is_configured():
    logger.info("Initialized Clerk Backend API service")
else:
    logger.warning("Clerk Backend API service not configured - session metadata features disabled")

# JWT Functions
def get_token_preview(token: str) -> str:
    """Get safe preview of token for logging (first and last 10 chars)"""
    if len(token) < 20:
        return "token_too_short"
    return f"{token[:10]}...{token[-10:]}"

def get_basic_auth_header() -> Optional[str]:
    """Create Basic Auth header for CouchDB"""
    if COUCHDB_USER and COUCHDB_PASSWORD:
        credentials = base64.b64encode(f"{COUCHDB_USER}:{COUCHDB_PASSWORD}".encode()).decode()
        return f"Basic {credentials}"
    return None

def decode_token_unsafe(token: str) -> Optional[Dict[str, Any]]:
    """Decode token without verification for debugging (only in logs)"""
    try:
        # Decode without verification to see what's in it
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload
    except Exception:
        return None

# Clerk JWT validation (RS256)
@lru_cache(maxsize=10)
def get_clerk_jwks_client(issuer: str) -> Optional[PyJWKClient]:
    """Get cached JWKS client for Clerk token validation"""
    if not issuer:
        return None
        
    jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
    
    try:
        client = PyJWKClient(jwks_url, cache_keys=True)
        logger.info(f"Clerk JWKS client initialized: {jwks_url}")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Clerk JWKS client for {issuer}: {e}")
        return None

def verify_clerk_jwt(token: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Verify Clerk JWT token (RS256). Returns (payload, error_reason)
    
    Note: Set SKIP_JWT_EXPIRATION_CHECK=true in .env to skip expiration validation (dev/testing only)
    """
    try:
        # 1. Extract issuer from unverified token
        unverified_payload = decode_token_unsafe(token)
        if not unverified_payload:
             logger.error(f"JWT verification failed: invalid_token_format")
             return None, "invalid_token_format"
             
        issuer = unverified_payload.get("iss")
        if not issuer:
            logger.error(f"JWT verification failed: missing_issuer_claim")
            return None, "missing_issuer_claim"
            
        # 2. Validate issuer is registered
        # Note: APPLICATIONS keys are issuers
        logger.debug(f"JWT issuer: {issuer}")
        logger.debug(f"Registered applications: {list(APPLICATIONS.keys())}")
        
        if issuer not in APPLICATIONS:
             logger.warning(f"JWT verification FAILED - Unknown issuer: {issuer}")
             logger.warning(f"  Registered issuers: {list(APPLICATIONS.keys())}")
             logger.warning(f"  Sub in token: {unverified_payload.get('sub')}")
             return None, "unknown_issuer"

        # 3. Get JWKS client for this issuer
        jwks_client = get_clerk_jwks_client(issuer)
        if not jwks_client:
            logger.error(f"JWKS client unavailable for issuer: {issuer}")
            return None, "clerk_jwks_unavailable"

        logger.debug(f"Attempting to validate JWT with JWKS from issuer: {issuer}")

        # Get signing key
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Verify token with Clerk's public key
        # Check if expiration validation should be skipped (for dev/testing)
        skip_exp_check = os.getenv("SKIP_JWT_EXPIRATION_CHECK", "false").lower() == "true"
        
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=None,  # Clerk JWTs don't have audience claim by default
            issuer=issuer,  # Verify issuer matches
            options={
                "verify_aud": False,
                "verify_iss": True,
                "verify_exp": not skip_exp_check,  # Skip expiration check if configured
                "leeway": 300  # Allow 5 minutes of clock skew (increased from 60s to handle larger drifts)
            }
        )
        
        if skip_exp_check:
            logger.warning("⚠️ JWT expiration check DISABLED - development/testing mode only")

        logger.debug(f"Clerk JWT validated successfully")
        return payload, None

    except jwt.ExpiredSignatureError as e:
        # Log timing details for debugging
        try:
            import time
            unverified = decode_token_unsafe(token)
            if unverified:
                exp = unverified.get('exp', 'N/A')
                iat = unverified.get('iat', 'N/A')
                nbf = unverified.get('nbf', 'N/A')
                now = int(time.time())
                logger.warning(f"JWT token expired. Now: {now}, IAT: {iat}, NBF: {nbf}, EXP: {exp}")
                if isinstance(exp, int):
                    logger.warning(f"Token expired {now - exp} seconds ago")
        except Exception:
            pass
        logger.warning(f"JWT token has expired: {e}")
        return None, "clerk_token_expired"
    except jwt.ImmatureSignatureError as e:
        # Log timing details for debugging
        try:
            import time
            unverified = decode_token_unsafe(token)
            if unverified:
                nbf = unverified.get('nbf', 'N/A')
                iat = unverified.get('iat', 'N/A')
                now = int(time.time())
                logger.warning(f"JWT not valid yet (ImmatureSignatureError). Now: {now}, IAT: {iat}, NBF: {nbf}")
                if isinstance(nbf, int):
                    logger.warning(f"Token will be valid in {nbf - now} seconds")
                    logger.warning(f"This indicates a {nbf - now}s clock skew between client and server")
        except Exception:
            pass
        logger.warning(f"JWT token not yet valid (ImmatureSignatureError): {e}")
        return None, f"clerk_invalid_token (ImmatureSignatureError)"
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {type(e).__name__} - {e}")
        return None, f"clerk_invalid_token ({type(e).__name__})"
    except Exception as e:
        logger.error(f"JWT validation error: {type(e).__name__} - {e}")
        logger.error(f"JWKS URL: {CLERK_JWKS_URL}")
        return None, f"clerk_token_error ({type(e).__name__})"

def is_couch_sitter_app(payload: Dict[str, Any], request_path: str = None) -> bool:
    """
    Check if this request is for the couch-sitter application.
    
    Args:
        payload: JWT payload dictionary
        request_path: The request path (optional, for fallback path check)
        
    Returns:
        True if couch-sitter app, False if multi-tenant app
    """
    issuer = payload.get("iss", "")
    
    # Check issuer against registered applications (primary check)
    if issuer in APPLICATIONS:
        app_config = APPLICATIONS[issuer]
        dbs = []
        if isinstance(app_config, dict):
            dbs = app_config.get("databaseNames", [])
        elif isinstance(app_config, list):
            dbs = app_config
        return "couch-sitter" in dbs
    
    # Fallback: check request path if issuer not registered
    if request_path and ("couch-sitter" in request_path.lower() or "couch_sitter" in request_path.lower()):
        return True
    
    return False

async def extract_tenant(payload: Dict[str, Any], request_path: str = None) -> str:
    """
    Extract tenant ID from JWT payload with 5-level lookup chain.

    This function implements automatic tenant discovery with multi-level fallback:
    - Level 1: Session cache (fastest)
    - Level 2: User document default
    - Level 3: First user-owned tenant
    - Level 4: Create new tenant (if user has none)
    - Level 5: Error (shouldn't reach here)

    For couch-sitter requests: Uses personal tenant (existing behavior)
    For multi-tenant requests: Uses 5-level discovery chain

    Args:
        payload: JWT payload dictionary
        request_path: The request path (optional, for database name extraction)

    Returns:
        Tenant ID string (without prefix)
    """
    import hashlib

    # Get the subject (sub) claim from the JWT
    sub = payload.get("sub")
    if not sub:
        logger.error("Missing 'sub' claim in JWT - cannot determine tenant")
        raise ValueError("Missing 'sub' claim in JWT")

    # Hash the sub for internal use
    sub_hash = hashlib.sha256(sub.encode('utf-8')).hexdigest()

    # Determine if this is a couch-sitter request (special case)
    is_couch_sitter_request = is_couch_sitter_app(payload, request_path)

    logger.debug(f"[EXTRACT_TENANT] Application: {'couch-sitter' if is_couch_sitter_request else 'multi-tenant'}")

    # For couch-sitter, use existing personal tenant behavior
    if is_couch_sitter_request:
        logger.debug(f"[EXTRACT_TENANT] Level 0: couch-sitter request, using personal tenant")
        
        # Try cache first
        cached_info = user_cache.get_user_by_sub_hash(sub_hash)
        if cached_info:
            return cached_info.tenant_id

        # Cache miss - fetch from couch-sitter database
        requested_db_name = "couch-sitter"
        if request_path:
            parts = request_path.strip('/').split('/')
            if parts:
                requested_db_name = parts[0]

        try:
            user_tenant_info = await couch_sitter_service.get_user_tenant_info(
                sub=sub,
                email=payload.get("email"),
                name=payload.get("name") or payload.get("given_name"),
                requested_db_name=requested_db_name
            )
            user_cache.set_user(sub_hash, user_tenant_info)
            logger.info(f"[EXTRACT_TENANT] Retrieved personal tenant: {user_tenant_info.tenant_id}")
            return user_tenant_info.tenant_id
        except Exception as e:
            logger.error(f"[EXTRACT_TENANT] Failed to get personal tenant: {e}")
            raise

    # ============================================================================
    # MULTI-TENANT REQUEST - 5-LEVEL DISCOVERY CHAIN
    # ============================================================================
    logger.debug(f"[EXTRACT_TENANT] Multi-tenant request - starting 5-level discovery")

    sid = payload.get("sid")
    app_id = payload.get("iss")  # Clerk issuer (app identifier)
    user_name = payload.get("name") or payload.get("given_name")

    # ============================================================================
    # LEVEL 1: Session cache (per-device tenant)
    # ============================================================================
    if sid and session_service:
        try:
            logger.debug(f"[EXTRACT_TENANT] Level 1: Checking session cache for sid={sid}")
            active_tenant_id = await session_service.get_active_tenant(sid)
            if active_tenant_id:
                logger.info(f"[EXTRACT_TENANT] ✅ Level 1 HIT: Found session tenant: {active_tenant_id}")
                return active_tenant_id
        except Exception as e:
            logger.warning(f"[EXTRACT_TENANT] Level 1 failed: {e}")

    logger.debug(f"[EXTRACT_TENANT] Level 1 miss - falling through")

    # ============================================================================
    # LEVEL 2: User document default
    # ============================================================================
    try:
        logger.debug(f"[EXTRACT_TENANT] Level 2: Checking user doc for default tenant")
        user_doc_id = f"user_{sub_hash}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{COUCHDB_INTERNAL_URL}/couch-sitter/{user_doc_id}",
                auth=(COUCHDB_USER, COUCHDB_PASSWORD),
            )

            if response.status_code == 200:
                user_doc = response.json()
                user_default = user_doc.get("active_tenant_id")
                
                if user_default:
                    logger.info(f"[EXTRACT_TENANT] ✅ Level 2 HIT: Found user default: {user_default}")
                    
                    # Create/update session with this default
                    if sid and session_service:
                        try:
                            await session_service.create_session(sid, sub_hash, user_default, app_id)
                            logger.debug(f"[EXTRACT_TENANT] Cached session {sid} with tenant {user_default}")
                        except Exception as e:
                            logger.warning(f"[EXTRACT_TENANT] Failed to create session: {e}")
                    
                    return user_default

                logger.debug(f"[EXTRACT_TENANT] Level 2 miss - user doc has no active_tenant_id")
    except Exception as e:
        logger.warning(f"[EXTRACT_TENANT] Level 2 failed: {e}")

    # ============================================================================
    # LEVEL 3: Query first user-owned tenant
    # ============================================================================
    try:
        logger.debug(f"[EXTRACT_TENANT] Level 3: Querying user's tenants")
        if not hasattr(extract_tenant, '_tenant_service'):
            extract_tenant._tenant_service = TenantService(
                COUCHDB_INTERNAL_URL,
                COUCHDB_USER,
                COUCHDB_PASSWORD
            )
        
        tenant_service = extract_tenant._tenant_service
        tenants = await tenant_service.query_user_tenants(sub_hash, database="roady")
        
        if tenants:
            first_tenant = tenants[0]
            tenant_id = first_tenant["_id"].replace("tenant_", "")  # Remove prefix for virtual ID
            
            logger.info(f"[EXTRACT_TENANT] ✅ Level 3 HIT: Found existing tenant: {tenant_id}")
            
            # Update user default and create session
            try:
                await tenant_service.set_user_default_tenant(sub_hash, tenant_id, database="couch-sitter")
                logger.debug(f"[EXTRACT_TENANT] Set user default to {tenant_id}")
            except Exception as e:
                logger.warning(f"[EXTRACT_TENANT] Failed to set user default: {e}")
            
            if sid and session_service:
                try:
                    await session_service.create_session(sid, sub_hash, tenant_id, app_id)
                except Exception as e:
                    logger.warning(f"[EXTRACT_TENANT] Failed to create session: {e}")
            
            return tenant_id
        
        logger.debug(f"[EXTRACT_TENANT] Level 3 miss - user has no tenants")
    except Exception as e:
        logger.warning(f"[EXTRACT_TENANT] Level 3 failed: {e}")

    # ============================================================================
    # LEVEL 4: Create new tenant for user
    # ============================================================================
    try:
        logger.debug(f"[EXTRACT_TENANT] Level 4: Creating new tenant for user")
        if not hasattr(extract_tenant, '_tenant_service'):
            extract_tenant._tenant_service = TenantService(
                COUCHDB_INTERNAL_URL,
                COUCHDB_USER,
                COUCHDB_PASSWORD
            )
        
        tenant_service = extract_tenant._tenant_service
        
        # Create tenant
        result = await tenant_service.create_tenant(
            sub_hash,
            user_name=user_name,
            database="roady"
        )
        tenant_id = result["tenant_id"]
        
        logger.info(f"[EXTRACT_TENANT] ✅ Level 4: Created new tenant: {tenant_id}")
        
        # Set as user default
        try:
            await tenant_service.set_user_default_tenant(sub_hash, tenant_id, database="couch-sitter")
            logger.debug(f"[EXTRACT_TENANT] Set user default to newly created tenant {tenant_id}")
        except Exception as e:
            logger.warning(f"[EXTRACT_TENANT] Failed to set user default: {e}")
        
        # Create session
        if sid and session_service:
            try:
                await session_service.create_session(sid, sub_hash, tenant_id, app_id)
            except Exception as e:
                logger.warning(f"[EXTRACT_TENANT] Failed to create session: {e}")
        
        return tenant_id
    except Exception as e:
        logger.error(f"[EXTRACT_TENANT] Level 4 failed: {e}")

    # ============================================================================
    # LEVEL 5: Error (all levels exhausted)
    # ============================================================================
    logger.error(f"[EXTRACT_TENANT] ❌ All levels exhausted - cannot determine tenant for {sub}")
    raise HTTPException(
        status_code=500,
        detail="Unable to determine or create tenant. Please contact support."
    )

def is_system_doc(doc_id: str) -> bool:
    """Check if document ID is a system document"""
    return doc_id.startswith("_")

def is_endpoint_allowed(path: str, method: str) -> bool:
    """Check if endpoint is allowed (tenant mode always enabled)"""
    logger.debug(f"🔍 Checking endpoint: path='{path}', method='{method}'")

    # Log all allowed endpoints for debugging
    logger.debug(f"📋 Available endpoints: {list(ALLOWED_ENDPOINTS.keys())}")

    # Special case for _local documents (PouchDB replication)
    # Explicitly handle _local paths to ensure they are not blocked by system doc checks
    # if prefix matching fails for some reason.
    if path.startswith("_local/") or path.startswith("/_local/") or path == "_local" or path == "/_local":
        is_allowed = method in ["GET", "PUT", "DELETE"]
        logger.debug(f"✅ Special _local check: path='{path}', method='{method}' = {is_allowed}")
        return is_allowed

    # Check exact endpoint match (handle both with and without leading slash)
    path_to_check = path if path.startswith('/') else f"/{path}"
    if path_to_check in ALLOWED_ENDPOINTS:
        allowed_methods = ALLOWED_ENDPOINTS[path_to_check]
        is_allowed = method in allowed_methods
        logger.debug(f"✅ Exact match: path='{path}' (as '{path_to_check}') matches allowed endpoint, method='{method}' in {allowed_methods} = {is_allowed}")
        return is_allowed
    elif path in ALLOWED_ENDPOINTS:  # Also check original path in case it already has slash
        allowed_methods = ALLOWED_ENDPOINTS[path]
        is_allowed = method in allowed_methods
        logger.debug(f"✅ Exact match: path='{path}' matches allowed endpoint, method='{method}' in {allowed_methods} = {is_allowed}")
        return is_allowed

    # Check prefix patterns for design documents and views
    # Sort endpoints by length (longest first) to ensure more specific paths match first
    sorted_endpoints = sorted(ALLOWED_ENDPOINTS.items(), key=lambda x: len(x[0]), reverse=True)
    for allowed_path, allowed_methods in sorted_endpoints:
        if allowed_path.endswith("/"):
            # Handle both cases: path might or might not start with '/'
            path_to_check = path if path.startswith('/') else f"/{path}"
            logger.debug(f"🔍 Checking prefix: allowed_path='{allowed_path}', original_path='{path}', path_to_check='{path_to_check}', starts_with={path_to_check.startswith(allowed_path)}")
            if path_to_check.startswith(allowed_path):
                is_allowed = method in allowed_methods
                logger.debug(f"✅ Prefix match: path='{path}' starts with allowed_path='{allowed_path}', method='{method}' in {allowed_methods} = {is_allowed}")
                return is_allowed
            else:
                logger.debug(f"❌ Prefix check: path='{path}' does NOT start with allowed_path='{allowed_path}'")

    logger.debug(f"🔍 No exact or prefix match found for path='{path}', checking other patterns...")

    # Check if it's a document endpoint (single document operations)
    # Allowed: GET /docid, PUT /docid, DELETE /docid, POST /docid
    if method in ["GET", "PUT", "DELETE", "POST", "HEAD", "COPY"] and "/" not in path.lstrip("/"):
        doc_id = path.lstrip("/")
        if not doc_id:  # Empty path - database info request
            # Allow GET for database info, block other methods
            return method == "GET"
        return not is_system_doc(doc_id)

    # Document revision endpoint: /docid?rev=...
    if method in ["GET", "DELETE"] and "?" in path:
        doc_id = path.split("?")[0].lstrip("/")
        if not doc_id:
            return False
        return not is_system_doc(doc_id)

    # Bulk operations on multiple documents: /_bulk_get
    if path == "_bulk_get" and method == "POST":
        return True

    # Attachment operations: /docid/attachmentname
    # But exclude system documents like _local/* which should have been handled by prefix matching
    if method in ["GET", "PUT", "DELETE", "HEAD"] and "/" in path:
        parts = path.split("/", 1)
        if len(parts) == 2:
            doc_id, attachment_part = parts
            logger.debug(f"🔎 Attachment check: doc_id='{doc_id}', is_system={is_system_doc(doc_id)}, attachment_part='{attachment_part}'")
            if doc_id and not is_system_doc(doc_id) and attachment_part:
                logger.debug(f"✅ Attachment allowed: {method} /{path}")
                return True
            else:
                logger.debug(f"❌ Attachment denied: doc_id is system doc or missing parts")

    logger.warning(f"🚫 ENDPOINT DENIED: No pattern matched for {method} '{path}'")
    logger.warning(f"📋 Summary check:")
    logger.warning(f"  - Exact path match: {path in ALLOWED_ENDPOINTS}")
    logger.warning(f"  - Prefix match: {any(path.startswith(p) for p in ALLOWED_ENDPOINTS.keys() if p.endswith('/'))}")
    logger.warning(f"  - Document endpoint: {method in ['GET', 'PUT', 'DELETE', 'POST', 'HEAD', 'COPY'] and '/' not in path.lstrip('/')}")
    logger.warning(f"  - Query endpoint: {method in ['GET', 'DELETE'] and '?' in path}")
    logger.warning(f"  - Attachment endpoint: {method in ['GET', 'PUT', 'DELETE', 'HEAD'] and '/' in path}")
    return False

def filter_document_for_tenant(doc: Dict[str, Any], tenant_id: str) -> Optional[Dict[str, Any]]:
    """Validate document for tenant access (tenant mode always enabled)"""
    doc_tenant = doc.get(TENANT_FIELD)
    if doc_tenant != tenant_id:
        logger.warning(f"Access denied: document tenant '{doc_tenant}' does not match '{tenant_id}'")
        return None
    return doc

def inject_tenant_into_doc(doc: Dict[str, Any], tenant_id: str, is_multi_tenant_app: bool = False) -> Dict[str, Any]:
     """
     Inject tenant ID into document (conditional based on application type).

     For multi-tenant apps: Always inject tenant ID
     For couch-sitter: Never inject tenant ID (simple behavior)
     """
     if is_multi_tenant_app:
         doc[TENANT_FIELD] = tenant_id
         logger.debug(f"Injected tenant ID into document for multi-tenant app: {tenant_id}")
     else:
         logger.debug(f"Skipping tenant injection for couch-sitter app")
     return doc

def rewrite_all_docs_query(query_params: str, tenant_id: str, is_multi_tenant_app: bool = False) -> str:
    """
    Rewrite _all_docs query to filter by tenant (conditional based on application type).

    For multi-tenant apps: Filter by tenant
    For couch-sitter: No tenant filtering
    """
    if not is_multi_tenant_app:
        logger.debug(f"Skipping tenant filtering for couch-sitter _all_docs query")
        return query_params or ""

    logger.debug(f"Adding tenant filtering for multi-tenant _all_docs query: {tenant_id}")
    # Add start/end keys for tenant filtering
    if query_params:
        return f"{query_params}&start_key=\"{tenant_id}:\"&end_key=\"{tenant_id}:\ufff0\""
    else:
        return f"start_key=\"{tenant_id}:\"&end_key=\"{tenant_id}:\ufff0\""

def rewrite_find_query(body: Dict[str, Any], tenant_id: str, is_multi_tenant_app: bool = False) -> Dict[str, Any]:
    """
    Rewrite _find query to inject tenant filter (conditional based on application type).

    For multi-tenant apps: Filter by tenant
    For couch-sitter: No tenant filtering
    """
    if not is_multi_tenant_app:
        logger.debug(f"Skipping tenant filtering for couch-sitter _find query")
        return body

    logger.debug(f"Adding tenant filtering for multi-tenant _find query: {tenant_id}")
    # Inject tenant into selector
    if "selector" not in body:
        body["selector"] = {}

    body["selector"][TENANT_FIELD] = tenant_id
    logger.debug(f"Rewrote _find query with tenant filter: {TENANT_FIELD}={tenant_id}")
    return body

def rewrite_bulk_docs(body: Dict[str, Any], tenant_id: str, is_multi_tenant_app: bool = False) -> Dict[str, Any]:
    """
    Inject tenant into bulk docs (conditional based on application type).

    For multi-tenant apps: Always inject tenant ID
    For couch-sitter: Never inject tenant ID
    """
    if "docs" in body:
        for doc in body["docs"]:
            if is_multi_tenant_app:
                # Always inject tenant ID (override any existing value)
                doc[TENANT_FIELD] = tenant_id

        if is_multi_tenant_app:
            logger.debug(f"Injected tenant into {len(body.get('docs', []))} documents for multi-tenant app")
        else:
            logger.debug(f"Skipping tenant injection for {len(body.get('docs', []))} documents for couch-sitter app")
    return body

def filter_response_documents(content: bytes, tenant_id: str) -> bytes:
    """Filter response to remove non-tenant documents (tenant mode always enabled)"""
    try:
        response = json.loads(content)

        # Filter rows in _all_docs response
        if "rows" in response:
            filtered_rows = []
            for row in response.get("rows", []):
                if "doc" in row:
                    doc = row["doc"]
                    if filter_document_for_tenant(doc, tenant_id):
                        filtered_rows.append(row)
                else:
                    # For responses without embedded docs, check value
                    if row.get("value", {}).get(TENANT_FIELD) == tenant_id:
                        filtered_rows.append(row)

            response["rows"] = filtered_rows
            response["total_rows"] = len(filtered_rows)

        # Filter results in _find response
        if "docs" in response:
            filtered_docs = []
            for doc in response.get("docs", []):
                if filter_document_for_tenant(doc, tenant_id):
                    filtered_docs.append(doc)

            response["docs"] = filtered_docs

        return json.dumps(response).encode()
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Could not filter response: {e}")
        return content

def filter_changes_response(content: bytes, tenant_id: str) -> bytes:
    """Filter _changes response to remove non-tenant documents (tenant mode always enabled)"""
    try:
        response = json.loads(content)

        # Filter results in _changes response
        if "results" in response:
            filtered_results = []
            for change in response.get("results", []):
                # Check if the change has document data
                if "doc" in change:
                    doc = change["doc"]
                    if filter_document_for_tenant(doc, tenant_id):
                        filtered_results.append(change)
                else:
                    # For changes without doc (deleted docs), include if tenant matches
                    # For deleted docs, we need to check the doc_id pattern
                    doc_id = change.get("id", "")
                    if doc_id.startswith(f"{tenant_id}:") or not doc_id:
                        filtered_results.append(change)

            response["results"] = filtered_results
            # Note: CouchDB _changes doesn't have total_rows, but we could add last_seq filtering if needed

        return json.dumps(response).encode()
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Could not filter _changes response: {e}")
        return content

async def proxy_to_couchdb_direct(request: Request, path: str):
    """Proxy request directly to CouchDB without JWT validation (for public endpoints)"""
    # Build CouchDB URL
    couchdb_url = f"{COUCHDB_INTERNAL_URL}/{path}" if path else COUCHDB_INTERNAL_URL
    query_string = str(request.url.query) if request.url.query else ""

    if query_string:
        couchdb_url += f"?{query_string}"

    # Get request body if present
    body = None
    if request.method in ["POST", "PUT", "PATCH"]:
        body = await request.body()

    # Forward request to CouchDB
    try:
        async with httpx.AsyncClient() as client:
            # Copy headers, excluding host
            headers = {}
            for key, value in request.headers.items():
                if key.lower() not in ["host"]:
                    headers[key] = value

            # Add CouchDB authentication if configured
            basic_auth = get_basic_auth_header()
            if basic_auth:
                headers["Authorization"] = basic_auth

            logger.debug(f"Direct proxy: {request.method} /{path} -> {couchdb_url}")

            response = await client.request(
                method=request.method,
                url=couchdb_url,
                headers=headers,
                content=body,
                follow_redirects=True,
                timeout=30.0
            )

            logger.debug(f"CouchDB response: {response.status_code} for {request.method} /{path}")

            # Return response from CouchDB
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type")
            )

    except httpx.ConnectError as e:
        logger.error(f"Failed to connect to CouchDB: {e}")
        raise HTTPException(status_code=503, detail="CouchDB server unavailable")
    except Exception as e:
        import traceback
        logger.error(f"Direct proxy error for {request.method} /{path}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application"""
    # Startup
    logger.info(f"Starting CouchDB JWT Proxy on {PROXY_HOST}:{PROXY_PORT}")
    logger.info(f"Proxying to CouchDB at {COUCHDB_INTERNAL_URL}")

    # Initialize applications from database
    await initialize_applications()

    # CouchDB credentials
    if COUCHDB_USER:
        logger.info(f"✓ CouchDB authentication enabled (user: {COUCHDB_USER})")
    else:
        logger.warning(f"⚠ No CouchDB credentials configured")

    # JWT configuration
    logger.info(f"✓ Clerk JWT validation ENABLED")
    logger.info(f"  Clerk issuer: {CLERK_ISSUER_URL}")
    logger.info(f"  JWKS URL: {CLERK_JWKS_URL}")

    # Tenant mode (always enabled)
    logger.info(f"✓ Tenant mode ENABLED (always)")
    logger.info(f"  Tenant field: {TENANT_FIELD}")

    logger.info(f"Logging level: {LOG_LEVEL}")

    # Start periodic cleanup service
    logger.info(f"Starting periodic cleanup service (interval: 24 hours)")
    cleanup_service.start_periodic_cleanup()

    yield

    # Shutdown
    logger.info("Shutting down CouchDB JWT Proxy")
    await cleanup_service.stop_periodic_cleanup()
    logger.info("Cleanup service stopped")

# Rate Limiting (CWE-770: No Rate Limiting on Auth Endpoints)
limiter = Limiter(key_func=get_remote_address)

# FastAPI Application
app = FastAPI(
    title="CouchDB JWT Proxy",
    description="HTTP proxy for CouchDB with JWT authentication",
    version="1.0.0",
    lifespan=lifespan
)

# Add rate limiter to app state for middleware
app.state.limiter = limiter

# Startup event to ensure log database exists
@app.on_event("startup")
async def startup_event():
    """Ensure auth log database exists and indexes are created on startup"""
    logger.info("[Startup] Starting up...")
    
    # Bootstrap indexes on all databases
    try:
        index_bootstrap = IndexBootstrap(
            couchdb_url=COUCHDB_INTERNAL_URL,
            username=COUCHDB_USER,
            password=COUCHDB_PASSWORD
        )
        await index_bootstrap.bootstrap_all()
    except Exception as e:
        logger.error(f"[Startup] Error bootstrapping indexes: {e}", exc_info=True)
    
    # Ensure auth log database exists
    if auth_log_service:
        logger.info(f"[Startup] Ensuring auth log database exists at: {COUCH_SITTER_LOG_DB_URL}")
        try:
            success = await auth_log_service.ensure_database_exists()
            if success:
                logger.info("[Startup] Auth log database ready")
            else:
                logger.error("[Startup] Failed to create or verify auth log database - logging may not work")
        except Exception as e:
            logger.error(f"[Startup] Exception while ensuring database: {e}", exc_info=True)
    else:
        logger.info("[Startup] Auth log service not configured")

# Add CORS middleware (before tenant router registration to ensure proper middleware ordering)
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:4000").split(",")
cors_origins = [origin.strip() for origin in cors_origins]  # Clean up whitespace

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,  # Specific origins instead of wildcard (required when allow_credentials=True)
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "HEAD", "COPY", "PATCH", "OPTIONS"],
    allow_headers=["accept", "authorization", "content-type", "origin", "x-csrf-token"],
)

# Add rate limit error handler
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors"""
    logger.warning(f"Rate limit exceeded for {request.client.host}: {exc.detail}")
    return Response(
        content=json.dumps({
            "detail": "Too many requests. Please try again later.",
            "error": "rate_limit_exceeded"
        }),
        status_code=429,
        media_type="application/json"
    )

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"Incoming request: {request.method} {request.url}", flush=True)
    try:
        response = await call_next(request)
        print(f"Response status: {response.status_code}", flush=True)
        return response
    except Exception as e:
        print(f"Request failed: {e}", flush=True)
        raise

async def initialize_applications():
    """Initialize applications from database - fail if database is not accessible"""
    global APPLICATIONS

    logger.info("🚀 Initializing applications from database...")

    try:
        # Load all applications from database
        APPLICATIONS = await couch_sitter_service.load_all_apps()
        logger.info(f"✅ Loaded {len(APPLICATIONS) if APPLICATIONS else 0} applications from database")

        if not APPLICATIONS:
            logger.error("❌ No applications found in database!")
            logger.error("   You need to create an application document in the couch-sitter database")
            logger.error("   Format: {_id: 'app_<issuer>', type: 'application', issuer: '...', databaseNames: ['roady', 'couch-sitter'], clerkSecretKey: 'sk_...'}")
            raise RuntimeError("No applications configured in database. Please add application documents to the couch-sitter database.")

        logger.info(f"📋 Registered application issuers:")
        for issuer, app_config in APPLICATIONS.items():
            logger.info(f"   - {issuer}")
            logger.info(f"     Databases: {app_config.get('databaseNames', [])}")
            has_secret = "✓" if app_config.get('clerkSecretKey') else "✗"
            logger.info(f"     Secret key: {has_secret}")

    except Exception as e:
        logger.error(f"Failed to initialize applications from database: {e}")
        logger.error("Application startup failed - database configuration is required")
        raise RuntimeError(f"Cannot start without database configuration: {e}") from e



# Routes

# Tenant Management Endpoints
# NOTE: GET /my-tenants endpoint removed - use virtual endpoint /__tenants instead
# POST /my-tenants endpoint removed - use virtual endpoint /__tenants instead
# DELETE /my-tenant/{tenant_id} endpoint removed - use virtual endpoint /__tenants instead




@app.post("/choose-tenant")
@limiter.limit("10/minute")
async def choose_tenant(
    request: Request,
    tenant_request: Dict[str, str] = Body(...),
    authorization: Optional[str] = Header(None)
):
    """
    Set the active tenant for the authenticated user.
    This endpoint updates the user's session metadata with the chosen active tenant.
    """
    logger.info("[CHOOSE-TENANT] POST /choose-tenant called")
    
    if not authorization:
        logger.warning("[CHOOSE-TENANT] Missing authorization header")
        raise HTTPException(status_code=401, detail="Missing authorization header")

    if not authorization.startswith("Bearer "):
        logger.warning("[CHOOSE-TENANT] Invalid authorization header format")
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization.split(" ", 1)[1]
    logger.debug(f"[CHOOSE-TENANT] Got bearer token")

    # Validate request body
    if "tenantId" not in tenant_request:
        logger.warning("[CHOOSE-TENANT] Missing tenantId in request body")
        raise HTTPException(status_code=400, detail="Missing tenantId in request body")

    tenant_id = tenant_request["tenantId"]
    logger.info(f"[CHOOSE-TENANT] Request to set active tenant to: {tenant_id}")

    try:
        # Validate JWT and extract user information
        logger.debug("[CHOOSE-TENANT] Extracting user info from JWT")
        user_info = await clerk_service.get_user_from_jwt(token)
        if not user_info:
            logger.error("[CHOOSE-TENANT] Invalid JWT token")
            raise HTTPException(status_code=401, detail="Invalid JWT token")
        
        logger.info(f"[CHOOSE-TENANT] User info from JWT: sub={user_info.get('sub')}, iss={user_info.get('iss')}")

        # Get user's current tenant information
        logger.debug("[CHOOSE-TENANT] Getting user tenant info from couch_sitter_service")
        user_tenant_info = await couch_sitter_service.get_user_tenant_info(
            sub=user_info["sub"],
            email=user_info.get("email"),
            name=user_info.get("name")
        )
        logger.debug(f"[CHOOSE-TENANT] Got user_tenant_info: user_id={user_tenant_info.user_id}")

        # Get all accessible tenants for validation
        logger.debug("[CHOOSE-TENANT] Getting accessible tenants for user")
        tenants, personal_tenant_id = await couch_sitter_service.get_user_tenants(user_info["sub"])
        accessible_tenant_ids = [t["tenantId"] for t in tenants]
        logger.info(f"[CHOOSE-TENANT] User {user_info['sub']} has accessible tenants: {accessible_tenant_ids}")

        # Verify the user has access to this tenant
        if tenant_id not in accessible_tenant_ids:
            logger.warning(f"[CHOOSE-TENANT] User {user_info['sub']} attempted to select inaccessible tenant: {tenant_id}")
            logger.warning(f"[CHOOSE-TENANT] Accessible tenants: {accessible_tenant_ids}")
            raise HTTPException(status_code=403, detail="Access denied: tenant not found")

        # Note: Active tenant is now stored in session documents (per-device)
        # No need to update Clerk metadata - session service handles it

        logger.info(f"[CHOOSE-TENANT] Returning success response with tenant {tenant_id}")
        return {
            "success": True,
            "message": "Active tenant updated successfully",
            "activeTenantId": tenant_id,
            "userId": user_tenant_info.user_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CHOOSE-TENANT] Error choosing tenant: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to set active tenant")

@app.get("/active-tenant")
async def get_active_tenant(
    request: Request,
    authorization: Optional[str] = Header(None)
):

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization.split(" ", 1)[1]

    try:
        # Validate JWT and extract user information
        user_info = await clerk_service.get_user_from_jwt(token)
        if not user_info:
            raise HTTPException(status_code=401, detail="Invalid JWT token")

        # Try to get active tenant from Clerk metadata first
        active_tenant_id = None
        if clerk_service.is_configured() and user_info.get("session_id"):
            active_tenant_id = await clerk_service.get_user_active_tenant(
                user_id=user_info["user_id"],
                session_id=user_info["session_id"],
                issuer=user_info.get("iss")
            )

        # Fallback: get personal tenant from database
        if not active_tenant_id:
            user_tenant_info = await couch_sitter_service.get_user_tenant_info(
                sub=user_info["sub"],
                email=user_info.get("email"),
                name=user_info.get("name")
            )
            active_tenant_id = user_tenant_info.tenant_id
            logger.debug(f"Using personal tenant as active tenant for user {user_info['user_id']}: {active_tenant_id}")
        else:
            logger.debug(f"Found active tenant in Clerk metadata for user {user_info['user_id']}: {active_tenant_id}")

        return {
            "activeTenantId": active_tenant_id,
            "userId": user_info["user_id"],
            "sub": user_info["sub"],
            "isPersonalTenant": True  # For now, always personal tenant
        }

    except Exception as e:
        logger.error(f"Error getting active tenant: {e}")
        raise HTTPException(status_code=500, detail="Failed to get active tenant")

# Public endpoints (must be defined before catch-all route)
@app.get("/admin/auth-logs")
async def get_auth_logs(
    request: Request,
    authorization: Optional[str] = Header(None),
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    skip: int = 0
):
    """
    Get authentication logs from couch-sitter-log database.
    
    Query parameters:
    - user_id: Filter by user ID
    - tenant_id: Filter by tenant ID
    - action: Filter by action type (login, tenant_switch, access_denied, rate_limited, token_validation, auth_request)
    - status: Filter by status (success, failed)
    - limit: Number of results to return (default 100, max 1000)
    - skip: Number of results to skip for pagination (default 0)
    """
    if not auth_log_service:
        raise HTTPException(status_code=503, detail="Auth logging not configured")
    
    # Validate authorization header
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    try:
        import time
        start = time.time()
        logger.info(f"[auth-logs] Request started")
        
        # Verify JWT to ensure user is authenticated
        token = authorization[7:]
        jwt_start = time.time()
        payload, error_reason = verify_clerk_jwt(token)
        logger.info(f"[auth-logs] JWT verification took {(time.time() - jwt_start)*1000:.0f}ms")
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        # TODO: Add admin role check once roles are implemented
        # For now, any authenticated user can view logs (consider restricting to admins)
        
        # Build query to fetch logs from CouchDB
        # Using _find endpoint to query logs with filters
        # Note: No sorting - CouchDB requires indexes for sorting that we may not have
        # Sorting can be done on the client side if needed
        # Build view query using Map/Reduce instead of Mango for better performance
        view_url = f"{auth_log_service.db_url}/_design/auth_logs/_view/"
        
        if action and status:
            view_name = "by_action_status_timestamp"
            startkey = json.dumps([action, status, ""])
            endkey = json.dumps([action, status, "\uffff"])
        elif action:
            view_name = "by_action_timestamp"
            startkey = json.dumps([action, ""])
            endkey = json.dumps([action, "\uffff"])
        elif status:
            view_name = "by_status_timestamp"
            startkey = json.dumps([status, ""])
            endkey = json.dumps([status, "\uffff"])
        else:
            view_name = "by_timestamp"
            startkey = json.dumps("")
            endkey = json.dumps("\uffff")
        
        view_url = f"{view_url}{view_name}?include_docs=true&descending=true&startkey={endkey}&endkey={startkey}&limit={min(limit, 1000)}&skip={skip}"
        
        logger.info(f"[auth-logs] Querying view: {view_url}")
        
        # Execute query via httpx directly to log database
        async with httpx.AsyncClient() as client:
            headers = auth_log_service.auth_headers.copy()
            
            response = await client.get(view_url, headers=headers)
            
            logger.info(f"[auth-logs] Response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"[auth-logs] Failed to query auth logs: {response.status_code}")
                logger.error(f"[auth-logs] Response body: {response.text}")
                raise HTTPException(status_code=500, detail="Failed to retrieve logs")
            
            result = response.json()
            # Convert view rows to docs format
            docs = [row.get("doc") for row in result.get("rows", []) if row.get("doc")]
            logger.info(f"[auth-logs] Results: {len(docs)} docs returned")
            logger.info(f"[auth-logs] Total request time: {(time.time() - start)*1000:.0f}ms")
            return {
                "docs": docs,
                "bookmark": None,
                "execution_stats": None
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving auth logs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/admin/auth-logs/stats")
async def get_auth_logs_stats(
    request: Request,
    authorization: Optional[str] = Header(None),
    days: int = 7,
    action: Optional[str] = None,
    status: Optional[str] = None
):
    """
    Get authentication logs statistics.
    
    Returns summary stats for the past N days:
    - Total requests
    - Successful logins
    - Failed authentications
    - Rate limit events
    - Requests by action type
    - Requests by status
    """
    if not auth_log_service:
        raise HTTPException(status_code=503, detail="Auth logging not configured")
    
    # Validate authorization header
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    try:
        # Verify JWT to ensure user is authenticated
        token = authorization[7:]
        payload, error_reason = verify_clerk_jwt(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        # TODO: Add admin role check once roles are implemented
        
        # Calculate date range
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Build query for logs within date range
        query = {
            "selector": {
                "type": "auth_event",
                "date": {
                    "$gte": start_date
                }
            },
            "limit": 10000
        }
        
        # Add filters if provided
        if action:
            query["selector"]["action"] = action
        if status:
            query["selector"]["status"] = status
        
        # Fetch all logs for the period
        async with httpx.AsyncClient() as client:
            headers = auth_log_service.auth_headers.copy()
            headers["Content-Type"] = "application/json"
            
            response = await client.post(
                f"{auth_log_service.db_url}/_find",
                json=query,
                headers=headers
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to query auth logs for stats: {response.status_code} {response.text}")
                raise HTTPException(status_code=500, detail="Failed to retrieve stats")
            
            result = response.json()
            docs = result.get("docs", [])
            
            # Calculate statistics
            stats = {
                "period_days": days,
                "total_events": len(docs),
                "by_action": {},
                "by_status": {},
                "successful_logins": 0,
                "failed_authentications": 0,
                "rate_limit_events": 0,
                "unique_users": len(set(doc.get("user_id") for doc in docs if doc.get("user_id"))),
                "unique_tenants": len(set(doc.get("tenant_id") for doc in docs if doc.get("tenant_id"))),
                "unique_ips": len(set(doc.get("ip") for doc in docs if doc.get("ip")))
            }
            
            # Aggregate by action and status
            for doc in docs:
                action = doc.get("action", "unknown")
                status = doc.get("status", "unknown")
                
                stats["by_action"][action] = stats["by_action"].get(action, 0) + 1
                stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
                
                # Count specific events
                if action == "login" and status == "success":
                    stats["successful_logins"] += 1
                elif status == "failed":
                    stats["failed_authentications"] += 1
                elif action == "rate_limited":
                    stats["rate_limit_events"] += 1
            
            return stats
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving auth log stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
@app.get("/health")
async def health_check():
    """Health check endpoint - pings CouchDB to verify it's alive"""
    try:
        # Use DAL for health check
        response = await dal.get("", "GET")
        
        if "couchdb" in response or "version" in response or "db_name" in response:
            return {
                "status": "ok",
                "service": "couchdb-jwt-proxy",
                "couchdb": "connected"
            }
        else:
            logger.warning(f"CouchDB returned unexpected response: {response}")
            return {
                "status": "degraded",
                "service": "couchdb-jwt-proxy",
                "couchdb": "error"
            }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "error",
            "service": "couchdb-jwt-proxy",
            "couchdb": "unavailable"
        }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "CouchDB JWT Proxy",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health"
        }
    }

async def proxy_couchdb_streaming(
    request: Request,
    path: str,
    db_name: str,
    tenant_id: str,
    payload: Dict[str, Any]
):
    """
    Streaming proxy for _changes endpoint to support long-polling.
    
    This bypasses the DAL and streams the response directly from CouchDB
    to avoid timeout issues with long-running _changes requests.
    """
    # Build CouchDB URL
    couchdb_url = f"{COUCHDB_INTERNAL_URL}/{db_name}/_changes"
    query_string = str(request.url.query) if request.url.query else ""
    
    if query_string:
        couchdb_url += f"?{query_string}"
    
    logger.info(f"Streaming _changes request to: {couchdb_url}")
    
    # Generator function that keeps the stream context alive
    async def stream_from_couchdb():
        # Keep client and stream alive for the duration of iteration
        async with httpx.AsyncClient(timeout=None) as client:
            # Add CouchDB authentication
            headers = {}
            basic_auth = get_basic_auth_header()
            if basic_auth:
                headers["Authorization"] = basic_auth
            
            # Stream the response
            async with client.stream("GET", couchdb_url, headers=headers) as response:
                # Iterate over chunks while keeping stream open
                async for chunk in response.aiter_bytes():
                    yield chunk
    
    # Return streaming response
    return StreamingResponse(
        stream_from_couchdb(),
        media_type="application/json"
    )

# Add Virtual Tables Routes (BEFORE catch-all to ensure /__users/* and /__tenants/* match first)

@app.get("/__users/{user_id}")
async def get_user(user_id: str, authorization: Optional[str] = Header(None)):
    """GET /__users/<id> - Get user document"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    return await virtual_table_handler.get_user(user_id, requesting_user_id)

@app.put("/__users/{user_id}")
async def update_user(user_id: str, request: Request, authorization: Optional[str] = Header(None)):
    """PUT /__users/<id> - Update user document"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    issuer = payload.get("iss")
    sid = payload.get("sid")  # Clerk session ID for per-device tenant mapping
    
    body = await request.json()
    return await virtual_table_handler.update_user(user_id, requesting_user_id, body, issuer=issuer, sid=sid)

@app.delete("/__users/{user_id}")
async def delete_user(user_id: str, authorization: Optional[str] = Header(None)):
    """DELETE /__users/<id> - Soft-delete user document"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    return await virtual_table_handler.delete_user(user_id, requesting_user_id)

@app.get("/__tenants/{tenant_id}")
async def get_tenant(tenant_id: str, authorization: Optional[str] = Header(None)):
    """GET /__tenants/<id> - Get tenant document"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    return await virtual_table_handler.get_tenant(tenant_id, requesting_user_id)

@app.get("/__tenants")
async def list_tenants(authorization: Optional[str] = Header(None)):
    """GET /__tenants - List all tenants user is member of"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    return await virtual_table_handler.list_tenants(requesting_user_id)

@app.post("/__tenants")
async def create_tenant(request: Request, authorization: Optional[str] = Header(None)):
    """POST /__tenants - Create new tenant"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    logger.info(f"[ROUTE] POST /__tenants: requesting_user_id={requesting_user_id}")
    body = await request.json()
    result = await virtual_table_handler.create_tenant(requesting_user_id, body)
    return result

@app.put("/__tenants/{tenant_id}")
async def update_tenant(tenant_id: str, request: Request, authorization: Optional[str] = Header(None)):
    """PUT /__tenants/<id> - Update tenant document"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    logger.info(f"[ROUTE] PUT /__tenants/{tenant_id}: requesting_user_id={requesting_user_id}")
    body = await request.json()
    return await virtual_table_handler.update_tenant(tenant_id, requesting_user_id, body)

@app.delete("/__tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, authorization: Optional[str] = Header(None)):
    """DELETE /__tenants/<id> - Soft-delete tenant"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    # Get user's active_tenant_id for validation
    active_tenant_id = payload.get("active_tenant_id")
    
    return await virtual_table_handler.delete_tenant(tenant_id, requesting_user_id, active_tenant_id or "")

@app.get("/__users/_changes")
async def user_changes(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """GET /__users/_changes - Get user document changes"""
    logger.info(f"🎯 EXPLICITLY HANDLING: GET /__users/_changes")
    logger.info(f"   Authorization header present: {bool(authorization)}")
    
    if not authorization or not authorization.startswith("Bearer "):
        logger.error(f"❌ GET /__users/_changes - Missing or invalid auth header: {authorization[:50] if authorization else 'None'}")
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    logger.info(f"   Token length: {len(token)}")
    payload, error_reason = verify_clerk_jwt(token)
    
    if not payload:
        logger.error(f"❌ GET /__users/_changes - JWT verification failed: {error_reason}")
        logger.error(f"   Will raise 403 Forbidden")
        raise HTTPException(status_code=403, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        logger.error(f"❌ GET /__users/_changes - Missing 'sub' in JWT")
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    # Extract query params
    since = request.query_params.get("since", "0")
    limit = request.query_params.get("limit")
    include_docs = request.query_params.get("include_docs", "false").lower() == "true"
    
    logger.info(f"✅ GET /__users/_changes - User: {requesting_user_id[:20]}..., Since: {since}, Include docs: {include_docs}")
    
    result = await virtual_table_handler.get_user_changes(
        requesting_user_id,
        since=since,
        limit=int(limit) if limit else None,
        include_docs=include_docs
    )
    logger.info(f"✅ GET /__users/_changes - Returning {len(result.get('results', []))} changes")
    return result

@app.post("/__users/_bulk_docs")
async def user_bulk_docs(request: Request, authorization: Optional[str] = Header(None)):
    """POST /__users/_bulk_docs - Bulk user operations"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    body = await request.json()
    docs = body.get("docs", [])
    
    return await virtual_table_handler.bulk_docs_users(requesting_user_id, docs)

@app.get("/__tenants/_changes")
async def tenant_changes(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """GET /__tenants/_changes - Get tenant document changes"""
    logger.info(f"🎯 EXPLICITLY HANDLING: GET /__tenants/_changes")
    logger.info(f"   Authorization header present: {bool(authorization)}")
    
    if not authorization or not authorization.startswith("Bearer "):
        logger.error(f"❌ GET /__tenants/_changes - Missing or invalid auth header: {authorization[:50] if authorization else 'None'}")
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    logger.info(f"   Token length: {len(token)}")
    payload, error_reason = verify_clerk_jwt(token)
    
    if not payload:
        logger.error(f"❌ GET /__tenants/_changes - JWT verification failed: {error_reason}")
        logger.error(f"   Will raise 403 Forbidden")
        raise HTTPException(status_code=403, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        logger.error(f"❌ GET /__tenants/_changes - Missing 'sub' in JWT")
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    # Extract query params
    since = request.query_params.get("since", "0")
    limit = request.query_params.get("limit")
    include_docs = request.query_params.get("include_docs", "false").lower() == "true"
    
    logger.info(f"✅ GET /__tenants/_changes - User: {requesting_user_id[:20]}..., Since: {since}, Include docs: {include_docs}")
    
    result = await virtual_table_handler.get_tenant_changes(
        requesting_user_id,
        since=since,
        limit=int(limit) if limit else None,
        include_docs=include_docs
    )
    logger.info(f"✅ GET /__tenants/_changes - Returning {len(result.get('results', []))} changes")
    return result

@app.post("/__tenants/_bulk_docs")
async def tenant_bulk_docs(request: Request, authorization: Optional[str] = Header(None)):
    """POST /__tenants/_bulk_docs - Bulk tenant operations"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization[7:]
    payload, error_reason = verify_clerk_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail=f"Invalid token ({error_reason})")
    
    requesting_user_id = payload.get("sub")
    if not requesting_user_id:
        raise HTTPException(status_code=400, detail="Missing 'sub' in JWT")
    
    # Get user's active_tenant_id for validation
    active_tenant_id = payload.get("active_tenant_id")
    
    body = await request.json()
    docs = body.get("docs", [])
    
    return await virtual_table_handler.bulk_docs_tenants(
        requesting_user_id,
        active_tenant_id or "",
        docs
    )

logger.info("✓ Registered virtual table routes (__users, __tenants, _changes, _bulk_docs)")

# Add Tenant Management Routes (BEFORE catch-all to ensure /api/* routes match first)
tenant_router = create_tenant_router(couch_sitter_service, invite_service)
app.include_router(tenant_router)
logger.info("✓ Registered tenant and invitation management routes")

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "COPY", "PATCH", "OPTIONS"])
async def proxy_couchdb(
    request: Request,
    path: str,
    authorization: Optional[str] = Header(None)
):
    """Proxy requests to CouchDB with JWT validation and tenant enforcement"""

    logger.debug(f"Incoming request: {request.method} /{path}")

    # NOTE: Virtual table routes (/__users/*, /__tenants/*, etc.) are handled by explicit @app.get() routes above.
    # If they reach here, something went wrong with route matching.
    # This catch-all should NOT handle these paths.
    if path.startswith("__users") or path.startswith("__tenants"):
        logger.error(f"❌ Virtual table path reached catch-all: {request.method} /{path}")
        logger.error(f"   This means explicit virtual routes are not being registered properly")
        raise HTTPException(status_code=500, detail="Virtual table route not registered")

    # Handle CORS preflight requests explicitly if middleware didn't catch them
    if request.method == "OPTIONS":
        return Response(status_code=200)

    # Special case: GET / is a public health/metadata endpoint (no JWT required)
    if request.method == "GET" and path == "":
        logger.info(f"Public health check: {request.method} /")
        # Skip JWT validation for root path
        return await proxy_to_couchdb_direct(request, path)

    # Extract and validate JWT token
    if not authorization:
        logger.warning(f"401 - Missing Authorization header | Client: {request.client.host} | Path: {request.method} /{path}")
        logger.warning("This typically means the user is not signed in with Clerk or the JWT is not being included in requests")
        logger.warning("Please ensure the frontend is properly configured with Clerk authentication")
        raise HTTPException(status_code=401, detail="Missing authorization header - please sign in with Clerk")

    # Parse Bearer token
    if not authorization.startswith("Bearer "):
        logger.warning(f"401 - Invalid auth header format | Client: {request.client.host} | Path: {request.method} /{path} | Header: {authorization[:50]}")
        raise HTTPException(status_code=401, detail="Invalid authorization header format - expected 'Bearer <token>'")

    token = authorization[7:]  # Remove "Bearer " prefix

    # Verify Clerk JWT
    payload, error_reason = verify_clerk_jwt(token)

    if not payload:
        # Decode token without verification to log what's in it
        unverified = decode_token_unsafe(token)
        token_preview = get_token_preview(token)

        log_msg = f"401 - {error_reason} | Client: {request.client.host} | Path: {request.method} /{path} | Token: {token_preview}"
        if unverified:
            log_msg += f" | Unverified payload: sub={unverified.get('sub', 'N/A')}, exp={unverified.get('exp', 'N/A')}, iat={unverified.get('iat', 'N/A')}"

        logger.warning(log_msg)
        
        # Log failed token validation
        if auth_log_service:
            import asyncio
            asyncio.create_task(auth_log_service.log_token_validation(
                success=False,
                ip=request.client.host if request.client else None,
                issuer=unverified.get('iss') if unverified else None,
                error_reason=error_reason,
                endpoint=f"{request.method} /{path}"
            ))
        
        raise HTTPException(status_code=401, detail=f"Invalid or expired token ({error_reason})")

    client_id = payload.get("sub")
    tenant_id = await extract_tenant(payload, path)

    # Determine application type
    is_multi_tenant_app = not is_couch_sitter_app(payload, path)

    # Extract database name and endpoint path
    if path == "_all_dbs":
        # _all_dbs is a system endpoint that doesn't belong to a specific database
        db_name = None
        endpoint_path = "_all_dbs"
    else:
        # Extract database name and endpoint from path for all other endpoints
        path_parts = path.split('/')
        if not path_parts:
            raise HTTPException(status_code=400, detail="Invalid request path")
        db_name = path_parts[0]

        # Extract endpoint path (everything after the database name)
        endpoint_path = '/'.join(path_parts[1:]) if len(path_parts) > 1 else ''
    
    # SPECIAL HANDLING: Route _changes requests to streaming handler
    # Must be done before DAL processing to avoid timeout issues
    if endpoint_path == "_changes" or path.endswith("/_changes"):
        logger.info(f"Routing _changes request to streaming handler for {db_name}")
        return await proxy_couchdb_streaming(request, path, db_name, tenant_id, payload)

    # CRITICAL: Prevent accidental database creation
    # Build allowed databases list dynamically from Application documents
    # Always include couch-sitter (admin database) and system databases
    allowed_databases = {'couch-sitter', '_users', '_replicator'}
    
    # Add all databases from registered applications
    for issuer, app_config in APPLICATIONS.items():
        if isinstance(app_config, dict) and "databaseNames" in app_config:
            allowed_databases.update(app_config["databaseNames"])
        elif isinstance(app_config, list):
            # Handle legacy format (list of strings) just in case
            allowed_databases.update(app_config)
    
    # Convert to list for error message
    allowed_databases_list = sorted(list(allowed_databases))
    
    # Skip whitelist check for system endpoints (db_name is None)
    if db_name is not None and db_name not in allowed_databases:
        logger.error(f"403 - Attempted access to non-whitelisted database: {db_name}")
        logger.error(f"This may indicate a bug where database name was not properly specified")
        logger.error(f"Allowed databases (from Application documents): {allowed_databases_list}")
        logger.error(f"To add a new database, create an Application document in couch-sitter")
        raise HTTPException(
            status_code=403, 
            detail=f"Access to database '{db_name}' is not allowed. Allowed databases: {allowed_databases_list}. Create an Application document in couch-sitter to register new databases."
        )
    
    # Additional check: Block PUT requests that would create databases
    # PUT /{db_name} without a document ID would create a database
    if db_name is not None and request.method == "PUT" and not endpoint_path:
        logger.error(f"403 - Blocked database creation attempt: PUT /{db_name}")
        logger.error(f"Database creation is not allowed through the proxy")
        raise HTTPException(
            status_code=403,
            detail=f"Database creation is not allowed. Use CouchDB admin interface to create databases, then register them via Application documents in couch-sitter."
        )


    # Log successful authentication with details
    log_msg = f"✓ Authenticated | Client: {client_id}"
    if tenant_id:
        log_msg += f" | Tenant: {tenant_id}"
    log_msg += f" | {request.method} /{path}"
    
    # Log successful authentication event
    if auth_log_service:
        import asyncio
        asyncio.create_task(auth_log_service.log_auth_event(
            action="auth_request",
            status="success",
            user_id=client_id,
            tenant_id=tenant_id,
            endpoint=f"{request.method} /{path}",
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            issuer=payload.get("iss")
        ))

    # SECURITY: Never log full JWT payload (CWE-532)
    # Instead log only safe, non-sensitive attributes
    logger.debug(f"🔐 JWT VALIDATED - {request.method} /{path}")
    logger.debug(f"🎯 JWT Issuer: {payload.get('iss')}")
    logger.debug(f"🗄️ Target Database: {db_name}")
    logger.debug(f"📱 Application detected: {'📊 Multi-tenant' if is_multi_tenant_app else '🛋️ Couch-sitter'}")

    # Safe logging: only log non-sensitive claim information
    if logger.level <= logging.DEBUG:
        logger.debug(f"User context | sub={payload.get('sub')} | tenant={tenant_id}")

    logger.debug(log_msg)

    # Check if endpoint is allowed (tenant mode always enabled)
    if not is_endpoint_allowed(endpoint_path, request.method):
        logger.warning(f"Access denied: {request.method} /{path} not allowed (endpoint: {endpoint_path})")
        raise HTTPException(status_code=403, detail="Endpoint not allowed")

    # Tenant ID is always required - extract_tenant will raise if missing
    if not tenant_id:
        logger.error(f"Failed to extract tenant_id for {client_id}")
        raise HTTPException(status_code=400, detail="Missing tenant information")

    # Build CouchDB URL
    if path == "_changes":
        # Use the database name determined from JWT issuer
        couchdb_url = f"{COUCHDB_INTERNAL_URL}/{db_name}/_changes"
    else:
        couchdb_url = f"{COUCHDB_INTERNAL_URL}/{path}"
    query_string = str(request.url.query) if request.url.query else ""

    # Rewrite query parameters for tenant enforcement (conditional)
    if path == "_all_docs":
        query_string = rewrite_all_docs_query(query_string, tenant_id, is_multi_tenant_app)
    elif path == "_changes":
        # For _changes, we need to filter by tenant_id in the response
        # CouchDB _changes doesn't support tenant filtering in query params
        # So we'll filter the response after getting it
        pass

    if query_string:
        couchdb_url += f"?{query_string}"

    # Get request body if present
    body = None
    body_dict = None
    logger.debug(f"Request method: {request.method}, checking for body...")
    if request.method in ["POST", "PUT", "PATCH"]:
        logger.debug(f"Reading body for {request.method} request...")
        body = await request.body()
        logger.debug(f"Body received: {len(body) if body else 0} bytes")
        if body:
            # Don't log body content for security - just size and type
            try:
                body_dict = json.loads(body)
                logger.debug(f"Body parsed as JSON with {len(body_dict)} keys")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse body as JSON: {e}")
        else:
            logger.debug(f"Body is empty for {request.method}")
    else:
        logger.debug(f"No body expected for {request.method}")

    # Rewrite body for tenant enforcement (conditional based on application type)
    if body_dict:
        if path == "_find":
            body_dict = rewrite_find_query(body_dict, tenant_id, is_multi_tenant_app)
        elif path == "_bulk_docs":
            body_dict = rewrite_bulk_docs(body_dict, tenant_id, is_multi_tenant_app)
        elif request.method in ["PUT"] and not path.startswith("_"):
            # Single document creation/update - inject tenant ID for multi-tenant apps only
            body_dict = inject_tenant_into_doc(body_dict, tenant_id, is_multi_tenant_app)
        elif request.method == "POST" and not path.startswith("_") and "/" not in path:
            # Document creation via POST to database - inject tenant ID for multi-tenant apps only
            body_dict = inject_tenant_into_doc(body_dict, tenant_id, is_multi_tenant_app)

        body = json.dumps(body_dict).encode()

    # CRITICAL: Prevent deletion of admin tenant
    ADMIN_TENANT_ID = "tenant_couch_sitter_admins"
    
    # Check 1: Direct DELETE or PUT to the document
    if endpoint_path == ADMIN_TENANT_ID or path.endswith(f"/{ADMIN_TENANT_ID}"):
        if request.method == "DELETE":
            logger.warning(f"Blocked attempt to DELETE admin tenant: {ADMIN_TENANT_ID}")
            raise HTTPException(status_code=403, detail="Deleting the admin tenant is not allowed")
        
        if request.method == "PUT" and body_dict:
            # Check for soft delete (deletedAt) or hard delete (_deleted)
            if body_dict.get("_deleted") is True or body_dict.get("deletedAt"):
                logger.warning(f"Blocked attempt to soft/hard delete admin tenant via PUT: {ADMIN_TENANT_ID}")
                raise HTTPException(status_code=403, detail="Deleting the admin tenant is not allowed")

    # Check 2: Bulk operations (_bulk_docs)
    if (endpoint_path == "_bulk_docs" or path.endswith("/_bulk_docs")) and body_dict:
        docs = body_dict.get("docs", [])
        for doc in docs:
            if doc.get("_id") == ADMIN_TENANT_ID:
                if doc.get("_deleted") is True or doc.get("deletedAt"):
                    logger.warning(f"Blocked attempt to delete admin tenant via _bulk_docs: {ADMIN_TENANT_ID}")
                    raise HTTPException(status_code=403, detail="Deleting the admin tenant is not allowed")

    # Forward request to CouchDB via DAL
    try:
        # Prepare payload
        payload = None
        if body_dict:
            payload = body_dict
        elif body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                # If body is not JSON, we can't pass it to DAL easily if DAL expects dict
                # But our DAL currently expects dict payload for POST/PUT
                # If it's raw bytes, we might need to adjust DAL or just pass as is if DAL supported it
                # For now, assume JSON for CouchDB operations
                logger.warning("Request body is not valid JSON, passing as None to DAL")
                pass

        # Execute request via DAL
        # Note: DAL handles authentication and URL construction
        params = dict(parse_qsl(query_string)) if query_string else None
        dal_response = await dal.get(path, request.method, payload, params=params)
        
        # Check for DAL errors
        if isinstance(dal_response, dict) and "error" in dal_response:
            error = dal_response["error"]
            reason = dal_response.get("reason", "Unknown error")
            
            # Map DAL errors to HTTP exceptions
            if error == "not_found":
                raise HTTPException(status_code=404, detail=reason)
            elif error == "bad_request":
                raise HTTPException(status_code=400, detail=reason)
            elif error == "unauthorized":
                raise HTTPException(status_code=401, detail=reason)
            elif error == "forbidden":
                raise HTTPException(status_code=403, detail=reason)
            elif error == "conflict":
                raise HTTPException(status_code=409, detail=reason)
            elif error == "connection_error":
                raise HTTPException(status_code=503, detail="Database unavailable")
            elif error == "http_error":
                # Try to extract status code from reason if possible, or default to 500
                raise HTTPException(status_code=500, detail=reason)
        
        # Filter response for tenant enforcement (always enabled)
        response_content = dal_response
        
        # Only filter if this is a multi-tenant app (couch-sitter admin app sees everything)
        if is_multi_tenant_app:
            # Use endpoint_path for checking which filter to apply
            # path contains "dbname/endpoint", endpoint_path contains "endpoint"
            if endpoint_path in ["_all_docs", "_find"] or path in ["_all_docs", "_find"]:
                # If response is a dict (parsed JSON), filter it directly
                # We need to serialize to string for filter_response_documents if it expects string
                # Or update filter_response_documents to handle dicts
                # Let's assume we need to re-serialize for now or update the filter function
                # Actually, let's update the filter logic to handle dicts if possible
                # But filter_response_documents takes bytes/str.
                # Let's serialize back to JSON for consistency with existing filter logic
                response_json = json.dumps(response_content).encode()
                filtered_json = filter_response_documents(response_json, tenant_id)
                response_content = json.loads(filtered_json)
                
            elif endpoint_path == "_changes" or path == "_changes":
                response_json = json.dumps(response_content).encode()
                filtered_json = filter_changes_response(response_json, tenant_id)
                response_content = json.loads(filtered_json)
        else:
            logger.debug(f"Skipping tenant filtering for couch-sitter app: {request.method} /{path}")

        # Debug logging for _changes to diagnose polling issues
        if endpoint_path == "_changes" or "_changes" in path:
            results = response_content.get('results', [])
            first_seq = results[0].get('seq') if results else None
            last_result_seq = results[-1].get('seq') if results else None
            logger.info(f"_changes response: last_seq={response_content.get('last_seq')}, results_count={len(results)}, pending={response_content.get('pending')}, first_seq={first_seq}, last_result_seq={last_result_seq}")
        
        # Log _local document operations (checkpoint reads/writes)
        if "_local" in path:
            logger.info(f"_local operation: {request.method} {path}, status=success")

        # Return response
        return Response(
            content=json.dumps(response_content),
            status_code=200,
            media_type="application/json"
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        # Log failed requests, especially _local writes
        if "_local" in path:
            logger.error(f"FAILED _local operation: {request.method} /{path}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
        else:
            logger.error(f"Proxy error for {request.method} /{path}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=PROXY_HOST,
        port=PROXY_PORT,
        log_level=LOG_LEVEL.lower()
    )
