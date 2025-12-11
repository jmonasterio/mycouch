# PRD: Virtual Tables (`__users` and `__tenants`)

**Status:** Design  
**Version:** 2.0  
**Date:** 2025-12-10

**Approach:** Thin HTTP layer over existing documents. Virtual tables (`__users`, `__tenants`) provide ID mapping + access control. No refactoring of underlying structure.

**Foundation:** See `tenancy-design.md` for overview.

---

## Executive Summary

Add HTTP endpoints (`__users` and `__tenants`) that proxy requests to underlying CouchDB documents with:
1. **ID mapping:** virtual IDs → internal doc IDs (e.g., `user_abc123` ↔ virtual ID `abc123`)
2. **Access control:** membership checks, role validation, soft-delete enforcement
3. **PouchDB support:** `_changes`, `_bulk_docs`, standard CRUD
4. **Bootstrap:** detect missing `active_tenant_id` → create user/tenant → 401 + JWT refresh

No changes to document structures; uses existing `user_*`, `tenant_*`, `tenant_user_mapping`, and `invitation` documents.

---

## Endpoints

### User Virtual Table: `__users/<id>`

**GET /__users/<id>**
- Returns user document for `<id>`
- User can only read their own doc (else 403)
- Returns internal ID as-is: `user_abc123`

**PUT /__users/<id>**
- Updates user doc with new values
- Allowed fields: `name`, `email`, `active_tenant_id`
- Rejects: `sub`, `type`, `_id`, `tenants[]`, `tenantIds`
- Returns updated doc or 400/409/403

**DELETE /__users/<id>**
- Soft-delete user doc: set `deleted = True`
- Rejects self-delete (403)
- Returns `{"ok": true, "_id": "...", "_rev": "..."}`

**GET /__users**
- Returns user's own doc only (filtered by JWT)
- Same as `GET /__users/<authenticated-user-id>`

**GET /__users/_changes**
- Returns change feed for user docs
- Filters: only requesting user's doc
- Supports `?since=<seq>&include_docs=true&limit=<n>`

**POST /__users/_bulk_docs**
- Batch user operations
- Validates each doc per access control rules
- Returns array of per-doc status: `[{ok: true, _id: ..., _rev: ...}, ...]`

---

### Tenant Virtual Table: `__tenants/<id>`

**GET /__tenants/<id>**
- Returns tenant doc for `<id>`
- User must be in `tenant.userIds` (else 403)
- Returns internal ID as-is: `tenant_1`

**GET /__tenants**
- Returns all tenants user is member of
- Filters: `tenantId in user.tenantIds` and `not deleted`
- Supports `?skip=<n>&limit=<n>`

**POST /__tenants**
- Create new tenant
- Request body: `{"name": "...", "metadata": {...}}`
- User becomes owner: `userId = user_id_from_jwt`, `userIds = [user_id]`
- Returns new tenant doc (201 Created)

**PUT /__tenants/<id>**
- Update tenant doc
- Allowed fields: `name`, `metadata`
- Rejects: `_id`, `type`, `userId`, `userIds`, `applicationId`
- Only owner can update (else 403)
- Returns updated doc or 400/403/409

**DELETE /__tenants/<id>**
- Soft-delete tenant: set `deleted = True`
- Only owner can delete (else 403)
- Rejects delete if tenant is user's `active_tenant_id` (403)
- Returns `{"ok": true, "_id": "...", "_rev": "..."}`

**GET /__tenants/_changes**
- Returns change feed for tenant docs
- Filters: only tenants user is member of; excludes deleted
- Supports `?since=<seq>&include_docs=true&limit=<n>`

**POST /__tenants/_bulk_docs**
- Batch tenant operations
- Validates each doc per access control rules
- Returns per-doc status array

---

## Request/Response Examples

### Create User (Bootstrap)

**Scenario:** First login, user doesn't exist.

```
POST /__users
Authorization: Bearer <jwt-no-active_tenant_id>
```

**Proxy detects missing user:**
1. Create user doc: `user_abc123` with `tenants = [{tenantId: personal, role: owner}]`
2. Create personal tenant: `tenant_abc123_personal`
3. Set `active_tenant_id = tenant_abc123_personal` in user doc
4. Return 401 with header `X-Clerk-Refresh-Required: true`

**Response:**
```json
{
  "error": "missing_active_tenant_id",
  "message": "Created user and personal tenant. Refresh JWT.",
  "bootstrapped": true
}
```

**Client action:** Call `Clerk.session.getToken()` → new JWT with `active_tenant_id` → retry.

---

### Update Active Tenant

**Request:**
```
PUT /__users/abc123
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "_id": "user_abc123",
  "_rev": "2-xxx",
  "active_tenant_id": "tenant_1"
}
```

**Proxy checks:**
- User must be in `tenant_1.userIds` ✓
- `tenant_1` exists and not deleted ✓
- Field update allowed (active_tenant_id) ✓

**Response:**
```json
{
  "_id": "user_abc123",
  "_rev": "3-yyy",
  "type": "user",
  "sub": "user_xyz",
  "email": "alice@example.com",
  "name": "Alice",
  "tenants": [...],
  "active_tenant_id": "tenant_1",
  "createdAt": "...",
  "updatedAt": "..."
}
```

**Client action:** Refresh JWT → new token with `active_tenant_id: tenant_1`.

---

### Create Tenant

**Request:**
```
POST /__tenants
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "name": "Blue Notes Band",
  "metadata": {"genre": "jazz"}
}
```

