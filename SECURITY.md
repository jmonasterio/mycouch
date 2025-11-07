# Security Audit Report - MyCouchDB JWT Proxy

**Audit Date**: 2025-11-07
**Current Risk Level**: **MEDIUM** 🟠

## Architecture Context

- **Authentication**: Clerk JWT (RS256) required for all requests
- **Transport**: HTTPS in production
- **Use Case**: Multi-domain PWA support (requires permissive CORS)
- **Deployment**: Remote CouchDB at argw.com

---

## CRITICAL RISKS 🔴

### 1. **Missing COUCHDB_PASSWORD in .env**
**Location**: `.env:16`
**Current State**: `COUCHDB_PASSWORD=` (empty)

**Risk**: Unauthenticated connection to CouchDB
**Impact**: If CouchDB has no authentication configured, anyone on the network can access it directly, bypassing the JWT proxy entirely.

**Recommendation**:
```bash
# Set a strong password in .env
COUCHDB_PASSWORD=<strong-random-password>

# Ensure CouchDB is configured with admin credentials
# Visit http://argw.com:5984/_utils and configure admin user
```

**Mitigation Priority**: IMMEDIATE

---



---

## HIGH RISKS 🟠

### 4. **Tenant Isolation Bypass in Bulk Operations**
**Location**: `main.py:279-281`

```python
if TENANT_FIELD not in doc:
    doc[TENANT_FIELD] = tenant_id
```

**Risk**: Malicious clients can specify `tenant_id` in documents sent to `_bulk_docs`, and the proxy will NOT override it.

**Attack Scenario**:
1. Authenticated user from tenant "A" sends bulk docs
2. User includes `{"_id": "doc1", "tenant_id": "B", "data": "stolen"}` in the bulk request
3. Proxy sees `tenant_id` already exists, doesn't override it
4. Document is written to tenant "B"'s data

**Impact**: Complete tenant isolation breach - users can read/write any tenant's data

**Recommendation**:
```python
# main.py:272-284 - Replace with:
def rewrite_bulk_docs(body: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Inject tenant into bulk docs"""
    if not ENABLE_TENANT_MODE:
        return body

    if "docs" in body:
        for doc in body["docs"]:
            # ALWAYS override tenant_id (remove the condition)
            doc[TENANT_FIELD] = tenant_id

            # Also validate that _deleted docs have the correct tenant
            if not doc.get("_deleted", False):
                # For new docs, force tenant
                pass
            else:
                # For deletions, we need to verify the doc belongs to this tenant
                # This requires a separate GET request or trust CouchDB's rev check
                pass

    logger.debug(f"Injected tenant into {len(body.get('docs', []))} documents")
    return body
```

**Mitigation Priority**: CRITICAL for multi-tenant deployments

---

### 5. **NoSQL Injection in Tenant Query Rewriting**
**Location**: `main.py:255, 268`

```python
return f"{query_params}&start_key=\"{tenant_id}:\"&end_key=\"{tenant_id}:\ufff0\""
body["selector"][TENANT_FIELD] = tenant_id
```

**Risk**: If tenant_id contains quotes, backslashes, or special characters, could break query parsing

**Attack Scenario**:
```
tenant_id = 'tenant1":"", "malicious_selector": {"$gt": null}'
```

**Impact**: Potential bypass of tenant isolation filters, access to unauthorized data

**Recommendation**:
```python
# Add tenant_id validation at extraction point (main.py:193-201)
def extract_tenant(payload: Dict[str, Any]) -> Optional[str]:
    """Extract tenant ID from JWT payload"""
    if not ENABLE_TENANT_MODE:
        return None
    tenant = payload.get(TENANT_CLAIM)
    if not tenant:
        logger.warning(f"Missing tenant claim '{TENANT_CLAIM}' in JWT")
        return None

    # Validate tenant_id format (alphanumeric, dash, underscore only)
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', tenant):
        logger.error(f"Invalid tenant_id format: {tenant}")
        return None

    return tenant
```

**Mitigation Priority**: HIGH

---

### 6. **No Rate Limiting**

**Risk**: System vulnerable to:
- Brute force attacks on API keys
- Token generation abuse
- DDoS attacks
- Resource exhaustion

**Impact**: Service disruption, cost escalation, potential security breaches

**Recommendation**:
```python
# Add to main.py after imports
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Apply to token endpoint
@app.post("/auth/token", response_model=TokenResponse)
@limiter.limit("10/minute")  # 10 requests per minute per IP
async def get_token(request: Request, token_request: TokenRequest):
    ...

# Apply to proxy endpoint
@app.api_route("/{path:path}", methods=[...])
@limiter.limit("1000/minute")  # Adjust based on expected load
async def proxy_couchdb(request: Request, ...):
    ...
```

**Mitigation Priority**: HIGH

---

## MEDIUM RISKS 🟡

### 7. **CORS Configuration with Credentials**
**Location**: `main.py:332-338`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # ⚠️
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Context**: You require Clerk JWT and support multiple domains for PWA

