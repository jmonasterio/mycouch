# Roady PWA + CouchDB JWT Proxy Integration Plan

## Vision Overview

Build a complete admin system for a CouchDB-backed equipment management platform:

1. **MyCouch (Admin/Multi-tenant Core)** - Manages tenants, users, and admin functions
2. **CouchDB JWT Proxy** - Secure gateway to CouchDB with token-based authentication
3. **Roady PWA** - Local-only equipment checklist management (syncs to proxied CouchDB)

The PWA runs locally on the user's device, stores data in PouchDB, and synchronizes with the cloud-hosted CouchDB through the JWT proxy.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Local Device (User's Browser)                          │
├─────────────────────────────────────────────────────────┤
│  Roady PWA (Alpine.js + PouchDB)                        │
│  ├── Equipment management                              │
│  ├── Gig checklists                                    │
│  ├── Band management                                   │
│  └── Local PouchDB (IndexedDB backend)                │
│      └── Syncs bidirectionally with:                   │
│          ↓                                              │
├─────────────────────────────────────────────────────────┤
│ HTTPS / Secure Connection                              │
├─────────────────────────────────────────────────────────┤
│  CouchDB JWT Proxy (Python FastAPI on port 5984)       │
│  ├── POST /auth/token (API key → JWT)                 │
│  ├── GET/POST/PUT/DELETE /* (JWT validation)          │
│  └── Request forwarding to internal CouchDB           │
│      ↓                                                  │
├─────────────────────────────────────────────────────────┤
│  Internal CouchDB (port 5983 - not exposed)            │
│  ├── Admin database (MyCouch data)                     │
│  ├── Roady database (gigs, equipment, bands)           │
│  └── Other application databases                       │
└─────────────────────────────────────────────────────────┘
```

---

## Phase 1: Local Roady PWA (Current State)

✅ **Completed:**
- Alpine.js + PouchDB application
- Equipment catalog management
- Gig templates and checklists
- Soft deletes with trash recovery
- Mobile-responsive PWA
- Service worker for offline support
- Band-level tenant isolation (local)

**Database Schema (Local PouchDB):**
```javascript
// Equipment
{
  _id: "equipment_xyz",
  type: "equipment",
  tenant_id: "550e8400-e29b-41d4-a716-446655440000",  // GUID
  band_id: "band_12345",
  name: "Shure SM58",
  description: "Microphone",
  quantity: 2,
  createdAt: "2024-11-01T12:00:00Z"
}

// Gig
{
  _id: "gig_abc",
  type: "gig",
  tenant_id: "550e8400-e29b-41d4-a716-446655440000",
  band_id: "band_12345",
  name: "Blue Note NYC",
  doorsOpenTime: "2024-11-15T19:00:00Z",
  arrivalTime: "2024-11-15T16:00:00Z",
  equipment: [/* array of equipment with load/pack status */],
  createdAt: "2024-11-01T12:00:00Z"
}

