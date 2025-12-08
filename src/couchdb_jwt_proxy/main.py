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
from fastapi import FastAPI, HTTPException, Header, Request
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
#   "databaseNames": ["roady", "couch-sitter"],
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

if not CLERK_ISSUER_URL:
    missing_vars.append("CLERK_ISSUER_URL")

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

if not CLERK_SECRET_KEY:
    missing_vars.append("CLERK_SECRET_KEY")

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
CLERK_ISSUER_URL = CLERK_ISSUER_URL.rstrip("/")
COUCH_SITTER_DB_URL = COUCH_SITTER_DB_URL.rstrip("/")
CLERK_JWKS_URL = f"{CLERK_ISSUER_URL}/.well-known/jwks.json"

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

# Initialize Clerk Backend API service
clerk_service = ClerkService(
    secret_key=CLERK_SECRET_KEY,
    issuer_url=CLERK_ISSUER_URL
)

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
    """Verify Clerk JWT token (RS256). Returns (payload, error_reason)"""
    try:
        # 1. Extract issuer from unverified token
        unverified_payload = decode_token_unsafe(token)
        if not unverified_payload:
             return None, "invalid_token_format"
             
        issuer = unverified_payload.get("iss")
        if not issuer:
            return None, "missing_issuer_claim"
            
        # 2. Validate issuer is registered
        # Note: APPLICATIONS keys are issuers
        if issuer not in APPLICATIONS:
             logger.warning(f"Unknown issuer: {issuer}")
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
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=None,  # Clerk JWTs don't have audience claim by default
            issuer=issuer,  # Verify issuer matches
            options={
                "verify_aud": False,
                "verify_iss": True,
                "leeway": 300  # Allow 5 minutes of clock skew (increased from 60s to handle larger drifts)
            }
        )

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

