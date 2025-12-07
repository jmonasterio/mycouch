# CLAUDE.md - Development Context




This file provides guidance to Claude Code when working with this repository.

## Project Overview

**MyCouch (CouchDB JWT Proxy)** is a secure HTTP proxy for CouchDB providing:

- **JWT Authentication**: Clerk JWT (RS256) with public key cryptography
- **Multi-Tenant Data Isolation**: Optional tenant-level access control
- **Offline-First Support**: Long-polling for PouchDB real-time sync
- **Production-Ready**: Deployed to Linux servers via GitHub Actions

## Architecture.
- Roady and Couch-Sitter are PWA javascript + Alpine apps that use index DB + PouchDB. PouchDB is used to, optionally, sync indexDB to mycouch.
- Mycouch is a couchdb proxy that will run onserver (in cloud), and adds tenancy model on top of couchDB which also runs in cloud. The couchdb is backed up to R2.
- Couch-sitter is allowed to touch, thru mycouch, the special couch-sitter db in couchdb. This contains apps, tenants, and users.
- Roady is only allowed to touch the "roady" DB via mycouch, with a JWT from clerk. The JWT will use REST APIs in mycouch to get a tenant id into the JWT. The mycouch proxy injects the tenant ID into every request. 
- Mycouch is supposed to do metadata injections, and the roady is supposed to reload the JWT token
 after.
- Roady can manage more than one band in a tenant. For now we only have one, but the bandID should should be in every document.
- In our couchdb documents, we only have one DB per app, like roady. All the documents have a type=xxx, field that represents documents in that table.
- Tenants are the concept for Roady invitations. A user will be able to invite other user's to see their personal tenant. For now, a user can only have one personal tenant.

**Primary Use Case**: Serves as the authentication gateway for **Roady PWA** (band management app) and Couch-Sitter (admin for apps, tenants, user).

## Guidelines for PRDs and coding.
- All work should be organized into a PRD. The work in the PRD should be a standalone, complete deliverable, when possible.
- PRD plan should have TESTS first. Plan to write tests before code, especially in in python.
- Service and UI tests should use a DAL layer to allow testing without corrupting the DB. This is particularly important for mycouch python layer, and less so for javascript which uses index DB. When testing indexDB, we can turn off pouchDB sync.
- PRD's do not need time estimates. 
- I appreciate phased plans that can be tested as we go.

## Claude Code Usage Guidelines

**IMPORTANT**: When using file operation tools like `Read()`, `Write()`, and `Edit()`:
- Always use **full absolute paths** with **forward slashes** (`/`)
- Example: `C:/github/mycouch/src/couchdb_jwt_proxy/main.py`
- Never use backslashes or relative paths
- This prevents file access errors on Windows systems

**Correct Examples:**
```python
Read("C:/github/mycouch/src/couchdb_jwt_proxy/main.py")
Write("C:/github/mycouch/.env.example", content)
Edit("C:/github/mycouch/CLAUDE.md", old_string, new_string)
```

**Incorrect Examples (will fail):**
```python
Read("C:\\github\\mycouch\\main.py")  # Backslashes
Read("src/couchdb_jwt_proxy/main.py")  # Relative path
```


**DO NOT make any git mutations without explicit permission.**

This includes:
- ❌ `git add` - Do NOT stage files
- ❌ `git commit` - Do NOT create commits
- ❌ `git push` - Do NOT push to remote
- ❌ `git branch` - Do NOT create branches
- ❌ `git stash` - Do NOT stash changes


Ask for permission before any git operations
Let the user review changes before committing

## Architecture

```
┌─────────────────────────────────────────┐
│  Roady PWA (Offline-First App)          │
│  Browser: PouchDB + Clerk Auth          │
│  (or other offline-first app)           │
└──────────────┬──────────────────────────┘
               │ HTTPS
               ↓
┌─────────────────────────────────────────┐
│  CouchDB JWT Proxy (FastAPI)            │
│  Port 5985 (production: behind Nginx)    │
│  - Clerk JWT validation (RS256)         │
│  - Multi-tenant isolation               │
│  - Long-polling support                 │
│  - Content-Type header fixing           │
└──────────────┬──────────────────────────┘
               │ Internal HTTP
               ↓
┌─────────────────────────────────────────┐
│  CouchDB (Internal)                     │
│  Port 5984 (NOT exposed to clients)     │
│  - Multi-database support               │
│  - Optional admin auth (basic)          │
└─────────────────────────────────────────┘
```
# Use PY for python.

### Authentication Flow

```
Client Request with Clerk JWT
  ↓
Clerk JWT validation (RS256)
    - Fetch signing keys from Clerk JWKS
    - Verify signature and claims
    ↓
    [SUCCESS] → Allow request
    [FAIL] → Return 401 Unauthorized
```