// Band
{
  _id: "band_12345",
  type: "band",
  tenant_id: "550e8400-e29b-41d4-a716-446655440000",
  name: "The Beatles",
  description: "",
  owner: "user@example.com",
  createdAt: "2024-11-01T12:00:00Z"
}
```

---

## Phase 2: JWT Proxy Integration (In Progress)

**Objective:** Enable Roady PWA to sync with cloud CouchDB through authenticated proxy.

### 2.1 JWT Proxy Configuration

**Proxy Environment:**
```bash
JWT_SECRET=super-secret-jwt-key-change-in-production
COUCHDB_INTERNAL_URL=http://localhost:5983  # Internal CouchDB
PROXY_PORT=5984  # Public-facing port
```

**API Keys (config/api_keys.json):**
```json
{
  "roady-local-pwa": "roady",
  "mycouch-admin": "admin",
  "test-key": "test-client"
}
```

### 2.2 Roady PWA Changes

#### **Database Connection Configuration**

Add connection settings in Roady PWA:

```javascript
// New: Database connection config
const dbConfig = {
  // Local mode (development, offline)
  local: {
    roady: new PouchDB('roady_local'),
    admin: null  // Not connected
  },

  // Remote mode (production, with sync)
  remote: {
    proxyUrl: 'https://couchdb-proxy.example.com:5984',
    apiKey: 'roady-local-pwa',
    jwtToken: null  // Acquired at login
  }
};
```

#### **Authentication Flow**

1. **User Login:**
   - Clerk authentication (email verification)
   - User email resolved to tenant_id via admin DB
   - Store tenant_id and user email

2. **Token Acquisition:**
   ```javascript
   // Roady PWA startup
   async function acquireJWT() {
     const response = await fetch('https://proxy:5984/auth/token', {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({ api_key: 'roady-local-pwa' })
     });
     const { token, expires_in } = await response.json();
     return { token, expiresAt: Date.now() + expires_in * 1000 };
   }
   ```

3. **Token Refresh:**
   - Store expiration time
   - Refresh 5 minutes before expiry
   - Automatic refresh on token-expired errors (401)

#### **PouchDB Sync Configuration**

```javascript
// Roady PWA sync setup
async function setupSync() {
  const localDb = new PouchDB('roady_local');
  const remoteUrl = `${config.proxyUrl}/roady`;

  const sync = PouchDB.sync(localDb, remoteUrl, {
    live: true,
    retry: true,
    headers: {
      'Authorization': `Bearer ${jwtToken}`
    }
  });

  sync.on('change', (change) => {
    console.log('Synced:', change);
    ui.showNotification('Data synced');
  });

  sync.on('error', (error) => {
    if (error.status === 401) {
      acquireJWT().then(token => {
        jwtToken = token;
        sync.retry();
      });
    } else {
      ui.showError('Sync failed: ' + error);
    }
  });
}
```

#### **Database Query Updates**

Update `js/db.js` to include tenant filtering:

```javascript
// Before: filter(doc => doc.tenant === 'demo')
// After: filter(doc => doc.tenant_id === selectedTenantId && doc.band_id === selectedBandId)

