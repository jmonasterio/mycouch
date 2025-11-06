# Multi-Tenant Mode Guide

This guide explains how to configure and use the proxy in multi-tenant mode for secure per-tenant data isolation.

## Overview

Multi-tenant mode allows the proxy to enforce row-level access control. Each tenant's data is automatically isolated, preventing cross-tenant access even if a malicious client modifies requests.

**Key benefits:**
- ✅ Transparent tenant isolation
- ✅ No client-side configuration needed
- ✅ Automatic tenant injection in documents
- ✅ Query rewriting for secure filtering
- ✅ Response filtering to prevent data leakage

## Enabling Tenant Mode

### Step 1: Update .env

```bash
# Enable tenant mode
ENABLE_TENANT_MODE=true

# JWT claim name for tenant ID (optional, default: tenant_id)
TENANT_CLAIM=tenant_id

# Document field name for tenant ID (optional, default: tenant_id)
TENANT_FIELD=tenant_id
```

### Step 2: Restart Proxy

```bash
# Stop current instance (Ctrl+C)
# Then restart:
uv run uvicorn main:app --reload --port 5985
```

You should see in logs:
```
Tenant mode ENABLED
  Tenant claim: tenant_id
  Tenant field: tenant_id
```

## Architecture

```
PouchDB Client (tenant-a)
    ↓
    Get JWT with {sub: "user", tenant_id: "tenant-a"}
    ↓
Proxy (Tenant Mode Enabled)
    ├─ Extract tenant from JWT
    ├─ Rewrite queries: inject tenant_id filter
    ├─ Inject tenant_id into all documents
    ├─ Filter responses: remove non-tenant docs
    └─ Block disallowed endpoints
    ↓
CouchDB (single shared database)
    └─ Stores documents with tenant_id field
```

## How It Works

### 1. JWT Must Contain Tenant Claim

When generating tokens, include the tenant ID:

```bash
curl -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "test-key",
    "tenant_id": "company-a"
  }'
```

Response contains JWT with:
```json
{
  "sub": "api-client",
  "tenant_id": "company-a",
  "iat": 1234567890,
  "exp": 1234571490
}
```

### 2. Document Creation (Automatic Tenant Injection)

Client creates document (no tenant_id):
```bash
curl -X POST http://localhost:5984/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Task 1", "status": "open"}'
```

Proxy automatically injects tenant:
```json
{
  "_id": "abc123",
  "title": "Task 1",
  "status": "open",
  "tenant_id": "company-a"
}
```

### 3. Queries (Automatic Tenant Filtering)

#### GET /_all_docs
Client requests:
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5984/tasks/_all_docs
```

Proxy rewrites to filter by tenant:
```
Start key: "company-a:"
End key: "company-a:\ufff0"
```

Result contains only company-a documents.

#### POST /_find
Client queries:
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "selector": {
      "status": "open"
    }
  }' \
  http://localhost:5984/tasks/_find
```

Proxy injects tenant filter:
```json
{
  "selector": {
    "status": "open",
    "tenant_id": "company-a"
  }
}
```

### 4. Response Filtering

