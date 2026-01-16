# Mango Query Fix Plan

## Problem
The `list_tenants()` query returns 0 results even though:
1. All documents exist in the database (debug shows 10 tenant documents)
2. Manual Python check finds the user IS in 3 of them
3. Both `$in` and `$elemMatch` operators are returning 0 results

## Root Cause Analysis

CouchDB Mango queries for array membership have specific requirements:

### Syntax Issue 1: `$in` with array fields (WRONG)
```python
"userIds": {"$in": [user_id]}
```
**Problem**: `$in` checks if a scalar field value equals one of the items in a list. Since `userIds` is itself an array, this doesn't work for array membership.

### Syntax Issue 2: `$elemMatch` with `$eq` (NEEDS TESTING)
```python
"userIds": {"$elemMatch": {"$eq": user_id}}
```
**Status**: Returns 502 errors in our setup - may need CouchDB configuration or different syntax.

### CouchDB 502 Errors
The 502 errors suggest:
1. CouchDB backend is down, OR
2. Mango query language feature isn't supported/enabled, OR
3. No suitable index exists for the query pattern

## Solution Strategy

Since CouchDB Mango has limitations, we should use a **hybrid approach**:

### A. Fetch-and-Filter Pattern (RECOMMENDED - Safe & Works)
```python
async def list_tenants(self, user_id: str):
    """List all tenants (unfiltered)."""
    query = {
        "selector": {
            "type": "tenant",
            "$and": [
                {"deletedAt": {"$exists": False}},
                {"deleted": {"$ne": True}}
            ]
        }
    }
    
    docs = await self.dal.query_documents("couch-sitter", query)
    
    # Filter in Python - guaranteed to work
    result = []
    for doc in docs.get("docs", []):
        if user_id in doc.get("userIds", []):
            result.append(doc)
    
    return result
```

**Pros:**
- Always works (no Mango query syntax issues)
- Already have debug code showing this works
- CouchDB will return results for simple type=tenant query

**Cons:**
- Fetches all tenants then filters (slight performance hit)
- OK because: typically 10-100 tenants per sitter DB

### B. Create Proper Mango Index (If CouchDB works)
```python
# Create index on userIds array
POST /{db}/_index
{
  "index": {
    "fields": ["type", "userIds"],
    "partial_filter_selector": {
      "$and": [
        {"type": {"$eq": "tenant"}},
        {"deletedAt": {"$exists": false}},
        {"deleted": {"$ne": true}}
      ]
    }
  },
  "name": "idx-tenant-userIds",
  "type": "json"
}

# Then query with proper syntax
{
  "selector": {
    "type": "tenant",
    "userIds": user_id,  # Try direct value match
    "$and": [...]
  }
}
```

## Recommended Fix: Hybrid Approach

1. **Keep approach A as primary** (fetch all tenants, filter in Python)
2. **Add approach B for future** (when CouchDB has proper index)
3. **Create detailed comment** explaining why we do both

## Implementation

### Code Change
File: `virtual_tables.py::list_tenants()`

```python
async def list_tenants(self, user_id: str):
    """
    List all tenants the user is a member of.
    
    ARCHITECTURE NOTE:
    We fetch ALL non-deleted tenants and filter in Python rather than
    using complex Mango query operators. This approach:
    
    1. WORKS: Simple type=tenant query always succeeds
    2. EFFICIENT: Typically 10-100 tenants per sitter DB
    3. DEBUGGABLE: Clear Python logic easy to test
    4. FUTURE: When CouchDB Mango supports array membership better,
               we can optimize to pure-query approach
    
    CouchDB Mango limitations:
    - $in doesn't work for array field membership
    - $elemMatch has complex requirements and 502 errors
    - No native "contains" operator for arrays
    """
    # Query for non-deleted tenants (simple constraint)
    query = {
        "selector": {
            "type": "tenant",
            "$and": [
                {"deletedAt": {"$exists": False}},
                {"deleted": {"$ne": True}}
            ]
        }
    }
    
    logger.info(f"[LIST_TENANTS] Querying for all non-deleted tenants")
    try:
        result = await self.dal.query_documents("couch-sitter", query)
    except Exception as e:
        logger.error(f"[LIST_TENANTS] Error querying tenants: {e}")
        raise HTTPException(status_code=500, detail="Error querying tenants")
    
    # Filter in Python - user must be in userIds array
    docs = result.get("docs", [])
    filtered = [doc for doc in docs if user_id in doc.get("userIds", [])]
    
    logger.info(f"[LIST_TENANTS] Fetched {len(docs)} total tenants, {len(filtered)} match user")
    
    # Rest of method: convert IDs to virtual format, populate members, etc...
```

## Testing the Fix

The test scripts created show:
1. **test_mango_query.py** - Tests various Mango syntaxes (needs CouchDB working)
2. **test_mango_couch_sitter.py** - Tests against actual couch-sitter DB

Both confirm: `$elemMatch` returns 502, fetch-and-filter works in Python.

## Migration Path

1. **Immediate**: Switch to fetch-and-filter (simple, reliable)
2. **Later**: Monitor CouchDB performance, optimize if needed
3. **Future**: Add proper indexes when ready
