# Tenant Creation & Management (CouchDB)

The first user automatically creates a tenant derived from their Clerk sub claim, and all tenant data is keyed off that tenant ID.

## Core Data Model

### Document Types

**Tenant Document**
```json
{
  "_id": "tenant:f3a6c9a7c2",
  "type": "tenant",
  "owner_user_id": "user_abc123",
  "name": "John's Band",
  "created_at": "2025-01-15T10:30:00Z"
}
```

**User Document**
```json
{
  "_id": "user:user_abc123:tenant:f3a6c9a7c2",
  "type": "user",
  "user_id": "user_abc123",
  "tenant_id": "tenant:f3a6c9a7c2",
  "role": "owner",
  "joined_at": "2025-01-15T10:30:00Z"
}
```

**Application Data Document (Example)**
```json
{
  "_id": "gig:12345",
  "type": "gig",
  "tenant_id": "tenant:f3a6c9a7c2",
  "name": "Spring Concert",
  "date": "2025-04-15",
  "created_at": "2025-01-15T10:35:00Z"
}
```

## Authentication & Tenant Creation Flow

### 1. User Signs In Through Clerk

- Frontend obtains the JWT from Clerk
- Backend verifies the token and extracts:
  - `sub` (Clerk user ID)
  - `email`
  - Any other optional metadata

### 2. Tenant Auto-Creation

- Backend queries CouchDB for user document: `user:user_abc123:*`
- If not found:
  1. Compute a deterministic tenant ID:
     ```
     tenant_id = "tenant_" + SHA256(sub)[:12]
     ```
  2. Create tenant document in CouchDB:
     ```json
     {
       "_id": "tenant:{tenant_id}",
       "type": "tenant",
       "owner_user_id": "{sub}",
       "created_at": "{iso_timestamp}"
     }
     ```
  3. Create user document in CouchDB:
     ```json
     {
       "_id": "user:{sub}:tenant:{tenant_id}",
       "type": "user",
       "user_id": "{sub}",
       "tenant_id": "tenant:{tenant_id}",
       "role": "owner",
       "joined_at": "{iso_timestamp}"
     }
     ```

**Result:** The first time any user signs in, they implicitly create their own isolated tenant.

### 3. Tenant Scoping

All application data includes a `tenant_id` field:

```json
{
  "_id": "gig:12345",
  "type": "gig",
  "tenant_id": "tenant:f3a6c9a7c2",
  "name": "Spring Concert"
}
```

Query documents using CouchDB `_find`:

```javascript
// Get all gigs for current tenant
{
  "selector": {
    "type": "gig",
    "tenant_id": "tenant:f3a6c9a7c2"
  }
}
```

## Design Documents & Views

### Tenant Lookup View

```javascript
// Design document: _design/tenants
{
  "_id": "_design/tenants",
  "views": {
    "by_owner": {
      "map": "function(doc) { if (doc.type === 'tenant') emit(doc.owner_user_id, doc); }"
    }
  }
}
```

### User Lookup View

```javascript
// Design document: _design/users
{
  "_id": "_design/users",
  "views": {
    "by_user_and_tenant": {
      "map": "function(doc) { if (doc.type === 'user') emit([doc.user_id, doc.tenant_id], doc); }"
    }
  }
}
```

### Data by Tenant View

```javascript
// Design document: _design/data
{
  "_id": "_design/data",
  "views": {
    "by_tenant_type": {
      "map": "function(doc) { if (doc.tenant_id) emit([doc.tenant_id, doc.type], doc); }"
    }
  }
}
```

## Future Extension Points

### Invitations

- Add invitation document type:
  ```json
  {
    "_id": "invite:{uuid}",
    "type": "invite",
    "email": "newuser@example.com",
    "tenant_id": "tenant:f3a6c9a7c2",
    "role": "member",
    "token": "{unique_token}",
    "expires_at": "2025-01-22T10:30:00Z",
    "created_by": "user_abc123"
  }
  ```

- When owner invites someone:
  1. Create invite document with unique token
  2. Send email with tokenized link
  3. On accept, user signs in with Clerk
  4. Backend verifies invite token exists and is valid
  5. Create user document linking Clerk user to tenant

### Tenant Deletion

- Only `owner_user_id` may delete
- Mark tenant as deleted (soft delete) or use `_deleted: true` in CouchDB:
  ```json
  {
    "_id": "tenant:f3a6c9a7c2",
    "_deleted": true,
    "_rev": "2-xyz"
  }
  ```
- Query to exclude deleted:
  ```javascript
  {
    "selector": {
      "type": "tenant",
      "_deleted": { "$exists": false }
    }
  }
  ```

### Role Management

- Add role enum: `owner`, `admin`, `member`, `viewer`
- Implement authorization middleware to check `role` field in user document
- Query users by role:
  ```javascript
  {
    "selector": {
      "type": "user",
      "tenant_id": "tenant:f3a6c9a7c2",
      "role": "admin"
    }
  }
  ```

### Tenant Switching (Multi-Tenant Users)

Optional: If users may belong to multiple tenants, query all user documents for that user:

```javascript
// Get all tenants for a user
{
  "selector": {
    "type": "user",
    "user_id": "user_abc123"
  }
}
```

Returns multiple user documents, each linking to different tenant.

For now, with one-tenant-per-user, a single user document per user is sufficient.

### JWT Enrichment (Optional)

In the future, use Clerk webhooks or custom JWT templates to include your generated `tenant_id` as a claim:

```json
{
  "sub": "user_abc123",
  "email": "user@example.com",
  "tenant_id": "tenant:f3a6c9a7c2"
}
```

This makes backend services stateless—they extract tenant from JWT instead of querying CouchDB.

## Replication & Sync Strategy

### Per-Tenant Sync

With offline-first apps (Roady PWA), sync only the current tenant's data:

```javascript
// PouchDB sync for specific tenant
db.sync(`${couchdbUrl}/${tenant_id}_db`, {
  live: true,
  retry: true
})
```

Or filter during sync:

```javascript
// Sync with continuous filter
db.sync(remoteDb, {
  live: true,
  selector: {
    "tenant_id": "tenant:f3a6c9a7c2"
  }
})
```

### Multi-Database Strategy

Option 1: Single database with tenant_id filtering (recommended for multi-tenant)
- All tenants share one CouchDB database
- Every query filters by tenant_id
- Simpler ops, clearer relationships

Option 2: Per-tenant database
- Create database `tenant_f3a6c9a7c2_db` per tenant
- Simpler sync (no filtering needed)
- More CouchDB instances/disks needed
- Harder to query across tenants

## Summary

- **Clerk** manages user identity (`sub` is your stable user ID)
- **CouchDB** stores tenant, user, and application data as documents
- **Document IDs** follow predictable patterns: `tenant:{id}`, `user:{uid}:tenant:{tid}`
- **Each user** automatically gets a tenant on first login
- **Everything downstream** is tagged with `tenant_id` and filtered on queries
- **Views** enable efficient lookups by tenant, type, and relationships
- **Offline-first** apps sync only their tenant's data for bandwidth efficiency
