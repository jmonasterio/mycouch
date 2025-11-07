# Tenant Determination Algorithm

This document explains how the CouchDB JWT Proxy determines which tenant a user belongs to.

## Current Algorithm

### Overview

The tenant for a user is determined by **extracting a specific claim from their JWT token**.

```
User sends request with JWT token
  ↓
Proxy validates JWT (Clerk or custom)
  ↓
Proxy extracts TENANT_CLAIM from JWT payload
  ↓
Tenant determined from claim value
  ↓
Requests filtered/restricted to that tenant's data
```

### Step-by-Step Process

#### 1. User Authentication
- User logs in with Clerk (or other auth provider)
- Clerk returns a JWT token containing user information
- User includes token in `Authorization: Bearer <token>` header

#### 2. Token Validation
- Proxy receives request with JWT token
- Proxy validates the JWT signature:
  - If using Clerk: Validates RS256 using Clerk's public keys
- If validation fails: Request rejected with 401

#### 3. Tenant Extraction
```python
def extract_tenant(payload: Dict[str, Any]) -> Optional[str]:
    """Extract tenant ID from JWT payload"""
    if not ENABLE_TENANT_MODE:
        return None

    # Read the TENANT_CLAIM setting (default: "tenant_id")
    tenant = payload.get(TENANT_CLAIM)

    if not tenant:
        logger.warning(f"Missing tenant claim '{TENANT_CLAIM}' in JWT")
        return None

    return tenant
```

#### 4. Data Isolation
Once tenant is determined, all CouchDB requests are filtered:
- Queries automatically restricted to user's tenant
- Documents automatically tagged with tenant_id
- Response documents filtered to show only tenant's data

---

## Configuration

### Tenant Mode (Must Be Enabled)

```bash
# In .env or environment variables
ENABLE_TENANT_MODE=true
```

When `ENABLE_TENANT_MODE=false`:
- Tenant extraction is skipped
- All documents visible to all users
- No data isolation

### Tenant Claim Name

```bash
# In .env or environment variables
TENANT_CLAIM=tenant_id
```

This is the **name of the JWT claim** containing the tenant ID.

**Examples:**

```
TENANT_CLAIM=tenant_id       # JWT must have: {"tenant_id": "band-1"}
TENANT_CLAIM=band_id         # JWT must have: {"band_id": "band-1"}
TENANT_CLAIM=organization    # JWT must have: {"organization": "band-1"}
TENANT_CLAIM=sub             # JWT must have: {"sub": "band-1"}
```

### Tenant Field Name

```bash
# In .env or environment variables
TENANT_FIELD=tenant_id
```

This is the **field name in CouchDB documents** that stores tenant_id.

**Example document:**

```json
{
  "_id": "gig_123456",
  "_rev": "1-abc123",
  "type": "gig",
  "tenant_id": "band-1",      // ← This field
  "name": "Spring Concert",
  "date": "2025-04-15"
}
```

---

## JWT Claim Requirements

### When Using Clerk

Your Clerk setup **must** include the tenant claim in the JWT:

1. **In Clerk Dashboard:**
   - Go to JWT Templates
   - Edit the default template (or create custom)
   - Add custom claim for tenant:

   ```javascript
   // In Clerk JWT Template
   {
     "tenant_id": "{{org.id}}"  // Organization ID
   }
   ```

2. **Resulting JWT will contain:**
   ```json
   {
     "iss": "https://your-clerk-instance.clerk.accounts.dev",
     "sub": "user_123",
     "org_id": "org_456",
     "tenant_id": "org_456",  // ← Added by template
     ...
   }
   ```

### When Using Custom JWT

When creating custom tokens, include the tenant claim:

```python
# In your auth endpoint
from datetime import datetime, timedelta, timezone

payload = {
    "sub": user_id,
    "iat": int(datetime.now(timezone.utc).timestamp()),
    "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    "tenant_id": "band-1"  # ← Include tenant
}

token = jwt.encode(payload, TBD, algorithm="HS256")
```

---

## Examples

### Example 1: User from Band-1

**JWT Token Contains:**
```json
{
  "sub": "user_alice",
  "tenant_id": "band-1",
  "email": "alice@band1.com"
}
```

**Behavior:**
- ✅ Can read: Documents with `tenant_id: "band-1"`
- ✅ Can create: New docs automatically get `tenant_id: "band-1"`
- ❌ Cannot read: Documents with `tenant_id: "band-2"`

### Example 2: User from Band-2

**JWT Token Contains:**
```json
{
  "sub": "user_bob",
  "tenant_id": "band-2",
  "email": "bob@band2.com"
}
```

**Behavior:**
- ✅ Can read: Documents with `tenant_id: "band-2"`
- ✅ Can create: New docs automatically get `tenant_id: "band-2"`
- ❌ Cannot read: Documents with `tenant_id: "band-1"`

### Example 3: Missing Tenant Claim

**JWT Token Contains:**
```json
{
  "sub": "user_charlie",
  "email": "charlie@unknown.com"
}
```

**Behavior:**
- ❌ Request rejected
- Logs: `WARNING - Missing tenant claim 'tenant_id' in JWT`
- Response: 400 Bad Request

---

## Data Isolation Methods

### On Write (CREATE/UPDATE)

When user creates a document, tenant ID is **automatically injected**:

