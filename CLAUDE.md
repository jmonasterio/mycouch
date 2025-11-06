# CLAUDE.md - Development Context

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**MyCouch (CouchDB JWT Proxy)** is a secure HTTP proxy for CouchDB providing:

- **JWT Authentication**: Supports both Clerk JWT (RS256, enterprise) and custom JWT (HS256, simple)
- **Multi-Tenant Data Isolation**: Optional tenant-level access control
- **Offline-First Support**: Long-polling for PouchDB real-time sync
- **Production-Ready**: Deployed to Linux servers via GitHub Actions

**Primary Use Case**: Serves as the authentication gateway for **Roady PWA** (band management app).

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
│  - Custom JWT validation (HS256)        │
│  - Automatic fallback between auth      │
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

### Authentication Flow

```
Client Request with JWT
  ↓
[1] Try Clerk JWT validation (RS256)
    - Fetch signing keys from Clerk JWKS
    - Verify signature and claims
    ↓
    [SUCCESS] → Allow request
    [FAIL] → Continue to [2]
  ↓
[2] Try Custom JWT validation (HS256)
    - Verify signature with JWT_SECRET
    - Check expiration
    ↓
    [SUCCESS] → Allow request
    [FAIL] → Return 401 Unauthorized
```

## Key Components

### Main Application (main.py)

Single-file FastAPI application (~650 lines):

**Authentication Functions:**
- `verify_clerk_jwt()` - RS256 validation using PyJWKClient (cached JWKS)
- `verify_jwt_token()` - HS256 validation with JWT_SECRET
- `create_jwt_token()` - Generate custom JWT from API key
- Fallback logic: Tries Clerk first, falls back to custom JWT

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
- Fails on startup if JWT_SECRET missing (when not using Clerk)
- Fails on startup if CLERK_ISSUER_URL missing (when Clerk enabled)
- Clear error messages guide users to correct setup

### Configuration Files

**.env** (local development, in .gitignore)
```
# Authentication (choose one or both)
ENABLE_CLERK_JWT=true|false
CLERK_ISSUER_URL=https://your-instance.clerk.accounts.dev
JWT_SECRET=<generated-secret>

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
- Instructions for generating secure JWT_SECRET
- Different configurations for Clerk vs custom JWT

**config/api_keys.json** (local only, in .gitignore)
- Only needed for custom JWT mode
- Maps API keys to client IDs
- Example: `{"api-key-1": "client-name"}`

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
nano .env                  # Set JWT_SECRET and CouchDB credentials

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
# Get custom JWT token
curl -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "test-key"}'

# Use token to query CouchDB
curl -H "Authorization: Bearer TOKEN" http://localhost:5985/_all_dbs

# Check health
curl http://localhost:5985/health

# Test Clerk JWT (use token from Clerk SDK)
curl -H "Authorization: Bearer $CLERK_TOKEN" http://localhost:5985/_all_dbs
```

## Critical Implementation Details

### Content-Type Header Fixing

CouchDB requires `Content-Type: application/json` for POST/PUT requests. PouchDB sometimes sends `text/plain`. **Solution:** Proxy always sets correct header for CouchDB endpoints.

**Code:** main.py lines 525-533

### Long-Polling Support

CouchDB `_changes?feed=longpoll` connections wait indefinitely for changes. Default 30-second timeout kills these connections. **Solution:** Detect long-polling and use 300-second timeout.

**Code:** main.py lines 546-548

### JWT Validation Fallback

Allows smooth transition between authentication methods:
- Start with Clerk only
- Later add custom JWT for testing/internal tools
- Then switch entirely to custom JWT if needed

**Code:** main.py lines 420-432

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
- ✅ `config/api_keys.json` in .gitignore
- ✅ No hardcoded defaults for secrets
- ✅ Configuration validation on startup

### Authentication

- ✅ Clerk JWT: RS256 with public key caching
- ✅ Custom JWT: HS256 with strong secret requirement
- ✅ Token expiration enforced
- ✅ Automatic fallback doesn't leak secrets

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
# Decode token at https://jwt.io
# Use JWT_SECRET as the signing key
```

### Verify CouchDB Connection
```bash
# Test direct CouchDB access (bypass proxy)
curl -u admin:password http://localhost:5984/
```

### Test Token Generation
```bash
# Custom JWT
curl -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "test-key"}'

# Clerk JWT (use Clerk SDK to get token)
const token = await Clerk.session.getToken()
```

### Inspect Proxy Logs
```bash
# On production server
sudo journalctl -u couchdb-proxy -f

# Search for errors
sudo journalctl -u couchdb-proxy | grep "401\|ERROR"
```

## Known Limitations

1. **API Key Management**: Currently static config file, could be database-backed
2. **Rate Limiting**: Not implemented, consider adding
3. **Audit Logging**: Limited to application logs
4. **Scoped Access**: All tokens have full access, could add scopes
5. **Database Quotas**: No per-database resource limits

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
- [ ] `config/api_keys.json` exists (even if empty)
- [ ] `JWT_SECRET` set for custom JWT mode
- [ ] Tests pass (`uv run pytest test_main.py`)
- [ ] Proxy starts (`uv run uvicorn main:app`)

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [PyJWT Documentation](https://pyjwt.readthedocs.io/)
- [Clerk JWT Documentation](https://clerk.com/docs/jwt/jwt-templates)
- [CouchDB Documentation](https://docs.couchdb.org/)
- [PouchDB Documentation](https://pouchdb.com/)
