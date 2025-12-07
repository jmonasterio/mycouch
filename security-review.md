# MyCouch Security Review

**Date:** 2025-12-07  
**Reviewer:** Security Specialist Analysis  
**Status:** Critical Issues Identified  

---

## Executive Summary

MyCouch's architecture is fundamentally sound, but the implementation has **critical security gaps** that must be addressed before production deployment. The most severe issue is the JWT fallback mechanism that can bypass tenant isolation entirely.

**Risk Level:** 🔴 **CRITICAL**

---

## CRITICAL ISSUES

### 1. JWT Fallback Creates Authentication Bypass
**Severity:** CRITICAL | **CWE-287 (Improper Authentication)**
**Status:** ✅ **FIXED** (2025-12-07)

**What was vulnerable:**
The backend had a fallback that synchronously called Clerk's API when `active_tenant_id` was missing from the JWT:

```python
# VULNERABLE PATTERN (REMOVED):
tenant_id = payload.get("active_tenant_id")
if not tenant_id:
    tenant_id = clerk_service.get_user_active_tenant(user_id)  # ❌ REMOVED
```

**Why critical:**
- Attacker could send request with expired/stale JWT
- Backend fallback would call Clerk API and grant access anyway
- Tenant isolation could be completely bypassed
- Cross-tenant data leakage possible

**Fix implemented:**
```python
# STRICT ENFORCEMENT (IMPLEMENTED):
active_tenant_id = payload.get("active_tenant_id") or payload.get("tenant_id")

if not active_tenant_id and payload.get("metadata"):
    active_tenant_id = payload.get("metadata").get("active_tenant_id")

if active_tenant_id:
    logger.debug(f"Found active tenant in JWT claims: {active_tenant_id}")
    return active_tenant_id

# NO FALLBACK - Reject immediately if claim missing
logger.warning(f"Missing active_tenant_id in JWT for roady request - rejecting")
raise HTTPException(
    status_code=401, 
    detail="Missing active_tenant_id claim in JWT. Please refresh your token."
)
```

**Changes made:**
- ✅ Removed `clerk_service.get_user_active_tenant()` fallback call
- ✅ Replaced with strict JWT claim validation
- ✅ Returns 401 error immediately if active_tenant_id missing
- ✅ Added 20+ comprehensive security tests
- ✅ Improved logging for security audit trail

**Test coverage:**
- ✅ Valid JWT with active_tenant_id accepted
- ✅ Stale JWT without claim rejected (no fallback)
- ✅ Clerk API NOT called for missing claims
- ✅ Proper error logging for audit trail
- ✅ All JWT claim variations tested
- ✅ CWE-287 compliance verified

**Code changes:**
- File: `src/couchdb_jwt_proxy/main.py` lines 415-431
- File: `tests/test_jwt_fallback_fix.py` (new test file)

---

### 2. Clerk JWT Template Configuration Not Enforced
**Severity:** CRITICAL | **CWE-345 (Insufficient Verification of Data Authenticity)**

The entire tenant isolation model depends on Clerk injecting `active_tenant_id` into the JWT, but:

