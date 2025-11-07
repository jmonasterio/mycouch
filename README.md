# CouchDB JWT Proxy

A secure HTTP proxy for CouchDB that provides Clerk JWT-based authentication (RS256) and optional multi-tenant data isolation. Perfect for offline-first applications like Roady PWA.

## Features

**Authentication & Security**
- ✅ **Clerk JWT validation** (RS256) - Enterprise auth with public key cryptography
- ✅ Cached JWKS endpoint for performance
- ✅ CORS support for browser clients
- ✅ Secure configuration validation on startup

**Proxy Features**
- ✅ Request forwarding to internal CouchDB
- ✅ Full HTTP method support (GET, POST, PUT, DELETE, HEAD, COPY, PATCH)
- ✅ Long-polling support for CouchDB `_changes` feed (for real-time sync)
- ✅ Automatic Content-Type header fixing (ensures CouchDB compatibility)
- ✅ Health check endpoint with CouchDB connectivity verification
- ✅ Comprehensive logging with DEBUG/INFO/WARNING levels

**Multi-Tenant Support** (Optional)
- ✅ Per-tenant data isolation
- ✅ Automatic tenant injection in documents
- ✅ Query rewriting for tenant filtering
- ✅ Response filtering to prevent cross-tenant access
- ✅ Configurable tenant claim and field names
- ✅ Can be enabled/disabled via environment variable

## Quick Start (Local Development)

### Prerequisites