**Risk**: While JWT authentication mitigates most CSRF risks, `allow_origins=["*"]` + `allow_credentials=True` is not allowed by browsers and may cause CORS failures.

**Current Behavior**: Browsers will BLOCK requests with this configuration when credentials are included.

**Recommendation**:
```python
# Option 1: Dynamic CORS (recommended for multiple domains)
from fastapi.middleware.cors import CORSMiddleware

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")
# Set in .env: ALLOWED_ORIGINS=https://app1.com,https://app2.com,https://app3.com

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS[0] else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "HEAD"],
    allow_headers=["Authorization", "Content-Type"],
)

# Option 2: If you truly need wildcard
# Remove allow_credentials=True, or implement dynamic origin reflection
```

**Mitigation Priority**: MEDIUM (may already be causing issues)

---

### 8. **Audience Verification Disabled for Clerk JWT**
**Location**: `main.py:178`

```python
payload = jwt.decode(
    token,
    signing_key.key,
    algorithms=["RS256"],
    audience=None,
    options={"verify_aud": False}
)
```

**Risk**: Clerk JWTs from ANY Clerk application (not just yours) can authenticate

**Impact**: If someone obtains a valid Clerk JWT from a different application using the same Clerk instance, they could use it here

**Recommendation**:
```python
# Add to .env
CLERK_AUDIENCE=https://argw.com  # Your proxy's URL

# Update verification
CLERK_AUDIENCE = os.getenv("CLERK_AUDIENCE")

payload = jwt.decode(
    token,
    signing_key.key,
    algorithms=["RS256"],
    audience=CLERK_AUDIENCE,
    options={"verify_aud": True if CLERK_AUDIENCE else False}
)
```

**Mitigation Priority**: MEDIUM

---

### 9. **Error Information Disclosure**
**Location**: `main.py:586-587`

```python
logger.error(f"Proxy error for {request.method} /{path}: {e}")
logger.error(f"Traceback: {traceback.format_exc()}")
```

**Risk**: Full stack traces in logs reveal internal structure, library versions, file paths

**Impact**: Aids attackers in reconnaissance, may reveal vulnerabilities

**Recommendation**:
```python
# Log detailed errors only in DEBUG mode
if logger.level <= logging.DEBUG:
    logger.error(f"Traceback: {traceback.format_exc()}")
else:
    logger.error(f"Proxy error for {request.method} /{path}: {type(e).__name__}")

# Always return generic errors to clients (already done correctly)
raise HTTPException(status_code=500, detail="Internal server error")
```

**Mitigation Priority**: MEDIUM

---

### 10. **Missing Input Validation on Path Parameters**
**Location**: `main.py:401`

```python
@app.api_route("/{path:path}", methods=[...])
```

**Risk**:
- Path traversal attempts (e.g., `../../etc/passwd`)
- Directory traversal in database names
- Special characters causing unexpected behavior

**Impact**: Potential access to unintended CouchDB endpoints

**Recommendation**:
```python
# Add path validation in proxy_couchdb function
def validate_path(path: str) -> bool:
    """Validate path for security issues"""
    # Block path traversal
    if ".." in path:
        return False
    # Block null bytes
    if "\x00" in path:
        return False
    # Add other checks as needed
    return True

# In proxy_couchdb
if not validate_path(path):
    logger.warning(f"Invalid path attempted: {path}")
    raise HTTPException(status_code=400, detail="Invalid path")
```

**Mitigation Priority**: MEDIUM

---

### 11. **COPY Method May Bypass Tenant Isolation**
**Location**: `main.py:398`

```python
methods=["GET", "POST", "PUT", "DELETE", "HEAD", "COPY", "PATCH"]
```

**Risk**: CouchDB COPY method copies documents. If not properly handled, could copy documents across tenant boundaries.

**Impact**: Tenant isolation breach

**Recommendation**:
```python
# Test COPY method with tenant mode
# If it bypasses isolation, either:
# 1. Block COPY method entirely
# 2. Implement COPY-specific tenant validation

# Option 1: Remove COPY
methods=["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"]

# Option 2: Add COPY validation in proxy_couchdb
if request.method == "COPY" and ENABLE_TENANT_MODE:
    # Parse Destination header
    destination = request.headers.get("Destination")
    if destination:
        # Validate destination document will have correct tenant_id
        # This is complex - recommend blocking COPY in tenant mode
        raise HTTPException(status_code=403, detail="COPY not allowed in tenant mode")
```

**Mitigation Priority**: MEDIUM (test first to confirm risk)

---

### 12. **System Document Protection Insufficient**
**Location**: `main.py:205`

```python
def is_system_doc(doc_id: str) -> bool:
    return doc_id.startswith("_")
```

**Risk**: This check blocks system docs, but the broader endpoint validation may not cover all CouchDB admin endpoints

**Impact**:
- Access to `_design` docs reveals view/query logic
- Access to `_security` could modify database security
- Access to `_local` docs (replication state)

