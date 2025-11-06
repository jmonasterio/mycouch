import os
import json
import httpx
import jwt
import logging
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
from functools import lru_cache
from jwt import PyJWKClient

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET")
COUCHDB_INTERNAL_URL = os.getenv("COUCHDB_INTERNAL_URL", "http://localhost:5984")
COUCHDB_USER = os.getenv("COUCHDB_USER", "")
COUCHDB_PASSWORD = os.getenv("COUCHDB_PASSWORD", "")
PROXY_HOST = os.getenv("PROXY_HOST", "0.0.0.0")
PROXY_PORT = int(os.getenv("PROXY_PORT", "5985"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Clerk configuration (for RS256 JWT validation)
CLERK_ISSUER_URL = os.getenv("CLERK_ISSUER_URL", "").rstrip("/")
ENABLE_CLERK_JWT = os.getenv("ENABLE_CLERK_JWT", "false").lower() == "true"
CLERK_JWKS_URL = f"{CLERK_ISSUER_URL}/.well-known/jwks.json" if CLERK_ISSUER_URL else None

# Tenant configuration
TENANT_CLAIM = os.getenv("TENANT_CLAIM", "tenant_id")
TENANT_FIELD = os.getenv("TENANT_FIELD", "tenant_id")
ENABLE_TENANT_MODE = os.getenv("ENABLE_TENANT_MODE", "false").lower() == "true"

# Allowed CouchDB endpoints for PouchDB (others will be rejected)
ALLOWED_ENDPOINTS = {
    "/_all_docs": ["GET"],
    "/_find": ["POST"],
    "/_bulk_docs": ["POST"],
    "/_changes": ["GET", "POST"],
    "/_revs_limit": ["GET", "PUT"],
    "/_compact": ["POST"],
    "/_view_cleanup": ["POST"],
    # Document endpoints (handled dynamically)
}

# Setup logging
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# Validation: Ensure required configuration is set
if not ENABLE_CLERK_JWT and not JWT_SECRET:
    raise ValueError("JWT_SECRET must be set when ENABLE_CLERK_JWT is false. Generate one with: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"")

if ENABLE_CLERK_JWT and not CLERK_ISSUER_URL:
    raise ValueError("CLERK_ISSUER_URL must be set when ENABLE_CLERK_JWT is true")

# Load API keys
def load_api_keys() -> Dict[str, str]:
    """Load API keys from config file"""
    config_path = Path(__file__).parent / "config" / "api_keys.json"
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load API keys: {e}")
        return {}

API_KEYS = load_api_keys()

# Models
class TokenRequest(BaseModel):
    api_key: str

class TokenResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    expires_in: int = 3600

# JWT Functions
def create_jwt_token(client_id: str, tenant_id: Optional[str] = None, expires_in: int = 3600) -> str:
    """Create JWT token for a client"""
    now = datetime.now(timezone.utc)
    expiration = now + timedelta(seconds=expires_in)

    payload = {
        "sub": client_id,
        "iat": int(now.timestamp()),
        "exp": int(expiration.timestamp()),
        "scope": ""
    }

    # Add tenant if provided
    if tenant_id and ENABLE_TENANT_MODE:
        payload[TENANT_CLAIM] = tenant_id

    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    logger.info(f"Generated token for client: {client_id}" + (f" (tenant: {tenant_id})" if tenant_id else ""))
    return token

def verify_jwt_token(token: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Verify and decode JWT token. Returns (payload, error_reason)"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload, None
    except jwt.ExpiredSignatureError as e:
        return None, "token_expired"
    except jwt.InvalidTokenError as e:
        error_type = type(e).__name__
        return None, f"invalid_token ({error_type})"
    except Exception as e:
        error_type = type(e).__name__
        return None, f"token_error ({error_type})"

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
@lru_cache(maxsize=1)
def get_clerk_jwks_client() -> Optional[PyJWKClient]:
    """Get cached JWKS client for Clerk token validation"""
    if not CLERK_JWKS_URL:
        return None
    try:
        client = PyJWKClient(CLERK_JWKS_URL, cache_keys=True)
        logger.info(f"Clerk JWKS client initialized: {CLERK_JWKS_URL}")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Clerk JWKS client: {e}")
        return None

def verify_clerk_jwt(token: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Verify Clerk JWT token (RS256). Returns (payload, error_reason)"""
    if not ENABLE_CLERK_JWT:
        return None, "clerk_jwt_not_enabled"

    try:
        # Get JWKS client
        jwks_client = get_clerk_jwks_client()
        if not jwks_client:
            return None, "clerk_jwks_unavailable"

        # Get signing key
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Verify token with Clerk's public key
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=None,  # Clerk JWTs don't have audience claim by default
            options={"verify_aud": False}
        )

        logger.debug(f"Clerk JWT validated successfully")
        return payload, None

    except jwt.ExpiredSignatureError:
        return None, "clerk_token_expired"
    except jwt.InvalidTokenError as e:
        error_type = type(e).__name__
        return None, f"clerk_invalid_token ({error_type})"
    except Exception as e:
        error_type = type(e).__name__
        return None, f"clerk_token_error ({error_type})"

def extract_tenant(payload: Dict[str, Any]) -> Optional[str]:
    """Extract tenant ID from JWT payload"""
    if not ENABLE_TENANT_MODE:
        return None
    tenant = payload.get(TENANT_CLAIM)
    if not tenant:
        logger.warning(f"Missing tenant claim '{TENANT_CLAIM}' in JWT")
        return None
    return tenant

def is_system_doc(doc_id: str) -> bool:
    """Check if document ID is a system document"""
    return doc_id.startswith("_")

def is_endpoint_allowed(path: str, method: str) -> bool:
    """Check if endpoint is allowed"""
    if not ENABLE_TENANT_MODE:
        return True

    # Check exact endpoint match
    if path in ALLOWED_ENDPOINTS:
        return method in ALLOWED_ENDPOINTS[path]

    # Check if it's a document endpoint (single document operations)
    # Allowed: GET /docid, PUT /docid, DELETE /docid
    if method in ["GET", "PUT", "DELETE", "POST", "HEAD"] and "/" not in path.lstrip("/"):
        return not is_system_doc(path.lstrip("/"))

    # Document revision endpoint: /docid?rev=...
    if method in ["GET", "DELETE"] and "?" in path:
        doc_id = path.split("?")[0].lstrip("/")
        return not is_system_doc(doc_id)

    logger.warning(f"Endpoint not allowed: {method} /{path}")
    return False

def filter_document_for_tenant(doc: Dict[str, Any], tenant_id: str) -> Optional[Dict[str, Any]]:
    """Validate and optionally filter document for tenant access"""
    if not ENABLE_TENANT_MODE:
        return doc

    doc_tenant = doc.get(TENANT_FIELD)
    if doc_tenant != tenant_id:
        logger.warning(f"Access denied: document tenant '{doc_tenant}' does not match '{tenant_id}'")
        return None
    return doc

def inject_tenant_into_doc(doc: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Inject tenant ID into document"""
    if not ENABLE_TENANT_MODE:
        return doc

    doc[TENANT_FIELD] = tenant_id
    return doc

def rewrite_all_docs_query(query_params: str, tenant_id: str) -> str:
    """Rewrite _all_docs query to filter by tenant"""
    if not ENABLE_TENANT_MODE:
        return query_params

    # Add start/end keys for tenant filtering
    if query_params:
        return f"{query_params}&start_key=\"{tenant_id}:\"&end_key=\"{tenant_id}:\ufff0\""
    else:
        return f"start_key=\"{tenant_id}:\"&end_key=\"{tenant_id}:\ufff0\""

def rewrite_find_query(body: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Rewrite _find query to inject tenant filter"""
    if not ENABLE_TENANT_MODE:
        return body

    # Inject tenant into selector
    if "selector" not in body:
        body["selector"] = {}

    body["selector"][TENANT_FIELD] = tenant_id
    logger.debug(f"Rewrote _find query with tenant filter: {TENANT_FIELD}={tenant_id}")
    return body

def rewrite_bulk_docs(body: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Inject tenant into bulk docs"""
    if not ENABLE_TENANT_MODE:
        return body

    if "docs" in body:
        for doc in body["docs"]:
            # Only inject if not already present (allow override for updates)
            if TENANT_FIELD not in doc:
                doc[TENANT_FIELD] = tenant_id

    logger.debug(f"Injected tenant into {len(body.get('docs', []))} documents")
    return body

def filter_response_documents(content: bytes, tenant_id: str) -> bytes:
    """Filter response to remove non-tenant documents"""
    if not ENABLE_TENANT_MODE:
        return content

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

# FastAPI Application
app = FastAPI(
    title="CouchDB JWT Proxy",
    description="HTTP proxy for CouchDB with JWT authentication",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins - restrict in production if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup event to log configuration
@app.on_event("startup")
async def startup_event():
    """Log configuration on startup"""
    logger.info(f"Starting CouchDB JWT Proxy on {PROXY_HOST}:{PROXY_PORT}")
    logger.info(f"Proxying to CouchDB at {COUCHDB_INTERNAL_URL}")

    # CouchDB credentials
    if COUCHDB_USER:
        logger.info(f"✓ CouchDB authentication enabled (user: {COUCHDB_USER})")
    else:
        logger.warning(f"⚠ No CouchDB credentials configured")

    # JWT configuration
    if ENABLE_CLERK_JWT:
        logger.info(f"✓ Clerk JWT validation ENABLED")
        logger.info(f"  Clerk issuer: {CLERK_ISSUER_URL}")
        logger.info(f"  JWKS URL: {CLERK_JWKS_URL}")
        logger.info(f"  Fallback to custom JWT: enabled")
    else:
        logger.info(f"✓ Using custom JWT validation (HS256)")
        logger.info(f"  Loaded {len(API_KEYS)} API keys")

    # Tenant mode
    if ENABLE_TENANT_MODE:
        logger.info(f"✓ Tenant mode ENABLED")
        logger.info(f"  Tenant claim: {TENANT_CLAIM}")
        logger.info(f"  Tenant field: {TENANT_FIELD}")
    else:
        logger.info(f"  Tenant mode DISABLED")

    logger.info(f"Logging level: {LOG_LEVEL}")

# Routes
@app.post("/auth/token", response_model=TokenResponse)
async def get_token(request: TokenRequest):
    """Generate JWT token from API key"""
    api_key = request.api_key

    if api_key not in API_KEYS:
        logger.warning(f"Failed authentication attempt with invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")

    client_id = API_KEYS[api_key]

    # Extract tenant if provided and tenant mode is enabled
    tenant_id = None
    if ENABLE_TENANT_MODE and hasattr(request, "tenant_id"):
        tenant_id = request.tenant_id

    token = create_jwt_token(client_id, tenant_id)

    return TokenResponse(
        token=token,
        token_type="Bearer",
        expires_in=3600
    )

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "COPY", "PATCH"])
async def proxy_couchdb(
    request: Request,
    path: str,
    authorization: Optional[str] = Header(None)
):
    """Proxy requests to CouchDB with JWT validation and tenant enforcement"""

    logger.debug(f"Incoming request: {request.method} /{path}")

    # Skip auth for auth endpoints
    if path.startswith("auth/"):
        raise HTTPException(status_code=404, detail="Not found")

    # Extract and validate JWT token
    if not authorization:
        logger.warning(f"401 - Missing Authorization header | Client: {request.client.host} | Path: {request.method} /{path}")
        raise HTTPException(status_code=401, detail="Missing authorization header")

    # Parse Bearer token
    if not authorization.startswith("Bearer "):
        logger.warning(f"401 - Invalid auth header format | Client: {request.client.host} | Path: {request.method} /{path} | Header: {authorization[:50]}")
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization[7:]  # Remove "Bearer " prefix
    payload = None
    error_reason = None

    # Try Clerk JWT first if enabled
    if ENABLE_CLERK_JWT:
        payload, error_reason = verify_clerk_jwt(token)
        if payload:
            logger.debug("Token verified as Clerk JWT")
        else:
            logger.debug(f"Clerk JWT validation failed: {error_reason}, trying custom JWT")

    # Fall back to custom JWT if Clerk validation fails or not enabled
    if not payload:
        payload, error_reason = verify_jwt_token(token)
        if payload:
            logger.debug("Token verified as custom JWT")

    if not payload:
        # Decode token without verification to log what's in it
        unverified = decode_token_unsafe(token)
        token_preview = get_token_preview(token)

        log_msg = f"401 - {error_reason} | Client: {request.client.host} | Path: {request.method} /{path} | Token: {token_preview}"
        if unverified:
            log_msg += f" | Unverified payload: sub={unverified.get('sub', 'N/A')}, exp={unverified.get('exp', 'N/A')}, iat={unverified.get('iat', 'N/A')}"

        logger.warning(log_msg)
        raise HTTPException(status_code=401, detail=f"Invalid or expired token ({error_reason})")

    client_id = payload.get("sub")
    tenant_id = extract_tenant(payload)

    # Log successful authentication with details
    log_msg = f"✓ Authenticated | Client: {client_id}"
    if tenant_id:
        log_msg += f" | Tenant: {tenant_id}"
    log_msg += f" | {request.method} /{path}"

    # Debug level: log full token details
    if logger.level <= logging.DEBUG:
        logger.debug(f"Token details | sub={payload.get('sub')} | iat={payload.get('iat')} | exp={payload.get('exp')}")

    logger.info(log_msg)

    # Check if endpoint is allowed (tenant mode)
    if ENABLE_TENANT_MODE and not is_endpoint_allowed(path, request.method):
        logger.warning(f"Access denied: {request.method} /{path} not allowed in tenant mode")
        raise HTTPException(status_code=403, detail="Endpoint not allowed")

    # Validate tenant is present when required
    if ENABLE_TENANT_MODE and not tenant_id:
        logger.error(f"Tenant mode enabled but no tenant_id in token for {client_id}")
        raise HTTPException(status_code=400, detail="Missing tenant information")

    # Build CouchDB URL
    couchdb_url = f"{COUCHDB_INTERNAL_URL}/{path}"
    query_string = str(request.url.query) if request.url.query else ""

    # Rewrite query parameters for tenant enforcement
    if ENABLE_TENANT_MODE and path == "_all_docs":
        query_string = rewrite_all_docs_query(query_string, tenant_id)

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
            logger.debug(f"Body content (first 100 chars): {body[:100]}")
            try:
                body_dict = json.loads(body)
                logger.debug(f"Body parsed as JSON")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse body as JSON: {e}")
        else:
            logger.debug(f"Body is empty for {request.method}")
    else:
        logger.debug(f"No body expected for {request.method}")

    # Rewrite body for tenant enforcement
    if ENABLE_TENANT_MODE and body_dict:
        if path == "_find":
            body_dict = rewrite_find_query(body_dict, tenant_id)
        elif path == "_bulk_docs":
            body_dict = rewrite_bulk_docs(body_dict, tenant_id)
        elif request.method in ["PUT"] and not path.startswith("_"):
            # Single document creation/update
            body_dict = inject_tenant_into_doc(body_dict, tenant_id)

        body = json.dumps(body_dict).encode()

    # Forward request to CouchDB
    try:
        async with httpx.AsyncClient() as client:
            # Copy headers, excluding authorization and host
            headers = {}
            for key, value in request.headers.items():
                if key.lower() not in ["authorization", "host"]:
                    headers[key] = value

            # For POST/PUT requests with body, ALWAYS set Content-Type to application/json
            # This is critical for CouchDB endpoints like _revs_diff
            # We override the client's Content-Type because CouchDB requires application/json
            if body and request.method in ["POST", "PUT", "PATCH"]:
                # Remove any existing content-type headers (case-insensitive)
                headers_to_remove = [k for k in headers.keys() if k.lower() == "content-type"]
                for k in headers_to_remove:
                    del headers[k]

                # Always set to application/json for CouchDB
                headers["Content-Type"] = "application/json"
                logger.debug(f"Set Content-Type to application/json for {request.method} with body")

            # Add CouchDB authentication (basic auth for internal connection)
            basic_auth = get_basic_auth_header()
            if basic_auth:
                headers["Authorization"] = basic_auth
                logger.debug(f"Using Basic Auth for CouchDB")

            logger.debug(f"Forwarding: {request.method} /{path} -> {couchdb_url}")
            logger.debug(f"  Body: {len(body) if body else 0} bytes")

            # Use longer timeout for long-polling requests (like _changes?feed=longpoll)
            # These connections can be open for a long time waiting for changes
            is_longpoll = "_changes" in path and "feed=longpoll" in str(request.url)
            request_timeout = 300.0 if is_longpoll else 30.0  # 5 min for long-poll, 30s for others

            response = await client.request(
                method=request.method,
                url=couchdb_url,
                headers=headers,
                content=body,
                follow_redirects=True,
                timeout=request_timeout
            )

            logger.debug(f"CouchDB response: {response.status_code} for {request.method} /{path}")

            # Filter response for tenant enforcement
            response_content = response.content
            if ENABLE_TENANT_MODE and response.status_code == 200 and response.headers.get("content-type", "").startswith("application/json"):
                if path in ["_all_docs", "_find"]:
                    response_content = filter_response_documents(response_content, tenant_id)

            # Return response from CouchDB
            return Response(
                content=response_content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type")
            )

    except httpx.ConnectError as e:
        logger.error(f"Failed to connect to CouchDB: {e}")
        raise HTTPException(status_code=503, detail="CouchDB server unavailable")
    except Exception as e:
        import traceback
        logger.error(f"Proxy error for {request.method} /{path}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    """Health check endpoint - pings CouchDB to verify it's alive"""
    try:
        async with httpx.AsyncClient() as client:
            headers = {}
            basic_auth = get_basic_auth_header()
            if basic_auth:
                headers["Authorization"] = basic_auth

            response = await client.get(
                f"{COUCHDB_INTERNAL_URL}/",
                headers=headers,
                timeout=5.0
            )
            if response.status_code == 200:
                return {
                    "status": "ok",
                    "service": "couchdb-jwt-proxy",
                    "couchdb": "connected"
                }
            else:
                logger.warning(f"CouchDB returned status {response.status_code}")
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
            "auth": "/auth/token",
            "health": "/health"
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=PROXY_HOST,
        port=PROXY_PORT,
        log_level=LOG_LEVEL.lower()
    )
