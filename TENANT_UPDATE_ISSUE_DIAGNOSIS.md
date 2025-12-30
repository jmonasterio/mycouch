# Tenant Update 403 Issue - Diagnosis

## Problem
Test `test_update_tenant` is failing with:
```
AssertionError: Expected 200, got 403: Only owner can update this tenant
```

The test creates a tenant successfully (200 status), but immediately updating it with the same token fails (403 status).

## Root Cause Analysis

The error "Only owner can update this tenant" comes from `VirtualTableAccessControl.can_update_tenant()` returning False.

This method checks: `if tenant_doc.get("userId") != user_id: return False`

For this to fail with the SAME token being used for both create and update, one of these must be true:

1. **`requesting_user_id` from JWT is different between requests** - unlikely, same token is reused
2. **`tenant_doc.userId` is different from what was stored** - database consistency issue
3. **`requesting_user_id` is becoming None or falsy** - JWT parsing issue
4. **Type mismatch** - e.g., one is a str and one is None, or different string values

## Code Review

### Create path (working):
```python
@app.post("/__tenants")
async def create_tenant(...):
    requesting_user_id = payload.get("sub")  # e.g., "user_34tzTwsQI0gQpXZIqZNkixYGfPq"
    # ...
    await virtual_table_handler.create_tenant(requesting_user_id, body)

# In create_tenant():
tenant_doc = {
    "_id": internal_id,
    "userId": requesting_user_id,  # Stored as-is
    ...
}
```

### Update path (failing):
```python
@app.put("/__tenants/{tenant_id}")
async def update_tenant(...):
    requesting_user_id = payload.get("sub")  # Should be same value
    # ...
    await virtual_table_handler.update_tenant(tenant_id, requesting_user_id, body)

# In update_tenant():
current_doc = await self.dal.get_document("couch-sitter", internal_id)  # Fetches tenant doc
if not VirtualTableAccessControl.can_update_tenant(requesting_user_id, current_doc, "_"):
    # This comparison is failing:
    # tenant_doc.get("userId") != user_id
    raise HTTPException(status_code=403, detail="Only owner can update this tenant")
```

## Most Likely Cause

The `requesting_user_id` being passed to `update_tenant()` is **different** or **invalid** compared to the `userId` stored in the tenant document.

Possible reasons:
1. JWT token validation is returning empty/None for `sub` claim in second request (but this would cause 400 error)
2. The token's `sub` claim changed (shouldn't happen with same token)
3. There's a whitespace, encoding, or type mismatch (e.g., `"user_34...   "` vs `"user_34..."`)
4. The tenant document is being fetched from a different database/version

## Enhanced Logging Added

I've added comprehensive logging to help debug:

- `[VIRTUAL] Creating tenant with owner: {requesting_user_id}` - logs owner ID during creation
- `[ROUTE] POST /__tenants: requesting_user_id={requesting_user_id}` - logs extracted JWT sub
- `[ROUTE] PUT /__tenants/{tenant_id}: requesting_user_id={requesting_user_id}` - logs extracted JWT sub for update
- `[VIRTUAL] Update tenant access check: ...` - detailed logging with quoted values and types
- `[CAN_UPDATE_TENANT] user_id='...' (type=...), tenant_userId='...' (type=...), is_owner=...` - detailed comparison info

## Next Steps to Debug

1. **Run the test with logging enabled** and capture the output to see:
   - What `requesting_user_id` is during create vs update
   - What `tenant_userId` is stored in the document
   - Whether they match and why the comparison is failing

2. **Check JWT token expiration** - if the token is expiring, a new one might need to be generated

3. **Verify database state** - check if the tenant document in CouchDB has the correct `userId` field

4. **Environment variables** - ensure SKIP_JWT_EXPIRATION_CHECK is set if testing with old tokens

## Fix Suggestions

1. Add validation to ensure `requesting_user_id` is not empty before update
2. Add string normalization (strip whitespace) in the comparison
3. Add better error messages that show the actual values being compared
4. Consider caching the authenticated user context to ensure consistency across requests

## Files Modified

- `/src/couchdb_jwt_proxy/virtual_tables.py` - Added logging and validation
- `/src/couchdb_jwt_proxy/main.py` - Added logging at route level
- `/tests/test_virtual_endpoints_manual.py` - Fixed Unicode encoding issues
