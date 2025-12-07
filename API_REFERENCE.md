# API Reference

## Overview

The CouchDB JWT Proxy provides a secure HTTP API for accessing CouchDB with Clerk JWT authentication and optional multi-tenant data isolation. All requests require a valid Clerk JWT token except for the health check endpoint.

## Base URL

- **Development:** `http://localhost:5985`
- **Production:** Configure via `PROXY_HOST` and `PROXY_PORT` environment variables

## Authentication

All API requests (except `/health`) require a Clerk JWT token in the Authorization header:

```
Authorization: Bearer <clerk_jwt_token>
```

### Getting a Token

```javascript
// In your frontend with Clerk SDK
const token = await window.Clerk.session.getToken();
```

### Token Validation

- **Algorithm:** RS256 (public key cryptography)
- **Validation:** Against Clerk's JWKS endpoint (cached for performance)
- **Expiration:** Managed by Clerk (typically 1 hour)
- **Required Claims:**
  - `sub`: Clerk user ID
  - `iss`: Clerk issuer URL (must match `CLERK_ISSUER_URL`)
  - `tenant_id`: Tenant identifier (for multi-tenant mode)

## Endpoints

### Health Check

**GET /health**

Check proxy and CouchDB connectivity. No authentication required.

**Response (200 OK - Healthy):**
```json
{
  "status": "ok",
  "service": "couchdb-jwt-proxy",
  "couchdb": "connected"
}
```

**Response (200 OK - Degraded):**
```json
{
  "status": "degraded",
  "service": "couchdb-jwt-proxy",
  "couchdb": "error"
}
```

**Response (503 Service Unavailable - Error):**
```json
{
  "status": "error",
  "service": "couchdb-jwt-proxy",
  "couchdb": "unavailable"
}
```

### CouchDB Proxy

**ANY /{database}/{path}**

Proxies all HTTP methods to CouchDB with JWT validation and optional tenant filtering.

**Supported Methods:** GET, POST, PUT, DELETE, HEAD, COPY, PATCH

**Headers:**
```
Authorization: Bearer <clerk_jwt_token>
Content-Type: application/json  (for POST/PUT requests)
```

**Behavior:**
1. Validates Clerk JWT token
2. Extracts tenant ID from JWT (if multi-tenant mode enabled)
3. Applies tenant filtering/injection (for roady apps)
4. Forwards request to CouchDB
5. Filters response (for roady apps)
6. Returns CouchDB response

## User & Tenant Management

**IMPORTANT:** All users and tenants are stored in the `couch-sitter` database, regardless of which application database the user is accessing. Application databases (roady, booking, etc.) contain only business data with `tenant_id` references.

### Database Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ couch-sitter Database (Central Registry)                   │
├─────────────────────────────────────────────────────────────┤
│ • All User Documents                                         │
│ • All Tenant Documents (personal & shared)                   │
│ • Application Metadata                                       │
└─────────────────────────────────────────────────────────────┘
                          ↓ (tenant_id references)
