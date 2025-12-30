# JWT Testing with Short Expiration Explained

## The Problem

Your Clerk instance issues JWT tokens with **60-second expiration**:
```json
{
  "iat": 1766693126,  // Issued at
  "exp": 1766693186   // Expires at (60 seconds later)
}
```

This means you'd have to:
1. Copy token from Roady
2. Paste into .env
3. Run tests
4. **All within 60 seconds** ⏱️

Very frustrating for testing!

## The Solution

We added a **development mode flag** to skip expiration checking:

```bash
SKIP_JWT_EXPIRATION_CHECK=true
```

## How It Works

### With Flag Enabled (Dev Mode)
```
Your JWT token
    ↓
MyCouch Proxy
    ↓
Parse JWT
    ↓
Check Signature ✓ (always checked)
    ↓
Check Issuer ✓ (always checked)
    ↓
Check Expiration? ✗ (SKIPPED)
    ↓
Token Valid ✓
```

### Without Flag (Production Mode)
```
Your JWT token
    ↓
MyCouch Proxy
    ↓
Parse JWT
    ↓
Check Signature ✓
    ↓
Check Issuer ✓
    ↓
Check Expiration ✓ (always checked)
    ↓
Token expired? ✗ Reject!
```

## Setup for Testing

In your `.env` file:

```bash
# Your JWT token (can be reused for multiple test runs now)
JWT_TOKEN=eyJhbGciOiJSUzI1NiIsImtpZCI6Ijk3OTE4YjM1NGJk...

# Enable dev mode - skip expiration checking
SKIP_JWT_EXPIRATION_CHECK=true
```

## Security Implications

✅ **Safe for Development/Testing:**
- Signature validation is still enforced (most important)
- Issuer validation is still enforced
- Only expiration timestamp is ignored
- Cannot be used in production with this setting

❌ **NOT Safe for Production:**
- Expired tokens would be accepted
- Always disable this in production
- Default is `false` (safe)

## How to Use

1. Copy JWT token once from Roady Settings
2. Add to `.env` with `SKIP_JWT_EXPIRATION_CHECK=true`
3. Run tests as many times as you want
4. Token will keep working even after 60 seconds (in dev mode)

```bash
# Copy token from Roady once
JWT_TOKEN=eyJhbGc...

# Enable skip
SKIP_JWT_EXPIRATION_CHECK=true

# Run tests multiple times without copying new token
pytest tests/test_virtual_endpoints_manual.py -v -s
pytest tests/test_virtual_endpoints_manual.py::TestUserEndpoints -v -s
pytest tests/test_virtual_endpoints_manual.py::TestTenantEndpoints -v -s
```

## Real-World Example

**Before (without flag):**
```
12:00:00 - Copy token from Roady
12:00:01 - Add to .env
12:00:02 - Run tests
12:00:58 - Token expires! ❌ Tests fail
```

**After (with flag):**
```
12:00:00 - Copy token from Roady once
12:00:01 - Add to .env with SKIP_JWT_EXPIRATION_CHECK=true
12:00:02 - Run tests ✓
12:01:00 - Run more tests ✓ (token still works!)
12:02:00 - Run even more tests ✓
```

## Important Notes

1. **Development Only**: Never commit `SKIP_JWT_EXPIRATION_CHECK=true` to production
2. **`.env` is in `.gitignore`**: Already excluded from version control
3. **Signature Still Checked**: You can't fake tokens - signature validation is always on
4. **Issuer Still Checked**: Invalid issuers are still rejected
5. **Single Token Reuse**: Use the same token for multiple test runs in dev mode

## Configuration

```bash
# To enable (development/testing)
SKIP_JWT_EXPIRATION_CHECK=true

# To disable (production - default)
SKIP_JWT_EXPIRATION_CHECK=false

# Or don't set it (defaults to false)
```

## Proxy Log Output

When enabled, you'll see this warning in proxy logs:

```
⚠️ JWT expiration check DISABLED - development/testing mode only
```

This is a reminder that expiration checking is off.

## Troubleshooting

**"Still getting 401 errors?"**
- Make sure `SKIP_JWT_EXPIRATION_CHECK=true` is in `.env`
- Make sure proxy is restarted after changing `.env`
- Check proxy logs for the warning message

**"Token still doesn't work after 60 seconds?"**
- Could be a different validation failed (issuer, signature)
- Check proxy logs for specific error
- Try with a fresh token to isolate the issue

**"Is this secure?"**
- Yes, for development
- No, never use in production
- Signature validation is always enforced
