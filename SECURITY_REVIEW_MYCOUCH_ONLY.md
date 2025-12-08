# MyCouch Security Review - Server-Side Only

**Date:** 2025-12-07
**Scope:** MyCouch Server-Side Responsibilities Only
**Status:** 5 of 7 issues completed or clarified

---

## ✅ Completed Items (Removed from work list)

The following items have been completed and are no longer part of the active security work:

1. ✅ JWT Fallback Authentication Bypass (CRITICAL - CWE-287) - FIXED
2. ✅ Clerk JWT Template Configuration (CRITICAL - CWE-345) - FIXED
3. ✅ Tenant Membership Validation (HIGH - CWE-639) - FIXED
4. ✅ JWT Token Leakage in Logs (HIGH - CWE-532) - FIXED
5. ✅ Session Timeout Strategy (MEDIUM-HIGH - CWE-613) - CLARIFIED

See `security-review.md` for detailed information on completed fixes.

---

## 🔴 CRITICAL - MyCouch Server-Side Only

### 1. CouchDB Underlying Configuration Not Documented
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

### 2. No Rate Limiting on Auth Endpoints
**Severity:** HIGH | **CWE-770 (Allocation of Resources Without Limits)**

The authentication endpoints have no documented rate limiting. Attack scenario:

```python
for i in range(10000):
    request(jwt)  # Brute force attempt
```

**Impact:**
- DoS against MyCouch
- Exhausts database connections
- High CPU usage from repeated JWT validation
- Potential Clerk API quota exhaustion

**Fix Required:**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/choose-tenant")
@limiter.limit("10/minute")  # Per IP
async def choose_tenant(tenantId: str):
    ...

@app.get("/my-tenants")
@limiter.limit("30/minute")
async def my_tenants():
    ...

# Protected endpoints need limits:
# POST /choose-tenant
# GET /my-tenants
# GET /roady/*
# GET /couch-sitter/*
```

**Implementation:** ~2-3 hours

---

## 🟠 HIGH - MyCouch Server-Side Only

### 1. No Session Logging & Monitoring
**Severity:** HIGH | **CWE-644 (Improper Restriction of Rendered UI Layers)**

MyCouch has no audit trail for authentication events.

**Required Implementation:**
```python
import json
from datetime import datetime

# Log all auth events
async def log_auth_event(
    event: str,
    user_id: str,
    tenant_id: str,
    status: str,
    details: dict = None,
    remote_addr: str = None
):
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": event,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "status": status,
        "remote_addr": remote_addr,
        "details": details or {}
    }
    
    # Log to audit log (not standard application log)
    audit_logger.info(json.dumps(log_entry))
    
    # Alert on suspicious patterns
    if await check_suspicious_pattern(user_id, remote_addr):
        alert_security_team(log_entry)

