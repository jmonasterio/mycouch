# JWT Session Architecture & Token Lifecycle

## Overview

MyCouch uses JWT tokens from Clerk for authentication. This document clarifies the responsibility boundaries between the client application and the MyCouch server.

---

## Token Lifecycle

```
Client App (React/Web)                    MyCouch (API Server)
─────────────────────────────────────────────────────────────

1. User signs in with Clerk
   ↓
2. Clerk returns JWT token (7 day expiry)
   ↓
3. Client stores token (localStorage/sessionStorage)
   ↓
4. Client includes token in Authorization header
   ─────────────────────────────→ MyCouch validates:
                                   - Signature (RS256)
                                   - Expiration (exp claim)
                                   - Tenant membership
                                   
5. MyCouch returns 401 if token expired
   ←─────────────────────────────
   
6. Client catches 401 error
   ↓
7. Client calls Clerk API to refresh token
   ↓
8. Clerk returns new JWT (or 401 if session expired)
   ↓
9. Client stores new token
   ↓
10. Client retries request with new token
```

---

## Responsibility Matrix

### Client Application (YOUR Code)

✅ **MUST DO:**
- Store JWT token securely (localStorage, sessionStorage, or memory)
- Detect when token is about to expire
- Refresh token BEFORE it expires (e.g., 5 minutes before expiry)
- Handle 401 responses from MyCouch (token expired)
- Prompt user to re-authenticate if refresh fails
- Clear stored token on logout
- Implement automatic token refresh on app startup

❌ **SHOULD NOT DO:**
- Try to refresh token on the server
- Rely on server to manage token expiration
- Store token in cookies without httpOnly flag
- Log or expose JWT tokens in browser console

### MyCouch Server

✅ **MUST DO:**
- Validate JWT signature using Clerk's JWKS endpoint
- Check token expiration (exp claim)
- Verify tenant membership (active_tenant_id claim)
- Return 401 Unauthorized if token invalid/expired
- Log token validation failures (without exposing token)
- Never log full JWT payload (CWE-532)

