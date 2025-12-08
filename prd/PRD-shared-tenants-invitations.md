# Shared Tenants & Invitations (Backend-Centric Model)

## Overview

Users create and manage **tenants** (workspaces). All tenants have the same structure and access control model.

- **Personal Tenant** (auto-created on first login) - Marked with `isPersonal: true`, owned by user, not yet shared via invitations
- **Workspace Tenants** (created by user) - Marked with `isPersonal: false`, can be shared with multiple users via invitations

Both types use identical schemas and authorization rules. The difference is invitations — personal tenants cannot be shared yet, but could be in the future.

Apps (like Roady) interpret workspaces as "bands" or "projects" — backend just calls them tenants.

---

## Core Principles

### 1. Tenant Ownership
- User who creates a tenant is the **owner** (stored in `userId` field)
- Owner cannot be removed or downgraded to admin/member
- Only owner can delete the tenant
- Personal tenants are auto-created, user is owner

### 2. Tenant Membership & Roles
- All tenants use identical structure: `userId` (owner), `userIds` array, `tenant_user_mapping` docs
- Users access tenants via **tenant_user_mapping** documents
- Roles: `owner`, `admin`, `member`
- Role enforcement is per-tenant
- Owner/admin can manage other members

### 3. Invitations
- Owner/admin creates invite tied to specific **non-personal** tenant
- Invitations are single-use, token-based
- On acceptance, invited user becomes member of workspace
- Personal tenants cannot be shared (future enhancement)

### 4. App-Agnostic Design
- Backend doesn't know what tenant represents (band, project, team, etc.)
- `isPersonal` flag is the only semantic difference
- Invitations work for any workspace tenant, any app

---

## Data Model

### User Document

```json
{
  "_id": "user_abc123",
  "type": "user",
  "sub": "user_abc123",
  "email": "alice@example.com",
  "name": "Alice",
  "personalTenantId": "tenant_xyz",
  "tenantIds": [
    "tenant_xyz",           // personal
    "tenant_1",             // workspace they own or joined
    "tenant_2"              // another workspace
  ],
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
  "activeTenantId": "tenant_xyz",
  "createdAt": "2025-01-08T12:00:00Z",
  "updatedAt": "2025-01-08T12:00:00Z"
}
```

### Tenant Document

```json
{
  "_id": "tenant_1",
  "type": "tenant",
  "name": "Workspace Name",
  "applicationId": "roady",
  "isPersonal": false,
  "userId": "user_abc123",       // owner (for personal tenants)
  "userIds": ["user_abc123", "user_def456"],
  "createdAt": "2025-01-08T12:00:00Z",
  "updatedAt": "2025-01-08T12:00:00Z",
  "metadata": {
    "createdBy": "user_abc123",
    "autoCreated": false
  }
}
```

Note: `isPersonal: true` = personal tenant (auto-created, cannot invite yet), `isPersonal: false` = workspace (can invite users)

### Tenant-User Mapping Document

Stores user roles in workspaces (not needed for personal tenants):

```json
{
  "_id": "tenant_user_mapping:tenant_1:user_def456",
  "type": "tenant_user_mapping",
  "tenantId": "tenant_1",
  "userId": "user_def456",
  "role": "member",                   // owner, admin, member
  "joinedAt": "2025-01-09T10:00:00Z",
  "invitedBy": "user_abc123",         // user_id of person who invited
  "acceptedAt": "2025-01-09T10:30:00Z"
}
```

### Invitation Document

```json
{
  "_id": "invite_abc123",
  "type": "invitation",
  "tenantId": "tenant_1",
  "tenantName": "Workspace Name",     // denormalized for preview
  "email": "bob@example.com",
  "role": "member",                   // default role on accept
  "token": "sk_abcdef123456...",      // single-use token (returned once)
  "tokenHash": "sha256(...)",         // what we store in DB
  "status": "pending",                // pending, accepted, revoked
  "createdBy": "user_abc123",
  "createdAt": "2025-01-08T12:00:00Z",
  "expiresAt": "2025-01-15T12:00:00Z",
  "acceptedAt": null,
  "acceptedBy": null
}
```

---

## API Endpoints

### Tenant Management

**Create Workspace Tenant**
```
POST /api/tenants
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "name": "Workspace Name"
}

Response: 
{
  "_id": "tenant_1",
  "name": "Workspace Name",
  "applicationId": "roady",
  "isPersonal": false,
  "userId": "user_abc123",
  "userIds": ["user_abc123"],
  "createdAt": "2025-01-08T12:00:00Z"
}
```