- Python 3.9 or higher
- [uv](https://github.com/astral-sh/uv) package manager (install with `pip install uv` or `pipx install uv`)
- [Docker Desktop](https://www.docker.com/products/docker-desktop) for local CouchDB

### 5-Minute Local Setup

```bash
# 1. Start local CouchDB in Docker
# Option A: Using docker-compose
docker-compose up -d

# Option B: Using the script (Linux/macOS)
./run_local_couchdb.sh

# Option C: Using the raw docker command
docker run -d --name couchdb -e COUCHDB_USER=admin -e COUCHDB_PASSWORD=admin -p 5984:5984 couchdb:3

# 2. Install proxy
uv sync --all-extras

# 3. Copy environment (already configured for local Docker)
cp .env.example .env

# 4. Configure Clerk in .env
# Edit .env and set: CLERK_ISSUER_URL=https://your-instance.clerk.accounts.dev

# 5. Start proxy (runs on http://localhost:5985)
PYTHONPATH=src uv run uvicorn couchdb_jwt_proxy.main:app --reload --port 5985

# 6. Get a token from Clerk (in your app)
# const token = await window.Clerk.session.getToken();

# 7. Use token to access CouchDB through proxy
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:5985/_all_dbs
```

**Note:** You need a Clerk account and configured Clerk issuer URL. See [CLERK_SETUP.md](CLERK_SETUP.md) for details.

CouchDB credentials (for direct access, bypass proxy): **admin** / **admin**

See [DOCKER_SETUP.md](DOCKER_SETUP.md) for detailed Docker setup and testing instructions.

## Installation

#### Linux/macOS

```bash
# Install dependencies
make install

# Or for development (includes test dependencies)
make dev
```

#### Windows (PowerShell)

```powershell
# Install dependencies
.\run.ps1 install

# Or for development
.\run.ps1 dev
```

#### Windows (CMD)

```cmd
:: Install dependencies
run.bat install

:: Or for development
run.bat dev
```

#### Manual with uv

```bash
uv sync              # Install dependencies
uv sync --all-extras # Install with dev dependencies
```

### Configuration

1. Copy environment template:

```bash
# Linux/macOS
make env-setup

# Windows PowerShell
.\run.ps1 env-setup

# Windows CMD
run.bat env-setup

# Manual
cp .env.example .env
```

2. Update `.env` with your settings:

```bash
# Required: Your Clerk issuer URL
CLERK_ISSUER_URL=https://your-clerk-instance.clerk.accounts.dev

# CouchDB configuration
COUCHDB_INTERNAL_URL=http://localhost:5984
COUCHDB_USER=admin
COUCHDB_PASSWORD=your-password

# Proxy configuration
PROXY_HOST=0.0.0.0
PROXY_PORT=5985
```

3. (Optional) Enable tenant mode for multi-tenant deployments:

**Edit `.env` and add:**
```bash
# Enable multi-tenant data isolation
ENABLE_TENANT_MODE=true

# JWT claim name for tenant ID (default: tenant_id)
TENANT_CLAIM=tenant_id

# Document field name for tenant ID (default: tenant_id)
TENANT_FIELD=tenant_id
```

When tenant mode is enabled:
- Proxy validates tenant from JWT claims
- Injects `tenant_id` into all documents
- Filters queries to only return tenant's documents
- Prevents cross-tenant data access
- Rejects disallowed endpoints with 403

### Running the Proxy

#### Linux/macOS (Make)

```bash
# Production mode
make run

# Development mode (auto-reload)
make dev-run
```

#### Windows (PowerShell)

```powershell
# Production mode
.\run.ps1 run

# Development mode (auto-reload)
.\run.ps1 dev-run
```

#### Windows (CMD)

```cmd
# Production mode
run.bat run

# Development mode (auto-reload)
run.bat dev-run
```

#### Manual with uv

```bash
# Production mode
uv run python main.py

# Development mode (auto-reload)
PYTHONPATH=src uv run uvicorn couchdb_jwt_proxy.main:app --reload --port 5985
```

## Usage

### Getting a JWT Token

```javascript
// Use Clerk SDK to get token
const token = await window.Clerk.session.getToken();
// Include in requests: Authorization: Bearer <token>
```

### Using Token to Access CouchDB

All requests go through the proxy on port 5985:

List all databases:
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:5985/_all_dbs
```

Create a database:
```bash
curl -X PUT \
  -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:5985/mydb
```

Query documents:
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:5985/mydb/_all_docs
```

Create a document:
```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "John", "age": 30}' \
  http://localhost:5985/mydb
```

## Architecture

```
Client (Roady PWA, etc.)
  ↓
Proxy (port 5985)
├── GET/POST/PUT/DELETE /* → Validate Clerk JWT → Forward to CouchDB
├── GET /health             → Health check endpoint
└── CouchDB (port 5984, internal) → Not directly exposed to clients
```

**Authentication Flow:**
```
Client Request with Clerk Bearer Token
  ↓
Validate Clerk JWT (RS256)
  ├─ If valid → Forward to CouchDB
  └─ If invalid → Return 401 Unauthorized
```

## Multi-Tenant Mode (Optional)

When `ENABLE_TENANT_MODE=true`, the proxy enforces per-tenant data isolation:

### How It Works

1. **JWT contains tenant ID** - Each JWT includes a `tenant_id` claim
2. **Automatic injection** - Proxy injects `tenant_id` into all documents created/updated
3. **Query rewriting** - Proxy rewrites `/_find` and `/_all_docs` to filter by tenant
4. **Response filtering** - Results are filtered to only show tenant's documents
5. **Endpoint restrictions** - Some endpoints are blocked to prevent data leakage

### Supported Operations in Tenant Mode

| Operation | Method | Behavior |
|-----------|--------|----------|
| List all documents | GET `/_all_docs` | Filtered by tenant |
| Find documents | POST `/_find` | Tenant filter auto-injected |
| Create/update doc | PUT `/docid` | `tenant_id` auto-injected |
| Bulk operations | POST `/_bulk_docs` | `tenant_id` auto-injected |
| Get single doc | GET `/docid` | Validated to match tenant |
| Delete doc | DELETE `/docid` | Validated to match tenant |
| Changes feed | GET/POST `/_changes` | Filtered by tenant |
| Other endpoints | any | Returns 403 Forbidden |

### Example: Creating a Tenant-Isolated Document

With `ENABLE_TENANT_MODE=true`:

```bash
# Tenant "company-a" creates a document
TOKEN="jwt-token-with-tenant_id-claim"
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Task 1","status":"open"}' \
  http://localhost:5984/tasks

# Proxy automatically adds tenant_id before storing:
# {"_id":"..","name":"Task 1","status":"open","tenant_id":"company-a"}

# Tenant "company-b" querying _all_docs only sees their docs
# Tenant "company-a" cannot see company-b's documents
```

### Security Guarantees

- ✅ Tenants cannot access other tenants' documents
- ✅ Tenants cannot enumerate other tenants' databases
- ✅ `tenant_id` field cannot be modified by clients (proxy enforces)
- ✅ System endpoints blocked to prevent bypass

## Environment Variables

### Required
| Variable | Description |
|----------|-------------|
| `CLERK_ISSUER_URL` | **REQUIRED** - Clerk issuer URL for JWT validation (e.g., `https://your-instance.clerk.accounts.dev`) |
| `COUCHDB_INTERNAL_URL` | Internal CouchDB URL (default: `http://localhost:5984`) |

### Optional
| Variable | Default | Description |
|----------|---------|-------------|
| `COUCHDB_USER` | `` | CouchDB username for proxy authentication |
| `COUCHDB_PASSWORD` | `` | CouchDB password for proxy authentication |
| `PROXY_HOST` | `0.0.0.0` | IP address to listen on (0.0.0.0 = all interfaces) |
| `PROXY_PORT` | `5985` | Port to run proxy on |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |

### Multi-Tenant Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_TENANT_MODE` | `false` | Enable multi-tenant data isolation |
| `TENANT_CLAIM` | `tenant_id` | JWT claim name that contains tenant ID |
| `TENANT_FIELD` | `tenant_id` | CouchDB document field name for tenant ID |

## API Reference

### Authentication

**Clerk JWT Authentication**
- Token generated by Clerk
- Use Clerk SDK in your application to get token: `await Clerk.session.getToken()`
- Include in request: `Authorization: Bearer <clerk-token>`
- Proxy validates using Clerk's JWKS endpoint (RS256)

### CouchDB Proxy
**Any HTTP method to /***

Request Headers:
```
Authorization: Bearer <jwt_token>
```

Behavior:
- Validates JWT
- Forwards request to internal CouchDB
- Returns CouchDB response directly

### Health Check
**GET /health**

Checks proxy and CouchDB connectivity. No authentication required.

Response (healthy):
```json
{
  "status": "ok",
  "service": "couchdb-jwt-proxy",
  "couchdb": "connected"
}
```

Response (degraded - CouchDB error):
```json
{
  "status": "degraded",
  "service": "couchdb-jwt-proxy",
  "couchdb": "error"
}
```

Response (error - CouchDB unavailable):
```json
{
  "status": "error",
  "service": "couchdb-jwt-proxy",
  "couchdb": "unavailable"
}
```

## Security Notes

- 🔐 **Clerk JWT**: RS256 keys are fetched from Clerk's JWKS endpoint (cached for performance)
- 🔐 **Public Key Crypto**: No shared secrets - authentication uses public/private key pairs
- ⚠️ **HTTPS**: Use HTTPS in production to protect JWTs in transit
- ⚠️ **CouchDB Port**: Keep port 5984 internal only - not exposed to clients
- ⚠️ **Logging**: DEBUG logs contain sensitive info - use INFO level in production
- ⚠️ **Tenants**: When using multi-tenant mode, validate tenant claims on every request

## Testing

### Unit Tests

#### Linux/macOS (Make)
```bash
# Run all tests
make test

# Run with coverage report
make test-cov
```

#### Windows (PowerShell)
```powershell
# Run all tests
.\run.ps1 test

# Run with coverage report
.\run.ps1 test-cov
```

#### Windows (CMD)
```cmd
# Run all tests
run.bat test

# Run with coverage report
run.bat test-cov
```

#### Manual with uv
```bash
# Run all tests
uv run pytest tests -v

# Run with coverage report
uv run pytest tests -v --cov=couchdb_jwt_proxy --cov-report=html
```

### Manual Integration Testing

1. Start local CouchDB in Docker:
   ```bash
   docker-compose up -d
   ```

2. Start proxy:
   ```bash
   make dev-run  # or .\run.ps1 dev-run on Windows
   ```
3. Get token from Clerk:
   ```javascript
   // In your app with Clerk SDK
   const token = await window.Clerk.session.getToken();
   ```
4. Test proxying:
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:5985/_all_dbs
   ```

## Troubleshooting

### "CouchDB server unavailable"
- Check CouchDB is running on port 5984
- Verify `COUCHDB_INTERNAL_URL` is correct in `.env`
- Verify `COUCHDB_USER` and `COUCHDB_PASSWORD` if CouchDB requires auth

### "Invalid or expired token"
- Tokens expire based on Clerk configuration (check Clerk dashboard)
- Get a fresh token from Clerk: `await Clerk.session.getToken()`
- Check token is in `Authorization: Bearer <token>` format

### "Missing authorization header"
- Include `Authorization: Bearer <token>` in request headers
- Request format: `-H "Authorization: Bearer YOUR_TOKEN"`

### "401 Unauthorized - Clerk JWT validation failed"
- Verify `CLERK_ISSUER_URL` is correct in `.env` (check Clerk dashboard)
- Verify user is signed in with Clerk
- Check Clerk JWKS endpoint is accessible: `curl https://your-issuer/.well-known/jwks.json`

## Future Enhancements

- [ ] Token refresh endpoint
- [ ] Scoped access control
- [ ] Rate limiting
- [ ] Audit logging
- [ ] Database-specific access control

## Integration with Roady PWA

This proxy is designed to work with the Roady PWA (offline-first band management app).

### How It Works Together

1. **Roady PWA** runs offline, storing data in PouchDB (browser IndexedDB)
2. **User logs in** with Clerk authentication
3. **Roady PWA gets JWT token** from Clerk: `await Clerk.session.getToken()`
4. **Roady PWA syncs** with CouchDB through this proxy: `PouchDB.sync(remoteUrl, {live: true})`
5. **Proxy validates** the Clerk JWT on every sync request
6. **Multi-tenant** data isolation keeps each band's data separate

See `../../roady/js/db.js` for the PouchDB sync implementation.

## Development

### Project Structure
```
mycouch/
├── main.py                           # FastAPI proxy application
├── test_main.py                      # Unit tests
├── pyproject.toml                    # Project dependencies
├── .env                              # Configuration (local only, in .gitignore)
├── .env.example                      # Configuration template
├── .gitignore                        # Git ignore rules
├── .github/
│   └── workflows/
│       └── deploy-proxy.yml         # GitHub Actions deployment
├── Documentation/
│   ├── README.md                    # This file
│   ├── CLERK_SETUP.md               # Clerk JWT integration
│   ├── LINUX_DEPLOYMENT_PROXY.md    # Linux server deployment
│   ├── GITHUB_ACTIONS_DEPLOY.md     # GitHub Actions setup
│   ├── SECURITY_CHECKLIST.md        # Security requirements
│   ├── TENANT_DETERMINATION.md      # Tenant isolation explained
│   └── ... other guides
```

### Dependencies
- **FastAPI**: Modern web framework
- **Uvicorn**: ASGI server
- **PyJWT**: JWT signing/verification
- **httpx**: Async HTTP client
- **python-dotenv**: Environment variables
- **pytest**: Testing framework
- **pytest-asyncio**: Async test support
- **pytest-cov**: Coverage reporting

### Using uv

See [UV_SETUP.md](UV_SETUP.md) for detailed uv setup instructions.

Quick start:
```bash
# Install uv
pip install uv

# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest tests -v

# Start development server
PYTHONPATH=src uv run uvicorn couchdb_jwt_proxy.main:app --reload --port 5985
```

## License

MIT
