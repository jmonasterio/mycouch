# Manual Integration Tests for Virtual Endpoints

This guide explains how to run manual integration tests for the `__users` and `__tenants` virtual endpoints.

## What These Endpoints Do

### User Endpoints (`/__users/*`)
- **GET /__users/{user_id}** - Get your user document (hashed Clerk sub ID)
- **PUT /__users/{user_id}** - Update your user document (name, email, active_tenant_id)
- **DELETE /__users/{user_id}** - Soft-delete user (cannot delete self)

### Tenant Endpoints (`/__tenants/*`)
- **GET /__tenants/{tenant_id}** - Get a tenant (must be member)
- **GET /__tenants** - List all your tenants
- **POST /__tenants** - Create new tenant
- **PUT /__tenants/{tenant_id}** - Update tenant (owner only)
- **DELETE /__tenants/{tenant_id}** - Delete tenant (owner only, not active)

## Prerequisites

1. **Running mycouch proxy** on `http://localhost:5985`
2. **Valid Clerk JWT token** from your Clerk application
3. **Python dependencies**:
   ```bash
   pip install pytest httpx python-dotenv
   ```

## Getting a JWT Token

### Option 1: From Clerk Dashboard
1. Go to Clerk Dashboard → Users
2. Select a user
3. Click "Get JWT Token" button
4. Copy the token

### Option 2: From Frontend
```javascript
// In a Clerk-enabled frontend app
const token = await window.Clerk.session.getToken();
console.log(token);
```

### Option 3: Using Clerk API
```bash
curl -X POST https://api.clerk.com/v1/jwt_templates \
  -H "Authorization: Bearer $CLERK_SECRET_KEY"
```

## Running Tests

### Quick Start (Recommended)

1. **Add to .env file:**
   ```bash
   JWT_TOKEN=your_token_here
   ```

2. **Run tests:**
   ```bash
   python -m pytest tests/test_virtual_endpoints_manual.py -v -s
   ```

That's it! The test automatically loads `JWT_TOKEN` from `.env`.

### Alternative: Set Environment Variable

**Linux/macOS:**
```bash
export JWT_TOKEN="eyJhbGc..."
python -m pytest tests/test_virtual_endpoints_manual.py -v -s
```

**Windows (PowerShell):**
```powershell
$env:JWT_TOKEN = "eyJhbGc..."
python -m pytest tests/test_virtual_endpoints_manual.py -v -s
```

**Windows (CMD):**
```cmd
set JWT_TOKEN=eyJhbGc...
python -m pytest tests/test_virtual_endpoints_manual.py -v -s
```

### Run All Tests
```bash
python -m pytest tests/test_virtual_endpoints_manual.py -v -s
```

### Run Specific Test Class
```bash
# Test user endpoints only
python -m pytest tests/test_virtual_endpoints_manual.py::TestUserEndpoints -v -s

# Test tenant endpoints only
python -m pytest tests/test_virtual_endpoints_manual.py::TestTenantEndpoints -v -s

# Test error cases only
python -m pytest tests/test_virtual_endpoints_manual.py::TestErrorCases -v -s
```

### Run Specific Test
```bash
python -m pytest tests/test_virtual_endpoints_manual.py::TestUserEndpoints::test_get_own_user -v -s
```

### Run as Direct Script
```bash
# Requires JWT_TOKEN in .env or environment variable
python tests/test_virtual_endpoints_manual.py
```

## Understanding Test Output

Each test shows HTTP requests and responses:

```
[GET] http://localhost:5985/__users/a3f7c2d9e1b4...
Status: 200
Response: {
  "_id": "a3f7c2d9e1b4...",
  "type": "user",
  "name": "John Doe",
  "email": "john@example.com",
  "_rev": "1-abc123"
}
```

## Common Test Scenarios

### Test 1: Read Your User Document
```bash
pytest tests/test_virtual_endpoints_manual.py::TestUserEndpoints::test_get_own_user -v -s
```

Expected: ✓ Gets your user document with your info

### Test 2: Update Your Profile
```bash
pytest tests/test_virtual_endpoints_manual.py::TestUserEndpoints::test_update_user_name -v -s
```

Expected: ✓ Your name gets updated