**List User's Tenants**
```
GET /api/tenants
Authorization: Bearer <jwt>

Response:
[
  {
    "_id": "tenant_xyz",
    "name": "Alice's Workspace",
    "isPersonal": true,
    "role": "owner",
    "userIds": ["user_abc123"]
  },
  {
    "_id": "tenant_1",
    "name": "Workspace Name",
    "isPersonal": false,
    "role": "owner",
    "userIds": ["user_abc123", "user_def456"]
  }
]
```

**Get Workspace Details**
```
GET /api/tenants/{tenantId}
Authorization: Bearer <jwt>

Response:
{
  "_id": "tenant_1",
  "name": "Workspace Name",
  "isPersonal": false,
  "userId": "user_abc123",     // owner
  "members": [
    {
      "userId": "user_abc123",
      "email": "alice@example.com",
      "role": "owner",
      "joinedAt": "2025-01-08T12:00:00Z"
    },
    {
      "userId": "user_def456",
      "email": "bob@example.com",
      "role": "member",
      "joinedAt": "2025-01-09T10:00:00Z"
    }
  ],
  "createdAt": "2025-01-08T12:00:00Z"
}
```

**Update Workspace** (owner only, personal tenant cannot be updated)
```
PUT /api/tenants/{tenantId}
Authorization: Bearer <jwt>

{
  "name": "New Workspace Name"
}
```

**Delete Workspace** (owner only, soft delete via metadata)
```
DELETE /api/tenants/{tenantId}
Authorization: Bearer <jwt>
```

---

### Invitations

**Create Invitation**
```
POST /api/tenants/{tenantId}/invitations
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "email": "newuser@example.com",
  "role": "member"  // member, admin (not owner)
}

Response:
{
  "_id": "invite_uuid",
  "tenantId": "tenant_1",
  "tenantName": "Workspace Name",
  "email": "newuser@example.com",
  "role": "member",
  "status": "pending",
  "token": "sk_...",    // ONLY returned once, then hashed
  "inviteLink": "https://app.example.com/join?invite=sk_...",
  "expiresAt": "2025-01-15T12:00:00Z",
  "createdAt": "2025-01-08T12:00:00Z"
}
```

**List Pending Invitations**
```
GET /api/tenants/{tenantId}/invitations?status=pending
Authorization: Bearer <jwt>

Response:
[
  {
    "_id": "invite_uuid",
    "email": "newuser@example.com",
    "role": "member",
    "status": "pending",
    "createdAt": "2025-01-08T12:00:00Z",
    "expiresAt": "2025-01-15T12:00:00Z"
  }
]
```

**Preview Invitation** (no auth, token only)
```
GET /api/invitations/preview?token=sk_...

Response:
{
  "tenantName": "Workspace Name",
  "role": "member",
  "isValid": true,
  "expiresAt": "2025-01-15T12:00:00Z"
}
```