Even if CouchDB returns cross-tenant docs (shouldn't happen), proxy filters them:

```javascript
// CouchDB returns:
{
  "rows": [
    {"doc": {"_id": "a", "tenant_id": "company-a"}},  // ✓ Included
    {"doc": {"_id": "b", "tenant_id": "company-b"}},  // ✗ Filtered out
    {"doc": {"_id": "c", "tenant_id": "company-a"}}   // ✓ Included
  ]
}

// Proxy returns:
{
  "rows": [
    {"doc": {"_id": "a", "tenant_id": "company-a"}},
    {"doc": {"_id": "c", "tenant_id": "company-a"}}
  ]
}
```

## Supported Operations

| Operation | HTTP Method | Behavior | Example |
|-----------|-------------|----------|---------|
| List documents | GET `/_all_docs` | Filtered by tenant | `GET /db/_all_docs` |
| Find documents | POST `/_find` | Tenant filter injected | `POST /db/_find` |
| Get document | GET `/docid` | Validated to match tenant | `GET /db/doc1` |
| Create document | PUT `/docid` | Tenant injected | `PUT /db/doc1` |
| Update document | PUT `/docid` | Tenant validated | `PUT /db/doc1` |
| Bulk operations | POST `/_bulk_docs` | Tenant injected | `POST /db/_bulk_docs` |
| Delete document | DELETE `/docid` | Validated to match tenant | `DELETE /db/doc1` |
| Changes feed | GET/POST `/_changes` | Filtered by tenant | `GET /db/_changes` |
| Revisions limit | GET/PUT `/_revs_limit` | Allowed | `GET /db/_revs_limit` |
| Compact | POST `/_compact` | Allowed | `POST /db/_compact` |
| Cleanup | POST `/_view_cleanup` | Allowed | `POST /db/_view_cleanup` |

## Blocked Operations

These endpoints return **403 Forbidden** in tenant mode:

- `GET/POST /_design/*` - Design documents
- `GET/POST /_view/*` - View operations
- `GET/PUT /_security` - Security settings
- `POST /_replicator` - Replication
- `GET /_session` - Session info
- Any other non-whitelisted endpoint

## Configuration Options

### TENANT_CLAIM

JWT claim name containing tenant ID (default: `tenant_id`)

```bash
TENANT_CLAIM=org_id
```

Then JWTs should contain:
```json
{"sub": "user", "org_id": "company-a"}
```

### TENANT_FIELD

Document field name for tenant ID (default: `tenant_id`)

```bash
TENANT_FIELD=organization_id
```

Then documents stored as:
```json
{"title": "Task 1", "organization_id": "company-a"}
```

## Example: PouchDB + Tenant Mode

### 1. Get Token with Tenant

```javascript
const response = await fetch('http://localhost:5985/auth/token', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    api_key: 'app-key',
    tenant_id: 'company-a'
  })
});

const {token} = await response.json();
```

### 2. Create PouchDB with Proxy URL

```javascript
const db = new PouchDB('http://localhost:5985/tasks', {
  fetch: (url, opts) => {
    opts.headers = opts.headers || {};
    opts.headers.Authorization = `Bearer ${token}`;
    return PouchDB.fetch(url, opts);
  }
});
```

### 3. Sync Data

```javascript
// Create document - tenant_id auto-injected by proxy
await db.put({
  _id: 'task1',
  title: 'My Task',
  status: 'open'
});

// Query - proxy filters by tenant
const docs = await db.allDocs({include_docs: true});
// Result only contains company-a documents
```

## Security Considerations

### ✅ Strengths

1. **Transparent** - Client doesn't need to manage tenant_id
2. **Enforced** - Server-side enforcement, can't be bypassed by client
3. **Automatic** - Tenant injection and filtering happens automatically
4. **Isolated** - One tenant cannot enumerate other tenants' data
5. **Audited** - All access logged with tenant context

### ⚠️ Important Notes

1. **JWT Secret** - Change `JWT_SECRET` in production
2. **HTTPS** - Use HTTPS in production to protect tokens
3. **Token Expiration** - Tokens expire after 1 hour
4. **Tenant Claim** - Must match your JWT structure
5. **Database Design** - All documents should have consistent structure

## Testing Tenant Isolation

### Test 1: Verify Tenant Filtering

```bash
# Create token for company-a
TOKEN_A=$(curl -s -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key":"test-key"}' | jq -r .token)

# Create token for company-b
TOKEN_B=$(curl -s -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key":"test-key"}' | jq -r .token)

# Create document as company-a
curl -X POST \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"task":"A1"}' \
  http://localhost:5985/tasks

# Create document as company-b
curl -X POST \
  -H "Authorization: Bearer $TOKEN_B" \
  -H "Content-Type: application/json" \
  -d '{"task":"B1"}' \
  http://localhost:5985/tasks

# Query as company-a - should only see A1
curl -H "Authorization: Bearer $TOKEN_A" \
  http://localhost:5985/tasks/_all_docs
# Result: only shows doc with tenant_id = company-a

# Query as company-b - should only see B1
curl -H "Authorization: Bearer $TOKEN_B" \
  http://localhost:5985/tasks/_all_docs
# Result: only shows doc with tenant_id = company-b
```

### Test 2: Verify Endpoint Blocking

```bash
# Try to access design docs (should be blocked)
curl -H "Authorization: Bearer $TOKEN_A" \
  http://localhost:5985/tasks/_design/docs
# Result: 403 Forbidden
```

### Test 3: Verify Tenant Injection

```bash
# Create doc without tenant_id
curl -X PUT \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"title":"Task"}' \
  http://localhost:5985/tasks/task1

# Get doc - should have tenant_id injected
curl -H "Authorization: Bearer $TOKEN_A" \
  http://localhost:5985/tasks/task1
# Result: {"_id":"task1","title":"Task","tenant_id":"company-a"}
```

## Troubleshooting

### "Missing tenant information"

**Problem:** Proxy says `Missing tenant information`
**Cause:** Tenant mode enabled but JWT doesn't have tenant_id claim
**Fix:** Ensure JWT includes tenant_id claim with value

```bash
# Check JWT claims
echo $TOKEN | jq -R 'split(".")[1] | @base64d | fromjson'
# Should show: {"tenant_id": "company-a"}
```

### "Access denied: document tenant mismatch"

**Problem:** Can't access a document
**Cause:** Document belongs to different tenant
**Fix:** This is correct behavior - each tenant can only access their docs

### "Endpoint not allowed"

**Problem:** 403 Forbidden on allowed endpoint
**Cause:** Endpoint is blocked in tenant mode
**Fix:** Use allowed endpoints only (see table above)

### "Invalid or expired token"

**Problem:** Token not working
**Cause:** Token expired or invalid signature
**Fix:** Get a new token

```bash
curl -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key":"test-key"}'
```

## Performance Tips

1. **Reuse tokens** - Get token once, use for multiple requests
2. **Batch operations** - Use `/_bulk_docs` for multiple documents
3. **Index for tenant** - Create CouchDB index on tenant_id for queries
4. **Connection pooling** - Reuse HTTP connections

## Production Checklist

- [ ] Set `JWT_SECRET` to secure random value
- [ ] Use HTTPS for all connections
- [ ] Set `PROXY_PORT` to non-default port
- [ ] Configure `TENANT_CLAIM` to match your JWT structure
- [ ] Test tenant isolation thoroughly
- [ ] Monitor logs for access patterns
- [ ] Set up backups for CouchDB
- [ ] Plan token rotation strategy
- [ ] Document tenant naming convention
- [ ] Set up monitoring/alerts

## Further Reading

- See [README.md](README.md) for general proxy documentation
- See [DOCKER_SETUP.md](DOCKER_SETUP.md) for Docker setup
- See [GETTING_STARTED.md](GETTING_STARTED.md) for quick start