## Key Components

### Main Application (main.py)

Single-file FastAPI application (~650 lines):

**Authentication Functions:**
- `verify_clerk_jwt()` - RS256 validation using PyJWKClient (cached JWKS)

**Proxy Functions:**
- `proxy_couchdb()` - Main request handler
- Request forwarding with header manipulation
- Long-polling detection for `_changes?feed=longpoll`
- Automatic Content-Type header setting (`application/json`)
- Multi-tenant request/response filtering

**Tenant Isolation (Optional):**
- `extract_tenant()` - Get tenant ID from JWT claim
- `inject_tenant_into_doc()` - Add tenant_id to documents
- `filter_response_documents()` - Remove non-tenant docs from results
- Query rewriting for `_all_docs` and `_find`

**Configuration Validation:**
- Fails on startup if CLERK_ISSUER_URL missing
- Clear error messages guide users to correct setup

### Configuration Files

**.env** (local development, in .gitignore)
```
# Authentication
CLERK_ISSUER_URL=https://your-instance.clerk.accounts.dev

# CouchDB
COUCHDB_INTERNAL_URL=http://localhost:5984
COUCHDB_USER=admin
COUCHDB_PASSWORD=<password>

# Proxy
PROXY_HOST=0.0.0.0  # 0.0.0.0=all interfaces, 127.0.0.1=localhost
PROXY_PORT=5985

# Optional: Multi-tenant
ENABLE_TENANT_MODE=true|false
TENANT_CLAIM=tenant_id
TENANT_FIELD=tenant_id

# Logging
LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
```

**.env.example** (template with documentation)
- Comprehensive comments explaining each setting
- Instructions for configuring Clerk

### Deployment

**GitHub Actions Workflow** (`.github/workflows/deploy-proxy.yml`)
- Triggered on push to main (or manual)
- SSH-based deployment (no git credentials needed)
- Copies files via SCP
- Stops/restarts systemd service
- Verifies health endpoint

**Linux Deployment** (systemd service)
- Runs as `nobody` user
- Auto-restart on failure
- Auto-start on system reboot
- Environment loaded from .env file on server

