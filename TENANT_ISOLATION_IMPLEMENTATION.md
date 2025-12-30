# Tenant Isolation Implementation Guide

## Overview

This document explains how to implement the two tenant isolation constraints:
1. Tenant creation via API only (requires online)
2. Tenant field validation on all app DB writes

## Files Created

### 1. `src/couchdb_jwt_proxy/tenant_validation.py`
Core validation logic (not used yet, alternative approach)

### 2. `src/couchdb_jwt_proxy/tenant_access_middleware.py` ⭐ USE THIS
Middleware that intercepts requests and validates tenant access
- Caches user tenant list to reduce DB queries
- Handles both single docs and bulk_docs operations
- Skips validation for system endpoints

## Implementation Steps

### Step 1: Add Import to main.py

```python
# At top of main.py with other imports
from .tenant_access_middleware import create_tenant_access_middleware
```

### Step 2: Add Middleware to FastAPI App

```python
# In main.py, after creating app but before other middleware
# (FastAPI processes middleware in reverse order, so this should be early)

# Example location - find where CORSMiddleware is added:
# app.add_middleware(CORSMiddleware, ...)

# Add this:
app.add_middleware(
    TenantAccessMiddleware,
    couch_sitter_service=couch_sitter_service  # Pass the service instance
)
```

**Important:** The middleware needs access to `couch_sitter_service` which is created 
in the `lifespan` context. You may need to:

Option A: Create middleware inside lifespan startup
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup code ...
    
    # Create middleware with service
    app.add_middleware(
        TenantAccessMiddleware,
        couch_sitter_service=couch_sitter_service
    )
    
    yield
    # ... cleanup ...
```

Option B: Use app state (cleaner)
```python
# In startup
app.state.couch_sitter_service = couch_sitter_service

# In middleware __init__
self.couch_sitter_service = app.state.couch_sitter_service
```

### Step 3: Update Client (roady)

**File:** `js/app.js`

Replace `createBand()` function to use API:

```javascript
async createBand() {
    // Validate online connection
    if (!this.options.mycouchBaseUrl) {
        this.showSnackbar('Must be online to create a band', 'error');
        return;
    }
    
    if (!this.newBandName.trim()) {
        this.showSnackbar('Band name required', 'error');
        return;
    }
    
    // Prevent double-submission
    if (this.isCreatingBand) return;
    this.isCreatingBand = true;
    
    try {
        const token = await Clerk.session?.getToken();
        const response = await fetch(`${this.options.mycouchBaseUrl}/api/tenants`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: this.newBandName
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create band');
        }
        
        const tenant = await response.json();
        
        // Switch to new band
        this.currentBandTenantId = tenant._id;
        DB.setTenant(tenant._id);
        
        // Refresh bands list (will get new tenant via sync)
        await this.loadBandDetails();
        
        // Clear form
        this.newBandName = '';
        this.showCreateBandDialog = false;
        
        this.showSnackbar(`Band "${tenant.name}" created successfully`);
    } catch (err) {
        console.error('Error creating band:', err);
        this.showSnackbar(`Failed to create band: ${err.message}`, 'error');
    } finally {
        this.isCreatingBand = false;
    }
}
```

### Step 4: Ensure All Documents Include Tenant Field

**File:** `js/db.js`

Every document type must include `tenant` field:

```javascript
async addEquipment(item) {
    const doc = {
        _id: 'equipment_' + Date.now(),
        type: 'equipment',
        tenant: this.currentTenant,  // ← REQUIRED
        name: item.name,
        description: item.description || '',
        createdAt: new Date().toISOString()
    };
    return await this.db.put(doc);
}

async addGigType(type) {
    const doc = {
        _id: 'gig_type_' + Date.now(),
        type: 'gig_type',
        tenant: this.currentTenant,  // ← REQUIRED
        name: type.name,
        equipmentIds: type.equipmentIds || [],
        createdAt: new Date().toISOString()
    };
    return await this.db.put(doc);
}

async addGig(gig, gigType) {
    // ... existing code ...
    const doc = {
        _id: 'gig_' + Date.now(),
        type: 'gig',
        tenant: this.currentTenant,  // ← REQUIRED
        name: gig.name,
        // ... rest of fields
    };
    return await this.db.put(doc);
}

