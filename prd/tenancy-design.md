# Tenancy Design: Virtual Tables Layer

**Purpose:** Lightweight HTTP layer for accessing user and tenant documents via PouchDB-compatible virtual collections.

**Version:** 1.0  
**Status:** Design  
**Approach:** Thin wrapper over existing documents; minimal changes; no refactoring.

---

## Overview

Virtual tables (`__users`, `__tenants`) provide HTTP endpoints that:
1. Accept requests on virtual collection names
2. Map virtual IDs to internal document IDs
3. Enforce access control
4. Return/accept CouchDB-compatible responses
5. Support PouchDB sync natively

The underlying document structures remain unchanged from PRD-shared-tenants-invitations.md.

---

## Existing Document Structures (Unchanged)

### User Document

```json
{
  "_id": "user_abc123",
  "type": "user",
  "sub": "user_abc123",
  "email": "alice@example.com",
  "name": "Alice",
  "personalTenantId": "tenant_xyz",
  "tenantIds": ["tenant_xyz", "tenant_1", "tenant_2"],
  "tenants": [
    {
      "tenantId": "tenant_xyz",
      "role": "owner",
      "personal": true,
      "joinedAt": "2025-01-08T12:00:00Z"
    },
    {
      "tenantId": "tenant_1",
      "role": "member",
      "personal": false,
      "joinedAt": "2025-01-09T10:00:00Z"
    }
  ],
  "active_tenant_id": "tenant_xyz",
  "createdAt": "2025-01-08T12:00:00Z",
  "updatedAt": "2025-01-08T12:00:00Z"
}
```

**Key fields:**
- `tenants[]` - Array of tenant memberships with roles
- `active_tenant_id` - Currently selected tenant (for JWT)
- `sub` - Immutable Clerk user ID

### Tenant Document

```json
{
  "_id": "tenant_1",
  "type": "tenant",
  "name": "Workspace Name",
  "applicationId": "roady",
  "userId": "user_abc123",
  "userIds": ["user_abc123", "user_def456"],
  "createdAt": "2025-01-08T12:00:00Z",
  "updatedAt": "2025-01-08T12:00:00Z",
  "metadata": {
    "createdBy": "user_abc123",
    "autoCreated": false
  }
}
```

### Tenant-User Mapping Document

```json
{
  "_id": "tenant_user_mapping:tenant_1:user_def456",
  "type": "tenant_user_mapping",
  "tenantId": "tenant_1",
  "userId": "user_def456",
  "role": "member",
  "joinedAt": "2025-01-09T10:00:00Z",
  "invitedBy": "user_abc123",
  "acceptedAt": "2025-01-09T10:30:00Z"
}
```

### Invitation Document

```json
{
  "_id": "invite_abc123",
  "type": "invitation",
  "tenantId": "tenant_1",
  "tenantName": "Workspace Name",
  "email": "bob@example.com",
  "role": "member",
  "token": "sk_abcdef123456...",
  "tokenHash": "sha256(...)",
  "status": "pending",
  "createdBy": "user_abc123",
  "createdAt": "2025-01-08T12:00:00Z",
  "expiresAt": "2025-01-15T12:00:00Z",
  "acceptedAt": null,
  "acceptedBy": null
}
```

---

## Virtual Table ID Mapping

### `__users/<id>` Mapping

| Virtual | Internal |
|---------|----------|
| `__users/<id>` | `user_<id>` |

**No transformation:** Virtual ID is appended directly to user_ prefix.

**Example:**
```
GET /__users/abc123
→ Fetch document: user_abc123
→ Return as-is (no ID rewriting)
```

### `__tenants/<id>` Mapping

| Virtual | Internal |
|---------|----------|
| `__tenants/<id>` | `tenant_<id>` |

**No transformation:** Virtual ID is appended directly to tenant_ prefix.

**Example:**
```
GET /__tenants/1
→ Fetch document: tenant_1
→ Return as-is (no ID rewriting)
```

---

## Access Control Rules

### User Document (`__users/<id>`)

**Read:** User can only read their own doc.
```python
if user_id_from_jwt != requested_user_id:
    raise 403 Forbidden
```

**Update:** User can update their own doc; allowed fields: `name`, `email`, `active_tenant_id`.
```python
immutable_fields = ["sub", "type", "_id", "tenantIds", "tenants"]
if field in immutable_fields:
    raise 400 Bad Request
if field not in ["name", "email", "active_tenant_id"]:
    raise 400 Bad Request
```