**Nginx Reverse Proxy**
- TLS termination (Let's Encrypt via Certbot)
- Long-polling support (300s timeouts)
- Security headers

## Development Workflow

### Setup

```bash
# Install dependencies
uv sync                    # Install runtime dependencies
uv sync --all-extras       # Include dev/test dependencies

# Create local .env
cp .env.example .env
nano .env                  # Set CLERK_ISSUER_URL and CouchDB credentials

# Start CouchDB
docker-compose up -d       # or manually: docker run -d -p 5984:5984 couchdb:3

# Run proxy
uv run uvicorn main:app --reload --port 5985
```

### Testing

```bash
# Run all tests
uv run pytest test_main.py -v

# Run with coverage report
uv run pytest test_main.py -v --cov=main --cov-report=html

# Run specific test
uv run pytest test_main.py::TestJWTFunctions -v

# Watch mode (reruns on file changes)
uv run pytest test_main.py -v --looponfail
```

### Manual Testing

```bash
# Get Clerk JWT token (use token from Clerk SDK in your app)
# const token = await window.Clerk.session.getToken();

# Use token to query CouchDB
curl -H "Authorization: Bearer YOUR_CLERK_TOKEN" http://localhost:5985/_all_dbs

# Check health
curl http://localhost:5985/health
```

## Critical Implementation Details

### Content-Type Header Fixing

CouchDB requires `Content-Type: application/json` for POST/PUT requests. PouchDB sometimes sends `text/plain`. **Solution:** Proxy always sets correct header for CouchDB endpoints.

**Code:** main.py lines 525-533

### Long-Polling Support

CouchDB `_changes?feed=longpoll` connections wait indefinitely for changes. Default 30-second timeout kills these connections. **Solution:** Detect long-polling and use 300-second timeout.

**Code:** main.py lines 546-548

### Multi-Tenant Isolation

When enabled, ensures:
- Users can only create documents with their tenant_id
- Users can only see documents matching their tenant_id
- System endpoints blocked to prevent enumeration
- Tenant_id extracted from JWT, not user input

**Code:** main.py lines 186-315

## Important Files & Locations

| File | Purpose | Lines |
|------|---------|-------|
| main.py | FastAPI application | 630 |
| test_main.py | Unit tests | 100+ |
| pyproject.toml | Dependencies | 47 |
| .env.example | Config template | 68 |
| .github/workflows/deploy-proxy.yml | CI/CD workflow | 80 |

### Documentation Files

| File | Purpose |
|------|---------|
| README.md | User guide, API reference, quick start |
| CLERK_SETUP.md | How to configure Clerk JWT |
| LINUX_DEPLOYMENT_PROXY.md | Step-by-step server deployment |
| GITHUB_ACTIONS_DEPLOY.md | GitHub Actions setup |
| SECURITY_CHECKLIST.md | Security requirements |
| TENANT_DETERMINATION.md | How tenant isolation works |
| .env.example | Configuration documentation |

## Common Tasks

### Adding a Feature

1. **Update main.py** with new logic
2. **Add tests** in test_main.py
3. **Update .env.example** if new env vars needed
4. **Document** in appropriate guide (.md file)
5. **Test locally** before committing

### Fixing a Bug

1. **Find test** that reproduces the issue
2. **Fix the bug** in main.py
3. **Verify test** passes
4. **Check for related** functions affected
5. **Test manually** if involves CouchDB interaction

### Deploying Changes

1. **Run tests**: `uv run pytest test_main.py -v`
2. **Commit changes**: `git add -A && git commit -m "..."`
3. **Push to main**: `git push origin main`
4. **GitHub Actions** automatically deploys to server
5. **Verify**: Check `/health` endpoint on production

## Security Considerations

### Secrets Management

- ✅ `.env` in .gitignore (never committed)
- ✅ No hardcoded defaults for secrets
- ✅ Configuration validation on startup

### Authentication

- ✅ Clerk JWT: RS256 with public key caching
- ✅ No shared secrets - uses public/private key cryptography
- ✅ Token expiration enforced

### Multi-Tenant

- ✅ Tenant extracted from JWT (not user input)
- ✅ All responses filtered by tenant
- ✅ System endpoints blocked in tenant mode
- ✅ Tenant_id cannot be modified by client

### Network

- ✅ CouchDB port 5984 internal only
- ✅ Proxy port 5985 accessible (behind Nginx in prod)
- ✅ HTTPS with Nginx in production
- ✅ TLS certificates auto-renewed

## Integration with Roady PWA

Roady uses this proxy for:

1. **Authentication**: `await Clerk.session.getToken()` → JWT token
2. **Sync**: `PouchDB.sync(proxyUrl, {live: true})` with Bearer token
3. **Multi-Tenant**: Each band is separate tenant via JWT claim
4. **Offline**: Local-first with proxy sync when online

See `../../roady/js/db.js` for implementation.

## Debugging Tips

### Enable Debug Logging
```bash
# In .env
LOG_LEVEL=DEBUG
```

### Check JWT Validity
```bash
# Decode JWT 
```

### Verify CouchDB Connection
```bash
# Test direct CouchDB access (bypass proxy)
curl -u admin:password http://localhost:5984/
```

### Test Token Generation
```javascript
// Clerk JWT (use Clerk SDK to get token)
const token = await window.Clerk.session.getToken()
```

### Inspect Proxy Logs
```bash
# On production server
sudo journalctl -u couchdb-proxy -f

# Search for errors
sudo journalctl -u couchdb-proxy | grep "401\|ERROR"
```

## Known Limitations

1. **Rate Limiting**: Not implemented, consider adding
2. **Audit Logging**: Limited to application logs
3. **Scoped Access**: All tokens have full access, could add scopes
4. **Database Quotas**: No per-database resource limits

## Related Projects

- **Roady PWA**: Band management app using this proxy (../../roady)
- **CouchDB**: Database backend
- **Clerk**: Optional authentication provider

## Environment Setup Checklist

- [ ] Python 3.9+ installed
- [ ] uv package manager installed
- [ ] Dependencies installed (`uv sync`)
- [ ] CouchDB running on localhost:5984
- [ ] `.env` file created with valid settings
- [ ] `CLERK_ISSUER_URL` set in `.env`
- [ ] Tests pass (`uv run pytest test_main.py`)
- [ ] Proxy starts (`uv run uvicorn main:app`)

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [PyJWT Documentation](https://pyjwt.readthedocs.io/)
- [Clerk JWT Documentation](https://clerk.com/docs/jwt/jwt-templates)
- [CouchDB Documentation](https://docs.couchdb.org/)
- [PouchDB Documentation](https://pouchdb.com/)
- ## CRITICAL: File Editing on Windows

### ⚠️ MANDATORY: Always Use Backslashes on Windows for File Paths with Tools like Read(), Write(), and Update()

**When using Edit or MultiEdit tools on Windows, you MUST use backslashes (`\`) in file paths, NOT forward slashes (`/`).**

#### ❌ WRONG - Will cause errors:
```
Edit(file_path: "D:/repos/project/file.tsx", ...)
MultiEdit(file_path: "D:/repos/project/file.tsx", ...)
```

#### ✅ CORRECT - Always works:
```
Edit(file_path: "D:\repos\project\file.tsx", ...)
MultiEdit(file_path: "D:\repos\project\file.tsx", ...)