**Recommendation**:
```python
# Expand system document check
def is_system_doc(doc_id: str) -> bool:
    """Check if document ID is a system document"""
    return doc_id.startswith("_")

# Add admin endpoint blocklist
BLOCKED_ENDPOINTS = {
    "/_security",
    "/_purge",
    "/_ensure_full_commit",
    "/_bulk_get",
    "/_all_dbs",
    "/_active_tasks",
    "/_config",
    "/_users",
    "/_replicator",
    "/_node",
    "/_up",
}

def is_endpoint_allowed(path: str, method: str) -> bool:
    """Check if endpoint is allowed"""
    if not ENABLE_TENANT_MODE:
        return True

    # Block admin endpoints
    clean_path = "/" + path.lstrip("/")
    if clean_path in BLOCKED_ENDPOINTS:
        return False

    # Existing checks...
```

**Mitigation Priority**: MEDIUM

---

## LOW RISKS 🟢

### 13. **Token Fragments in Logs**
**Location**: `main.py:443-447`

```python
token_preview = get_token_preview(token)
log_msg = f"... | Token: {token_preview}"
```

**Risk**: Token previews (first/last 10 chars) in logs could aid brute force

**Recommendation**: Only log tokens in DEBUG mode

---

### 14. **Logging Sensitive Data**
**Location**: `main.py:349`

**Risk**: Username in INFO level logs

**Recommendation**: Log usernames only in DEBUG mode

---

### 15. **No Request ID Tracking**

**Impact**: Difficult to trace requests across distributed logs

**Recommendation**: Add request ID middleware for debugging

---

### 16. **PROXY_HOST=0.0.0.0**
**Location**: `.env:20`

**Current**: Listening on all network interfaces

**Recommendation**: If behind reverse proxy, use `127.0.0.1`. Otherwise, ensure firewall rules restrict access.

---

## CONFIGURATION CHECKLIST

### Before Production Deployment

- [ ] Set strong `COUCHDB_PASSWORD` in `.env`
- [ ] Fix tenant isolation bypass in `_bulk_docs`
- [ ] Add tenant_id validation to prevent injection
- [ ] Implement rate limiting
- [ ] Configure specific CORS origins or dynamic origin validation
- [ ] Enable Clerk JWT audience verification
- [ ] Deploy behind HTTPS reverse proxy (nginx/Caddy)
- [ ] Set up log aggregation and monitoring
- [ ] Test tenant isolation thoroughly
- [ ] Penetration testing
- [ ] Security audit by external party

### Operational Security

- [ ] Rotate API keys quarterly
- [ ] Monitor logs for suspicious activity
- [ ] Set up alerts for failed authentication attempts
- [ ] Regular dependency updates (Python packages)
- [ ] Backup CouchDB data regularly
- [ ] Test disaster recovery procedures
- [ ] Document security incident response plan

---

## Environment Configuration Status

**Current .env Configuration:**
```bash
CLERK_ISSUER_URL=<configured>         # ✅ Good
COUCHDB_INTERNAL_URL=http://argw.com:5984  # ⚠️ HTTP (you mentioned HTTPS is used)
COUCHDB_USER=admin                    # ✅ Good
COUCHDB_PASSWORD=                     # 🔴 EMPTY - CRITICAL
ENABLE_TENANT_MODE=true               # ✅ Good
PROXY_HOST=0.0.0.0                    # ⚠️ Review
PROXY_PORT=5985                       # ✅ Good
```

**Note**: You mentioned using HTTPS, but `.env` shows HTTP. If you're using HTTPS in production via reverse proxy, update documentation. If the proxy connects to CouchDB via HTTP over internal network, ensure network is secured.

---

## Testing Recommendations

### Tenant Isolation Testing
```bash
# Test 1: Bulk docs with tenant override attempt
curl -X POST http://localhost:5985/mydb/_bulk_docs \
  -H "Authorization: Bearer $TOKEN_TENANT_A" \
  -H "Content-Type: application/json" \
  -d '{
    "docs": [
      {"_id": "doc1", "tenant_id": "tenant_b", "data": "malicious"}
    ]
  }'
# Expected: document should be saved with tenant_id="tenant_a"
# Current behavior: May save with tenant_id="tenant_b" (VULNERABILITY)

# Test 2: Query injection via tenant_id
# Create JWT with malicious tenant_id and verify it's rejected

# Test 3: COPY method across tenants
# Verify COPY cannot duplicate documents to other tenants

# Test 4: Design document access
# Verify tenants cannot access _design docs

# Test 5: Rate limiting
# Send 100 requests in 1 second, verify throttling
```

---

## Incident Response

If tenant isolation breach is suspected:
1. Immediately disable affected tenant accounts
2. Audit access logs for the compromised tenant
3. Review all documents for unauthorized `tenant_id` modifications
4. Rotate API keys and JWT secrets
5. Notify affected users per data breach protocol
6. Apply security patches immediately

---

## References

- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [CouchDB Security Best Practices](https://docs.couchdb.org/en/stable/intro/security.html)
- [JWT Best Current Practices](https://datatracker.ietf.org/doc/html/rfc8725)
- [CORS Security Considerations](https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS)

---

**Last Updated**: 2025-11-07
**Next Review**: Quarterly or after significant code changes
