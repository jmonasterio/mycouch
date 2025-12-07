# Agent Guidelines for Testing

## Testing Strategy

When writing or fixing tests, prefer using the Memory DAL for creating test data instead of mocking where possible. This provides more realistic testing and helps catch integration issues.

### What NOT to Mock

1.  **DAL (Data Access Layer)**: Use Memory DAL instead of mocking `dal.get()` calls
2.  **APPLICATIONS Dictionary**: Populate the DAL with Application documents and call `initialize_applications()` instead of patching `APPLICATIONS`

### When to Use Memory DAL

-   Creating test documents (users, tenants, applications, etc.)
-   Testing database operations
-   Integration tests that need realistic data flow

### Example

```python
# ❌ Don't do this
with patch('module.dal.get') as mock_dal:
    mock_dal.return_value = {'id': 'test'}

# ✅ Do this instead
await dal.get("/testdb/doc_id", "PUT", {"id": "test"})
```

## Git Operations

**DO NOT** perform git mutations like:
- `git checkout` (to discard changes)
- `git reset`
- `git commit`
- `git push`
- `git stash`

The human handles all git operations. If a file needs to be restored, inform the user and let them handle it.

## Database Protection
- **Whitelist Protection**: The proxy enforces a whitelist of allowed databases.
- **Dynamic Whitelist**: The whitelist is dynamically built from Application documents in the `couch-sitter` database.
- **Couch-Sitter Special Case**: The `couch-sitter` database is always allowed as the admin database.
- **System Databases**: `_users` and `_replicator` are always allowed.