# Events to log:
# - Successful JWT validation
# - Failed authentication (expired, invalid sig, missing claim)
# - Successful tenant switch
# - Unauthorized tenant access attempts
# - Failed authorization (403 responses)
```

**Implementation:** ~4-6 hours

---

## 🟡 MEDIUM - MyCouch Server-Side Only

### 1. Personal Tenant Deletion Not Prevented
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

**Implementation:** ~1-2 hours

---

## ⚪ CLIENT-SIDE ONLY (Not MyCouch responsibility)

These items are **Application responsibility**, not MyCouch server:

### ⚪ Invite Token Security (Client-side CSRF + Server-side expiry)
**Severity:** MEDIUM | **CWE-640 (Weak Password Recovery Mechanism)**

**MyCouch Responsibility:**
- ✅ Validate token format and entropy
- ✅ Enforce single-use (mark as used after acceptance)
- ✅ Check expiration dates
- ✅ Return 400/404 for invalid/expired invites

**Client Application Responsibility:**
- ❌ Implement CSRF protection on accept endpoint (SameSite cookies, CSRF tokens)
- ❌ Secure token storage and transmission
- ❌ Rate limiting on accept attempts
- ❌ User feedback on expired/invalid invites

**Note:** Client is responsible for protecting the invite acceptance endpoint with CSRF mechanisms.

---

### ⚪ CSRF Protection on State-Changing Operations
**Severity:** MEDIUM | **CWE-352 (Cross-Site Request Forgery - CSRF)**

**MyCouch Responsibility:**
- ✅ Accept JWT in Authorization header (immune to CSRF from cookies)
- ✅ Validate request signatures if needed

**Client Application Responsibility:**
- ❌ Implement CSRF token validation for any form submissions
- ❌ Set SameSite cookie flags (if using cookies)
- ❌ Verify Origin headers in browser
- ❌ Implement double-submit cookie pattern (if applicable)

**Why This Is Client-Side:**
MyCouch validates JWT in Authorization header, which is immune to CSRF. Client-side CSRF protection only needed if:
1. Using cookies for auth (not recommended with JWT)
2. Accepting form data without JWT
3. Making cross-origin requests

---

### ⚪ Tenant Switching Race Condition
**Severity:** MEDIUM | **CWE-362 (Concurrent Execution using Shared Resource)**

**MyCouch Responsibility:**
- ✅ Update Clerk session metadata immediately
- ✅ Return 401 if JWT missing active_tenant_id claim

**Client Application Responsibility:**
- ❌ Retry JWT refresh until new tenant_id appears in token
- ❌ Wait for token propagation before making requests
- ❌ Implement client-side synchronization

**Client-Side Pattern:**
```typescript
async function switchTenant(tenantId: string) {
    // Call MyCouch endpoint
    await fetch("/choose-tenant", {
        method: "POST",
        body: JSON.stringify({tenantId}),
        headers: {"Authorization": `Bearer ${token}`}
    });
    
    // RETRY: Clerk JWT update may take time
    for (let i = 0; i < 10; i++) {
        const newToken = await clerk.session.getToken();
        const decoded = jwtDecode(newToken);
        
        if (decoded.active_tenant_id === tenantId) {
            return; // Success - tenant updated
        }
        
        await delay(200); // Wait and retry
    }
    
    throw new Error("Tenant switch timeout");
}
```

---

### ⚪ Session Timeout & Token Refresh
**Severity:** MEDIUM-HIGH | **CWE-613 (Insufficient Session Expiration)**

**MyCouch Responsibility:**
- ✅ Validate JWT expiration
- ✅ Return 401 if token expired

**Client Application Responsibility:**
- ❌ Refresh JWT before expiry (5 min buffer)
- ❌ Store token securely
- ❌ Handle 401 responses
- ❌ Implement inactivity timeout
- ❌ Redirect to login on session failure

**Why This Is Client-Side:**
- Clerk manages session lifecycle (7 days)
- Client controls when token is used
- Server can only validate, not enforce refresh timing
- Multiple frontends need independent refresh logic

**Reference:** See `docs/JWT_SESSION_ARCHITECTURE.md` for implementation guide.

---

## Summary Table

| Issue | Type | Scope | Status |
|-------|------|-------|--------|
| JWT Fallback | Auth | Server | ✅ Fixed |
| JWT Template | Config | Server | ✅ Fixed |
| Tenant Membership | Auth | Server | ✅ Fixed |
| Token Leakage | Logging | Server | ✅ Fixed |
| Session Timeout | Arch | Both | ✅ Clarified |
| CouchDB Security | Ops | Server | ⏳ Pending (1-2 hrs) |
| Rate Limiting | DoS | Server | ⏳ Pending (2-3 hrs) |
| Audit Logging | Monitoring | Server | ⏳ Pending (4-6 hrs) |
| Personal Tenant | Data | Server | ⏳ Pending (1-2 hrs) |
| Invite Tokens | Security | Client | 📝 Doc in `docs/JWT_SESSION_ARCHITECTURE.md` |
| CSRF Protection | Security | Client | 📝 Doc in `docs/JWT_SESSION_ARCHITECTURE.md` |
| Race Conditions | Sync | Client | 📝 Doc in `docs/JWT_SESSION_ARCHITECTURE.md` |
| Token Refresh | Session | Client | 📝 Doc in `docs/JWT_SESSION_ARCHITECTURE.md` |

---

## MyCouch Server-Side Work Remaining

**🔴 CRITICAL (Before Production)**
- [ ] CouchDB security documentation (1-2 hours)
- [ ] Rate limiting on endpoints (2-3 hours)

**🟠 HIGH (Fix ASAP)**
- [ ] Session logging & monitoring (4-6 hours)

**🟡 MEDIUM (Before 1st Users)**
- [ ] Personal tenant protection (1-2 hours)

**Total Server-Side Work:** ~10-13 hours

---

## Client-Side Work (Reference Only)

These items need to be handled by the frontend application(s). See `docs/JWT_SESSION_ARCHITECTURE.md` for implementation guidance:

- Token refresh before expiry
- Handling 401 responses
- Inactivity timeout
- CSRF protection (if using cookies)
- Tenant switch synchronization
- Token secure storage

---

**Document Version:** 2.0  
**Last Updated:** 2025-12-07  
**Focus:** MyCouch Server-Side Only
