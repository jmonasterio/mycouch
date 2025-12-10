# Catch-All Routing Problem and Solution

## Problem Summary

The proxy is receiving `/api/tenants/*/members` requests at the catch-all handler (`proxy_couchdb`) instead of letting the tenant router handle them. This causes 404 errors instead of proper API responses.

Error log:
```
CRITICAL: /api path reached proxy catch-all handler instead of tenant router!
Affected path: /api/tenants/tenant_fc0508aa.../members
```

## Root Cause Analysis

### How FastAPI Routes Work

FastAPI's routing system matches incoming paths against registered routes in order of **specificity**, not definition order:

1. **Most specific routes match first** (e.g., `/api/tenants/{tenant_id}/members` is more specific than `/{path:path}`)
2. **More generic routes match later** (e.g., `/{path:path}` catches everything else)
3. **Included routers are part of the same matching pool** (their routes don't bypass the catch-all)

### Why `/api/tenants/*` Is Reaching the Catch-All

The problem occurs when:

1. `tenant_router` is included with `app.include_router(tenant_router)` → registers `/api/tenants/*` routes
2. Catch-all handler is defined with `@app.api_route("/{path:path}", ...)` 
3. **FastAPI matches `/api/tenants/*/members` against the catch-all** because:
   - The catch-all pattern `/{path:path}` matches **any** path (greedy)
   - If the path doesn't match a more specific route registered earlier, the catch-all wins
   - The issue is that the tenant router routes **aren't considered "more specific"** in FastAPI's routing logic when both are at the app level

### Key Insight

The routing priority depends on:
- Route **specificity** (longer paths with fixed segments are more specific)
- Route **registration order** (only matters as a tiebreaker in FastAPI)
- Whether routes are on the **same handler** or through **included routers**

In this case, `/api/tenants/{tenant_id}/members` is registered through `include_router()`, but FastAPI's middleware/routing system is evaluating the catch-all `/{path:path}` **at the app level** and it's matching first.

## Solution

### Method 1: Add Guard Check (Current Implementation)

Add an explicit guard at the start of the catch-all handler:

```python
if path.startswith("api/") or path == "api":
    logger.error("CRITICAL: /api path should be handled by tenant router!")
    raise HTTPException(status_code=404, detail="API endpoint not found")
```

**Pros:**
- Prevents misconfigured requests from reaching CouchDB
- Provides clear error messages
- Simple to implement

**Cons:**
- Doesn't fix the root cause (routing configuration)
- Still rejects valid API requests if router isn't working

### Method 2: Separate Routers (Better Architecture)

Reorganize routes by creating separate app instances or organizing at a higher level:

```python
# Option A: Different path prefixes
app.include_router(tenant_router)  # prefix="/api"
app.include_router(couchdb_router)  # prefix="/couchdb" or "/" for CouchDB paths

# Then catch-all only applies to "/couchdb/*" or database paths
@app.api_route("/couchdb/{path:path}", ...)
async def proxy_couchdb(path: str, ...):
    # Only handles /couchdb/* paths
```

**Pros:**
- Clear separation of concerns
- No path conflicts
- Better routing clarity

**Cons:**
- Requires frontend/client changes (new URL format)
- More restructuring

### Method 3: Smart Route Ordering

Ensure `/api/*` routes are evaluated **before** the catch-all by organizing the application setup:

```python
# 1. Register all specific /api routes FIRST
app.include_router(tenant_router, prefix="/api")

# 2. Register health/admin endpoints
@app.get("/health")
@app.get("/choose-tenant")
@app.get("/my-tenants")
# ... other specific routes

# 3. ONLY THEN register the catch-all
@app.api_route("/{path:path}", ...)
async def proxy_couchdb(path: str, ...):
    # This now only catches database paths like:
    # - couch-sitter/doc_id
    # - roady/_changes
    # - etc.
    
    # Reject any /api paths that slipped through
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Unregistered API endpoint")
```

## Current Implementation Status

✅ **Method 1 (Guard Check)** is already implemented in the code:
- Guard checks if `path.startswith("api/")`
- Logs detailed error messages
- Rejects the request with 404

## Recommended Next Steps

1. **Verify the guard is working**: Check logs to confirm `/api/*` requests are hitting the guard check
2. **Debug why tenant router isn't matching**:
   - Ensure `app.include_router(tenant_router)` is called before the catch-all is defined
   - Check that the router prefix is exactly `/api`
   - Look for middleware that might be stripping `/api`

3. **If guard works but routing is still broken**:
   - Implement Method 2 (Separate prefixes) if you want to reorganize
   - Or keep Method 1 and ensure all `/api/*` routes are properly registered

## Debugging Checklist

- [ ] Verify `tenant_router` is created with `prefix="/api"`
- [ ] Verify `app.include_router(tenant_router)` is called before catch-all definition
- [ ] Check logs for "Registered tenant and invitation management routes" message
- [ ] Check if any middleware is rewriting `/api/*` paths
- [ ] Verify the catch-all guard check is being executed (error logs should appear)
- [ ] Test with explicit routes: `POST /api/tenants` (this should work)
- [ ] Test with catch-all: `GET /api/tenants/tenant_id/members` (this should be caught by guard if router doesn't match)

## Architecture Recommendation

For clarity and to prevent future routing issues, consider **Method 3**:

```
Current: app → (include_router) → tenant_router → catch_all_proxy
Problem: catch_all_proxy matches before tenant_router because of path matching logic

Better: app → tenant_router (specific) → system_routes (health, etc.) → catch_all_proxy (database only)
```

This makes it clear that:
- API routes (`/api/*`) are handled by dedicated routers
- System routes (`/health`, `/choose-tenant`, etc.) are explicit handlers  
- Only database paths (`database/doc`, `database/_changes`, etc.) reach the catch-all
