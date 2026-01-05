# User ID Format Validation Implementation

## Overview

Following the same pattern as tenant ID validation, implemented comprehensive user ID format validation across all endpoints that use user_id. This ensures consistency and prevents format mismatches that could cause bugs.

## Implementation Details

### 1. Validation Function (tenant_validation.py)

Added `validate_user_id_format()` function that:
- Validates format: `user_<64-char-sha256-hash>`
- Checks prefix: must be exactly "user_"
- Checks hash length: must be exactly 64 characters
- Checks hash content: must be valid hexadecimal (0-9, a-f, A-F)
- Raises `UserIdFormatError` with clear, actionable error messages

```python
def validate_user_id_format(user_id: str) -> None:
    """
    Validate that user ID matches the required format: user_<64-char-sha256-hash>
    """
```

### 2. Validation Applied at HTTP Endpoints (main.py)

Added validation immediately after normalization in all endpoints:

| Endpoint | Method | Line |
|----------|--------|------|
| GET /__tenants | `get_tenants()` | After line 1675 |
| POST /__tenants | `create_tenant()` | After line 1700 |
| PUT /__tenants/{id} | `update_tenant()` | After line 1729 |
| DELETE /__tenants/{id} | `delete_tenant()` | After line 1767 |

**Pattern:**
```python
# Normalize to internal user ID format
user_id = _normalize_clerk_sub_to_user_id(sub)
try:
    validate_user_id_format(user_id)
except UserIdFormatError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

This ensures:
- Validation happens early (fail fast)
- Clear error messages to API callers
- Consistent error format (400 Bad Request)
- No invalid IDs reach service layer

### 3. Service Layer Documentation

Added CALLER RESPONSIBILITY comments to methods that receive user_id:

- `couch_sitter_service._add_user_to_admin_tenant()`
- `couch_sitter_service.create_workspace_tenant()`
- `virtual_tables.list_tenants()`
- `virtual_tables.create_tenant()`

```python
"""
CALLER RESPONSIBILITY: user_id MUST be in internal format (user_<64-char-sha256-hash>).
Normalization from Clerk sub happens at the HTTP endpoint layer (main.py).
"""
```

This makes it explicit:
- What format methods expect
- Where normalization happens
- Who is responsible for ensuring consistency

### 4. Comprehensive Test Suite (test_user_id_validation.py)

**Test Classes:**

1. **TestUserIdValidation** (15 tests)
   - Valid formats (single hash, mixed/uppercase hex, etc.)
   - Invalid: missing prefix, empty, wrong prefix, hash too short/long
   - Invalid hex characters (non-hex chars, special chars, spaces)
   - Case sensitivity (prefix must be lowercase)

2. **TestNormalizationAndValidation** (3 tests)
   - Real Clerk subs normalize to valid user IDs
   - Various Clerk subs all produce valid format
   - SHA256 always produces 64-char hex digest

3. **TestEdgeCases** (8 tests)
   - All lowercase/uppercase hex
   - Mixed case hex
   - All zeros/all f's (technically valid)
   - Whitespace handling
   - Newline characters

4. **TestCommonInvalidPatterns** (6 tests)
   - Just hash without prefix
   - UUID format (different ID type)
   - Bare Clerk sub without normalization
   - Email format
   - Arbitrary strings

**Total: 32 comprehensive tests** covering all validation rules and edge cases.

## User ID Format Consistency

### The Three Formats

This implementation clarifies three ID formats used throughout the codebase:

1. **Clerk Sub** (JWT claim)
   - Format: `user_<alphanumeric>`
   - Example: `user_34tzJwWB3jaQT6ZKPqZIQoJwsmz`
   - Source: Clerk JWT
   - Used: Only in `verify_clerk_jwt()` output

2. **Internal User ID** (CouchDB, service methods)
   - Format: `user_<64-char-sha256-hash>`
   - Example: `user_a3f7c2d9e1b4...` (64 hex chars)
   - Source: `_normalize_clerk_sub_to_user_id()`
   - Used: Database, service methods, validation
   - **THIS IS THE STANDARD FORMAT**

3. **Virtual User ID** (API requests, might be added later)
   - Format: `<64-char-sha256-hash>` (no prefix)
   - Example: `a3f7c2d9e1b4...`
   - Source: Frontend (not currently used)
   - Used: API client requests

### Validation Ensures

✅ All service methods receive consistent format  
✅ No Clerk subs leak into service layer  
✅ No raw hashes passed without prefix  
✅ Early failure with clear error messages  
✅ Type safety via strict format validation  

## Key Differences from Tenant ID Validation

| Aspect | Tenant ID | User ID |
|--------|-----------|---------|
| Format | `tenant_<uuid>` | `user_<64-char-hex>` |
| Length | Variable (UUID) | Fixed (64 chars) |
| Content | Valid UUID | Valid hex digits |
| Normalization | None (UUID generated) | SHA256 hash from Clerk sub |
| Origin | Backend generates | Frontend (Clerk JWT) |

## Error Handling

Validation errors return 400 Bad Request with descriptive messages:

```
"User ID cannot be empty"
"User ID must start with 'user_', got: {value}"
"User ID must include a hash after 'user_'"
"User ID hash must be 64 characters (SHA256 hex), got {actual}: {hash}"
"User ID hash must be valid hexadecimal, got: {hash}"
```

## Testing

Run the test suite:

```bash
uv run pytest tests/test_user_id_validation.py -v
```

Expected output: **32 passing tests** covering all validation scenarios.

## Files Modified

1. **src/couchdb_jwt_proxy/tenant_validation.py**
   - Added `UserIdFormatError` exception class
   - Added `validate_user_id_format()` function

2. **src/couchdb_jwt_proxy/main.py**
   - Updated import statement
   - Added validation in 4 HTTP endpoints

3. **src/couchdb_jwt_proxy/couch_sitter_service.py**
   - Added CALLER RESPONSIBILITY documentation to 2 methods

4. **tests/test_user_id_validation.py** (NEW)
   - 32 comprehensive tests
   - Tests for format, normalization, edge cases, patterns