**Delete:** Soft-delete only; user cannot delete themselves.
```python
if user_id_from_jwt == requested_user_id:
    raise 403 Forbidden (self-delete)
doc.deleted = True
```

### Tenant Document (`__tenants/<id>`)

**Read:** User can read if they're in `tenant.userIds`.
```python
if user_id not in tenant.userIds:
    raise 403 Forbidden
```

**Update:** Only owner can update; allowed fields: `name`, `metadata`.
```python
if tenant.userId != user_id:
    raise 403 Forbidden (not owner)
immutable_fields = ["_id", "type", "userId", "userIds", "applicationId"]
if field in immutable_fields:
    raise 400 Bad Request
```

**Delete:** Only owner; soft-delete only; cannot delete active tenant.
```python
if tenant.userId != user_id:
    raise 403 Forbidden
if user.active_tenant_id == tenant._id:
    raise 403 Forbidden (cannot delete active)
doc.deleted = True
```

**Create:** `POST /__tenants` creates new tenant; user becomes owner.
```python
new_tenant = {
  "_id": "tenant_" + uuid(),
  "userId": user_id_from_jwt,
  "userIds": [user_id_from_jwt],
  "type": "tenant",
  ...
}
```

---

## Bootstrap Flow

**Trigger:** JWT present but missing `active_tenant_id` claim.

```
1. Client makes request with valid JWT (no active_tenant_id)
2. Proxy checks if user doc exists
   - YES → Extract active_tenant_id from user doc
   - NO → Create user doc + personal tenant (below)
3. If creating:
   - Create user doc with personal tenant in tenants[]
   - Create personal tenant doc
   - Set active_tenant_id in user doc
4. Proxy returns 401 with X-Clerk-Refresh-Required header
5. Client calls Clerk refreshSession() → new JWT with active_tenant_id claim
6. Client retries with new JWT
7. Request succeeds
```

---

## Tenant Switching

**Flow:** User changes `active_tenant_id` via PUT /__users/<id>

```
1. User calls PUT /__users/<id> with { active_tenant_id: "tenant_new" }
2. Proxy validates:
   - User must be in tenant_new.userIds
   - Tenant exists and not deleted
3. Update user doc: active_tenant_id = "tenant_new"
4. Return 200 OK
5. Client calls Clerk refreshSession() → new JWT with updated claim
6. Client uses new JWT (scoped to tenant_new)
```

---

## PouchDB Sync Support

### _changes Endpoint

```
GET /__users/_changes?since=0&include_docs=true
```

Proxy filters:
- Return only the requesting user's doc
- Omit deleted docs
- No ID rewriting needed (return user_abc123 as-is)

### _bulk_docs Endpoint

```
POST /__users/_bulk_docs
POST /__tenants/_bulk_docs
```

Proxy:
- Validates each doc per access control rules
- Performs bulk CouchDB insert
- Returns per-doc status

---

## Error Responses

| Condition | Status | Body |
|-----------|--------|------|
| Missing tenant_id in JWT | 401 | `{"error": "missing_tenant_id", "bootstrapped": true}` |
| Self-delete attempt | 403 | `{"error": "self_delete_not_allowed"}` |
| Not tenant member | 403 | `{"error": "forbidden", "reason": "not_member"}` |
| Active tenant delete | 403 | `{"error": "cannot_delete_active_tenant"}` |
| Immutable field update | 400 | `{"error": "immutable_field", "field": "sub"}` |
| Not found | 404 | `{"error": "not_found"}` |
| Revision conflict | 409 | `{"error": "conflict", "current_rev": "..."}` |

---

## Summary

| Aspect | Details |
|--------|---------|
| **Documents** | Use existing structures; no refactoring |
| **Virtual Tables** | Thin HTTP layer; ID mapping only |
| **Access Control** | Enforce at proxy; membership + role checks |
| **Field Names** | Use `active_tenant_id` (snake_case) |
| **Bootstrap** | Missing claim → create user + tenant → 401 + refresh |
| **Tenant Switching** | Update `active_tenant_id` → refresh JWT |
| **Sync** | PouchDB-compatible `_changes` and `_bulk_docs` |
| **Soft-Delete** | Only mode; preserve history |

---

**Status:** Design Ready  
**Next:** VIRTUAL_TABLES_PRD.md (endpoint specifications)