- ❌ No verification that this template is configured in production Clerk Dashboard
- ❌ No automated tests validating the claim is present
- ❌ Frontend doesn't validate claim before making requests
- ❌ Missing configuration silently degrades to fallback (see Issue #1)

**Required Clerk Configuration:**
```json
{
  "Template Name": "roady",
  "Claims Mapping": {
    "active_tenant_id": "{{session.public_metadata.active_tenant_id}}",
    "tenant_id": "{{session.public_metadata.active_tenant_id}}"
  }
}
```

**Action Items:**
1. Manually verify Clerk Dashboard has template configured
2. Add automated validation in `/choose-tenant` endpoint to verify claim was injected
3. Log warning if JWT missing tenant claim
4. Frontend must decode and validate claim presence before any DB operation

---

### 3. No Rate Limiting on Auth Endpoints
**Severity:** HIGH | **CWE-770 (Allocation of Resources Without Limits)**

The fallback mechanism has no documented rate limiting. Attack scenario:

```
for i in range(10000):
    request(old_jwt)  # Triggers Clerk API call
```

**Impact:**
- DoS against Clerk infrastructure (costs money)
- Exhausts Clerk API quota
- MyCouch becomes bottleneck calling Clerk repeatedly
- Potential Clerk account suspension

**Fix Required:**
```python
# Rate limiting on all auth endpoints:
from slowapi import Limiter

limiter = Limiter(key_func=get_remote_address)

@app.post("/choose-tenant")
@limiter.limit("10/minute")  # Per IP
async def choose_tenant(tenantId: str):
    ...

@app.get("/my-tenants")
@limiter.limit("30/minute")
async def my_tenants():
    ...
```

---

## HIGH-RISK ISSUES

### 4. Tenant Membership Not Validated Before Switch
**Severity:** HIGH | **CWE-639 (Authorization Bypass Through User-Controlled Key)**

The `/choose-tenant` endpoint updates Clerk session metadata, but documentation doesn't explicitly show validation that user belongs to the tenant:

```python
async def choose_tenant(tenantId: str, user_id: str):
    # ❌ Does this validate membership?
    update_clerk_session(user_id, tenantId)
```

**Attack Vector:**
- Attacker guesses tenant IDs from other users
- Calls `/choose-tenant` with unauthorized tenant
- If not validated, gets access to another user's data

**Required Implementation:**
```python
async def choose_tenant(tenantId: str, user_id: str):
    # Validate user is actually a member
    user_tenants = await get_user_tenants(user_id)
    tenant_ids = [t.id for t in user_tenants]
    
    if tenantId not in tenant_ids:
        logger.warning(f"Unauthorized tenant switch attempt: {user_id} -> {tenantId}")
        raise HTTPException(403, "Not a member of this tenant")
    
    # Only then update session
    await update_clerk_session(user_id, tenantId)
```

---

### 5. CouchDB Underlying Configuration Not Documented
**Severity:** HIGH | **CWE-276 (Incorrect Default Permissions)**

MyCouch proxies to CouchDB, but critical security setup is not documented:

**Missing Documentation:**
- [ ] Is CouchDB's "admin party" mode disabled? (default = anyone is admin!)
- [ ] Is HTTPS/TLS enforced? (HTTP exposes all data)
- [ ] How are admin credentials secured?
- [ ] Are design documents restricted to admins only?
- [ ] Are `_security` documents properly configured per database?
- [ ] Are replication credentials managed securely?

**Critical CouchDB Setup Checklist:**

```
Security Items:
□ Admin user created, admin party disabled
□ All HTTP traffic redirected to HTTPS (TLS 1.2+)
□ CouchDB bound to internal network only (VPS firewall)
□ Default credentials removed
□ Design docs restricted to admins in _security
□ No world-readable databases
□ Replication credentials stored in environment variables
□ Regular security patches applied

Operational Items:
□ Audit logging enabled (track who accesses what)
□ Monitoring alerts for failed auth attempts
□ Backup encryption (you mention R2, verify with KMS)
□ Regular backup testing/restore validation
□ Database compression enabled
```

**Action Required:** Document CouchDB security setup in a new `docs/couchdb-security.md` file.

---

### 6. JWT Token Leakage in Request Logs
**Severity:** HIGH | **CWE-532 (Insertion of Sensitive Information into Log File)**

MyCouch accepts JWT in Authorization header and passes requests to CouchDB. If these logs are exposed:

```
[2025-12-07] POST /db/_all_docs
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Risk:**
- If logs leaked, attacker gets valid JWTs
- JWT validity depends on expiry time (could be hours/days away)
- Log exposure from monitoring tools, ELK stacks, etc.

**Better Pattern:**
```
Client → MyCouch (Authorization: Bearer JWT)
    ↓ (MyCouch validates JWT)
MyCouch → CouchDB (CouchDB session cookie only, NO JWT)
    ↓ (CouchDB returns data)
MyCouch → Client (Data only)
```

**Implementation:**
- MyCouch exchanges JWT for CouchDB session token
- Only session token passed to CouchDB
- Logging/monitoring never sees raw JWT

---

### 7. No Documented Session Timeout Strategy
**Severity:** MEDIUM-HIGH | **CWE-613 (Insufficient Session Expiration)**

From documentation: "Clerk sessions typically last 7 days"

**Gaps:**
- ❌ No mention of token refresh mechanics in MyCouch
- ❌ Offline users could have stale/expired tokens
- ❌ No graceful error handling when token expires
- ❌ No forced re-authentication after inactivity

**Required Implementation:**
```python
# Track token expiration
def extract_token_expiry(token: str) -> datetime:
    payload = jwt.decode(token)
    return datetime.fromtimestamp(payload['exp'])

# Implement refresh before expiry
async def refresh_jwt_if_needed():
    if token_expires_in_next(minutes=5):
        new_token = await clerk_api.refresh_token()
        store_token(new_token)
```

---

## MEDIUM-RISK ISSUES

### 8. Invite Token Security Vulnerabilities
**Severity:** MEDIUM | **CWE-640 (Weak Password Recovery Mechanism)**

From TODO.md, invites use token-based system:

```json
{
  "_id": "invite:uuid-123",
  "token": "token-abc-456",
  "invitee_email": "paul@example.com",
  "expires_at": "2025-01-17T00:00:00Z"
}
```

**Vulnerabilities:**
- ❌ Token format unspecified (could be predictable)
- ❌ Entropy not documented (minimum 32 bytes required)
- ❌ No timing-attack resistance mentioned
- ❌ No single-use enforcement
- ❌ No CSRF protection on `/api/invite/accept`

**Security Requirements:**
```python
import secrets
import hmac

def generate_invite_token() -> str:
    # Cryptographically secure random token
    return secrets.token_urlsafe(32)  # 256 bits entropy

def verify_invite_token(token: str, stored_token: str) -> bool:
    # Timing-attack resistant comparison
    return hmac.compare_digest(token, stored_token)

# Single-use enforcement:
async def accept_invite(token: str):
    invite = await db.get_invite_by_token(token)
    
    if not invite:
        raise HTTPException(404, "Invalid invite")
    
    if invite.status != "pending":
        raise HTTPException(400, "Invite already used")
    
    if datetime.now() > invite.expires_at:
        raise HTTPException(400, "Invite expired")
    
    # Accept the invite
    await add_user_to_tenant(invite.invitee_email, invite.tenant_id)
    
    # Invalidate token immediately (single-use)
    await db.update_invite(token, status="accepted")
```

---

### 9. No CSRF Protection Mentioned
**Severity:** MEDIUM | **CWE-352 (Cross-Site Request Forgery - CSRF)**

The PWA accepts JWT in headers (which is good), but state-changing operations need explicit CSRF protection:

**Current Risk:**
```html
<!-- Attacker's site -->
<form action="https://mycouch.example.com/choose-tenant" method="POST">
  <input name="tenantId" value="attacker-tenant-123">
</form>
```

**Required Mitigations:**
```python
# 1. Require CSRF token for state changes
@app.post("/choose-tenant")
async def choose_tenant(request: Request):
    csrf_token = request.headers.get("X-CSRF-Token")
    if not csrf_token or csrf_token != session.get("csrf_token"):
        raise HTTPException(403, "CSRF token invalid")

# 2. Enforce SameSite cookies
response.set_cookie(
    "session",
    value=session_id,
    samesite="Strict",  # Prevent cross-site cookie sending
    secure=True,
    httponly=True
)

# 3. Verify Origin header
allowed_origins = ["https://roady.example.com"]
origin = request.headers.get("Origin")
if origin not in allowed_origins:
    raise HTTPException(403, "Origin not allowed")
```

---

### 10. Tenant Switching Race Condition
**Severity:** MEDIUM | **CWE-362 (Concurrent Execution using Shared Resource with Improper Synchronization)**

The tenant switch flow has a timing window:

```
1. Frontend calls POST /choose-tenant ✅
2. Backend updates Clerk session metadata ✅
3. Frontend refreshes JWT (JWT still has OLD tenant) ⚠️
4. JWT updated with new tenant (delay here)
5. Frontend makes DB request
```

**Risk:**
- Between steps 2-4, frontend may make requests with stale JWT
- User briefly sees data from wrong tenant
- Data inconsistency in offline scenarios

**Mitigation:**
```python
# Frontend: Retry until new tenant appears in JWT
async def switchTenant(tenantId) {
    await apiCall("/choose-tenant", {tenantId});
    
    // Retry loop: ensure tenant propagated
    for (let i = 0; i < 10; i++) {
        const newToken = await Clerk.session.getToken();
        const decoded = jwt_decode(newToken);
        
        if (decoded.active_tenant_id === tenantId) {
            return; // Success
        }
        
        await delay(200); // Wait and retry
    }
    
    throw new Error("Tenant switch timeout");
}
```

---

### 11. Personal Tenant Deletion Not Prevented
**Severity:** LOW-MEDIUM | **CWE-405 (Incorrect Restriction of Rendered UI Layers or Frames)**

Design requires personal tenants to be immutable, but no documented enforcement:

```python
# Missing validation:
async def delete_tenant(tenantId: str, user_id: str):
    tenant = await db.get_tenant(tenantId)
    
    # ❌ Does this check if it's personal tenant?
    await db.delete_tenant(tenantId)
```

**Fix:**
```python
async def delete_tenant(tenantId: str, user_id: str):
    tenant = await db.get_tenant(tenantId)
    
    # Prevent deletion of personal tenant
    if tenant.personal == True:
        raise HTTPException(400, "Cannot delete personal tenant")
    
    # Validate ownership before deletion
    if tenant.owner_id != user_id:
        raise HTTPException(403, "Not the owner of this tenant")
    
    await db.delete_tenant(tenantId)
```

---

## ARCHITECTURAL RECOMMENDATIONS

### 1. Implement Zero-Trust Architecture

```
┌─────────────────────────────────────────────────────┐
│ MyCouch Proxy (Zero-Trust Boundary)                  │
├─────────────────────────────────────────────────────┤
│                                                       │
│  1. Validate JWT signature (RS256 from Clerk JWKS)  │
│  2. Check token expiry (reject if expired)          │
│  3. Require active_tenant_id claim (reject if missing)
│  4. Validate tenant membership (user belongs?)      │
│  5. Rate limit request (prevent abuse)              │
│  6. Log authentication event                        │
│  7. Only then forward to CouchDB                    │
│                                                       │
└─────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────┐
│ CouchDB (Internal Network Only)   │
│ - HTTPS only                       │
│ - Admin auth required              │
│ - Design docs read-only            │
└──────────────────────────────────┘
```

### 2. Add Security Logging & Monitoring

```python
# Log all auth events
logger.info({
    "event": "tenant_switch",
    "user_id": user_id,
    "from_tenant": old_tenant,
    "to_tenant": new_tenant,
    "timestamp": datetime.now().isoformat(),
    "status": "success" or "failed"
})

# Alert on suspicious patterns
if failed_auth_attempts > 5 in 1_minute:
    alert("Brute force detected: {ip_address}")

if unauthorized_tenant_switch_attempts > 3:
    alert("Unauthorized access attempt: {user_id}")
```

### 3. Implement Tenant Audit Trail

```json
{
  "_id": "audit:tenant_123:2025-12-07T10:30:00Z",
  "type": "audit",
  "tenant_id": "tenant_123",
  "event": "data_accessed",
  "user_id": "user_abc",
  "resource": "equipment_items",
  "action": "read",
  "count": 42,
  "timestamp": "2025-12-07T10:30:00Z"
}
```

---

## IMPLEMENTATION PRIORITY

### 🔴 CRITICAL (Must Fix Before Production)

1. ✅ **Remove JWT fallback** (COMPLETED 2025-12-07)
   - Fixed: `src/couchdb_jwt_proxy/main.py` lines 415-431
   - Tests: `tests/test_jwt_fallback_fix.py` (20+ tests)

2. **Verify Clerk JWT template** (15 minutes)
3. **Add tenant membership validation** (2-3 hours)
4. **Document CouchDB security setup** (1-2 hours)
5. **Implement rate limiting** (2-3 hours)

**Remaining:** ~2 days of work

### 🟠 HIGH (Fix ASAP)

6. **Session logging & monitoring** (4-6 hours)
7. **Token exchange pattern** (4-6 hours)
8. **Invite token security hardening** (2-3 hours)

**Total:** ~1 week of work

### 🟡 MEDIUM (Before 1st Users)

9. **CSRF protection** (4-6 hours)
10. **Tenant race condition handling** (2-4 hours)
11. **Personal tenant deletion prevention** (1-2 hours)

**Total:** ~3-4 days of work

---

## TESTING STRATEGY

### Security Tests Required

```python
# Test 1: JWT fallback removal
def test_missing_tenant_id_claim_rejected():
    token = create_jwt_without_tenant_claim()
    response = client.get("/my-tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    
# Test 2: Unauthorized tenant switch blocked
def test_unauthorized_tenant_switch():
    user_id = "user_abc"
    unauthorized_tenant = "tenant_xyz"  # User not member
    response = client.post(
        "/choose-tenant",
        json={"tenantId": unauthorized_tenant},
        headers={"Authorization": f"Bearer {valid_jwt}"}
    )
    assert response.status_code == 403

# Test 3: Invite token single-use enforcement
def test_invite_token_single_use():
    invite = create_invite()
    accept_response_1 = accept_invite(invite.token)
    assert accept_response_1.status_code == 200
    
    accept_response_2 = accept_invite(invite.token)
    assert accept_response_2.status_code == 400  # Already used

# Test 4: Rate limiting
def test_rate_limiting():
    for i in range(11):
        response = client.post("/choose-tenant", ...)
    assert response.status_code == 429  # Too Many Requests
```

---

## COMPLIANCE & AUDIT

- **GDPR:** Tenant isolation must be verified regularly
- **SOC 2:** Audit trails required for data access
- **HIPAA (if applicable):** Encryption at rest & in transit required
- **PCI DSS:** If storing payment info, additional controls needed

---

## EXTERNAL DEPENDENCIES

- **Clerk:** Dependency on Clerk's JWT validation
  - Verify JWKS endpoint is cached (not called on every request)
  - Document fallback if Clerk API unavailable
  
- **CouchDB:** Underlying database security
  - Regular patching schedule required
  - Version pinning in deployment

---

## Conclusion

MyCouch has a solid architectural foundation but requires **critical security fixes before production use**. The JWT fallback mechanism is the highest priority—removing it will eliminate the largest attack surface.

**Estimated Effort to Production-Ready:** 2-3 weeks of focused security hardening

**Risk of Skipping:** Data breaches, cross-tenant access, compliance violations

---

## Appendix: Quick Reference Checklist

```
CRITICAL:
[ ] Remove JWT fallback mechanism
[ ] Verify Clerk JWT template in production
[ ] Add tenant membership validation
[ ] Document CouchDB security setup
[ ] Implement rate limiting

HIGH:
[ ] JWT → session token exchange
[ ] Session logging & monitoring
[ ] Invite token security hardening

MEDIUM:
[ ] CSRF protection
[ ] Tenant switch race condition handling
[ ] Personal tenant immutability enforcement

OPERATIONAL:
[ ] Security test suite
[ ] Incident response plan
[ ] Regular security audits (quarterly)
[ ] Dependency vulnerability scanning
```

---

**Document Version:** 1.0  
**Last Updated:** 2025-12-07  
**Review Status:** Complete - Awaiting Implementation
