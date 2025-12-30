# Tenant Update 403 Issue - Fix Recommendations

## Summary of Issue
The `test_update_tenant` test is failing with a 403 "Only owner can update this tenant" error when trying to update a tenant that was just created by the same authenticated user.

## Immediate Actions Taken

### 1. Enhanced Logging
Added detailed logging at multiple levels to help diagnose the issue:
- Route level: Log the `requesting_user_id` extracted from JWT
- Virtual table handler level: Log the tenant owner check with explicit values and types
- Access control level: Log the owner comparison with types and results

### 2. Input Validation
Added validation to ensure `requesting_user_id` is not empty before processing the update.

### 3. Test Code Fixes
Fixed Unicode encoding issues in test file that were preventing tests from running properly.

## Root Cause Hypothesis

Based on the test output showing successful creation (200) but failed update (403), the most likely cause is:

**The `requesting_user_id` extracted from the JWT is different between the POST (create) and PUT (update) requests, even though the same token is being used.**

This could be caused by:
1. JWT parsing/decoding issue that's environment-specific
2. Clerk JWKS caching issue causing different validation results
3. Token state or claim changes between requests
4. Whitespace or encoding differences in how the `sub` claim is stored

## Recommended Permanent Fixes

### Option A: Add Defensive Normalization (Safest)
Normalize user IDs before comparison to handle whitespace/encoding issues:

```python
def can_update_tenant(user_id: str, tenant_doc: Dict[str, Any], field: str) -> bool:
    if not tenant_doc:
        return False
    
    # Normalize both values for comparison
    tenant_userId = (tenant_doc.get("userId") or "").strip()
    normalized_user_id = (user_id or "").strip()
    
    if tenant_userId != normalized_user_id:
        logger.warning(f"Owner check failed: '{normalized_user_id}' != '{tenant_userId}'")
        return False
    
    # ... rest of method
```

### Option B: JWT Validation Debugging
If the fix above doesn't work, enable JWT validation logging:

```python
# In verify_clerk_jwt():
unverified_payload = decode_token_unsafe(token)
logger.debug(f"JWT 'sub' claim: '{unverified_payload.get('sub')}'")
# ... later after validation ...
logger.debug(f"Verified 'sub' claim: '{payload.get('sub')}'")
```

### Option C: Session Consistency Check
Ensure the authenticated user context is maintained across requests by storing it in a request-local context variable rather than extracting it each time.

## Testing the Fix

1. **Run single test**:
   ```bash
   python -m pytest tests/test_virtual_endpoints_manual.py::TestTenantEndpoints::test_update_tenant -xvs
   ```

2. **Check logs** for the new debugging output:
   ```
   [ROUTE] POST /__tenants: requesting_user_id=...
   [ROUTE] PUT /__tenants/{id}: requesting_user_id=...
   [VIRTUAL] Update tenant access check: ...
   [CAN_UPDATE_TENANT] ...
   ```

3. **Verify the values match**:
   - Look for any whitespace, encoding, or type differences
   - Confirm `userId` stored in tenant doc matches the authenticated user

## Environment Considerations

The issue might be specific to:
- The Clerk issuer/environment being used
- Token expiration or freshness
- Environment variable configuration (especially `SKIP_JWT_EXPIRATION_CHECK`)

Check that:
- `.env` file has valid JWT_TOKEN
- Clerk issuer is registered in APPLICATIONS config
- Token hasn't expired (should be recent)

## Files Modified

1. `src/couchdb_jwt_proxy/virtual_tables.py`:
   - Added validation for empty `requesting_user_id`
   - Enhanced `can_update_tenant()` logging
   - Added logging in `create_tenant()` and `update_tenant()`

2. `src/couchdb_jwt_proxy/main.py`:
   - Added route-level logging for JWT `sub` extraction

3. `tests/test_virtual_endpoints_manual.py`:
   - Fixed Unicode encoding issues (✓ → [OK], ✗ → [FAIL], etc.)

## Next Steps

1. Run the test with the new logging enabled
2. Review the log output to see where the mismatch occurs
3. Apply Option A (normalization) if whitespace/encoding is the issue
4. Apply Option B/C if JWT parsing is the problem
5. Run full test suite to confirm no regressions
