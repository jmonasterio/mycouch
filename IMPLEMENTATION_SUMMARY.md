# Tenancy & Invitations Implementation Summary

## Overview

Implemented the complete multi-tenant workspace and invitation system per PRD-shared-tenants-invitations.md.

**Status**: Backend implementation complete (MVP ready for testing)

---

## What Was Implemented

### 1. Tenant Management Schema (mycouch-1gw) ✓

**Files Modified/Created**:
- `src/couchdb_jwt_proxy/couch_sitter_service.py` - Added methods:
  - `create_workspace_tenant()` - Create new workspace (not personal)
  - `get_tenant()` - Fetch tenant by ID
  - `add_user_to_tenant()` - Add user with role mapping
  - `get_tenant_user_mapping()` - Fetch role for user in tenant

**Key Features**:
- Tenant document structure: `userId` (owner), `userIds` (all members), `metadata`
- No `isPersonal` flag on tenant - distinction tracked in `User.tenants[].personal` field only
- Personal tenants auto-created on first login with `metadata.autoCreated=true`
- Workspace tenants created via `/api/tenants` with `autoCreated=false`

### 2. Invitation Service (mycouch-7dc) ✓

**File Created**: `src/couchdb_jwt_proxy/invite_service.py`

**Key Features**:
- **Token Generation**: `sk_` prefix + 32 bytes (256-bit entropy)
- **Token Storage**: SHA256 hash only (plain token never stored)
- **Token Verification**: `hmac.compare_digest()` for timing-attack resistance
- **Single-Use Enforcement**: Status changes from `pending` → `accepted` after first use
- **Expiration**: 7-day default TTL
- **Email Verification**: Matches invited email to accepting user

**Methods**:
- `generate_token()` - Create secure token
- `hash_token()` - SHA256 hashing
- `verify_token()` - Validate token with expiration/status checks
- `create_invitation()` - Create new invitation
- `accept_invitation()` - Mark as accepted
- `revoke_invitation()` - Soft-delete
- `create_tenant_user_mapping()` - Track roles

### 3. API Endpoints (mycouch-2be) ✓

**File Created**: `src/couchdb_jwt_proxy/tenant_routes.py`

**Tenant Management**:
```
POST   /api/tenants                    - Create workspace
GET    /api/my-tenants                 - List user's tenants
GET    /api/tenants/{id}               - Get details + members
PUT    /api/tenants/{id}               - Update name (owner)
DELETE /api/tenants/{id}               - Delete (owner, not personal)
```

**Invitations**:
```
POST   /api/tenants/{id}/invitations   - Create invite (owner/admin)
GET    /api/tenants/{id}/invitations   - List invites (owner/admin)
GET    /api/invitations/preview        - Preview (no auth)
POST   /api/invitations/accept         - Accept (no auth, uses token)
DELETE /api/tenants/{id}/invitations/{inviteId} - Revoke (owner/admin)
POST   /api/tenants/{id}/invitations/{inviteId}/resend - Resend (owner/admin)
```

**Member Management**:
```
PUT    /api/tenants/{id}/members/{userId}/role - Change role (owner)
DELETE /api/tenants/{id}/members/{userId}      - Remove (owner/admin)
```

### 4. Authorization Checks (mycouch-2ao) ✓

**Embedded in**: `src/couchdb_jwt_proxy/tenant_routes.py`

**Universal Owner Rules**:
- Owner cannot be removed from tenant
- Owner role cannot be changed to admin/member
- Only owner can delete tenant
- Only owner can change member roles

**Invitation Rules**:
- Invitations only work for workspace tenants (not personal)
- Admin can invite (to workspace only)
- Cannot invite to personal tenants (returns 400)

**Role-Based Access**:
| Action | Owner | Admin | Member |
|--------|-------|-------|--------|
| Read tenant | ✓ | ✓ | ✓ |
| Update name | ✓ | ✗ | ✗ |
| Delete | ✓ | ✗ | ✗ |
| Invite | ✓ | ✓* | ✗ |
| Change roles | ✓ | ✗ | ✗ |
| Remove members | ✓ | ✓ | ✗ |
| View members | ✓ | ✓ | ✓ |
| Access data | ✓ | ✓ | ✓ |