```python
# User sends:
{
  "name": "Spring Concert",
  "date": "2025-04-15"
}

# Proxy transforms to:
{
  "name": "Spring Concert",
  "date": "2025-04-15",
  "tenant_id": "band-1"  // ← Injected from JWT
}

# Stored in CouchDB as above
```

### On Read (QUERY/GET)

When user queries documents, results are **filtered by tenant**:

```python
# User sends query:
GET /_all_docs

# Proxy transforms query to:
GET /_all_docs?start_key="band-1:"&end_key="band-1:\uffff"

# Result: Only documents with tenant_id="band-1"
```

### On DELETE

When user deletes, only their tenant's documents can be deleted:

```python
# User tries to delete:
DELETE /gig_123

# Proxy checks:
# 1. Fetch document
# 2. Verify tenant_id matches user's tenant
# 3. If match: Allow delete
# 4. If mismatch: Return 403 Forbidden
```

---

## Current Implementation Details

### Code Location

**File:** `main.py`

**Key functions:**
- `extract_tenant()` - Lines 186-194
  - Extracts tenant from JWT payload
- `filter_document_for_tenant()` - Lines 222-231
  - Validates document belongs to tenant
- `inject_tenant_into_doc()` - Lines 233-239
  - Adds tenant to outgoing documents
- `rewrite_all_docs_query()` - Lines 241-250
  - Modifies CouchDB queries for tenant filtering
- `rewrite_find_query()` - Lines 252-263
  - Filters _find queries by tenant
- `filter_response_documents()` - Lines 279-315
  - Removes non-tenant documents from responses

### Configuration Variables

- `ENABLE_TENANT_MODE` - Boolean to enable/disable tenant isolation
- `TENANT_CLAIM` - JWT claim name (default: "tenant_id")
- `TENANT_FIELD` - Document field name (default: "tenant_id")

---

## Troubleshooting

### Symptom: 400 Bad Request - Missing tenant information

**Cause:** JWT doesn't contain the tenant claim

**Solution:**
1. Check JWT claim name matches `TENANT_CLAIM` setting
2. Verify JWT actually contains the claim
3. Decode token: https://jwt.io
4. If using Clerk, check JWT template includes the claim

### Symptom: User can't see their data

**Cause:** Tenant ID mismatch

**Check:**
```bash
# Decode your JWT at jwt.io
# Verify "tenant_id" matches the documents you expect

# Check documents in CouchDB
curl -u admin:password http://localhost:5984/roady/_all_docs?include_docs=true | grep tenant_id

# All should match
```

### Symptom: Cross-tenant data visible (SECURITY ISSUE!)

**Cause:** `ENABLE_TENANT_MODE=false` or tenant filtering not working

**Solution:**
```bash
# Verify tenant mode is enabled
grep ENABLE_TENANT_MODE .env
# Should show: ENABLE_TENANT_MODE=true

# Restart proxy to apply setting
sudo systemctl restart couchdb-proxy
```

---

## Roady PWA Integration

In the Roady PWA (`js/db.js`), the tenant is set:

```javascript
// Set tenant for current band
DB.setTenant('band-1');

// This affects all subsequent database operations
// Documents created will have: tenant_id: "band-1"
// Queries will be filtered to: tenant_id: "band-1"
```

---

## Algorithm Summary

| Step | Operation | Input | Output |
|------|-----------|-------|--------|
| 1 | User sends request | JWT token in header | - |
| 2 | Validate token | JWT token | Decoded payload |
| 3 | Extract tenant | Payload + TENANT_CLAIM | tenant_id (string) |
| 4 | Filter request | tenant_id + request | Modified request |
| 5 | Send to CouchDB | Modified request | CouchDB response |
| 6 | Filter response | Response + tenant_id | Filtered response |
| 7 | Return to user | Filtered response | User sees only their tenant data |

---

## Future Improvements (Optional)

Current limitations that could be enhanced:

1. **Single tenant per user:**
   - Currently: User has one tenant (tenant_id claim)
   - Could: Support users with multiple tenant access
   - Example JWT: `"tenants": ["band-1", "band-2"]`

2. **Role-based access:**
   - Currently: All users in tenant have same access
   - Could: Add role claims to JWT
   - Example JWT: `"role": "admin"` or `"role": "viewer"`

3. **Dynamic tenant lists:**
   - Currently: Tenant list in JWT
   - Could: Query auth server for tenant permissions
   - More flexible but slower

4. **Hierarchical tenants:**
   - Currently: Flat tenant structure
   - Could: Support `parent_tenant` for data rollup
   - Example: organization → team → project

---

## Security Considerations

### Threats Mitigated

- ✅ **Cross-tenant data leakage:** Tenant verification on every request
- ✅ **Privilege escalation:** Tenant extracted from JWT, not user input
- ✅ **Missing data isolation:** Responses filtered by tenant
- ✅ **Injection attacks:** Tenant used in selector, not query string

### Best Practices

2. **Use HTTPS** - Prevent token interception
3. **Keep tokens short-lived** - Reduce exposure window
4. **Validate tenant on server** - Don't trust client claims
5. **Log tenant operations** - Audit data access
6. **Test cross-tenant queries** - Verify isolation works

---

## Current Status

**Tenant isolation:** ✅ Fully implemented
- Extract tenant from JWT claim
- Inject tenant into new documents
- Filter queries by tenant
- Filter responses by tenant
- Validation on every operation

**Ready for:** ✅ Production use with ENABLE_TENANT_MODE=true