**Accept Invitation** (no auth, uses token + new user's clerk ID)
```
POST /api/invitations/accept
Content-Type: application/json

{
  "token": "sk_...",
  "clerkUserId": "user_def456"
}

Response:
{
  "success": true,
  "tenantId": "tenant_1",
  "tenantName": "Workspace Name",
  "role": "member"
}
```

**Revoke Invitation** (owner/admin only)
```
DELETE /api/tenants/{tenantId}/invitations/{inviteId}
Authorization: Bearer <jwt>
```

**Resend Invitation** (owner/admin only)
```
POST /api/tenants/{tenantId}/invitations/{inviteId}/resend
Authorization: Bearer <jwt>
```

---

### Member Management

**Change Member Role** (owner only, cannot change owner role)
```
PUT /api/tenants/{tenantId}/members/{userId}/role
Authorization: Bearer <jwt>

{
  "role": "admin"  // admin, member (not owner)
}
```

**Remove Member** (owner/admin only, cannot remove owner)
```
DELETE /api/tenants/{tenantId}/members/{userId}
Authorization: Bearer <jwt>
```

---

## Authorization Rules

| Action | Owner | Admin | Member |
|--------|-------|-------|--------|
| Read tenant | ✓ | ✓ | ✓ |
| Update name | ✓ | ✗ | ✗ |
| Delete tenant | ✓ | ✗ | ✗ |
| Create invites | ✓ | ✓ | ✗ |
| Change member roles | ✓ | ✗ | ✗ |
| Remove members | ✓ | ✓ | ✗ |
| View members | ✓ | ✓ | ✓ |
| Access data | ✓ | ✓ | ✓ |
| Remove self | ✓ (no) | ✓ | ✓ |

**Owner Rules:**
- Owner cannot be removed
- Owner cannot be downgraded (role change not allowed)
- Only owner can delete tenant
- Only owner can change member roles

---

## Invitation Flow

### Step 1: Alice Creates Workspace Tenant
```
Alice signs in → Personal tenant auto-created
Alice creates workspace "My Band" → Workspace tenant created
→ Alice is owner of the workspace
→ Alice added to workspace.userIds
→ tenant_user_mapping:workspace:alice created with role=owner
```

### Step 2: Alice Invites Bob
```
Alice calls POST /tenants/{id}/invitations with bob@example.com
→ Invitation document created with secure token
→ Email sent to bob@example.com with invite link
```

### Step 3: Bob Receives Email & Previews
```
Bob gets email with link: https://app.com/join?invite=sk_...
Bob clicks link (no login required yet)
→ App calls GET /invitations/preview?token=sk_...
→ Shows: "You've been invited to My Band as a member"
```

### Step 4: Bob Signs In
```
Bob clicks "Accept" button
→ Redirects to Clerk login (if not signed in)
→ Bob signs in with his Clerk account
→ Bob's personal tenant auto-created (if first time)
```

### Step 5: Bob Accepts Invitation
```
App calls POST /invitations/accept with token + Bob's Clerk user_id
→ Backend verifies:
   - Token is valid and not expired
   - Token hasn't been used (status = pending)
   - Email matches invited email
→ Adds Bob to workspace.userIds
→ Creates tenant_user_mapping:workspace:bob with role=member
→ Marks invitation as accepted
→ Returns: success + workspace details
```

### Step 6: Bob Accesses Workspace
```
Bob's user.tenantIds now includes workspace tenant ID
Bob can query/sync workspace data with tenant_id filter
Bob sees workspace in his list (backend doesn't care that it's a "band")
```

---

## Security Considerations

### Invitation Tokens
- Format: `sk_` prefix + 32 bytes random (256-bit entropy)
- Storage: Never store plain token, only SHA256 hash
- Verification: Use `hmac.compare_digest()` (timing-attack resistant)
- Single-use: Mark `status: "accepted"` after use, cannot reuse
- Expiration: 7 days default, configurable per invite

### Email Verification
- Invitation email must match user's Clerk email
- Clerk ensures email is verified before signup
- No cross-email invitation acceptance

### Authorization Checks
- Always verify user has access to tenant before returning data
- Check role before allowing admin actions
- Cannot change owner's role
- Cannot remove owner from tenant
- Backend enforces at API level

### Preventing Attacks
- No email enumeration: return 400 for invalid token (not "user not found")
- No duplicate invitations: revoke old, create new
- Rate limit invitation creation per tenant
- Audit log all membership changes
- Validate token entropy: reject weak tokens

---

## Backend Enforcement

The backend enforces:

1. **Ownership**: Creator is owner, tracked in `ownerId` field
2. **Membership**: Users in tenant tracked via `userIds` array + `tenant_user_mapping` docs
3. **Roles**: Stored per-user per-tenant in `tenant_user_mapping`
4. **Access Control**: Routes check user's role before allowing action
5. **Invitation Single-Use**: Token can only be accepted once
6. **Owner Protection**: Cannot remove/downgrade owner

Apps don't manage membership directly — they query backend and receive filtered data.

---

## App-Agnostic Features

- Backend doesn't care what a tenant represents (band, project, team)
- Metadata allows apps to add semantic meaning
- Same invitation system works for any app/tenant type
- Owner rule is universal, not app-specific
- Any app can rely on backend role enforcement

---

## Implementation Phases

### Phase 1: Backend (MVP)
- [ ] Update tenant document schema (add ownerId)
- [ ] Create tenant_user_mapping document type
- [ ] Implement invitation service (tokens, single-use, expiration)
- [ ] Add API endpoints (create tenant, invite, accept, manage members)
- [ ] Implement authorization checks (owner rule, role checks)
- [ ] Write unit + integration tests

### Phase 2: Frontend PWA
- [ ] List user's tenants (personal + workspaces)
- [ ] Create workspace form
- [ ] Manage members UI
- [ ] Invite user form
- [ ] Accept invitation flow
- [ ] Preview invitation before login

### Phase 3: Enhancement
- [ ] Email service integration
- [ ] Advanced audit logging
- [ ] Member activity tracking
- [ ] Rate limiting on invitations

---

## Success Criteria

✅ Can create workspace (tenant)
✅ Can invite multiple users with roles
✅ Can accept invitations
✅ Can manage member roles (except owner)
✅ Backend enforces owner rule
✅ Invitations are single-use, expiring
✅ All authorization checks working
✅ Tests passing (unit + integration + E2E)
