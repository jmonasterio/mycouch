# Integration Test Setup Guide

Quick guide to set up and run the virtual endpoint integration tests.

## Setup (One-Time)

### 1. Install Dependencies
```bash
pip install python-dotenv pytest httpx
```

### 2. Get a JWT Token

**From Roady App (Recommended):**
1. Open Roady in browser (http://localhost:5173 or your URL)
2. Log in with Clerk
3. Click **Settings** (top nav)
4. Click **Options** tab
5. Scroll to **Authentication** section
6. Click **📋 Copy** button next to JWT Token
7. ⚠️ Token expires quickly (60 seconds) - use it immediately in next step

**From Clerk Dashboard:**
1. Go to Clerk Dashboard
2. Users → Select a user
3. Click Sessions tab
4. Find the active session and copy the JWT token

### 3. Add to .env File

Add two settings to `.env`:

```bash
# Your JWT token from Roady or Clerk Dashboard
JWT_TOKEN=your_token_here

# Skip expiration check for expired tokens (dev only!)
SKIP_JWT_EXPIRATION_CHECK=true
```

**Why `SKIP_JWT_EXPIRATION_CHECK=true`?**
- Clerk tokens expire in ~60 seconds
- This lets you run tests without rushing to beat the clock
- ⚠️ Only for development/testing - never use in production!

**What happens:**
- Token validation still checks signature (secure)
- Only skips the expiration timestamp check
- You can reuse the same token for multiple test runs

## Running Tests

### Simple Run
```bash
cd c:/github/mycouch
python -m pytest tests/test_virtual_endpoints_manual.py -v -s
```

### Run Specific Tests
```bash
# Test user endpoints
pytest tests/test_virtual_endpoints_manual.py::TestUserEndpoints -v -s

# Test tenant endpoints  
pytest tests/test_virtual_endpoints_manual.py::TestTenantEndpoints -v -s

# Test one specific function
pytest tests/test_virtual_endpoints_manual.py::TestUserEndpoints::test_get_own_user -v -s
```

### Run as Direct Script
```bash
python tests/test_virtual_endpoints_manual.py
```

## Verification

You should see output like:

```
[GET] http://localhost:5985/__users/a3f7c2d9e1b4...
Status: 200
Response: {
  "_id": "a3f7c2d9e1b4...",
  "type": "user",
  "name": "Your Name",
  ...
}
✓ Got user: user_a3f7c2d9...
```

## Troubleshooting

### "JWT_TOKEN not found" Error
- Make sure you added `JWT_TOKEN=your_token` to `.env`
- Make sure `.env` is in the mycouch root directory
- The token value should not be in quotes in .env file

### "Connection refused" Error
- Make sure mycouch proxy is running: `python src/couchdb_jwt_proxy/main.py`
- Check that it's listening on `http://localhost:5985`

### "Invalid token" Error
- Token may be expired
- Get a fresh token from Roady or Clerk Dashboard
- Update the value in `.env`

### "python-dotenv not installed"
```bash
pip install python-dotenv
```

## What the Tests Validate

The tests verify:
- ✓ Users can read their own user document
- ✓ Users can update their own profile (name, email)
- ✓ Users cannot access other users' documents (403)
- ✓ Users cannot delete themselves (403)
- ✓ Users can list their tenants
- ✓ Users can create new tenants
- ✓ Users can update their tenants (as owner)
- ✓ Users can delete tenants (as owner, not active)
- ✓ Missing auth header returns 401
- ✓ Invalid token returns 401

## Common Workflows

**Test after deploying proxy changes:**
```bash
python -m pytest tests/test_virtual_endpoints_manual.py -v -s
```

**Test specific endpoint:**
```bash
pytest tests/test_virtual_endpoints_manual.py::TestTenantEndpoints::test_create_tenant -v -s
```

**Run tests with output:**
```bash
pytest tests/test_virtual_endpoints_manual.py -v -s --tb=short
```

**Save test results to file:**
```bash
pytest tests/test_virtual_endpoints_manual.py -v > test_results.txt 2>&1
```

## Token Security

⚠️ **IMPORTANT:**
- Never commit `.env` file to git (it's in `.gitignore`)
- JWT tokens are temporary and expire
- If you commit a token by accident, rotate it in Clerk Dashboard
- Keep your `.env` file local only

## Next Steps

1. Run the tests: `pytest tests/test_virtual_endpoints_manual.py -v -s`
2. Check the output for any failures
3. If tests pass: your proxy is working correctly
4. If tests fail: check the error messages in the output

See `TEST_VIRTUAL_ENDPOINTS.md` for detailed test documentation.
