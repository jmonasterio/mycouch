# Debugging 401 Authorization Errors

This guide explains how to debug JWT authentication issues in the proxy.

## Enhanced 401 Logging

The proxy now provides detailed debug information for all 401 errors.

### Log Message Format

Each 401 error includes:

```
401 - <error_reason> | Client: <ip_address> | Path: <METHOD> /<path> | Token: <token_preview> | Unverified payload: sub=..., exp=..., iat=...
```

### Example Log Messages

#### Missing Authorization Header
```
WARNING:main:401 - Missing Authorization header | Client: 127.0.0.1 | Path: GET /roady/_all_docs
```

**Fix:** Add `Authorization: Bearer <token>` header to request

#### Invalid Auth Header Format
```
WARNING:main:401 - Invalid auth header format | Client: 127.0.0.1 | Path: GET /roady/_all_docs | Header: Basic YWRtaW46cGFzc3dvcmQ=
```

**Fix:** Use format `Authorization: Bearer <token>` (not Basic auth)

#### Expired Token
```
WARNING:main:401 - token_expired | Client: 127.0.0.1 | Path: POST /roady | Token: eyJhbGc...zZ0Ig | Unverified payload: sub=test-client, exp=1699564800, iat=1699561200
```

**Fix:** Get a new token - tokens expire after 1 hour

```bash
curl -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "test-key"}'
```

#### Invalid Token (Bad Signature)
```
WARNING:main:401 - invalid_token (DecodeError) | Client: 127.0.0.1 | Path: GET /roady/_all_docs | Token: invalid...token | Unverified payload: N/A
```

**Causes:**
- Token was modified after creation
- Token was signed with different secret
- Token format is corrupted

**Fix:** Get a new valid token

#### Token Error (Other)
```
WARNING:main:401 - token_error (ValueError) | Client: 127.0.0.1 | Path: GET /roady/_all_docs | Token: too_short
```

**Fix:** Ensure token is complete and valid

## Understanding the Log Fields

| Field | Meaning | Example |
|-------|---------|---------|
| `error_reason` | Type of auth failure | `token_expired`, `invalid_token`, `token_error` |
| `Client` | Client IP address | `127.0.0.1` |
| `Path` | Request method and path | `GET /roady/_all_docs` |
| `Token` | First 10 and last 10 chars of token | `eyJhbGc...zZ0Ig` |
| `sub` | JWT subject (client ID) | `test-client` |
| `exp` | Token expiration time (Unix timestamp) | `1699564800` |
| `iat` | Token issued-at time (Unix timestamp) | `1699561200` |

## Enable Debug Logging

For even more detailed information, set `LOG_LEVEL=DEBUG`:

```bash
# Edit .env
LOG_LEVEL=DEBUG

# Or set via environment
export LOG_LEVEL=DEBUG
uv run uvicorn main:app --reload --port 5985
```

With DEBUG enabled, you'll see:

```
DEBUG:main:Token details | sub=test-client | iat=1699561200 | exp=1699564800
```

## Common Issues and Fixes

### Issue: "Missing authorization header"

**Problem:**
```
401 - Missing Authorization header | Client: 127.0.0.1 | Path: GET /roady/_all_docs
```

**Solution:** Add Authorization header with Bearer token

```javascript
// Browser/JavaScript
fetch('http://localhost:5985/roady/_all_docs', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});

// curl
curl -H "Authorization: Bearer $TOKEN" http://localhost:5985/roady/_all_docs
```

### Issue: "Invalid auth header format"

**Problem:**
```
401 - Invalid auth header format | Client: 127.0.0.1 | Header: Basic YWRtaW46cGFzc3dvcmQ=
```

**Solution:** Use Bearer token, not Basic auth

```bash
# ✗ Wrong
curl -u admin:password http://localhost:5985/roady/_all_docs

# ✓ Correct
curl -H "Authorization: Bearer $TOKEN" http://localhost:5985/roady/_all_docs
```

### Issue: "token_expired"

**Problem:**
```
401 - token_expired | Token: eyJhbGc...zZ0Ig | Unverified payload: sub=test-client, exp=1699564800
```

**Diagnosis:**
- Token expiration (exp): `1699564800`
- Current time: Check if current time > exp
- Duration: Tokens last 1 hour from creation

**Solution:** Get a new token

```bash
curl -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "test-key"}'
```

### Issue: "token_too_short"

**Problem:**
```
401 - invalid_token (...) | Token: token_too_short
```

**Solution:** Authorization header value is not a valid JWT token

```bash
# Check what you're sending
echo $TOKEN
# Should be: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## Testing with curl

### Get a Token

```bash
TOKEN=$(curl -s -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "test-key"}' | jq -r .token)

echo $TOKEN
```

### Use the Token

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5985/roady/_all_docs
```

### Debug a Bad Token

```bash
# Use an invalid token
curl -H "Authorization: Bearer invalid.token.here" \
  http://localhost:5985/roady/_all_docs

# Check the logs for detailed error info
```

## Testing with JavaScript/Browser

```javascript
// Get token
const tokenResponse = await fetch('http://localhost:5985/auth/token', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({api_key: 'test-key'})
});

const {token} = await tokenResponse.json();
console.log('Token:', token);

// Use token
const docsResponse = await fetch('http://localhost:5985/roady/_all_docs', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});

if (docsResponse.status === 401) {
  const error = await docsResponse.json();
  console.error('Auth error:', error);
  // Check proxy logs for detailed error info
} else {
  const docs = await docsResponse.json();
  console.log('Docs:', docs);
}
```

## Checking Token Expiration

### Decode Token (JavaScript)

```javascript
// Decode JWT to check expiration
function parseJwt(token) {
  const base64 = token.split('.')[1];
  const jsonString = atob(base64);
  return JSON.parse(jsonString);
}

const payload = parseJwt(token);
console.log('Expires at:', new Date(payload.exp * 1000));
console.log('Issued at:', new Date(payload.iat * 1000));
console.log('Is expired?', Date.now() > payload.exp * 1000);
```

### Decode Token (curl + jq)

```bash
# Extract and decode token payload
TOKEN="your_token_here"
echo $TOKEN | cut -d. -f2 | base64 -d | jq .

# Check expiration
EXPIRY=$(echo $TOKEN | cut -d. -f2 | base64 -d | jq .exp)
NOW=$(date +%s)
echo "Token expires in: $((EXPIRY - NOW)) seconds"
```

## Troubleshooting Checklist

- [ ] Is Authorization header being sent? (check logs: "Missing Authorization header")
- [ ] Is it Bearer token format? (check logs: "Invalid auth header format")
- [ ] Is token expired? (check logs: "token_expired", check exp time)
- [ ] Is token complete? (not truncated or modified)
- [ ] Check client IP in logs - is it expected?
- [ ] Check path in logs - is endpoint allowed?

## Production Debugging

For production, set `LOG_LEVEL=INFO` (default) to see only important errors without token details.

For debugging, set `LOG_LEVEL=DEBUG` temporarily to get full token inspection.

**Important:** Don't leave `LOG_LEVEL=DEBUG` in production - logs may contain sensitive information.

## More Information

- See [TENANT_MODE.md](TENANT_MODE.md) for tenant-specific 401 errors
- See [README.md](README.md) for general API documentation
- Check logs with: `grep "401" /path/to/logs`