*workspace only

**Security**:
- JWT validation via Clerk
- Email matching on acceptance
- Timing-attack resistant token comparison
- Single-use token enforcement
- Role validation at endpoint level

### 5. Authentication Middleware (auth_middleware.py) ✓

**File Created**: `src/couchdb_jwt_proxy/auth_middleware.py`

- `get_current_user()` dependency for protected routes
- Extracts JWT claims (sub, email, name, issuer)
- Integrates with Clerk service for validation

### 6. Integration into Main App ✓

**Modified**: `src/couchdb_jwt_proxy/main.py`

**Added**:
- InviteService initialization
- Tenant router registration (`/api/tenants`, `/api/invitations`)
- Auth middleware integration

### 7. Comprehensive Test Suite (mycouch-052) ✓

**File Created**: `tests/test_tenant_invitations.py`

**Test Coverage**:

**Unit Tests (Token & Crypto)**:
- Token generation format and uniqueness
- Hash determinism and differences
- Timing-attack resistant verification
- Token format validation

**Unit Tests (Invitations)**:
- Creating invitations with token
- Validating tokens (valid, expired, accepted, revoked)
- Single-use enforcement
- Expiration checking

**Unit Tests (Tenants)**:
- Creating workspace tenants
- Fetching tenants
- Adding users to tenants
- Role mapping

**Integration Tests**:
- Complete invitation flow (create → validate → accept)
- User addition to tenant
- Role assignment

**Security Tests**:
- Cannot invite to personal tenants
- Owner cannot be removed
- Owner role cannot be changed
- Token only returned once
- Timing-attack resistance

**Role-Based Access Tests**:
- Owner permissions
- Admin permissions
- Member permissions

---

## Data Model Changes

### Tenant Document
```json
{
  "_id": "tenant_{uuid}",
  "type": "tenant",
  "name": "Workspace Name",
  "applicationId": "roady",
  "userId": "user_abc123",        // Owner (creator)
  "userIds": ["user_abc123", "user_def456"],  // All members
  "createdAt": "2025-01-08T12:00:00Z",
  "metadata": {
    "createdBy": "user_abc123",
    "autoCreated": false          // true for personal only
  }
}
```

### User Document
```json
{
  "_id": "user_{sub_hash}",
  "type": "user",
  "tenants": [
    {
      "tenantId": "tenant_xyz",
      "role": "owner",
      "personal": true,            // Marks personal vs workspace
      "joinedAt": "2025-01-08T12:00:00Z"
    },
    {
      "tenantId": "tenant_1",
      "role": "member",
      "personal": false,
      "joinedAt": "2025-01-09T10:00:00Z"
    }
  ],
  "personalTenantId": "tenant_xyz",
  "activeTenantId": "tenant_xyz"
}
```

### Tenant-User Mapping
```json
{
  "_id": "tenant_user_mapping:tenant_1:user_def456",
  "type": "tenant_user_mapping",
  "tenantId": "tenant_1",
  "userId": "user_def456",
  "role": "member",              // owner, admin, member
  "joinedAt": "2025-01-09T10:00:00Z",
  "invitedBy": "user_abc123",    // Who invited
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
  "token": "sk_...",              // Only returned at creation
  "tokenHash": "sha256(...)",     // Stored in DB
  "status": "pending",            // pending, accepted, revoked
  "createdBy": "user_abc123",
  "createdAt": "2025-01-08T12:00:00Z",
  "expiresAt": "2025-01-15T12:00:00Z",
  "acceptedAt": null,
  "acceptedBy": null
}
```

---

## API Documentation

Full API reference with request/response examples is in `API_REFERENCE.md` under "Tenant & Invitation Management" section.

---

## Key Design Decisions

1. **No `isPersonal` Flag on Tenant**: Personal vs workspace distinction tracked at User level (`User.tenants[].personal`), not on the tenant document itself. This allows identical schema and access control for both.

2. **Token Never Stored in Plain**: Invitation tokens only returned at creation time. Database stores only SHA256 hash. This prevents token compromise via database breach.