### Test 3: List Your Tenants
```bash
pytest tests/test_virtual_endpoints_manual.py::TestTenantEndpoints::test_list_tenants -v -s
```

Expected: ✓ Returns list of tenants you're a member of

### Test 4: Create New Tenant
```bash
pytest tests/test_virtual_endpoints_manual.py::TestTenantEndpoints::test_create_tenant -v -s
```

Expected: ✓ New tenant created with you as owner

### Test 5: Security - Cannot Update Other User
```bash
pytest tests/test_virtual_endpoints_manual.py::TestUserEndpoints::test_update_other_user_fails -v -s
```

Expected: ✓ Returns 403 Forbidden

### Test 6: Security - Cannot Delete Self
```bash
pytest tests/test_virtual_endpoints_manual.py::TestUserEndpoints::test_delete_self_fails -v -s
```

Expected: ✓ Returns 403 Forbidden

## Troubleshooting

### "JWT_TOKEN environment variable not set"
Make sure you exported the token:
```bash
export JWT_TOKEN="your_token_here"
echo $JWT_TOKEN  # Verify it's set
```

### "Connection refused" on localhost:5985
Make sure mycouch proxy is running:
```bash
python run.py  # or your startup command
```

### "Invalid token"
1. Check token is recent (not expired)
2. Verify token is for correct Clerk instance
3. Get fresh token from Clerk Dashboard

### "User not found" on first test
This is normal - the virtual endpoint automatically creates the user on first request. Try again.

### "Tenant not found" after creation
Small timing issue - the document may not be immediately visible. Try waiting a moment and testing again.

## Understanding the Virtual ID System

The tests use **hashed user IDs** (not raw Clerk `sub` claim):

```
Clerk JWT: { "sub": "user_1234567890", ... }
                    ↓ (hashed)
Virtual ID: "a3f7c2d9e1b4f6a8c9d0e1f2a3b4c5d6"
                    ↓ (when stored)
Internal ID: "user_a3f7c2d9e1b4f6a8c9d0e1f2a3b4c5d6"
```

The tests automatically handle this hashing for you.

## Checking Test Results

Successful test:
```
✓ Got user: user_a3f7c2d9...
✓ Updated user name to: Test User a3f7c2d9...
```

Failed test:
```
✗ Cannot update other user (403)
AssertionError: ...
```

## Advanced Testing

### Test with curl

Get user:
```bash
curl -H "Authorization: Bearer $JWT_TOKEN" \
  http://localhost:5985/__users/a3f7c2d9...
```

Update user:
```bash
curl -X PUT \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"New Name"}' \
  http://localhost:5985/__users/a3f7c2d9...
```

List tenants:
```bash
curl -H "Authorization: Bearer $JWT_TOKEN" \
  http://localhost:5985/__tenants
```

### Test with Python Script

```python
import os
import httpx
import json

token = os.getenv("JWT_TOKEN")
headers = {"Authorization": f"Bearer {token}"}

# Get your user
response = httpx.get("http://localhost:5985/__users/your_hashed_id", headers=headers)
print(json.dumps(response.json(), indent=2))

# List your tenants
response = httpx.get("http://localhost:5985/__tenants", headers=headers)
print(json.dumps(response.json(), indent=2))

# Create new tenant
data = {"name": "My New Tenant"}
response = httpx.post("http://localhost:5985/__tenants", headers=headers, json=data)
print(json.dumps(response.json(), indent=2))
```

## Notes

- Tests use real proxy endpoints (not mocked)
- Tests create real documents in your couch-sitter database
- Some tests clean up after themselves (deletes), others don't
- To run same test twice, it will detect existing data and handle appropriately
- All updates are to the real database, so you can verify changes in CouchDB UI

## Extending Tests

To add your own tests:

```python
class TestCustomScenarios:
    def test_my_scenario(self, client, sub_hash):
        """Test description"""
        # Your test code
        result = client.create_tenant("My Tenant")
        assert result.get("_id"), "Should have ID"
        print(f"✓ My test passed")
```

Then run:
```bash
pytest tests/test_virtual_endpoints_manual.py::TestCustomScenarios::test_my_scenario -v -s
```

## Questions?

Check the code comments in `test_virtual_endpoints_manual.py` for detailed explanations of what each test does.
