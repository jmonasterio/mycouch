# MyCouch - Multi-Tenant Admin System PRD

## Overview

**MyCouch** is a complete multi-tenant platform for managing CouchDB workspaces, users, and applications. It provides:

1. **JWT Authentication Proxy** - Secure gateway to CouchDB (✅ Complete)
2. **Admin PWA** - Web application for tenant and workspace management (🔨 To Build)
3. **Multi-database Backend** - CouchDB supporting admin, applications, and user data

The system allows teams to:
- Create and manage separate workspaces (tenants) for different organizations/projects
- Control user access via API keys and team roles
- Support multiple applications (Roady, custom apps, etc.) on shared infrastructure
- Work offline with PouchDB sync when needed

---

## Problem Statement

Teams need a platform to:
1. Manage multiple isolated workspaces without complex database configurations
2. Control access to each workspace via secure tokens
3. Administer users, permissions, and API keys
4. Support multiple applications on shared infrastructure
5. Work reliably offline with cloud sync

**Current State:**
- ✅ JWT proxy is complete and tested
- ❌ Admin PWA does not exist
- ❌ No user/tenant management interface
- ❌ No API key generation UI
- ❌ No workspace administration

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────┐
│  Users (Browsers)                                   │
└──────────────┬──────────────────────────────────────┘
               │ HTTPS
               ├──────────────────┬────────────────────┐
               ↓                  ↓                    ↓
        ┌────────────┐    ┌────────────┐      ┌────────────┐
        │ Admin PWA  │    │  Roady PWA │      │  Other App │
        │(MyCouch)   │    │(Equipment) │      │  (Future)  │
        └─────┬──────┘    └─────┬──────┘      └─────┬──────┘
              │                 │                    │
              │ JWT via Bearer token (same proxy)    │
              └─────────────────┼────────────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │  JWT Proxy (FastAPI)    │
                    │  Port 5985              │
                    │  - /auth/token          │
                    │  - /* (with JWT check)  │
                    └────────────┬────────────┘
                                 │ Internal HTTP
                                 ↓
                    ┌─────────────────────────┐
                    │  CouchDB (Internal)     │
                    │  Port 5984             │
                    │  - admin (MyCouch)      │
                    │  - roady (apps)         │
                    │  - user-data (apps)     │
                    └─────────────────────────┘
```

### Data Flow

**Admin User Creates Workspace:**
1. Admin PWA sends workspace + user data via proxy
2. Proxy validates JWT from "mycouch-admin" API key
3. CouchDB stores workspace in `admin` database
4. Admin PWA shows confirmation

**Roady App Accesses Workspace:**
1. Roady PWA acquires JWT using "roady-pwa" API key
2. Roady queries CouchDB via proxy with JWT
3. Proxy forwards request to CouchDB
4. Roady PWA filters results by tenant_id from workspace

---

## Database Schema

### Admin Database (`/couch-sitter`)

The `couch-sitter` database stores admin data including workspaces, users, API keys, and audit logs.

Document type: Workspace (tenant)
```javascript
{
  _id: "workspace_550e8400-e29b-41d4-a716-446655440000",
  type: "workspace",
  tenant_id: "550e8400-e29b-41d4-a716-446655440000",  // GUID
  name: "ACME Inc.",
  description: "Music venue equipment management",
  owner_email: "admin@acmeinc.com",
  enabled: true,
  createdAt: "2024-11-01T12:00:00Z",
  updatedAt: "2024-11-01T12:00:00Z"
}
```

Document type: Admin User
```javascript
{
  _id: "admin_user@example.com",
  type: "admin_user",
  email: "user@example.com",
  tenant_id: "550e8400-e29b-41d4-a716-446655440000",
  role: "owner",  // owner, admin, viewer
  enabled: true,
  createdAt: "2024-11-01T12:00:00Z",
  invitedAt: null,
  joinedAt: "2024-11-01T13:00:00Z"
}
```

Document type: API Key
```javascript
{
  _id: "apikey_550e8400-xyz",
  type: "api_key",
  tenant_id: "550e8400-e29b-41d4-a716-446655440000",
  name: "Roady Production Key",
  key_hash: "sha256(api_key_value)",  // Never store plain key
  created_by: "admin@example.com",
  enabled: true,
  last_used: "2024-11-02T10:30:00Z",
  createdAt: "2024-11-01T14:00:00Z",
  expiresAt: null  // Optional expiration
}
```

Document type: Audit Log
```javascript
{
  _id: "audit_550e8400-xyz",
  type: "audit_log",
  tenant_id: "550e8400-e29b-41d4-a716-446655440000",
  action: "workspace_created",  // workspace_created, user_added, key_generated, etc.
  actor: "admin@example.com",
  resource_type: "workspace",
  resource_id: "workspace_550e8400-xyz",
  details: {},
  createdAt: "2024-11-01T12:00:00Z"
}
```

### Roady Database (`/roady`)

(Maintains existing structure, adds tenant_id filtering)
```javascript
{
  _id: "equipment_xyz",
  type: "equipment",
  tenant_id: "550e8400-e29b-41d4-a716-446655440000",  // GUID from admin DB
  band_id: "band_12345",
  name: "Shure SM58",
  description: "Microphone",
  quantity: 2,
  createdAt: "2024-11-01T12:00:00Z"
}
```

---

## Admin PWA Features

### Phase 1: MVP (Admin Workspace Management)

#### 1.1 User Authentication
- [ ] Clerk integration for user login
- [ ] Redirect to login if not authenticated
- [ ] Session management (store user email in localStorage)
- [ ] Logout functionality

#### 1.2 Workspace Management
- [ ] List all workspaces where user is admin/owner
- [ ] Create new workspace (form: name, description)
- [ ] Edit workspace (name, description, enabled status)
- [ ] Delete workspace (soft delete with confirmation)
- [ ] Archive/restore workspaces
- [ ] View workspace details (owner, members, creation date)

#### 1.3 User Management
- [ ] Add user to workspace (email input, role selector)
- [ ] List workspace members with roles
- [ ] Change user role (owner, admin, viewer)
- [ ] Remove user from workspace
- [ ] Send email invitations (future: via service)
- [ ] Track invitation status (pending, joined, declined)

#### 1.4 API Key Management
- [ ] Generate new API key (display once, then hash)
- [ ] List API keys for workspace (name, created_by, last_used)
- [ ] Revoke API key
- [ ] Set API key expiration
- [ ] Copy API key to clipboard (with security warning)
- [ ] Track API key usage

#### 1.5 Basic Dashboard
- [ ] Overview card: number of workspaces, users, API keys
- [ ] Recent activity feed (last 10 audit log entries)
- [ ] Quick stats: active users, API key usage
- [ ] Links to management sections

### Phase 2: Enhanced Features (Not MVP)

- [ ] User invitations via email links
- [ ] Two-factor authentication
- [ ] Workspace sharing/collaboration settings
- [ ] Advanced audit logging and filtering
- [ ] API key usage analytics
- [ ] Workspace usage quotas
- [ ] Backup/export functionality

---

## Admin PWA Tech Stack

Following Roady PWA patterns for consistency:

### Frontend Framework
- **Alpine.js** - Lightweight reactive framework (no build step)
- **PouchDB** - Local-first data management with offline support
- **Pico CSS** - Classless styling framework
- **Service Worker** - PWA offline support

### Project Structure
```
mycouch/
├── pwa/                      # Admin PWA (new directory)
│   ├── index.html            # Main application HTML
│   ├── js/
│   │   ├── app.js            # Alpine.js application logic
│   │   ├── db.js             # PouchDB database operations
│   │   ├── sync.js           # PouchDB sync management
│   │   └── auth.js           # Clerk authentication
│   ├── css/
│   │   └── styles.css        # Pico CSS overrides
│   ├── icons/                # PWA icons
│   ├── manifest.json         # PWA metadata
│   ├── sw.js                 # Service worker
│   └── README.md             # PWA documentation
├── main.py                   # JWT Proxy (existing)
└── CLAUDE.md                 # Guidance for Claude Code
```

---

## Admin PWA Implementation Details

### 1. Clerk Integration

```javascript
// app.js initialization
async function init() {
  // 1. Check if user is authenticated via Clerk
  const user = await getUserFromClerk();
  if (!user) {
    redirectToClerkLogin();
    return;
  }

  // 2. Store email in session
  app.currentUser = user.email;

  // 3. Acquire JWT token
  const jwtData = await acquireJWT('mycouch-admin');
  app.jwtToken = jwtData.token;

  // 4. Load workspaces for this user
  await loadUserWorkspaces();
}
```

### 2. PouchDB Sync Strategy

```javascript
// db.js setup
async function setupSync() {
  const localDb = new PouchDB('mycouch_admin');
  const remoteUrl = `${config.proxyUrl}/admin`;

  const sync = PouchDB.sync(localDb, remoteUrl, {
    live: true,
    retry: true,
    headers: {
      'Authorization': `Bearer ${jwtToken}`
    }
  });

  // Handle sync events
  sync.on('change', (change) => {
    console.log('Synced:', change.direction);
    updateUI();
  });

  sync.on('error', (error) => {
    if (error.status === 401) {
      // Token expired, refresh
      refreshJWT().then(token => {
        jwtToken = token;
        sync.retry();
      });
    } else {
      showError('Sync error: ' + error.message);
    }
  });
}
```

### 3. Multi-Tenant Filtering

```javascript
// db.js queries filter by user email and tenant
async function getUserWorkspaces(userEmail) {
  const docs = await this.db.allDocs({ include_docs: true });
  return docs.rows
    .map(row => row.doc)
    .filter(doc =>
      doc.type === 'workspace' &&
      doc.owner_email === userEmail &&
      !doc.deletedAt
    );
}

async function getWorkspaceUsers(tenantId) {
  const docs = await this.db.allDocs({ include_docs: true });
  return docs.rows
    .map(row => row.doc)
    .filter(doc =>
      doc.type === 'admin_user' &&
      doc.tenant_id === tenantId &&
      !doc.deletedAt
    );
}
```

### 4. Soft Deletes & Restoration

```javascript
// Mark as deleted instead of removing
async function deleteWorkspace(id) {
  const doc = await this.db.get(id);
  doc.deletedAt = new Date().toISOString();
  return this.db.put(doc);
}

// Restore from trash
async function restoreWorkspace(id) {
  const doc = await this.db.get(id);
  delete doc.deletedAt;
  return this.db.put(doc);
}

// Show trash UI component
async function loadDeletedWorkspaces(userEmail) {
  const docs = await this.db.allDocs({ include_docs: true });
  return docs.rows
    .map(row => row.doc)
    .filter(doc =>
      doc.type === 'workspace' &&
      doc.owner_email === userEmail &&
      doc.deletedAt
    )
    .sort((a, b) => new Date(b.deletedAt) - new Date(a.deletedAt));
}
```

### 5. API Key Generation

```javascript
// Never store plain API keys in DB
async function generateAPIKey(tenantId, name) {
  const plainKey = 'sk_' + generateRandomString(32);
  const keyHash = sha256(plainKey);

  const doc = {
    _id: 'apikey_' + Date.now(),
    type: 'api_key',
    tenant_id: tenantId,
    name: name,
    key_hash: keyHash,
    created_by: currentUser,
    enabled: true,
    createdAt: new Date().toISOString()
  };

  await this.db.put(doc);

  // Return plain key once (user must copy it)
  return {
    plainKey,  // Show once, then discard
    saved: true
  };
}
```

---

## API Integration (with JWT Proxy)

### Admin PWA → Proxy → CouchDB

All requests go through the proxy:

**Example: Create workspace**
```bash
curl -X POST http://localhost:5984/admin \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "_id": "workspace_xyz",
    "type": "workspace",
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "ACME Inc.",
    "owner_email": "admin@acmeinc.com"
  }'
```

**Example: Query workspaces**
```bash
curl -X POST http://localhost:5984/admin/_find \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "selector": {
      "type": "workspace",
      "owner_email": "admin@acmeinc.com",
      "deletedAt": { "$exists": false }
    }
  }'
```

## Multi-Tenancy Implementation

### Tenant Isolation Strategy

1. **Database Level**: CouchDB has separate databases
   - `/admin` - Admin PWA data, shared across all users
   - `/roady` - Application data, filtered by `tenant_id`

2. **Document Level**: All documents include `tenant_id` (GUID)
   ```javascript
   {
     type: "workspace",
     tenant_id: "550e8400-e29b-41d4-a716-446655440000",
     owner_email: "user@example.com"
   }
   ```

3. **Query Level**: PWA filters by user + tenant
   ```javascript
   // Only show workspaces this user owns
   filter(doc =>
     doc.type === 'workspace' &&
     doc.owner_email === currentUser &&
     !doc.deletedAt
   )
   ```

4. **JWT Level**: Claims include client ID (not tenant)
   ```javascript
   {
     "sub": "admin",  // client ID from API key
     "iat": 1234567890,
     "exp": 1234571490
   }
   ```

### Security Note
- Proxy doesn't enforce tenant boundaries (application responsibility)
- PWA must validate user has access before queries
- CouchDB config can add document-level permissions (future enhancement)

---

## Offline & Sync Strategy

### Local-First Architecture

1. **All data stored locally** in PouchDB (IndexedDB backend)
2. **Sync continuously** with CouchDB through proxy
3. **Conflict resolution**: Last-write-wins with manual review option
4. **Queue updates** when offline, sync when reconnected

### Sync Status UI

```javascript
// Show user when app is:
app.syncStatus = 'synced'      // ✓ All changes synced
app.syncStatus = 'syncing'     // ⟳ Syncing in progress
app.syncStatus = 'error'       // ✗ Sync failed
app.syncStatus = 'offline'     // ⚠ No connection
```

### Handling Sync Conflicts

PouchDB provides conflict resolution. In MVP:
- Use last-write-wins strategy (default PouchDB behavior)
- Show notification to user if conflict detected
- Future: Add manual conflict resolution UI

---

## Implementation Phases

### Phase 1: MVP (Week 1-2)
- [ ] Project structure with Pico CSS
- [ ] Clerk integration
- [ ] PouchDB setup with sync
- [ ] List workspaces (read-only view)
- [ ] Create workspace (form + save)
- [ ] Edit workspace
- [ ] Delete workspace (soft delete)
- [ ] List workspace members
- [ ] Add member to workspace
- [ ] Remove member
- [ ] Generate API key
- [ ] List API keys
- [ ] Revoke API key
- [ ] Basic dashboard
- [ ] Offline support with service worker
- [ ] PWA installation
- [ ] Full test coverage

### Phase 2: Polish & UX (Week 3)
- [ ] Email invitations
- [ ] Invitation acceptance flow
- [ ] Advanced audit logging
- [ ] Better error messages
- [ ] Loading states
- [ ] Trash/recover UI
- [ ] Settings page

### Phase 3: Enhancement (Future)
- [ ] Two-factor authentication
- [ ] Workspace quotas
- [ ] Usage analytics
- [ ] Backup/export
- [ ] API key usage graphs

---

## Security Considerations

### JWT & Tokens
- ✅ Tokens expire in 1 hour (refresh required)
- ✅ API keys stored as hashes in CouchDB
- ⚠️ TODO: Implement token refresh endpoint
- ⚠️ TODO: Add API key expiration support

### Data Protection
- ✅ All API requests require JWT Bearer token
- ✅ Proxy strips authorization headers before forwarding to CouchDB
- ✅ CouchDB internal port not exposed
- ✅ PouchDB uses IndexedDB (browser storage isolation)
- ⚠️ TODO: Use HTTPS in production
- ⚠️ TODO: Add CORS headers to proxy

### User Access Control
- ✅ Admin PWA filters by user email
- ✅ Roles: owner, admin, viewer (future)
- ⚠️ TODO: Enforce role-based permissions
- ⚠️ TODO: Add document-level access control in CouchDB

### Logging & Audit
- ✅ Audit log documents for all major actions
- ✅ Include actor email, action, resource, timestamp
- ⚠️ TODO: Protect audit logs from modification
- ⚠️ TODO: Export audit logs for compliance

---

## Testing Checklist

### Unit Tests
- [ ] JWT token generation with correct expiration
- [ ] JWT token validation (valid, expired, invalid)
- [ ] API key hashing consistency
- [ ] Workspace CRUD operations
- [ ] User membership management
- [ ] API key generation and revocation
- [ ] Soft delete and restore
- [ ] Query filtering by email and tenant_id
- [ ] Sync conflict resolution

### Integration Tests
- [ ] Proxy authentication flow (API key → JWT)
- [ ] Admin PWA → Proxy → CouchDB request chain
- [ ] PouchDB sync with JWT bearer token
- [ ] Create workspace and sync to CouchDB
- [ ] Add user to workspace and verify data
- [ ] Generate API key and use it from another app
- [ ] Token refresh on 401 error

### E2E Tests (Browser)
- [ ] Login with Clerk
- [ ] Create workspace
- [ ] Add user to workspace
- [ ] Generate API key
- [ ] Logout
- [ ] Offline: Edit data, go offline, reconnect and sync
- [ ] Delete workspace and restore from trash
- [ ] Switch between workspaces

### Security Tests
- [ ] Request without JWT returns 401
- [ ] Request with expired JWT returns 401
- [ ] Request with invalid token returns 401
- [ ] User can only see own workspaces
- [ ] User cannot modify other users' workspaces
- [ ] API key hash is never returned in response

---

## Deployment

### Development Setup
```bash
# 1. Start CouchDB
docker run -d -p 5983:5984 couchdb:latest

# 2. Create databases
curl -X PUT http://localhost:5983/admin

# 3. Start proxy
cd mycouch
make env-setup
make dev-run

# 4. Start admin PWA
cd mycouch/pwa
npx live-server --port=8000
```

### Production Setup
- Deploy proxy with gunicorn on HTTPS
- Deploy PWA to static hosting (GitHub Pages, Netlify, S3)
- Use environment variables for secrets
- Enable CORS headers on proxy
- Regular CouchDB backups
- Monitor proxy logs for auth failures

---

## Success Criteria

### Phase 1 (MVP)
✅ Can create and manage workspaces
✅ Can add users to workspaces
✅ Can generate and revoke API keys
✅ Offline support with PouchDB sync
✅ All tests passing
✅ Documentation updated

### Phase 2 & Beyond
- User invitations working
- Email integration
- Advanced audit logging
- Usage analytics
- Production deployment

---

## Dependencies & Tools

### Backend (Already Complete)
- FastAPI (0.104.1) - API server
- PyJWT (2.8.1) - JWT handling
- httpx (0.25.1) - Async HTTP client
- CouchDB 3.x - Database

### Frontend (To Build)
- Alpine.js - Reactive framework
- PouchDB - Client-side database
- Pico CSS - Styling
- Clerk - Authentication
- Service Worker - PWA offline

### Development
- uv - Python dependency management
- npm - JavaScript package management
- pytest - Backend testing
- live-server - Frontend development

---

## Next Steps

1. ✅ Review and approve this PRD
2. ⏳ Create `pwa/` directory structure
3. ⏳ Set up Alpine.js + PouchDB skeleton
4. ⏳ Integrate Clerk authentication
5. ⏳ Build workspace CRUD operations
6. ⏳ Build user management
7. ⏳ Build API key management
8. ⏳ Add offline support
9. ⏳ Deploy to staging
10. ⏳ User acceptance testing

---

## References

- **CouchDB Docs**: https://docs.couchdb.org
- **PouchDB Docs**: https://pouchdb.com
- **Alpine.js Docs**: https://alpinejs.dev
- **Pico CSS**: https://picocss.com
- **Roady PWA**: `/c/github/roady` (pattern reference)
- **JWT.io**: https://jwt.io

---

## Questions & Assumptions

1. **What email service for invitations?** (Future phase, using in-app invites for MVP)
2. **Support multiple roles per user?** (Future; MVP has single owner per workspace)
3. **Team-owned workspaces?** (Future; MVP is user-owned)
4. **API key auto-rotation?** (Future; MVP is manual)
5. **CouchDB authentication layers?** (Future; MVP uses proxy only)