**Proxy:**
- Generates UUID for tenant
- Sets `userId = user_from_jwt`, `userIds = [user_from_jwt]`
- Writes to CouchDB: `tenant_<uuid>`

**Response (201):**
```json
{
  "_id": "tenant_abc123",
  "_rev": "1-xxx",
  "type": "tenant",
  "name": "Blue Notes Band",
  "userId": "user_abc123",
  "userIds": ["user_abc123"],
  "applicationId": "roady",
  "metadata": {"genre": "jazz"},
  "createdAt": "2025-01-15T10:00:00Z",
  "updatedAt": "2025-01-15T10:00:00Z"
}
```

---

### Get Changes (PouchDB Sync)

**Request:**
```
GET /__tenants/_changes?since=0&include_docs=true
Authorization: Bearer <jwt>
```

**Proxy:**
- Queries CouchDB `_changes` for `type=tenant` docs
- Filters: only tenants where `user_id in userIds` and `!deleted`
- Returns change feed

**Response:**
```json
{
  "results": [
    {
      "seq": "10-abc",
      "id": "tenant_1",
      "changes": [{"rev": "2-xxx"}],
      "doc": {
        "_id": "tenant_1",
        "_rev": "2-xxx",
        "type": "tenant",
        "name": "Band 1",
        ...
      }
    },
    {
      "seq": "11-def",
      "id": "tenant_2",
      "changes": [{"rev": "1-yyy"}],
      "doc": {...}
    }
  ],
  "pending": 0,
  "last_seq": "11-def"
}
```

---

## Error Responses

**Missing active_tenant_id in JWT (Bootstrap)**
```json
{
  "status": 401,
  "error": "missing_active_tenant_id",
  "message": "Created user and personal tenant. Refresh JWT.",
  "bootstrapped": true
}
```

**Self-Delete Attempt**
```json
{
  "status": 403,
  "error": "self_delete_not_allowed",
  "message": "Users cannot delete themselves."
}
```

**Not Tenant Member**
```json
{
  "status": 403,
  "error": "forbidden",
  "reason": "not_member",
  "message": "You are not a member of this tenant."
}
```

**Immutable Field Update**
```json
{
  "status": 400,
  "error": "immutable_field",
  "field": "sub",
  "message": "Field 'sub' cannot be modified."
}
```

**Cannot Delete Active Tenant**
```json
{
  "status": 403,
  "error": "cannot_delete_active_tenant",
  "message": "Switch to another tenant before deleting.",
  "active_tenant_id": "tenant_xyz"
}
```

**Not Found**
```json
{
  "status": 404,
  "error": "not_found"
}
```

**Revision Conflict**
```json
{
  "status": 409,
  "error": "conflict",
  "current_rev": "2-xxx",
  "requested_rev": "1-yyy"
}
```

---

## Access Control Matrix

| Operation | Owner | Member | Non-Member | Soft-Deleted |
|-----------|-------|--------|------------|-------------|
| **GET __users/<self>** | ✓ | — | — | ✓ |
| **GET __users/<other>** | ✗ | — | — | — |
| **PUT __users/<self>** | ✓ | — | — | ✗ |
| **DELETE __users/<self>** | ✗ (forbidden) | — | — | — |
| **GET __tenants/<id>** | ✓ | ✓ | ✗ | ✗ |
| **PUT __tenants/<id>** | ✓ | ✗ | ✗ | ✗ |
| **DELETE __tenants/<id>** | ✓ (not active) | ✗ | ✗ | — |
| **POST __tenants** | ✓ | — | — | — |
| **GET __tenants** | Own/member list | — | — | — |
| **_changes** | Own docs | — | — | Filtered |

---

## Implementation Checklist

- [ ] ID mapping utility: `__users/<id>` ↔ `user_<id>`, `__tenants/<id>` ↔ `tenant_<id>`
- [ ] Access control middleware: membership checks, role validation
- [ ] Bootstrap logic: detect missing `active_tenant_id`, create user + tenant
- [ ] User endpoints: GET, PUT, DELETE, _changes, _bulk_docs
- [ ] Tenant endpoints: GET, POST, PUT, DELETE, _changes, _bulk_docs
- [ ] Error responses: all cases with correct status codes
- [ ] PouchDB sync support: _changes filtering, _bulk_docs validation
- [ ] Tests: unit (access control, bootstrap), integration (sync), E2E

---

## Deliverables

1. **Proxy routes** for `__users` and `__tenants` (FastAPI)
2. **ID mapping utility** (stateless functions)
3. **Access control enforcement** (middleware/helpers)
4. **Bootstrap logic** integrated into auth flow
5. **_changes and _bulk_docs** handlers
6. **Unit + integration tests** covering all scenarios
7. **API documentation** (this PRD serves as spec)

---

## Success Criteria

1. All virtual table endpoints functional and tested
2. Bootstrap flow: missing JWT → create user/tenant → 401 + refresh → success
3. Tenant switching: update `active_tenant_id` → JWT refresh → scoped requests
4. PouchDB sync: client can replicate against `__users` and `__tenants`
5. Access control: users only see/modify what they should
6. Soft-delete: deleted docs not returned; can be restored
7. All error codes correct; JSON error bodies consistent

---

## References

- **tenancy-design.md** - Overview, document structures, access rules
- **PRD-shared-tenants-invitations.md** - Full invitation and membership model
- **strict-jwt-tenant-propagation.md** - JWT claim configuration

---

**Version:** 2.0  
**Last Updated:** 2025-12-10  
**Status:** Ready for Implementation
