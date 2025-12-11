# Virtual Tables Design Summary

**Date:** 2025-12-10  
**Approach:** Thin HTTP layer; ID mapping + access control; minimal changes to documents.

---

## What Was Created

### 1. **tenancy-design.md**

Overview of virtual tables approach:
- Uses existing document structures (no refactoring)
- Virtual tables are HTTP endpoints that map virtual IDs to internal IDs
- `__users/<id>` maps to `user_<id>`
- `__tenants/<id>` maps to `tenant_<id>`
- Access control enforced at proxy layer
- Bootstrap flow: missing `active_tenant_id` → create user + tenant → 401 + refresh
- Tenant switching via `active_tenant_id` update + JWT refresh
- PouchDB sync support via `_changes` and `_bulk_docs`

---

### 2. **VIRTUAL_TABLES_PRD.md** (v2.0)

Technical specification for virtual table endpoints:
- Complete endpoint descriptions (GET, POST, PUT, DELETE, _changes, _bulk_docs)
- Request/response examples with real JSON
- Error codes and error bodies
- Access control matrix
- Implementation checklist
- Success criteria

---

### 3. **10 Beads (Issues)** in Dependency Chain

M1-M6 implementation roadmap:
- **M1:** Virtual table routing + ID mapping
- **M2:** Bootstrap logic + JWT refresh
- **M3:** User CRUD + Tenant CRUD + access control
- **M4:** PouchDB _changes + _bulk_docs
- **M5:** Unit + integration tests
- **M6:** API docs + migration guide

---

## Architecture

```
┌─────────────────────────────────────────┐
│ Client (PouchDB, Roady PWA)             │
│ - Syncs __users, __tenants              │
│ - JWT has active_tenant_id              │
└────────────────┬────────────────────────┘
                 │ HTTP + Bearer JWT
                 ↓
┌─────────────────────────────────────────┐
│ MyCouch Proxy                           │
├─────────────────────────────────────────┤
│ Virtual Tables Layer                    │
│ (__users, __tenants)                    │
│ - ID mapping (virtual ↔ internal)       │
│ - Access control (membership, role)     │
│ - Soft-delete enforcement               │
│ - Bootstrap flow                        │
└────────────────┬────────────────────────┘
                 │ Internal HTTP
                 ↓
        ┌────────────────────┐
        │ CouchDB            │
        │ (couch-sitter DB)  │
        │                    │
        │ - user_*           │
        │ - tenant_*         │
        │ - invitation_*     │
        │ - mapping_*        │
        └────────────────────┘
```

---

## Key Concepts

| Concept | Details |
|---------|---------|
| **Virtual Tables** | HTTP endpoints that map virtual IDs to internal CouchDB documents |
| **ID Mapping** | `__users/abc123` → `user_abc123`, `__tenants/1` → `tenant_1` (no hashing) |
| **Access Control** | User can read own doc; can read/write tenants they're member of; only owner can delete |
| **Active Tenant** | Currently selected tenant; stored as `active_tenant_id` field in user doc and JWT |
| **Bootstrap** | First login: detect missing `active_tenant_id` → create user + personal tenant → return 401 + refresh JWT |
| **Tenant Switching** | Update `active_tenant_id` in user doc → refresh JWT → JWT now scoped to new tenant |
| **PouchDB Sync** | Virtual tables support `_changes` (filtered by membership) and `_bulk_docs` (per-doc validation) |
| **Soft-Delete** | Only deletion mode; `deleted = true`; docs filtered from queries |

---

## Document Structures (Unchanged)

All existing documents from PRD-shared-tenants-invitations.md are preserved:
- **User doc:** `user_<id>` with `tenants[]`, `active_tenant_id`, `tenantIds`
- **Tenant doc:** `tenant_<id>` with `userId`, `userIds`, `metadata`
- **Tenant-user mapping:** `tenant_user_mapping:*` for role tracking (deprecated but kept)
- **Invitation:** `invite_*` for single-use invite tokens

No refactoring; virtual tables just provide HTTP access.

---

## HTTP Layer (What's New)