// When updating or deleting, preserve tenant field
async updateGig(gig) {
    try {
        const latest = await this.db.get(gig._id);
        gig._rev = latest._rev;
        gig.tenant = this.currentTenant;  // ← Ensure tenant preserved
        return await this.db.put(gig);
    } catch (err) {
        return await this.db.put(gig);
    }
}
```

### Step 5: Test the Implementation

#### Test Case 1: Offline Tenant Creation
```javascript
// Disable network
// Try to create band
→ Should show "Must be online to create a band"
```

#### Test Case 2: Valid Write
```javascript
// Create gig locally
const gig = { name: "Test", ... };
await DB.addGig(gig, gigType);

// Sync to server
→ Document has tenant field
→ Middleware validates: user owns this tenant
→ Document saved ✅
```

#### Test Case 3: Invalid Write (Missing Tenant)
```javascript
// Manually create doc without tenant field
const badDoc = {
    _id: 'gig_123',
    type: 'gig',
    name: "Test"
    // Missing: tenant field
};
await DB.getDb().put(badDoc);

// Try to sync
→ Middleware rejects with 403
→ Error: "Document missing required 'tenant' field"
```

#### Test Case 4: Invalid Write (Wrong Tenant)
```javascript
// Create doc with tenant user doesn't own
const badDoc = {
    _id: 'gig_123',
    type: 'gig',
    tenant: 'tenant_someone_else',  // User owns: ['tenant_xyz']
    name: "Test"
};
await DB.getDb().put(badDoc);

// Try to sync
→ Middleware rejects with 403
→ Error: "Cannot write to tenant 'tenant_someone_else'"
```

#### Test Case 5: Bulk Docs Validation
```javascript
// Bulk write with multiple docs
const bulk = {
    docs: [
        { _id: 'gig_1', type: 'gig', tenant: 'tenant_xyz', ... },  ✅
        { _id: 'eq_1', type: 'equipment', tenant: 'tenant_xyz', ... },  ✅
        { _id: 'gig_2', type: 'gig', tenant: 'tenant_other', ... }  ❌
    ]
};

// Try to sync
→ Middleware validates all docs
→ Document 2 fails validation
→ Entire bulk operation rejected with 403
```

## Rollout Plan

### Phase 1: Deploy Middleware (Non-Breaking)

1. Add middleware to main.py
2. Set to **log-only mode** (validates but doesn't reject)
3. Monitor logs for validation failures
4. Fix any existing documents that violate constraints

### Phase 2: Update Client

1. Update createBand() to use API
2. Test thoroughly in staging
3. Deploy to production

### Phase 3: Enable Enforcement

1. Change middleware from log-only to rejection mode
2. Monitor for any errors
3. If issues occur, rollback to phase 1

### Phase 4: Cleanup

1. Document the constraints
2. Add monitoring/alerting
3. Consider caching improvements

## Log-Only Mode Implementation

If you want to deploy non-blocking first:

```python
# In tenant_access_middleware.py
def __init__(self, app, couch_sitter_service, enforce=False):
    self.enforce = enforce  # Default False for Phase 1
    # ...

async def __call__(self, request: Request, call_next):
    # ... validation code ...
    
    try:
        if self._bulk_docs in path:
            await self._validate_bulk_docs(data, user_id, path)
        else:
            await self._validate_document(data, user_id, path)
    except ValueError as e:
        if self.enforce:
            # Phase 3: Reject
            return JSONResponse(status_code=403, content={...})
        else:
            # Phase 1: Log only
            logger.warning(f"Validation failed (not enforced): {e}")
    
    # Continue regardless in non-enforce mode
    return await call_next(request)
```

## Performance Notes

- **Caching**: User tenant list is cached per request lifecycle
- **DB Queries**: One query to couch-sitter per unique user per request
- **Bulk Docs**: Single query, then validate all docs in memory
- **Large Syncs**: Should be fine, middleware runs before body parsing

## Security Considerations

- ✅ Validates based on JWT sub claim (user_id)
- ✅ Server source of truth for user's authorized tenants
- ✅ Cannot forge tenant membership (checked against couch-sitter)
- ✅ Works for all write operations (PUT, POST, _bulk_docs)
- ❌ Does not validate reads (could leak via _changes feed - separate issue)

## Future Improvements

1. Cache invalidation when user's tenants change
2. Rate limiting by tenant (prevent single tenant from flooding)
3. Audit logging of all writes by tenant
4. Tenant quota enforcement (max docs, storage)
5. Cross-tenant query prevention via read validation