❌ **SHOULD NOT DO:**
- Try to refresh tokens (not MyCouch's responsibility)
- Store token state on server
- Implement session timeout beyond JWT expiry
- Call Clerk API to refresh tokens
- Manage token lifecycle

---

## JWT Validation in MyCouch

### Current Implementation ✅

**File:** `src/couchdb_jwt_proxy/main.py` (lines 215-300)

```python
def verify_clerk_jwt(token: str) -> Tuple[Optional[Dict], str]:
    """
    Verify JWT signature and expiration.
    Returns (payload, error_reason) tuple.
    """
    try:
        # Get JWKS client for Clerk
        jwks_client = get_clerk_jwks_client(issuer)
        signing_key = jwks_client.get_signing_key(...)
        
        # Verify signature and expiration (raises ExpiredSignatureError if expired)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=CLERK_ISSUER,
            options={"verify_exp": True}  # Verify expiration
        )
        
        return payload, None
        
    except jwt.ExpiredSignatureError:
        logger.warning(f"JWT token has expired")
        return None, "clerk_token_expired"
        
    except jwt.InvalidSignatureError:
        logger.warning(f"JWT signature invalid")
        return None, "invalid_signature"
```

### Response to Expired Token

```python
if not payload:
    # Token validation failed (expired, invalid signature, etc.)
    raise HTTPException(
        status_code=401,
        detail=f"Invalid or expired token ({error_reason})"
    )
```

**Result:** Client receives 401 Unauthorized
**Client Action:** Refresh token with Clerk API and retry

---

## Clerk Session Lifetime

From Clerk documentation:
- **Session Duration:** 7 days (default)
- **Refresh Token:** Available during session lifetime
- **Token Expiry:** Tokens expire based on JWT exp claim
- **Session Expiry:** Session expires after 7 days of inactivity (or can be customized)

### Token Refresh Flow (Client Side)

```typescript
// Client-side pseudocode (React example)

async function makeAuthenticatedRequest(url: string, options: RequestInit) {
    // 1. Get current token
    let token = getStoredToken();
    
    // 2. Check if token expires in next 5 minutes
    if (tokenExpiresIn(token) < 5 * 60) {
        // 3. Refresh token BEFORE it expires
        token = await clerk.session.getToken();
        storeToken(token);
    }
    
    // 4. Make request with token
    const response = await fetch(url, {
        ...options,
        headers: {
            ...options.headers,
            Authorization: `Bearer ${token}`
        }
    });
    
    // 5. Handle 401 (token expired)
    if (response.status === 401) {
        // Token refresh failed or session expired
        clearStoredToken();
        redirectToLogin();
        return;
    }
    
    return response;
}
```

---

## Security Considerations

### Token Storage

**DON'T:**
```typescript
// ❌ Never store in plain localStorage
localStorage.setItem('jwt', token);

// ❌ Never log token
console.log('Token:', token);

// ❌ Never expose in URL
window.location = `https://api.example.com/data?token=${token}`;
```

**DO:**
```typescript
// ✅ Use secure storage
// Option 1: Memory (cleared on page reload)
let tokenInMemory = null;

// Option 2: Secure httpOnly cookie (if using cookie auth)
// Server sets: Set-Cookie: jwt=...; HttpOnly; Secure; SameSite=Strict

// Option 3: sessionStorage (cleared on tab close)
sessionStorage.setItem('jwt', token);
```

### Token Refresh Strategy

**Best Practice:**
- Refresh token **5 minutes before** expiration
- Refresh on app startup (user returns to app)
- Refresh on OAuth redirect from Clerk
- Handle refresh failure gracefully (prompt re-auth)

**Example:**
```typescript
// Refresh token every 5 minutes if still valid
setInterval(async () => {
    if (isAuthenticated()) {
        try {
            const newToken = await clerk.session.getToken();
            storeToken(newToken);
        } catch (error) {
            // Session expired, force re-authentication
            redirectToLogin();
        }
    }
}, 5 * 60 * 1000);
```

---

## MyCouch Error Responses

### 401 Unauthorized - Token Issues

**Possible Causes:**
- Token expired (server time > token exp claim)
- Token signature invalid
- Token issuer doesn't match Clerk
- Missing active_tenant_id claim
- User not member of requested tenant

**Response:**
```json
{
    "detail": "Invalid or expired token (clerk_token_expired)"
}
```

**Client Action:**
1. Clear stored token
2. Request new token from Clerk
3. Retry request with new token
4. If Clerk refresh fails, redirect to login

### Handling in React

```typescript
// Create axios/fetch interceptor
api.interceptors.response.use(
    (response) => response,
    async (error) => {
        if (error.response?.status === 401) {
            // Token expired or invalid
            try {
                // Try to refresh
                const newToken = await clerk.session.getToken();
                
                // Retry original request with new token
                error.config.headers.Authorization = `Bearer ${newToken}`;
                return api(error.config);
                
            } catch (refreshError) {
                // Refresh failed - redirect to login
                redirectToLogin();
            }
        }
        return Promise.reject(error);
    }
);
```

---

## Clerk Integration Reference

### Clerk Docs
- Session Token: https://clerk.com/docs/references/backend-resources/sessions
- Token Refresh: https://clerk.com/docs/references/javascript/session
- Logout: https://clerk.com/docs/references/javascript/sign-out

### Environment Setup
```bash
# Your frontend needs:
VITE_CLERK_PUBLISHABLE_KEY=pk_...
VITE_CLERK_SECRET_KEY=sk_...

# MyCouch proxy needs:
CLERK_ISSUER=https://your-app.clerk.accounts.dev
CLERK_JWKS_URL=https://your-app.clerk.accounts.dev/.well-known/jwks.json
```

---

## Session Timeout vs Token Expiry

### JWT Token Expiration (Server-side)
- **Duration:** Set by Clerk (typically 1 hour for access tokens)
- **Validation:** MyCouch checks `exp` claim
- **Action:** Return 401 if expired

### Clerk Session (Client-side)
- **Duration:** 7 days (configurable)
- **Validation:** Clerk API checks session validity
- **Action:** Client refreshes token before expiry

### Inactivity Timeout (Client-side)
- **Duration:** Application-specific (e.g., 15 minutes)
- **Implementation:** Client tracks last activity
- **Action:** Log out user if inactive

**Example Inactivity Handler:**
```typescript
let inactivityTimeout;

function resetInactivityTimer() {
    clearTimeout(inactivityTimeout);
    inactivityTimeout = setTimeout(() => {
        // Log out user after 15 minutes of inactivity
        logoutUser();
    }, 15 * 60 * 1000);
}

// Reset timer on user activity
document.addEventListener('mousemove', resetInactivityTimer);
document.addEventListener('keypress', resetInactivityTimer);
```

---

## Troubleshooting

### "Token expired" errors frequently
- **Cause:** Token not being refreshed before expiry
- **Fix:** Client should refresh token 5+ minutes before expiry
- **Check:** Verify Clerk session is still valid

### "Missing active_tenant_id claim"
- **Cause:** Clerk JWT template not configured
- **Fix:** Configure Clerk to inject active_tenant_id in JWT
- **Check:** Call `/choose-tenant` endpoint to update metadata

### Can't refresh token after logout
- **Cause:** Session was destroyed
- **Expected:** Clerk refresh should fail with 401
- **Fix:** Clear stored token and redirect to login

---

## Summary

| Responsibility | Component | Action |
|----------------|-----------|--------|
| Token Storage | Client | Store securely, clear on logout |
| Token Refresh | Client | Refresh before expiry (5 min buffer) |
| Token Validation | MyCouch | Verify signature & expiration |
| Session Timeout | Client | Implement inactivity timeout |
| Re-authentication | Client | Handle 401 responses |
| Error Handling | Both | Log appropriately, inform user |

**Bottom Line:** 
- MyCouch is responsible for **validating** JWTs ✅
- Client is responsible for **managing** JWTs ✅
- Neither should try to do the other's job ✅