┌───────────────────┐  ┌───────────────────┐  ┌──────────────┐
│ roady Database    │  │ booking Database  │  │ other DBs... │
├───────────────────┤  ├───────────────────┤  ├──────────────┤
│ Business Data:    │  │ Business Data:    │  │ Business Data│
│ • Gigs            │  │ • Reservations    │  │ ...          │
│ • Equipment       │  │ • Venues          │  │              │
│ (with tenant_id)  │  │ (with tenant_id)  │  │              │
└───────────────────┘  └───────────────────┘  └──────────────┘
```

### Automatic User Creation

When a user first authenticates with a Clerk JWT:

1. **User Lookup:** Proxy checks `couch-sitter` database for existing user by hashed `sub` claim
2. **User Creation:** If not found, creates in `couch-sitter` database:
   - User document with Clerk metadata
   - Personal tenant with `applicationId` matching the database they're accessing
3. **Tenant Assignment:** Returns tenant ID for subsequent requests to app database

**Special Case - Couch-Sitter Admins:**
- Users accessing the `couch-sitter` database itself are added to a shared admin tenant
- Admin tenant ID: `tenant_couch_sitter_admins`
- All admins share this tenant to manage the system together

**Each user gets one personal tenant per application:**
- User logs into Roady → tenant in `couch-sitter` DB with `applicationId: "roady"`
- Same user logs into Booking → separate tenant in `couch-sitter` DB with `applicationId: "booking"`
- Roady database contains gigs/equipment with references to these tenant IDs
- Booking database contains reservations with references to these tenant IDs

**User Document Structure (in couch-sitter DB):**
```json
{
  "_id": "user_{uuid}",
  "type": "user",
  "sub_hash": "sha256_hash_of_clerk_sub",
  "email": "user@example.com",
  "name": "John Doe",
  "personal_tenant_id": "tenant_{uuid}",
  "active_tenant_id": "tenant_{uuid}",
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

**Personal Tenant Document Structure (in couch-sitter DB):**
```json
{
  "_id": "tenant_{uuid}",
  "type": "tenant",
  "name": "John's Roady Workspace",
  "applicationId": "roady",
  "owner_user_id": "user_{uuid}",
  "is_personal": true,
  "created_at": "2025-01-15T10:30:00Z"
}
```

**Shared Tenant Document Structure (in couch-sitter DB):**
```json
{
  "_id": "tenant_{uuid}",
  "type": "tenant",
  "name": "Band XYZ Equipment",
  "applicationId": "roady",
  "owner_user_id": "user_{uuid}",
  "is_personal": false,
  "user_ids": ["user_{uuid1}", "user_{uuid2}"],
  "created_at": "2025-01-15T10:30:00Z"
}
```

**Admin Tenant Document Structure (in couch-sitter DB):**
```json
{
  "_id": "tenant_couch_sitter_admins",
  "type": "tenant",
  "name": "Couch-Sitter Administrators",
  "applicationId": "couch-sitter",
  "is_personal": false,
  "user_ids": ["user_{admin1}", "user_{admin2}"],
  "created_at": "2025-01-15T10:30:00Z"
}
```

### Application Registration

Applications are registered in the `couch-sitter` database to map Clerk issuers to allowed databases.

**Application Document Structure:**
```json
{
  "_id": "app_{uuid}",
  "type": "application",
  "name": "Roady",
  "issuer": "https://clerk.jmonasterio.github.io",
  "allowed_databases": ["roady"],
  "created_at": "2025-01-15T10:30:00Z"
}
```

### Admin Database (Workspace Management)

The `couch-sitter` database also serves as the admin database for managing workspaces, admin users, and API keys.

**Workspace Document Structure:**
```json
{
  "_id": "workspace_{uuid}",
  "type": "workspace",
  "tenant_id": "{uuid}",
  "name": "ACME Inc.",
  "description": "Music venue equipment management",
  "owner_email": "admin@acmeinc.com",
  "enabled": true,
  "created_at": "2024-11-01T12:00:00Z",
  "updated_at": "2024-11-01T12:00:00Z"
}
```

**Admin User Document Structure:**
```json
{
  "_id": "admin_{email}",
  "type": "admin_user",
  "email": "user@example.com",
  "tenant_id": "{uuid}",
  "role": "owner",
  "enabled": true,
  "created_at": "2024-11-01T12:00:00Z",
  "invited_at": null,
  "joined_at": "2024-11-01T13:00:00Z"
}
```

**API Key Document Structure:**
```json
{
  "_id": "apikey_{uuid}",
  "type": "api_key",
  "tenant_id": "{uuid}",
  "name": "Roady Production Key",
  "key_hash": "sha256_hash",
  "created_by": "admin@example.com",
  "enabled": true,
  "last_used": "2024-11-02T10:30:00Z",
  "created_at": "2024-11-01T14:00:00Z",
  "expires_at": null
}
```

**Audit Log Document Structure:**
```json
{
  "_id": "audit_{uuid}",
  "type": "audit_log",
  "tenant_id": "{uuid}",
  "action": "workspace_created",
  "actor": "admin@example.com",
  "resource_type": "workspace",
  "resource_id": "workspace_{uuid}",
  "details": {},
  "created_at": "2024-11-01T12:00:00Z"
}
```

**Roles:**
- `owner` - Full workspace control, can manage users and API keys
- `admin` - Can manage workspace settings and users
- `viewer` - Read-only access to workspace data

## Multi-Tenant Data Isolation

When accessing roady databases, the proxy enforces strict tenant isolation:

### Tenant Injection

All documents created/updated automatically include `tenant_id`:

**Request:**
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Task 1","status":"open"}' \
  http://localhost:5985/roady
```

**Stored Document:**
```json
{
  "_id": "generated_id",
  "name": "Task 1",
  "status": "open",
  "tenant_id": "tenant_abc123"
}
```

### Query Filtering

Queries are automatically filtered by tenant:

**Original Request:**
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"selector":{"type":"task"}}' \
  http://localhost:5985/roady/_find
```

**Rewritten Query:**
```json
{
  "selector": {
    "type": "task",
    "tenant_id": "tenant_abc123"
  }
}
```

### Response Filtering

All responses are filtered to only include documents matching the user's tenant:

- `_all_docs`: Filtered by tenant
- `_find`: Filtered by tenant
- `_changes`: Filtered by tenant
- Single document GET: Validated against tenant

### Allowed Endpoints (Roady Apps)

| Endpoint | Methods | Description |
|----------|---------|-------------|
| `/_all_docs` | GET | List all documents (filtered by tenant) |
| `/_find` | POST | Query documents (tenant filter injected) |
| `/_bulk_docs` | POST | Bulk operations (tenant injected) |
| `/{docid}` | GET, PUT, DELETE | Single document operations (tenant validated) |
| `/_changes` | GET, POST | Changes feed (filtered by tenant) |
| `/_local/{id}` | GET, PUT, DELETE | Local documents (for PouchDB sync) |

### Blocked Endpoints (Roady Apps)

The following endpoints return `403 Forbidden` to prevent tenant bypass:

- `/_all_dbs` - Would expose other databases
- `/_users` - System database
- `/_replicator` - System database
- `/_global_changes` - Cross-database changes
- Design document operations (except queries)

## Couch-Sitter Admin Access

The `couch-sitter` database has special privileges:

- **No tenant filtering:** Can see all users and tenants
- **All endpoints allowed:** Full CouchDB access
- **Purpose:** Admin interface for managing applications, users, and tenants

## Error Responses

### Authentication Errors

**401 Unauthorized - Missing Token:**
```json
{
  "detail": "Missing authorization header"
}
```

**401 Unauthorized - Invalid Token:**
```json
{
  "detail": "Invalid token"
}
```

**401 Unauthorized - Expired Token:**
```json
{
  "detail": "Token has expired"
}
```

### Authorization Errors

**403 Forbidden - Endpoint Not Allowed:**
```json
{
  "detail": "Endpoint not allowed"
}
```

**403 Forbidden - Tenant Mismatch:**
```json
{
  "detail": "Document does not belong to your tenant"
}
```

**403 Forbidden - Unauthorized Application:**
```json
{
  "detail": "Unauthorized access to database"
}
```

### Client Errors

**400 Bad Request - Missing Tenant:**
```json
{
  "detail": "Missing tenant information"
}
```

**400 Bad Request - Invalid Database Name:**
```json
{
  "detail": "Database name missing from request"
}
```

### Server Errors

**500 Internal Server Error:**
```json
{
  "detail": "Internal server error"
}
```

**503 Service Unavailable:**
```json
{
  "detail": "Database unavailable"
}
```

## Example Workflows

### First-Time User Authentication

```javascript
// 1. User signs in with Clerk
await Clerk.signIn.create({...});

// 2. Get JWT token
const token = await Clerk.session.getToken();

// 3. Make first request (triggers user/tenant creation)
const response = await fetch('http://localhost:5985/roady/_all_docs', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});

// Proxy automatically:
// - Creates user document
// - Creates personal tenant
// - Returns filtered results
```

### Creating a Document

```javascript
const token = await Clerk.session.getToken();

const response = await fetch('http://localhost:5985/roady', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    type: 'gig',
    name: 'Spring Concert',
    date: '2025-04-15'
  })
});

// Proxy automatically injects tenant_id before storing
```

### Querying Documents

```javascript
const token = await Clerk.session.getToken();

const response = await fetch('http://localhost:5985/roady/_find', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    selector: {
      type: 'gig',
      date: { $gte: '2025-01-01' }
    }
  })
});

// Proxy automatically adds tenant_id filter
// Only returns documents for user's tenant
```

### PouchDB Sync

```javascript
const token = await Clerk.session.getToken();

const localDB = new PouchDB('roady');
const remoteDB = new PouchDB('http://localhost:5985/roady', {
  fetch: async (url, opts) => {
    return PouchDB.fetch(url, {
      ...opts,
      headers: {
        ...opts.headers,
        'Authorization': `Bearer ${token}`
      }
    });
  }
});

// Sync with automatic tenant filtering
localDB.sync(remoteDB, {
  live: true,
  retry: true
});
```

### Workspace Management (Admin)

```javascript
const token = await Clerk.session.getToken();

// Create a workspace
const response = await fetch('http://localhost:5985/couch-sitter', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    _id: `workspace_${crypto.randomUUID()}`,
    type: 'workspace',
    tenant_id: crypto.randomUUID(),
    name: 'ACME Inc.',
    description: 'Music venue equipment',
    owner_email: 'admin@acmeinc.com',
    enabled: true,
    created_at: new Date().toISOString()
  })
});

// Query workspaces for current user
const workspaces = await fetch('http://localhost:5985/couch-sitter/_find', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    selector: {
      type: 'workspace',
      owner_email: 'admin@acmeinc.com',
      deletedAt: { $exists: false }
    }
  })
});
```

### API Key Management

```javascript
const token = await Clerk.session.getToken();

// Generate API key (hash before storing)
const plainKey = 'sk_' + crypto.randomUUID().replace(/-/g, '');
const keyHash = await crypto.subtle.digest(
  'SHA-256',
  new TextEncoder().encode(plainKey)
);

const response = await fetch('http://localhost:5985/couch-sitter', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    _id: `apikey_${crypto.randomUUID()}`,
    type: 'api_key',
    tenant_id: 'workspace-tenant-id',
    name: 'Roady Production Key',
    key_hash: Array.from(new Uint8Array(keyHash))
      .map(b => b.toString(16).padStart(2, '0'))
      .join(''),
    created_by: 'admin@example.com',
    enabled: true,
    created_at: new Date().toISOString()
  })
});

// IMPORTANT: Display plainKey to user once, then discard
// It cannot be recovered after this point
console.log('API Key (save this):', plainKey);

## Configuration

### Environment Variables

**Required:**
- `CLERK_ISSUER_URL` - Clerk issuer URL for JWT validation
- `COUCHDB_INTERNAL_URL` - Internal CouchDB URL (default: `http://localhost:5984`)
- `COUCHDB_USER` - CouchDB username
- `COUCHDB_PASSWORD` - CouchDB password

**Optional:**
- `PROXY_HOST` - Proxy listen address (default: `0.0.0.0`)
- `PROXY_PORT` - Proxy listen port (default: `5985`)
- `LOG_LEVEL` - Logging level (default: `INFO`)
- `TENANT_FIELD` - Document field for tenant ID (default: `tenant_id`)
- `CLERK_SECRET_KEY` - Clerk Backend API key (optional, for session metadata)
- `COUCH_SITTER_DB_URL` - URL to couch-sitter database (default: `{COUCHDB_INTERNAL_URL}/couch-sitter`)
- `USER_CACHE_TTL_SECONDS` - User cache TTL (default: `300`)

## Security Considerations

### JWT Security
- **RS256 Validation:** Public key cryptography prevents token forgery
- **JWKS Caching:** Clerk's public keys are cached for performance
- **Token Expiration:** Tokens expire based on Clerk configuration
- **No Shared Secrets:** Proxy never stores or transmits secrets

### Tenant Isolation
- **Automatic Injection:** `tenant_id` cannot be modified by clients
- **Query Rewriting:** All queries filtered by tenant
- **Response Filtering:** Results validated against tenant
- **Endpoint Restrictions:** System endpoints blocked

### CouchDB Protection
- **Internal Port:** CouchDB not exposed directly to clients
- **Proxy-Only Access:** All requests go through JWT validation
- **Credential Management:** CouchDB credentials in environment only

### Best Practices
- ✅ Use HTTPS in production
- ✅ Keep CouchDB on internal network
- ✅ Rotate Clerk keys regularly
- ✅ Monitor failed authentication attempts
- ✅ Use INFO log level in production (DEBUG exposes sensitive data)

## Rate Limiting & Performance

### Caching
- **JWKS Cache:** Clerk public keys cached indefinitely (until restart)
- **User Cache:** User/tenant info cached for 5 minutes (configurable)

### Performance Tips
- Use PouchDB's `batch_size` option for large syncs
- Enable `live: true` for continuous sync (reduces polling)
- Use `_changes` feed with `since` parameter for incremental updates

## Troubleshooting

### Common Issues

**"Missing authorization header"**
- Ensure `Authorization: Bearer <token>` header is included
- Check token is not empty or undefined

**"Invalid token"**
- Token may be expired - get fresh token from Clerk
- Verify `CLERK_ISSUER_URL` matches token issuer
- Check Clerk JWKS endpoint is accessible

**"Endpoint not allowed"**
- Endpoint may be blocked for tenant isolation
- Use allowed endpoints: `_all_docs`, `_find`, `_bulk_docs`, `_changes`

**"Document does not belong to your tenant"**
- Attempting to access another tenant's document
- Verify document ID and tenant ID match

**"Database unavailable"**
- CouchDB may be down or unreachable
- Check `COUCHDB_INTERNAL_URL` configuration
- Verify CouchDB credentials

## Migration Guide

### From Direct CouchDB Access

**Before:**
```javascript
const db = new PouchDB('http://localhost:5984/roady', {
  auth: {
    username: 'admin',
    password: 'password'
  }
});
```

**After:**
```javascript
const token = await Clerk.session.getToken();
const db = new PouchDB('http://localhost:5985/roady', {
  fetch: async (url, opts) => {
    return PouchDB.fetch(url, {
      ...opts,
      headers: {
        ...opts.headers,
        'Authorization': `Bearer ${token}`
      }
    });
  }
});
```

### From API Key Authentication

The proxy no longer supports API key authentication. All authentication is via Clerk JWT tokens. Update your application to:

1. Integrate Clerk SDK
2. Obtain JWT tokens from Clerk
3. Include tokens in Authorization header
4. Remove API key logic

## API Versioning

**Current Version:** 1.0

The API is currently unversioned. Breaking changes will be communicated via:
- GitHub releases
- Documentation updates
- Migration guides

Future versions may include `/v1/`, `/v2/` prefixes for backward compatibility.
