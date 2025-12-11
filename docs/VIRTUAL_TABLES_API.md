# Virtual Tables API Documentation

**Version:** 1.0  
**Status:** Implemented (M1-M5 complete)  
**Updated:** 2025-12-10

## Overview

Virtual tables provide HTTP endpoints for managing users and tenants through mycouch (CouchDB JWT proxy). They implement proper access control, multi-tenancy, and offline-first compatibility with PouchDB.

## Endpoints

### User Management (`/__users/...`)

#### GET /__users/<user_id>
Get a user document. Users can only read their own document.

**Request:**
```
GET /__users/abc123
Authorization: Bearer <JWT>
```

**Response (200 OK):**
```json
{
  "_id": "user_abc123",
  "type": "user",
  "sub": "abc123",
  "email": "user@example.com",
  "name": "John Doe",
  "personalTenantId": "tenant_abc123_personal",
  "tenantIds": ["tenant_abc123_personal", "tenant_team123"],
  "tenants": [
    {
      "tenantId": "tenant_abc123_personal",
      "role": "owner",
      "personal": true,
      "joinedAt": "2025-12-10T15:30:00Z"
    }
  ],
  "active_tenant_id": "tenant_abc123_personal",
  "createdAt": "2025-12-10T15:30:00Z",
  "updatedAt": "2025-12-10T15:30:00Z"
}
```

**Errors:**
- `401` - Missing or invalid JWT
- `403` - User trying to read another user's document
- `404` - User document not found

#### PUT /__users/<user_id>
Update allowed fields in a user document. Users can only update their own document.

**Allowed fields:** `name`, `email`, `active_tenant_id`

**Request:**
```
PUT /__users/abc123
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "name": "Jane Doe",
  "active_tenant_id": "tenant_team123"
}
```

**Response (200 OK):**
```json
{
  "ok": true,
  "_id": "user_abc123",
  "_rev": "2-abc..."
}
```

**Errors:**
- `400` - Attempting to update immutable fields (sub, type, _id, tenants, tenantIds)
- `403` - User trying to update another user's document
- `404` - User document not found
- `409` - Revision mismatch

#### DELETE /__users/<user_id>
Soft-delete a user document (set `deleted: true`). Users cannot delete themselves.

**Request:**
```
DELETE /__users/abc123
Authorization: Bearer <JWT>
```

**Response (200 OK):**
```json
{
  "ok": true,
  "_id": "user_abc123"
}
```

**Errors:**
- `403` - User trying to delete themselves or delete another user's document
- `404` - User document not found

#### GET /__users/_changes
Get stream of changes for the current user's document. Used by PouchDB for sync.

**Request:**
```
GET /__users/_changes?since=0&include_docs=true&limit=100
Authorization: Bearer <JWT>
```

**Response (200 OK):**
```json
{
  "results": [
    {
      "seq": 1,
      "id": "user_abc123",
      "changes": [
        { "rev": "1-abc..." }
      ],
      "doc": { "_id": "user_abc123", ... }
    }
  ],
  "last_seq": 1,
  "pending": 0
}
```

#### POST /__users/_bulk_docs
Perform bulk operations on user documents (update/delete multiple users).

**Request:**
```
POST /__users/_bulk_docs
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "docs": [
    { "_id": "user_abc123", "name": "Updated" },
    { "_id": "user_xyz789", "_deleted": true }
  ]
}
```

**Response (200 OK):**
```json
[
  { "ok": true, "_id": "user_abc123", "_rev": "2-..." },
  { "ok": true, "_id": "user_xyz789" }
]
```

---

### Tenant Management (`/__tenants/...`)

#### GET /__tenants
List all tenants the user is a member of. Access control enforced server-side.

**Request:**
```
GET /__tenants
Authorization: Bearer <JWT>
```

**Response (200 OK):**
Array of tenant documents where user is in `userIds`:
```json
[
  {
    "_id": "tenant_abc123_personal",
    "type": "tenant",
    "name": "John's Workspace",
    "userId": "user_abc123",
    "userIds": ["user_abc123"],
    "applicationId": "roady",
    "metadata": {
      "isPersonal": true,
      "autoCreated": true
    },
    "createdAt": "2025-12-10T15:30:00Z",
    "updatedAt": "2025-12-10T15:30:00Z"
  },
  {
    "_id": "tenant_team123",
    "type": "tenant",
    "name": "Band Equipment",
    "userId": "user_owner",
    "userIds": ["user_abc123", "user_owner"],
    "applicationId": "roady",
    "createdAt": "2025-12-10T16:00:00Z",
    "updatedAt": "2025-12-10T16:00:00Z"
  }
]
```

**Errors:**
- `401` - Missing or invalid JWT

#### GET /__tenants/<tenant_id>
Get a specific tenant document. User must be a member (`tenant.userIds` contains user_id).

**Request:**
```
GET /__tenants/team123
Authorization: Bearer <JWT>
```

**Response (200 OK):** Tenant document (see above)

**Errors:**
- `401` - Missing or invalid JWT
- `403` - User is not a member of the tenant
- `404` - Tenant not found

#### POST /__tenants
Create a new tenant. Caller becomes the owner.

**Request:**
```
POST /__tenants
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "name": "New Team"
}
```

**Response (200 OK):**
```json
{
  "ok": true,
  "_id": "tenant_abc123team",
  "_rev": "1-abc..."
}
```