async def extract_tenant(payload: Dict[str, Any], request_path: str = None) -> str:
    """
    Extract tenant ID from JWT payload using user/tenant management system.

    This function supports both personal tenant (couch-sitter) and active tenant (roady) modes:
    - For couch-sitter: Always uses personal tenant
    - For roady: Uses active tenant from Clerk metadata, falls back to personal tenant

    Args:
        payload: JWT payload dictionary
        request_path: The request path to determine application type (optional)

    Returns:
        Tenant ID string
    """
    import hashlib

    # Get the subject (sub) claim from the JWT
    sub = payload.get("sub")
    if not sub:
        logger.error("Missing 'sub' claim in JWT - cannot determine tenant")
        raise ValueError("Missing 'sub' claim in JWT")

    # Get JWT token from payload for Clerk service (extract from original token if available)
    # For now, we'll work with the payload data we have
    user_info = {
        "sub": sub,
        "user_id": sub,  # In Clerk, sub is the user ID
        "email": payload.get("email"),
        "name": payload.get("name") or payload.get("given_name"),
        "session_id": payload.get("sid")  # Session ID if available
    }

    # Determine application type from request path or issuer
    is_roady_request = False
    is_couch_sitter_request = False
    
    # 1. Check issuer against registered applications (most reliable)
    issuer = payload.get("iss", "")
    if issuer in APPLICATIONS:
        app_config = APPLICATIONS[issuer]
        dbs = []
        if isinstance(app_config, dict):
            dbs = app_config.get("databaseNames", [])
        elif isinstance(app_config, list):
            dbs = app_config
            
        if "roady" in dbs:
            is_roady_request = True
        elif "couch-sitter" in dbs:
            is_couch_sitter_request = True
            
    # 2. Fallback to request path check
    if not is_roady_request and not is_couch_sitter_request:
        if request_path and "roady" in request_path.lower():
            is_roady_request = True
        elif request_path and ("couch-sitter" in request_path.lower() or "couch_sitter" in request_path.lower()):
            is_couch_sitter_request = True
            
    # 3. Fallback to issuer string check
    if not is_roady_request and not is_couch_sitter_request:
        if "roady" in issuer.lower():
            is_roady_request = True
        elif "couch-sitter" in issuer.lower() or "couch_sitter" in issuer.lower():
            is_couch_sitter_request = True

    # Default to couch-sitter behavior if we can't determine
    if not is_roady_request:
        is_couch_sitter_request = True

    logger.debug(f"Application type detected: {'roady' if is_roady_request else 'couch-sitter'}")

    # Create sub hash for cache lookup
    sub_hash = hashlib.sha256(sub.encode('utf-8')).hexdigest()

    # For couch-sitter, always use personal tenant (simple behavior)
    if is_couch_sitter_request:
        logger.debug(f"Couch-sitter request - using personal tenant for sub '{sub}'")

        # Try cache first
        cached_info = user_cache.get_user_by_sub_hash(sub_hash)
        if cached_info:
            logger.debug(f"Using cached tenant info for couch-sitter sub '{sub}': tenant_id={cached_info.tenant_id}")
            return cached_info.tenant_id

        # Determine database name from request path
        # Format is usually /<db_name>/...
        requested_db_name = "couch-sitter"  # Default
        if request_path:
            parts = request_path.strip('/').split('/')
            if parts:
                requested_db_name = parts[0]

        # Cache miss - fetch from couch-sitter database
        try:
            user_tenant_info = await couch_sitter_service.get_user_tenant_info(
                sub=sub,
                email=user_info.get("email"),
                name=user_info.get("name"),
                requested_db_name=requested_db_name
            )

            # Cache the result
            user_cache.set_user(sub_hash, user_tenant_info)

            logger.info(f"Retrieved personal tenant for couch-sitter sub '{sub}': tenant_id={user_tenant_info.tenant_id}")
            return user_tenant_info.tenant_id

        except Exception as e:
            logger.error(f"Failed to get tenant info for couch-sitter sub '{sub}': {e}")
            raise

    # For roady, strictly get active tenant from JWT claims
    # CRITICAL SECURITY FIX: Remove fallback mechanism entirely
    logger.debug(f"Roady request - checking for active tenant in JWT for sub '{sub}'")

    # Check for active_tenant_id claim in JWT
    active_tenant_id = payload.get("active_tenant_id") or payload.get("tenant_id")
    
    # Check metadata inside JWT if not at top level (Clerk sometimes puts it there)
    if not active_tenant_id and payload.get("metadata"):
        active_tenant_id = payload.get("metadata").get("active_tenant_id")
        
    if active_tenant_id:
        logger.debug(f"Found active tenant in JWT claims: {active_tenant_id}")
        return active_tenant_id
    
    # STRICT ENFORCEMENT: No fallback to backend API or personal tenant
    # Reject request immediately if active_tenant_id claim is missing
    logger.warning(f"Missing active_tenant_id in JWT for roady request from sub '{sub}' - rejecting request")
    raise HTTPException(
        status_code=401, 
        detail="Missing active_tenant_id claim in JWT. Please refresh your token and try again."
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

def inject_tenant_into_doc(doc: Dict[str, Any], tenant_id: str, is_roady_app: bool = False) -> Dict[str, Any]:
    """
    Inject tenant ID into document (conditional based on application type).

    For roady: Always inject tenant ID
    For couch-sitter: Never inject tenant ID (simple behavior)
    """
    if is_roady_app:
        doc[TENANT_FIELD] = tenant_id
        logger.debug(f"Injected tenant ID into document for roady app: {tenant_id}")
    else:
        logger.debug(f"Skipping tenant injection for couch-sitter app")
    return doc

def rewrite_all_docs_query(query_params: str, tenant_id: str, is_roady_app: bool = False) -> str:
    """
    Rewrite _all_docs query to filter by tenant (conditional based on application type).

    For roady: Filter by tenant
    For couch-sitter: No tenant filtering
    """
    if not is_roady_app:
        logger.debug(f"Skipping tenant filtering for couch-sitter _all_docs query")
        return query_params or ""

    logger.debug(f"Adding tenant filtering for roady _all_docs query: {tenant_id}")
    # Add start/end keys for tenant filtering
    if query_params:
        return f"{query_params}&start_key=\"{tenant_id}:\"&end_key=\"{tenant_id}:\ufff0\""
    else:
        return f"start_key=\"{tenant_id}:\"&end_key=\"{tenant_id}:\ufff0\""

def rewrite_find_query(body: Dict[str, Any], tenant_id: str, is_roady_app: bool = False) -> Dict[str, Any]:
    """
    Rewrite _find query to inject tenant filter (conditional based on application type).

    For roady: Filter by tenant
    For couch-sitter: No tenant filtering
    """
    if not is_roady_app:
        logger.debug(f"Skipping tenant filtering for couch-sitter _find query")
        return body

    logger.debug(f"Adding tenant filtering for roady _find query: {tenant_id}")
    # Inject tenant into selector
    if "selector" not in body:
        body["selector"] = {}

    body["selector"][TENANT_FIELD] = tenant_id
    logger.debug(f"Rewrote _find query with tenant filter: {TENANT_FIELD}={tenant_id}")
    return body

def rewrite_bulk_docs(body: Dict[str, Any], tenant_id: str, is_roady_app: bool = False) -> Dict[str, Any]:
    """
    Inject tenant into bulk docs (conditional based on application type).

    For roady: Always inject tenant ID
    For couch-sitter: Never inject tenant ID
    """
    if "docs" in body:
        for doc in body["docs"]:
            if is_roady_app:
                # Always inject tenant ID (override any existing value)
                doc[TENANT_FIELD] = tenant_id

        if is_roady_app:
            logger.debug(f"Injected tenant into {len(body.get('docs', []))} documents for roady app")
        else:
            logger.debug(f"Skipping tenant injection for {len(body.get('docs', []))} documents for couch-sitter app")
    return body

def is_roady_application(request_path: str, payload: Dict[str, Any]) -> bool:
    """
    Determine if the request is for a roady application.

    Args:
        request_path: The request path
        payload: JWT payload

    Returns:
        True if this is a roady request, False if couch-sitter
    """
    # Check request path first
    if request_path and "roady" in request_path.lower():
        return True
    if request_path and ("couch-sitter" in request_path.lower() or "couch_sitter" in request_path.lower()):
        return False

    # Check the issuer from JWT
    issuer = payload.get("iss", "")
    if "roady" in issuer.lower():
        return True
    if "couch-sitter" in issuer.lower() or "couch_sitter" in issuer.lower():
        return False

    # Default to couch-sitter if we can't determine
    return False

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

    yield

    # Shutdown (if needed in the future)
    logger.info("Shutting down CouchDB JWT Proxy")

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
    """Ensure auth log database exists on startup"""
    logger.info("[Startup] Starting up...")
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

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins - restrict in production if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

    logger.info("Initializing applications from database...")

    try:
        # Load all applications from database
        APPLICATIONS = await couch_sitter_service.load_all_apps()
        logger.info(f"initialize_applications: Loaded apps: {APPLICATIONS}")

        if not APPLICATIONS:
            logger.error("No applications found in database")
            raise RuntimeError("No applications configured in database. Please add application documents to the couch-sitter database.")

        logger.info(f"✓ Loaded {len(APPLICATIONS)} applications from database")
        for issuer, app_config in APPLICATIONS.items():
            logger.info(f"  {issuer} -> {app_config}")

    except Exception as e:
        logger.error(f"Failed to initialize applications from database: {e}")
        logger.error("Application startup failed - database configuration is required")
        raise RuntimeError(f"Cannot start without database configuration: {e}") from e



# Routes

# Tenant Management Endpoints
@app.get("/my-tenants")
@limiter.limit("30/minute")
async def get_my_tenants(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Get all tenants for the authenticated user.
    This endpoint works for both roady and couch-sitter applications.
    """
    print("=" * 80, flush=True)
    print("GET /my-tenants called", flush=True)
    print("=" * 80, flush=True)
    logger.info("=" * 80)
    logger.info("GET /my-tenants called")
    logger.info("=" * 80)
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization.split(" ", 1)[1]

    try:
        # Validate JWT and extract user information
        user_info = await clerk_service.get_user_from_jwt(token)
        if not user_info:
            raise HTTPException(status_code=401, detail="Invalid JWT token")

        # Determine database name from issuer to ensure correct tenant type
        issuer = user_info.get("iss")
        
        # Fallback: If name or email is missing, try to fetch from Clerk API
        if (not user_info.get("email") or not user_info.get("name")) and clerk_service.is_configured():
            logger.info(f"Missing email/name in JWT (email={user_info.get('email')}, name={user_info.get('name')}), fetching from Clerk API...")
            details = await clerk_service.fetch_user_details(user_info["sub"], issuer)
            if details:
                logger.info(f"Fetched details from Clerk API: {details}")
                if details.get("email"):
                    user_info["email"] = details["email"]
                if details.get("name"):
                    user_info["name"] = details["name"]
            else:
                logger.warning(f"Failed to fetch user details from Clerk API for {user_info['sub']}")
        elif not clerk_service.is_configured():
            logger.warning("Clerk service not configured - cannot fetch missing user details")
        else:
            logger.info(f"User info complete from JWT: email={user_info.get('email')}, name={user_info.get('name')}")
        
        # CRITICAL: Validate that we have email and name before proceeding
        if not user_info.get("email") or not user_info.get("name"):
            warning_msg = f"""
================================================================================
WARNING: Missing required user fields in JWT
================================================================================
Email: {user_info.get('email')}
Name: {user_info.get('name')}

To fix this, configure your Clerk Session Token to include:
{{
    "active_tenant_id": "{{{{session.public_metadata.active_tenant_id}}}}",
    "email": "{{{{user.primary_email_address}}}}",
    "name": "{{{{user.full_name}}}}"
}}

Clerk Dashboard → Sessions → Customize session token
================================================================================
"""
            logger.warning(warning_msg)
            # Still raise error to prevent incomplete user creation
            raise HTTPException(status_code=500, detail="Missing required fields: email and/or name. Check server logs for configuration instructions.")
        
        logger.info(f"DEBUG: Issuer from JWT: {issuer}")
        logger.info(f"DEBUG: APPLICATIONS keys: {list(APPLICATIONS.keys())}")
        
        requested_db_name = None
        
        # Get app config from loaded applications (no fallback)
        if not issuer:
            logger.error("No issuer found in JWT")
            raise HTTPException(status_code=401, detail="Invalid JWT: missing issuer")
            
        if issuer not in APPLICATIONS:
            logger.error(f"Unknown issuer: {issuer}. Available issuers: {list(APPLICATIONS.keys())}")
            raise HTTPException(status_code=401, detail=f"Unknown application issuer: {issuer}")
        
        app_config = APPLICATIONS[issuer]
        if isinstance(app_config, dict):
            dbs = app_config.get("databaseNames", [])
            if dbs:
                requested_db_name = dbs[0]
        elif isinstance(app_config, list) and app_config:
            requested_db_name = app_config[0]

        logger.info(f"DEBUG: requested_db_name: {requested_db_name}")

        # Resolve App ID from DB Name to support correct linking
        app_doc = await couch_sitter_service.find_application_by_db_name(requested_db_name)
        app_id = app_doc.get("_id") if app_doc else None
        
        # Ensure user exists (passing resolved ID if available)
        creation_app_id = app_id or requested_db_name

        # Get user's tenants from database
        user_tenant_info = await couch_sitter_service.get_user_tenant_info(
            sub=user_info["sub"],
            email=user_info.get("email"),
            name=user_info.get("name"),
            requested_db_name=creation_app_id
        )

        # Get all tenants for this user (not just personal tenant)
        tenants, personal_tenant_id = await couch_sitter_service.get_user_tenants(user_info["sub"])

        # Log successful login event
        if auth_log_service:
            import asyncio
            asyncio.create_task(auth_log_service.log_login(
                user_id=user_info["user_id"],
                tenant_id=user_tenant_info.tenant_id,
                success=True,
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                issuer=user_info.get("iss")
            ))

        # VALIDATION: Filter tenants for this application
        # If no requested_db_name, we might want to return all, but for safety in roady context, 
        # let's be strict if we know we are in an app context.
        filtered_tenants = []
        if requested_db_name:
             logger.info(f"Filtering tenants for application: {requested_db_name} (AppID: {app_id})")
             for t in tenants:
                 t_app_id = t.get("applicationId")
                 
                 if requested_db_name == 'couch-sitter':
                     filtered_tenants.append(t)
                 # Match against DB name (legacy) OR Resolved App ID (correct)
                 elif t_app_id == requested_db_name or (app_id and t_app_id == app_id):
                     filtered_tenants.append(t)
                 elif not t_app_id:
                     logger.debug(f"Skipping tenant {t.get('tenantId')} without applicationId")
        else:
            # No specific app requested (unlikely with current JWT logic), return all
            filtered_tenants = tenants

        logger.info(f"Tenant filtering: {len(tenants)} -> {len(filtered_tenants)} tenants")

        # Mark the active tenant
        # Priority 1: App-specific Personal Tenant (from user_tenant_info) is a safe default
        active_tenant_id = user_tenant_info.tenant_id
        
        # Priority 2: Active tenant from Clerk metadata (if valid for this app)
        if clerk_service.is_configured() and user_info.get("session_id"):
             clerk_active_tenant = await clerk_service.get_user_active_tenant(
                 user_id=user_info["user_id"],
                 session_id=user_info["session_id"],
                 issuer=user_info.get("iss")
             )
             
             if clerk_active_tenant:
                 # VALIDATE: Does this tenant exist in our filtered list?
                 # If we switched apps, we might have an active_tenant_id from the OLD app.
                 # We must NOT use it if it's not accessible in the NEW app.
                 is_valid = any(t["tenantId"] == clerk_active_tenant for t in filtered_tenants)
                 
                 if is_valid:
                     active_tenant_id = clerk_active_tenant
                     logger.info(f"Using valid active tenant from Clerk: {active_tenant_id}")
                 else:
                     logger.warning(f"Ignored active tenant {clerk_active_tenant} from Clerk - not valid for app {requested_db_name}")

        return {
            "tenants": filtered_tenants,
            "activeTenantId": active_tenant_id,
            "userId": user_tenant_info.user_id,
            "sub": user_tenant_info.sub
        }

    except Exception as e:
        logger.error(f"Error getting user tenants: {e}")
        raise HTTPException(status_code=500, detail="Failed to get tenant information")



@app.post("/choose-tenant")
@limiter.limit("10/minute")
async def choose_tenant(
    request: Request,
    tenant_request: Dict[str, str],
    authorization: Optional[str] = Header(None)
):
    """
    Set the active tenant for the authenticated user.
    This endpoint updates the user's session metadata with the chosen active tenant.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization.split(" ", 1)[1]

    # Validate request body
    if "tenantId" not in tenant_request:
        raise HTTPException(status_code=400, detail="Missing tenantId in request body")

    tenant_id = tenant_request["tenantId"]

    try:
        # Validate JWT and extract user information
        user_info = await clerk_service.get_user_from_jwt(token)
        if not user_info:
            raise HTTPException(status_code=401, detail="Invalid JWT token")

        # Get user's current tenant information
        user_tenant_info = await couch_sitter_service.get_user_tenant_info(
            sub=user_info["sub"],
            email=user_info.get("email"),
            name=user_info.get("name")
        )

        # Get all accessible tenants for validation
        tenants, personal_tenant_id = await couch_sitter_service.get_user_tenants(user_info["sub"])
        accessible_tenant_ids = [t["tenantId"] for t in tenants]

        # Verify the user has access to this tenant
        if tenant_id not in accessible_tenant_ids:
            logger.warning(f"User {user_info['sub']} attempted to select inaccessible tenant: {tenant_id}")
            logger.warning(f"Accessible tenants: {accessible_tenant_ids}")
            raise HTTPException(status_code=403, detail="Access denied: tenant not found")

        # Update active tenant in Clerk metadata (if Clerk Backend API is configured)
        if clerk_service.is_configured() and user_info.get("session_id"):
            success = await clerk_service.update_active_tenant_in_session(
                user_id=user_info["user_id"],
                session_id=user_info["session_id"],
                tenant_id=tenant_id,
                issuer=user_info.get("iss")
            )
            if success:
                logger.info(f"Updated active tenant in Clerk metadata for user {user_info['user_id']}: {tenant_id}")
                
                # SECURITY FIX #2: Validate JWT template configuration
                # The client should get a new JWT which will contain the active_tenant_id claim
                # if Clerk JWT Template is properly configured
                logger.info(f"ℹ️ JWT template verification: Client should refresh token to get active_tenant_id claim")
                logger.info(f"   If claim is missing after refresh, Clerk JWT Template may not be configured correctly")
            else:
                logger.warning(f"Failed to update active tenant in Clerk metadata for user {user_info['user_id']}")
        else:
            # Fallback: Update user metadata instead of session metadata
            success = await clerk_service.update_user_active_tenant(
                user_id=user_info["user_id"],
                tenant_id=tenant_id
            )
            if success:
                logger.info(f"Updated active tenant in user metadata for user {user_info['user_id']}: {tenant_id}")
            else:
                logger.warning(f"Failed to update active tenant in user metadata for user {user_info['user_id']}")

        return {
            "success": True,
            "message": "Active tenant updated successfully",
            "activeTenantId": tenant_id,
            "userId": user_tenant_info.user_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error choosing tenant: {e}")
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

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "COPY", "PATCH", "OPTIONS"])
async def proxy_couchdb(
    request: Request,
    path: str,
    authorization: Optional[str] = Header(None)
):
    """Proxy requests to CouchDB with JWT validation and tenant enforcement"""

    logger.debug(f"Incoming request: {request.method} /{path}")

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

    # Determine application type (roady vs couch-sitter)
    is_roady_app = is_roady_application(path, payload)

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

    # Determine application type for conditional tenant enforcement (moved up for logging)
    is_roady_app = is_roady_application(path, payload)
    
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
    logger.debug(f"📱 Application detected: {'🚗 ROADY' if is_roady_app else '🛋️ COUCH-SITTER'}")

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
        query_string = rewrite_all_docs_query(query_string, tenant_id, is_roady_app)
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
            body_dict = rewrite_find_query(body_dict, tenant_id, is_roady_app)
        elif path == "_bulk_docs":
            body_dict = rewrite_bulk_docs(body_dict, tenant_id, is_roady_app)
        elif request.method in ["PUT"] and not path.startswith("_"):
            # Single document creation/update - inject tenant ID for roady only
            body_dict = inject_tenant_into_doc(body_dict, tenant_id, is_roady_app)
        elif request.method == "POST" and not path.startswith("_") and "/" not in path:
            # Document creation via POST to database - inject tenant ID for roady only
            body_dict = inject_tenant_into_doc(body_dict, tenant_id, is_roady_app)

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
        
        # Only filter if this is a roady app (couch-sitter admin app sees everything)
        if is_roady_app:
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
