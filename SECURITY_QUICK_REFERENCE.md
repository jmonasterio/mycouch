# Security Quick Reference

## For MyCouch Server Developers

### ✅ What's Done
1. JWT validation ✅
2. Tenant isolation ✅
3. No token leakage in logs ✅
4. Authentication hardening ✅

### ⏳ What's Left (Server-Side)
1. **Rate limiting** (2-3 hours) - Prevent brute force
2. **Audit logging** (4-6 hours) - Track auth events
3. **CouchDB docs** (1-2 hours) - Security setup guide
4. **Personal tenant protection** (1-2 hours) - Prevent accidental deletion

**Total:** ~10 hours of server-side work

### 📚 Reference Docs
- `SECURITY_REVIEW_MYCOUCH_ONLY.md` - Server-side issues only
- `security-review.md` - Complete review (includes client-side)
- `docs/JWT_SESSION_ARCHITECTURE.md` - Architecture decisions

---

## For Frontend Developers

### ✅ MyCouch Handles
- JWT signature validation ✅
- Token expiration checking ✅
- Tenant membership validation ✅
- 401 response on invalid token ✅

### ❌ Frontend Must Handle
1. **Token storage** - Store securely (not localStorage)
2. **Token refresh** - Refresh before expiry (5 min buffer)
3. **Error handling** - Catch 401 and re-authenticate
4. **Inactivity logout** - Log out after N minutes idle
5. **CSRF protection** - If using cookies (not needed with JWT headers)
6. **Tenant sync** - Wait for JWT update after tenant switch

### 📚 Reference Docs
- `docs/JWT_SESSION_ARCHITECTURE.md` - Full implementation guide
- `SECURITY_REVIEW_MYCOUCH_ONLY.md` - What NOT to implement on server

---

## Security Checklist

### Before Deployment
- [ ] MyCouch: Rate limiting enabled
- [ ] MyCouch: Audit logging enabled
- [ ] MyCouch: CouchDB security documented
- [ ] Frontend: Token refresh implemented
- [ ] Frontend: 401 error handling
- [ ] Frontend: Inactivity timeout
- [ ] All: HTTPS/TLS enabled
- [ ] All: Secrets in environment variables

### Testing
- [ ] Security tests passing (39 tests)
- [ ] Expired token handled (401)
- [ ] Invalid tenant access blocked (403)
- [ ] Token not in logs
- [ ] Rate limits working
- [ ] Audit logs created

---

## Common Mistakes

### ❌ Don't Do This (Server)
```python
# Server trying to refresh token - WRONG
except jwt.ExpiredSignatureError:
    new_token = await clerk_api.refresh_token()  # ❌ WRONG
    
# Logging full JWT payload - WRONG
logger.debug(f"JWT: {json.dumps(payload)}")  # ❌ WRONG

# No tenant validation - WRONG
async def choose_tenant(tenantId):
    update_session(tenantId)  # ❌ WRONG - no validation
```

### ❌ Don't Do This (Client)
```typescript
// Storing token in localStorage without security - WRONG
localStorage.setItem('jwt', token);  // ❌ WRONG

// Logging token - WRONG
console.log('Token:', token);  // ❌ WRONG

// Not handling 401 - WRONG
fetch('/api/data', {headers: {Authorization: `Bearer ${token}`}})
    .then(r => r.json())  // ❌ WRONG - no 401 handling

// Not refreshing token - WRONG
// Using same token for days  // ❌ WRONG
```

### ✅ Do This Instead

**Server:**
```python
# Safe logging
logger.debug(f"User {sub} accessing {tenant_id}")

# Token validation
payload = jwt.decode(token)
if expired: raise HTTPException(401, "Token expired")
if tenant_id not in user_tenants: raise HTTPException(403)

# Return 401 on invalid
raise HTTPException(401, "Invalid token - please refresh")
```

**Client:**
```typescript
// Secure storage
let token = null;  // Memory only

// Refresh before expiry
setInterval(async () => {
    token = await clerk.session.getToken();
}, 4 * 60 * 1000);  // Every 4 minutes

// Handle 401
.catch(err => {
    if (err.status === 401) {
        clearToken();
        redirectToLogin();
    }
});

// Inactivity timeout
let timeout;
document.addEventListener('mousemove', () => {
    clearTimeout(timeout);
    timeout = setTimeout(logout, 15 * 60 * 1000);
});
```

---

## Testing Commands

```bash
# Run security tests
python -m pytest tests/test_jwt_*.py -v

# Test expired token
curl -H "Authorization: Bearer <expired_token>" \
  https://mycouch.example.com/my-tenants

# Test invalid tenant
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -d '{"tenantId": "unauthorized-tenant"}' \
  https://mycouch.example.com/choose-tenant
```

---

## Security Support

**For MyCouch Issues:**
- See `SECURITY_REVIEW_MYCOUCH_ONLY.md`
- File issues in `/issues` with label `security`

**For Client Integration:**
- See `docs/JWT_SESSION_ARCHITECTURE.md`
- Ask in your frontend team's security channel

**Questions?**
- Check the comprehensive `security-review.md`
- Review test files in `tests/test_jwt_*.py`

---

**Last Updated:** 2025-12-07