**Errors:**
- `400` - Invalid request body
- `401` - Missing or invalid JWT

#### PUT /__tenants/<tenant_id>
Update a tenant document. Only the owner can update allowed fields.

**Allowed fields:** `name`, `metadata`

**Request:**
```
PUT /__tenants/team123
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "name": "Updated Team Name"
}
```

**Response (200 OK):**
```json
{
  "ok": true,
  "_id": "tenant_team123",
  "_rev": "2-abc..."
}
```

**Errors:**
- `400` - Attempting to update immutable fields (_id, type, userId, userIds, applicationId)
- `403` - User is not the owner
- `404` - Tenant not found
- `409` - Revision mismatch

#### DELETE /__tenants/<tenant_id>
Soft-delete a tenant document. Only the owner can delete, and cannot delete their active tenant.

**Request:**
```
DELETE /__tenants/team123
Authorization: Bearer <JWT>
```

**Response (200 OK):**
```json
{
  "ok": true,
  "_id": "tenant_team123"
}
```

**Errors:**
- `403` - User is not the owner or trying to delete active tenant
- `404` - Tenant not found

#### GET /__tenants/_changes
Get stream of changes for tenants the user is a member of. Used by PouchDB for sync.

**Request:**
```
GET /__tenants/_changes?since=0&include_docs=true&limit=100
Authorization: Bearer <JWT>
```

**Response (200 OK):** Changes feed filtered to member tenants

#### POST /__tenants/_bulk_docs
Perform bulk operations on tenant documents.

**Request:**
```
POST /__tenants/_bulk_docs
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "docs": [
    { "_id": "tenant_team123", "name": "Updated" }
  ]
}
```

**Response (200 OK):** Array of operation results

---

## Bootstrap Flow (First Login)

When a user first logs in with a JWT that lacks `active_tenant_id` claim:

1. **Client calls any roady endpoint** (e.g., `GET /roady/_all_docs`)
2. **MyCouch extract_tenant() detects missing active_tenant_id** in JWT
3. **Bootstrap triggered:**
   - Creates user document: `user_<sub>`
   - Creates personal tenant: `tenant_<sub>_personal`
   - Links them (tenant.userId, user.personalTenantId)
   - Sets user.active_tenant_id = personal tenant ID
4. **Client must refresh JWT** to get updated `active_tenant_id` claim (Clerk session reload)
5. **Next request succeeds** with active_tenant_id in JWT

**Bootstrap API (Internal):**
```
POST /__bootstrap
Authorization: Bearer <JWT>
Content-Type: application/json

Response (200 OK):
{
  "active_tenant_id": "tenant_abc123_personal",
  "user_doc": { ... },
  "tenant_doc": { ... },
  "bootstrapped": true
}
```

---

## ID Mapping

Virtual tables use transparent ID mapping for convenience:

| Virtual | Internal | Example |
|---------|----------|---------|
| `abc123` | `user_abc123` | User ID in URL |
| `team123` | `tenant_team123` | Tenant ID in URL |

Responses always contain internal IDs (`_id` fields).

---

## Access Control

### Users
- ✓ Can read own document
- ✓ Can update allowed fields (name, email, active_tenant_id)
- ✗ Cannot update immutable fields (sub, type, _id, tenants, tenantIds)
- ✗ Cannot delete themselves
- ✗ Cannot read/update other users

### Tenants
- ✓ Members can read tenant
- ✓ Owner can update allowed fields (name, metadata)
- ✓ Owner can delete tenant
- ✗ Cannot update immutable fields (_id, type, userId, userIds, applicationId)
- ✗ Cannot delete active tenant
- ✗ Non-members cannot read

---

## Soft Delete

When a document is deleted via `DELETE /__users/<id>` or `DELETE /__tenants/<id>`, it's soft-deleted:

```json
{
  "_id": "user_abc123",
  "deleted": true,
  "deletedAt": "2025-12-10T16:00:00Z"
}
```

Queries automatically exclude soft-deleted documents.

---

## Multi-Tenant Behavior

- Every user has a personal tenant (auto-created on first login)
- Users can create/join additional tenants
- Active tenant determines which PouchDB data is synced
- Switching tenants updates `active_tenant_id` claim and refreshes JWT

---

## PouchDB Sync Integration

Virtual endpoints support PouchDB's replication protocol:
- `GET /__users/_changes` - User document change feed
- `GET /__tenants/_changes` - Tenant change feed
- `POST /__users/_bulk_docs` - Batch updates
- `POST /__tenants/_bulk_docs` - Batch updates

## Error Responses

All endpoints return standardized error responses:

```json
{
  "detail": "Error message",
  "status_code": 403
}
```

Common status codes:
- `400` - Bad request (invalid body, missing fields)
- `401` - Unauthorized (missing/invalid JWT)
- `403` - Forbidden (access control violation)
- `404` - Not found
- `409` - Conflict (revision mismatch)
- `500` - Internal server error

---

## Testing

Run virtual table tests:
```bash
cd mycouch
uv run pytest tests/test_virtual_tables.py -v
```

Coverage:
- Access control enforcement
- Immutable field protection
- Soft-delete filtering
- Bootstrap flow
- PouchDB compatibility
- Multi-tenant isolation

**Status:** 43 passed, 2 xfailed (DAL $elemMatch refinement needed)
