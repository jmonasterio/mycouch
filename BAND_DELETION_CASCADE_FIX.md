# Band Deletion Cascade Fix

## Problem

When deleting a band (tenant) in Roady, only the **tenant document** in couch-sitter was being soft-deleted. The **roady database** containing all the band's equipment, gigs, and other data was NOT being deleted.

This caused:
1. Orphaned band records that couldn't be fully deleted
2. Data accumulation with no cleanup when bands were removed
3. Inconsistency between couch-sitter (band gone) and roady (band still has data)

### Example:
- User deletes "Jorge's Band" (tenant_3c94ae1d-...)
- ✓ Tenant document in couch-sitter is soft-deleted
- ✗ The roady database containing the band's data still exists

## Solution

Implement **cascade delete**: When a band is deleted via `DELETE /__tenants/{id}`, BOTH should be deleted:

1. **Soft-delete tenant document** in couch-sitter
2. **Hard-delete the database** (e.g., DELETE /roady) containing band's data

### Design Principle

Both deletion steps are attempted independently:
- **If tenant deletion fails**: Operation fails immediately (can't proceed)
- **If database deletion fails**: Operation still succeeds but returns warnings
  - The tenant is already marked deleted, which is the critical part
  - Database deletion is best-effort (can be retried manually if needed)

## Implementation

### 1. Added `delete_database()` method to DAL (`dal.py`)

```python
async def delete_database(self, db: str) -> Dict[str, Any]:
    """Delete an entire database (cascade delete for band/tenant)."""
    response = await self.get(f"/{db}", "DELETE")
    
    if "error" in response:
        raise HTTPException(status_code=400, detail=response.get("reason", "Database deletion failed"))
    
    return response
```

This calls the CouchDB API: `DELETE /database_name`

### 2. Updated `delete_tenant()` in Virtual Tables Handler (`virtual_tables.py`)

**Before:**
```python
# Only soft-deleted tenant document
current_doc["deleted"] = True
await self.dal.put_document("couch-sitter", internal_id, current_doc)
return {"ok": True, "_id": ..., "_rev": ...}
```

**After:**
```python
# STEP 1: Soft-delete tenant in couch-sitter
tenant_deleted = False
try:
    put_result = await self.dal.put_document("couch-sitter", internal_id, current_doc)
    tenant_deleted = True
except Exception as e:
    warnings.append(f"Failed to delete tenant document: {e}")

# STEP 2: Cascade-delete the database
db_name = current_doc.get("applicationId")  # e.g., "roady"
db_deleted = False
if db_name and db_name != "couch-sitter":
    try:
        await self.dal.delete_database(db_name)
        db_deleted = True
    except Exception as e:
        warnings.append(f"Failed to delete database '{db_name}': {e}")

# Fail if tenant deletion failed (critical)
if not tenant_deleted:
    raise HTTPException(status_code=500, detail=warnings[0])

# Return success even if database deletion failed
return {
    "ok": True,
    "_id": ...,
    "_rev": ...,
    "warnings": warnings  # Include warnings if any
}
```

## Data Flow

```
User clicks "Delete Band" in Roady UI
           ↓
DELETE /__tenants/band-uuid
           ↓
VirtualTableHandler.delete_tenant()
           ├─ Get tenant_id from URL
           ├─ Get applicationId from tenant doc (e.g., "roady")
           ├─ Soft-delete tenant in couch-sitter ✓
           └─ Hard-delete /roady database ✓
           ↓
{ok: true, warnings: []}  (or warnings if db deletion failed)
           ↓
Roady UI removes band from list + shows success message
```

## Response Examples

### Full Success
```json
{
  "ok": true,
  "_id": "band-uuid",
  "_rev": "2-xyz"
}
```

### Success with Database Deletion Warning
```json
{
  "ok": true,
  "_id": "band-uuid",
  "_rev": "2-xyz",
  "warnings": ["Failed to delete database 'roady': Connection timeout"]
}
```

### Failure (Tenant Deletion Failed)
```json
{
  "error": "Failed to delete tenant document: Revision conflict",
  "status": 500
}
```

## Database Name Mapping

The `applicationId` field in the tenant document tells us which database contains the band's data:

| Tenant Document | Database |
|---|---|
| `applicationId: "roady"` | Deletes `/roady` database |
| `applicationId: "booking"` | Deletes `/booking` database |
| `applicationId: "inventory"` | Deletes `/inventory` database |
| `applicationId: "couch-sitter"` | Skipped (system database) |

## Error Handling

**Three failure modes:**

1. **Tenant deletion failed**: Reject entire operation (critical)
   ```
   HTTP 500: Failed to delete tenant document: {error}
   ```

2. **Database deletion failed**: Success with warning (non-critical)
   ```
   HTTP 200: {ok: true, warnings: ["Failed to delete database 'roady': {error}"]}
   ```

3. **Both failed**: Clear error message
   ```
   HTTP 500: Failed to delete tenant AND database deletion failed
   ```

## Testing Checklist

- [ ] Delete a band with equipment and gigs
  - [ ] Verify tenant document marked `deleted=true` in couch-sitter
  - [ ] Verify roady database is gone (HTTP GET /roady returns 404)
  - [ ] Verify band removed from UI
  
- [ ] Test error handling
  - [ ] Simulate database not found (should still succeed)
  - [ ] Simulate tenant deletion failure (should fail)
  - [ ] Verify warnings are included in response

- [ ] Test with different application types
  - [ ] roady application
  - [ ] Other applications using same pattern

## Files Modified

1. **dal.py**: Added `delete_database()` method
2. **virtual_tables.py**: Updated `delete_tenant()` to cascade delete
3. **main.py**: No changes needed (already calls virtual table handler)

## Future Enhancements

- [ ] Add orphaned database cleanup (find databases with no tenant in couch-sitter)
- [ ] Add confirmation for database deletion (warn user if database is large)
- [ ] Implement async deletion for large databases (return job ID, check status)
- [ ] Add cascade delete for users (delete all their tenants + databases)
