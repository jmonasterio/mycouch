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

bd - Dependency-Aware Issue Tracker

Issues chained together like beads.

GETTING STARTED
  bd init   Initialize bd in your project
            Creates .beads/ directory with pro
            Auto-detects prefix from directory

  bd init --prefix api   Initialize with custo
            Issues will be named: api-1, api-2

CREATING ISSUES
  bd create "Fix login bug"
  bd create "Add auth" -p 0 -t feature
  bd create "Write tests" -d "Unit tests for a

VIEWING ISSUES
  bd list       List all issues
  bd list --status open  List by status
  bd list --priority 0  List by priority (0-4,
  bd show bd-1       Show issue details

MANAGING DEPENDENCIES
  bd dep add bd-1 bd-2     Add dependency (bd-
  bd dep tree bd-1  Visualize dependency tree
  bd dep cycles      Detect circular dependenc

DEPENDENCY TYPES
  blocks  Task B must complete before task A
  related  Soft connection, doesn't block prog
  parent-child  Epic/subtask hierarchical rela
  discovered-from  Auto-created when AI discov

READY WORK
  bd ready       Show issues ready to work on
            Ready = status is 'open' AND no bl
            Perfect for agents to claim next w

UPDATING ISSUES
  bd update bd-1 --status in_progress
  bd update bd-1 --priority 0
ready to claim
    • Use --json flags for programmatic parsing
    • Dependencies prevent agents from duplicating effort

DATABASE EXTENSION
  Applications can extend bd's SQLite database:
    • Add your own tables (e.g., myapp_executions)
    • Join with issues table for powerful queries
    • See database extension docs for integration patterns:
      https://github.com/steveyegge/beads/blob/main/EXTENDING.md

GIT WORKFLOW (AUTO-SYNC)
  bd automatically keeps git in sync:
    • ✓ Export to JSONL after CRUD operations (5s debounce)
    • ✓ Import from JSONL when newer than DB (after git pull)
    • ✓ Works seamlessly across machines and team members
    • No manual export/import needed!
  Disable with: --no-auto-flush or --no-auto-import