async getAllEquipment(tenantId, bandId) {
  const docs = await this.db.allDocs({ include_docs: true });
  return docs.rows
    .map(row => row.doc)
    .filter(doc =>
      doc.type === 'equipment' &&
      doc.tenant_id === tenantId &&
      doc.band_id === bandId &&
      !doc.deletedAt
    );
}
```

#### **Startup/Band Resolution**

```javascript
// New: Resolve tenant from Clerk
async function resolveTenantFromClerk() {
  // 1. Check Clerk session
  const user = await getClerkUser();
  if (!user) {
    redirectToClerkLogin();
    return;
  }

  // 2. Query admin DB for tenant
  const adminDbUrl = `${config.proxyUrl}/admin`;
  const response = await fetch(`${adminDbUrl}/_find`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${jwtToken}` },
    body: JSON.stringify({
      selector: { type: 'admin', email: user.email }
    })
  });

  const admins = await response.json();
  if (admins.docs.length === 0) {
    showError('No workspace found for ' + user.email);
    return;
  }

  const admin = admins.docs[0];
  return {
    tenantId: admin.tenant_id,
    email: user.email,
    isEnabled: admin.enabled === true
  };
}

// New: Load bands for tenant
async function loadBandsForTenant(tenantId) {
  const docs = await this.db.allDocs({ include_docs: true });
  return docs.rows
    .map(row => row.doc)
    .filter(doc =>
      doc.type === 'band' &&
      doc.tenant_id === tenantId &&
      !doc.deletedAt
    );
}

// Updated: App initialization
async function init() {
  try {
    // 1. Acquire JWT token
    const jwtData = await acquireJWT();
    app.jwtToken = jwtData.token;
    app.jwtExpiresAt = jwtData.expiresAt;

    // 2. Resolve tenant from Clerk
    const tenant = await resolveTenantFromClerk();
    if (!tenant.isEnabled) {
      showError('Your workspace is disabled');
      return;
    }
    app.selectedTenantId = tenant.tenantId;

    // 3. Load bands for tenant
    const bands = await loadBandsForTenant(app.selectedTenantId);
    if (bands.length === 0) {
      showBandCreationForm();
      return;
    }

    if (bands.length === 1) {
      app.selectedBandId = bands[0]._id;
      setupSync();
      loadData();
    } else {
      // Phase 2: Show band selection
      showBandSelectionScreen(bands);
    }
  } catch (error) {
    showError('Startup error: ' + error.message);
  }
}
```

---

## Phase 3: Multi-Tenant Admin System (Future)

**Objective:** Enable users to manage multiple bands/workspaces.

### Changes:
- Add "Switch Band" or "Switch Workspace" in settings
- Show list of available bands for tenant
- Load different equipment/gigs per band without reload
- Update all queries to re-filter on band change

### New UI Components:
- Band selector dropdown (settings or sidebar)
- Create new band dialog
- Leave/join band flows (Phase 4)

---

## Database Requirements

### 1. Admin Database Schema (MyCouch)

```javascript
// Admin user (single document per admin)
{
  _id: "admin_user@example.com",
  type: "admin",
  email: "user@example.com",
  tenant_id: "550e8400-e29b-41d4-a716-446655440000",
  role: "owner",
  enabled: true,
  createdAt: "2024-11-01T12:00:00Z"
}

// Tenant
{
  _id: "550e8400-e29b-41d4-a716-446655440000",
  type: "tenant",
  name: "My Organization",
  owner_email: "user@example.com",
  enabled: true,
  createdAt: "2024-11-01T12:00:00Z"
}
```

### 2. Roady Database Schema

```javascript
// Band (tenant-specific)
// Equipment, Gig, Template (tenant_id + band_id)
// (All documents now include tenant_id and band_id for isolation)
```

---

## CouchDB Security & Access Control

### Current (MVP):
- Single API key for Roady PWA (no user-level access control)
- Proxy validates JWT, forwards all requests to CouchDB
- CouchDB allows all authenticated requests

### Phase 2 Enhancement:
- Add scoped access (read-only vs read-write)
- Per-database permissions in JWT
- Proxy enforces scope before forwarding

### Future:
- Per-user credentials instead of single API key
- CouchDB-native user management
- Document-level access control

---

## Configuration & Deployment

### Local Development Setup

1. **Start CouchDB:**
   ```bash
   # Linux/macOS
   sudo systemctl start couchdb

   # Docker
   docker run -d -p 5983:5984 couchdb:latest
   ```

2. **Create databases:**
   ```bash
   curl -X PUT http://localhost:5983/admin
   curl -X PUT http://localhost:5983/roady
   ```

3. **Start JWT Proxy:**
   ```bash
   cd mycouch
   make env-setup
   # Edit .env with your settings
   make dev-run
   ```

4. **Start Roady PWA (development):**
   ```bash
   cd roady
   npx live-server --port=8000
   ```

5. **Test token acquisition:**
   ```bash
   curl -X POST http://localhost:5984/auth/token \
     -H "Content-Type: application/json" \
     -d '{"api_key": "roady-local-pwa"}'
   ```

### Production Deployment

1. **CouchDB:**
   - Run on isolated internal network
   - Port 5983 (not exposed)
   - Enable authentication in CouchDB config
   - Regular backups

2. **JWT Proxy:**
   - Deploy with gunicorn/uvicorn on public port (5984)
   - HTTPS only
   - Strong JWT_SECRET (environment variable)
   - Rotate API keys regularly
   - Rate limiting (future phase)

3. **Roady PWA:**
   - Static hosting (GitHub Pages, Netlify, S3)
   - Manifest.json with proxy URL
   - Service worker caching strategy
   - CORS headers configured on proxy

---

## Implementation Timeline

### Phase 1: ✅ Complete
- Local Roady PWA with PouchDB
- Band & equipment management
- Soft deletes and trash
- Offline support

### Phase 2: ⏳ In Progress (This Plan)
- JWT proxy authentication
- Remote sync with CouchDB
- Tenant resolution from Clerk
- Error handling & token refresh
- **Timeline:** 2-3 weeks

### Phase 3: 🔮 Planned
- Multi-band support in UI
- Band switching without reload
- **Timeline:** 1-2 weeks

### Phase 4: 📅 Future
- Per-user credentials
- Advanced access control
- Audit logging
- **Timeline:** TBD

---

## Risk Mitigation

### Security:
- ✅ JWT tokens validated on proxy
- ✅ CouchDB isolated on internal network
- ⚠️ TODO: Use HTTPS in production
- ⚠️ TODO: Implement rate limiting on proxy
- ⚠️ TODO: Add request signing for proxy authenticity

### Data Loss:
- ✅ PouchDB local storage provides offline buffer
- ✅ Soft deletes with trash recovery
- ⚠️ TODO: Implement regular CouchDB backups
- ⚠️ TODO: Add conflict resolution strategies

### Performance:
- ✅ PouchDB indexed queries
- ✅ Async/await FastAPI on proxy
- ⚠️ TODO: Add caching headers to proxy
- ⚠️ TODO: Monitor sync bandwidth

---

## Success Criteria

✅ **Phase 1:**
- Roady PWA functions offline
- Equipment checklists work locally
- Mobile-responsive UI

✅ **Phase 2:**
- Roady PWA connects to cloud CouchDB through proxy
- Bidirectional sync working
- Token refresh handling errors gracefully
- Tenant resolution from Clerk
- Band creation and selection
- All queries filter by tenant_id + band_id

📋 **Phase 3:**
- Multi-band UI with instant switching
- No reload needed for band changes
- Consistent data across all bands

---

## Quick Reference: Key File Locations

### CouchDB JWT Proxy (mycouch/)
- `main.py` - FastAPI application
- `config/api_keys.json` - API key configuration
- `.env` - Environment variables (JWT_SECRET, etc.)
- `Makefile` / `run.ps1` / `run.bat` - Build commands

### Roady PWA (roady/)
- `index.html` - Main UI
- `js/app.js` - Alpine.js application logic
- `js/db.js` - PouchDB database operations
- `js/sync.js` - (New) Remote sync management
- `manifest.json` - PWA metadata

---

## Dependencies & Tools

### Backend
- FastAPI (Python) - API server
- PyJWT - JWT handling
- httpx - Async HTTP client
- CouchDB - Database

### Frontend
- Alpine.js - Lightweight reactive framework
- PouchDB - Client-side database + sync
- Pico CSS - Styling
- Service Worker - Offline support

### DevOps
- uv - Python dependency management
- npm - JavaScript package management
- Docker - Containerization (optional)
- systemd - Service management (Linux)

---

## Notes & Assumptions

1. **HTTPS in Production:** All communication should use HTTPS
2. **JWT_SECRET:** Generate strong random key, rotate regularly
3. **API Key Model:** Current MVP uses single API key for PWA; future phase may use per-user credentials
4. **CouchDB Replication:** Native CouchDB replication between local and remote DB recommended for conflict resolution
5. **Offline Queue:** PouchDB handles queueing edits during offline; no additional queue needed
6. **User Context:** Tenant and band context stored in session (localStorage); cleared on logout

---

## Next Steps

1. ✅ CLAUDE.md created for mycouch project
2. ⏳ Review this plan with team
3. ⏳ Implement Phase 2 changes to Roady PWA
4. ⏳ Test JWT proxy with PouchDB sync
5. ⏳ Deploy to staging for end-to-end testing
6. ⏳ Plan Phase 3 multi-band UI enhancements