3. **Timing-Attack Resistant**: Uses `hmac.compare_digest()` for token verification to prevent timing attacks that could leak information about valid tokens.

4. **Single-Use Tokens**: Status changes from `pending` to `accepted` after first use. Subsequent uses fail validation. Token cannot be reused.

5. **7-Day Expiration**: Invitations expire after 7 days. Can be resent to generate new token if needed.

6. **Role-Based Access**: All authorization checks at API level. Routes verify user role before allowing admin actions.

7. **Email Verification**: User's email must match invitation email at acceptance time (Clerk ensures verified emails).

---

## Testing Strategy

Run tests with:
```bash
pytest tests/test_tenant_invitations.py -v
```

**What's Tested**:
- ✓ Unit: Token generation, hashing, verification
- ✓ Unit: Invitation CRUD operations
- ✓ Unit: Tenant creation and user management
- ✓ Integration: Full invitation acceptance flow
- ✓ Security: Owner protection, personal tenant protection, token reuse prevention
- ✓ Security: Timing-attack resistance
- ✓ Authorization: Role-based access control

**Next Phase Tests** (E2E):
- Full API flow with real HTTP requests
- PWA UI acceptance flow
- Email delivery integration
- Database state verification

---

## Files Changed/Created

**Created**:
- `src/couchdb_jwt_proxy/invite_service.py` (314 lines) - Token and invitation management
- `src/couchdb_jwt_proxy/tenant_routes.py` (612 lines) - API endpoints
- `src/couchdb_jwt_proxy/auth_middleware.py` (71 lines) - JWT extraction for API
- `tests/test_tenant_invitations.py` (389 lines) - Comprehensive test suite
- `IMPLEMENTATION_SUMMARY.md` (this file)

**Modified**:
- `src/couchdb_jwt_proxy/couch_sitter_service.py` - Added 6 new methods for tenant management
- `src/couchdb_jwt_proxy/main.py` - Registered tenant routes and invite service
- `API_REFERENCE.md` - Added tenant/invitation API documentation

**Total Lines Added**: ~1,400 lines of production code + tests

---

## Migration Path

Existing users with old single-tenant schema will be automatically migrated to the new multi-tenant schema on next login via `_migrate_user_to_multi_tenant()` method. Their personal tenant remains unchanged.

---

## Security Considerations

- ✓ Token entropy: 256-bit random
- ✓ Token storage: SHA256 hash only
- ✓ Token comparison: timing-attack resistant
- ✓ Single-use enforcement: status-based
- ✓ Email verification: matched at acceptance
- ✓ Owner protection: cannot remove/downgrade
- ✓ Personal tenant protection: cannot invite to personal
- ✓ JWT validation: RS256 via Clerk JWKS
- ✓ Rate limiting: Already on `/my-tenants`, can extend to invitations

---

## Known Limitations & Future Work

1. **Email Delivery** (mycouch-oob) - Still needs implementation:
   - SendGrid/Resend/AWS SES integration
   - Email templates with invite links

2. **PWA UI** (mycouch-gbu) - Still needs implementation:
   - Workspace creation form
   - Invite user interface
   - Accept invitation flow
   - Member management UI

3. **Advanced Audit Logging** - Could add:
   - Detailed audit trail of all membership changes
   - Invitation resend tracking
   - Failed acceptance attempts

4. **Rate Limiting** - Could extend to:
   - Invitation creation (prevent spam)
   - Token validation attempts (prevent brute force)

---

## Next Steps

1. **Run Tests**: `pytest tests/test_tenant_invitations.py -v`
2. **Manual Testing**: Test each endpoint with curl/Postman
3. **Email Integration** (mycouch-oob): Add email service
4. **PWA UI** (mycouch-gbu): Build workspace/invitation UI
5. **E2E Tests** (mycouch-052): Add full HTTP flow tests

---

## Summary

The multi-tenant workspace and invitation system is now fully implemented at the backend level. The system enforces:

- ✓ Personal and workspace tenants with identical schema
- ✓ Secure, single-use invitation tokens
- ✓ Role-based access control
- ✓ Owner protection and privilege separation
- ✓ Email verification
- ✓ Timing-attack resistance

Ready for testing and UI integration.