Virtual table endpoints provide:

1. **ID Translation**
   - Accept virtual IDs (e.g., `abc123`)
   - Map to internal IDs (e.g., `user_abc123`)
   - Return with internal IDs (no rewriting back)

2. **Access Control**
   - Check JWT user ID
   - Verify membership (in `tenant.userIds` or own doc)
   - Verify role if needed (owner vs member)
   - Return 403 if not allowed

3. **CouchDB Compatibility**
   - Standard CRUD (GET, POST, PUT, DELETE)
   - `_changes` endpoint (with filtering)
   - `_bulk_docs` endpoint (with validation)
   - Proper conflict handling (409)

4. **Bootstrap**
   - Detect missing `active_tenant_id` in JWT
   - Create user doc + personal tenant if needed
   - Return 401 with `X-Clerk-Refresh-Required` header
   - Client refreshes JWT via Clerk

---

## Implementation Flow

### Request Arrives

```
GET /__tenants/1
Authorization: Bearer <jwt>

Proxy:
1. Decode JWT → extract user_id
2. Map virtual ID: "1" → "tenant_1"
3. Fetch doc from CouchDB: tenant_1
4. Check access: is user_id in tenant_1.userIds? ✓
5. Return doc (or 403 if not member)
```

### Bulk Operations

```
POST /__tenants/_bulk_docs
[{_id: "1", name: "Updated"}, {_id: "2", _deleted: true}]

Proxy (for each doc):
1. Map virtual ID to internal
2. Fetch current doc from CouchDB
3. Check access (owner? admin? member?)
4. Validate field changes (immutable fields?)
5. Perform operation (update/delete)
6. Return per-doc status
```

### Bootstrap

```
GET /api/my-data
Authorization: Bearer <jwt-no-active_tenant_id>

Proxy:
1. Decode JWT → active_tenant_id missing
2. Fetch user doc by user_id from JWT
   - If exists: skip to step 5
   - If missing: continue
3. Create user doc: user_<id> with default tenants[]
4. Create personal tenant: tenant_<id>_personal
5. Return 401 + X-Clerk-Refresh-Required
6. Client calls Clerk → new JWT with active_tenant_id
7. Client retries → success
```

---

## What Stays the Same

- Document structures (all fields unchanged)
- Invitation flow (token-based, single-use)
- Role system (owner, admin, member in tenant_user_mapping)
- Tenants array in user doc
- All existing CouchDB queries and views
- Existing auth logic (just enhanced with access control)

---

## What's New

- HTTP endpoints: `__users`, `__tenants`
- ID mapping layer (virtual ↔ internal)
- Access control enforcement at proxy
- `_changes` and `_bulk_docs` support
- Bootstrap logic (create user + tenant on first login)
- Soft-delete enforcement

---

## Deployment Checklist

- [ ] Clerk JWT template configured with `active_tenant_id` claim
- [ ] Virtual table routes registered in FastAPI proxy
- [ ] ID mapping utility implemented (no-op in this approach)
- [ ] Access control middleware implemented
- [ ] Bootstrap logic implemented
- [ ] `_changes` filtering implemented
- [ ] `_bulk_docs` validation implemented
- [ ] All tests passing
- [ ] Docs updated

---

## Questions to Resolve Before Implementation

1. **Personal tenant naming:** Auto-name as `tenant_<user_id>_personal`? Or use UUID?
2. **Clerk configuration:** Is JWT template with `active_tenant_id` claim already configured?
3. **Admin users:** Do we need admin role beyond owner? Or just owner + member?
4. **Soft-delete queries:** Should queries automatically exclude `deleted=true` docs? (Recommended: yes)
5. **Error messages:** Consistent JSON format for all errors? (Recommended: `{"status": <int>, "error": "<code>", "message": "<string>"}`)

---

**Status:** Design Complete; Ready for Implementation Review

**Next Steps:**
1. Team reviews tenancy-design.md and VIRTUAL_TABLES_PRD.md
2. Answers questions above
3. Begin M1 implementation (mycouch-odf)
