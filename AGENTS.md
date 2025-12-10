# MyCouch Agent Guidelines

## Quick Commands

**Build & Test:**
- `uv sync --all-extras` - Install all dependencies (dev + test)
- `uv run pytest tests/ -v` - Run all tests
- `uv run pytest tests/test_main.py::TestClass::test_method -v` - Run single test
- `make test-cov` - Run tests with coverage report
- `make lint` && `make format` - Lint and format code

**Running:**
- `make dev-run` - Start proxy with auto-reload on :5985
- `make run` - Start production proxy

## Architecture (MyCouch + Roady)

**MyCouch**: FastAPI CouchDB proxy with JWT auth (Clerk RS256)
- Port 5985 (proxy) ← Frontend
- Port 5984 (CouchDB) ← Proxy only
- Databases: `couch-sitter` (users/tenants/apps), `roady` (band data)
- Multi-tenant isolation via JWT claims

**Roady**: PWA band equipment checklist
- Uses PouchDB for offline-first sync
- Manages multiple tenants (bands) per user
- User documents in `couch-sitter`, tenant/equipment in `roady`

## File Structure

```
src/couchdb_jwt_proxy/
  main.py (endpoints, JWT validation, proxy logic)
  clerk.py (Clerk Backend API, user metadata)
  auth.py (JWT verification)
  couch_sitter_service.py (user/tenant management)
  tenant_routes.py (tenant APIs)
  invite_service.py (invitations)
tests/ (pytest + asyncio)
```

## Code Standards

**Python**: PEP 8, type hints, async/await, docstrings
**Imports**: `from typing import Optional, Dict, Any`; `import httpx`, `from fastapi import HTTPException`
**Errors**: Always raise `HTTPException` with status_code + detail
**Logging**: Use `logger.info()`, `logger.error()` (config via LOG_LEVEL env var)
**Multi-tenant**: Extract tenant_id from JWT claim, never user input

## Critical Notes

- User docs in `couch-sitter` DB (format: `user_{sub_hash}`)
- Tenant/band docs in `roady` DB (format: `tenant_{uuid}`)
- `tenant_user_mapping` documents are redundant (being removed per mycouch-ba4)
- Always ensure user_id comes from `ensure_user_exists()`, not JWT directly
- Test with DAL layer (no real DB corruption)

## Issue Tracking (bd)

- `bd list --status open` - See open work
- `bd ready` - Show unblocked issues
- `bd create "Task name" -p 2 -t feature` - Create new issue
- `bd close mycouch-xxx --reason "Fixed in PR"` - Close issue

## Git Workflow

**DO NOT commit/push.** User controls commits. Apply changes → stage in git → user reviews → user commits.
