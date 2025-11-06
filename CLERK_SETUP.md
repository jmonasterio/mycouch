# Clerk JWT Validation Setup

This guide explains how to configure the proxy to validate **Clerk JWTs** instead of custom JWT tokens.

## Why Clerk JWT?

Using Clerk JWTs provides:
- ✅ Enterprise authentication via Clerk
- ✅ User management built-in
- ✅ No need to manage JWT_SECRET
- ✅ RS256 asymmetric signing (more secure)
- ✅ Can still fall back to custom JWT if needed

## Prerequisites

- Clerk account (https://clerk.com)
- Clerk application created in dashboard
- Clerk publishable key and issuer URL

## Step 1: Find Your Clerk Issuer URL

From your Clerk dashboard:

1. Go to **API Keys**
2. Find **Issuer URL** (e.g., `https://your-clerk-instance.clerk.accounts.dev`)
3. Copy this URL

## Step 2: Configure Proxy

Edit `.env`:

```bash
# Enable Clerk JWT validation
ENABLE_CLERK_JWT=true

# Your Clerk issuer URL
CLERK_ISSUER_URL=https://your-clerk-instance.clerk.accounts.dev
```

## Step 3: Restart Proxy

```bash
# Stop current instance (Ctrl+C)
# Then restart
uv run uvicorn main:app --reload --port 5985
```

You should see in logs:

```
✓ Clerk JWT validation ENABLED
  Clerk issuer: https://your-clerk-instance.clerk.accounts.dev
  JWKS URL: https://your-clerk-instance.clerk.accounts.dev/.well-known/jwks.json
  Fallback to custom JWT: enabled
```

## How It Works

### Token Validation Flow

```
1. PouchDB sends request with Clerk JWT
   Authorization: Bearer eyJhbGc...

2. Proxy receives request

3. Proxy tries to validate as Clerk JWT (RS256)
   - Fetches Clerk's public keys from JWKS endpoint
   - Validates signature using public key
   - Checks expiration, issuer, etc.

4a. If Clerk JWT valid → Allow request ✓

4b. If Clerk JWT invalid → Try custom JWT (HS256)
   - Validates with JWT_SECRET
   - If valid → Allow request ✓
   - If invalid → Return 401 ✗
```

### Key Points

- **RS256 validation:** Clerk uses asymmetric signing (public/private keys)
- **JWKS caching:** Public keys are cached to avoid hitting Clerk API on every request
- **Fallback mode:** Can still accept custom JWTs for testing/migration
- **No JWT_SECRET needed:** Can be ignored when using Clerk

## Extracting User Info from Clerk JWT

Clerk JWTs contain useful claims:

```javascript
// Example Clerk JWT payload
{
  "iss": "https://your-clerk-instance.clerk.accounts.dev",
  "sub": "user_abc123def456",          // Clerk user ID
  "aud": "your-app-id",
  "iat": 1699561200,
  "exp": 1699564800,
  "email": "user@example.com",          // User email
  "name": "John Doe",                   // User name
  "picture": "https://...",             // Profile picture
  "org_id": "org_abc123",               // Organization (if using Clerk orgs)
  "role": "admin"                       // Role (if configured)
}
```

## Multi-Tenant with Clerk

Use Clerk organizations for multi-tenant:

1. **Enable Organizations** in Clerk dashboard
2. **Extract org_id** in proxy:

```bash
# In .env
TENANT_CLAIM=org_id

# Or for email-based tenants:
# TENANT_CLAIM=email
```

Then documents are automatically filtered by `org_id`.

## Testing Clerk JWT Validation

### 1. Get Token from Frontend

In your browser (Roady PWA):

```javascript
const token = await window.Clerk.session.getToken();
console.log("Token:", token);
```

### 2. Test with curl

```bash
# Copy the token from browser console
TOKEN="eyJhbGc..."

# Test with proxy
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5985/roady/_all_docs

# Check proxy logs - should see:
# ✓ Authenticated | Client: user_abc123def456 | GET /roady/_all_docs
```

### 3. Decode Token to Verify

```bash
# Decode to see claims (bash/jq)
TOKEN="your_token_here"
echo $TOKEN | cut -d. -f2 | base64 -d | jq .

# Should show:
# {
#   "sub": "user_abc123def456",
#   "email": "user@example.com",
#   ...
# }
```

## Troubleshooting

### "JWKS unavailable"

**Problem:**
```
401 - clerk_jwks_unavailable
```

**Cause:** Can't reach Clerk's JWKS endpoint

**Solution:** Check:
1. CLERK_ISSUER_URL is correct
2. Network connection to Clerk
3. ENABLE_CLERK_JWT is true

```bash
# Test manually
curl https://your-clerk-issuer/.well-known/jwks.json
```

### "clerk_token_expired"

**Problem:**
```
401 - clerk_token_expired
```

**Cause:** Token expired (usually 1 hour from issue)

**Solution:** Get a new token

```javascript
// In Roady PWA
const newToken = await window.Clerk.session.getToken({forceRefresh: true});
```

### "clerk_invalid_token"

**Problem:**
```
401 - clerk_invalid_token (DecodeError)
```

**Cause:** Token signature invalid or malformed

**Solution:**
1. Verify CLERK_ISSUER_URL matches token issuer
2. Get new token from Clerk

### Falling Back to Custom JWT

If Clerk JWT fails but custom JWT works:

```
DEBUG:main:Clerk JWT validation failed: ..., trying custom JWT
✓ Authenticated (via custom JWT)
```

This is fine! The proxy is working as designed - falling back to custom JWT.

To disable fallback (require Clerk only):
- Remove JWT_SECRET from .env
- Won't work, but logs will be clearer about what's failing

## Performance Notes

- ✅ **JWKS cached:** Public keys fetched once, then cached
- ✅ **No network calls per request:** Caching is per-process
- ✅ **Fast validation:** RS256 verification is fast
- ⚠️ **Cache invalidation:** Keys cached until process restart
  - For key rotation: restart proxy

## Security Notes

- ✅ **Public keys public:** JWKS endpoint is public (that's OK!)
- ✅ **Signature verified:** Each token signature validated
- ✅ **Expiration checked:** Expired tokens rejected
- ✅ **Issuer verified:** Tokens must be from your Clerk instance
- ⚠️ **HTTPS required:** Always use HTTPS with Clerk in production

## Production Checklist

- [ ] ENABLE_CLERK_JWT=true
- [ ] CLERK_ISSUER_URL set correctly
- [ ] HTTPS enabled for proxy
- [ ] HTTPS enabled for Clerk (always)
- [ ] Logs monitored for auth failures
- [ ] Fallback JWT disabled if not needed
- [ ] Test token refresh (after 1 hour)

## Migration Path

1. **Phase 1:** Enable ENABLE_CLERK_JWT=true with custom JWT fallback
   - Accept both Clerk and custom JWTs
   - Verify Clerk works without breaking existing clients

2. **Phase 2:** Remove JWT_SECRET from production
   - Forces Clerk JWT only
   - Commits to Clerk auth

## More Information

- [Clerk Documentation](https://clerk.com/docs)
- [Clerk JWT Reference](https://clerk.com/docs/backend-requests/handling/jwt)
- See [DEBUGGING.md](DEBUGGING.md) for debugging auth issues
- See [README.md](README.md) for general proxy documentation
