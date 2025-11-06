# Testing Scripts

This directory includes scripts to help you test your CouchDB JWT Proxy setup.

## Available Scripts

### 1. `run_local_couchdb.sh` (Linux/macOS)
Starts a local CouchDB container using Docker.

```bash
./run_local_couchdb.sh
```

**What it does:**
- Starts CouchDB container with admin/admin credentials
- Waits for CouchDB to be ready
- Verifies connectivity
- Prints connection info

### 2. `test_setup.sh` (Linux/macOS)
Comprehensive end-to-end test of the entire proxy setup.

```bash
./test_setup.sh
```

**Tests performed:**
1. ✓ CouchDB connectivity
2. ✓ Proxy connectivity
3. ✓ Health check endpoint
4. ✓ JWT token generation
5. ✓ Database creation through proxy
6. ✓ Document creation
7. ✓ Document queries
8. ✓ Database listing
9. ✓ Invalid token rejection
10. ✓ Missing auth rejection
11. ✓ Cleanup (removes test database)

**Requirements:**
- `curl` installed
- `grep`, `sed`, and standard bash tools
- Proxy running on port 5985
- CouchDB running on port 5984

### 3. `test_setup.ps1` (Windows PowerShell)
PowerShell equivalent of `test_setup.sh` with full functionality.

```powershell
.\test_setup.ps1
```

**Same tests as `test_setup.sh` but using PowerShell native commands**

**Requirements:**
- PowerShell 5.0+ (or PowerShell Core)
- Proxy running on port 5985
- CouchDB running on port 5984

### 4. `test_setup.bat` (Windows CMD)
Basic test script for Windows Command Prompt.

```cmd
test_setup.bat
```

**Note:** Limited functionality compared to .ps1 and .sh versions due to cmd.exe limitations. For full testing on Windows, use PowerShell or WSL.

## Quick Test Workflow

### Linux/macOS with Docker Compose

```bash
# Terminal 1: Start CouchDB
docker-compose up -d

# Terminal 1: Wait a moment, then start proxy
uv run uvicorn main:app --reload --port 5985

# Terminal 2: Run tests
./test_setup.sh
```

### Linux/macOS with Script

```bash
# Terminal 1: Start CouchDB with script
./run_local_couchdb.sh

# Terminal 1: Wait a moment, then start proxy
uv run uvicorn main:app --reload --port 5985

# Terminal 2: Run tests
./test_setup.sh
```

### Windows with Docker Desktop and PowerShell

```powershell
# Terminal 1: Start CouchDB
docker-compose up -d

# Terminal 1: Wait 10 seconds, then start proxy
uv run uvicorn main:app --reload --port 5985

# Terminal 2: Run tests
.\test_setup.ps1
```

### Windows with WSL

```bash
# In WSL terminal
# Terminal 1: Start CouchDB (from WSL or Windows)
docker-compose up -d

# Terminal 1: Start proxy
uv run uvicorn main:app --reload --port 5985

# Terminal 2: Run tests
./test_setup.sh
```

## Manual Testing with curl

If you prefer manual testing or don't have bash/PowerShell available:

### 1. Check CouchDB
```bash
curl http://localhost:5984/
```

### 2. Get a JWT Token
```bash
curl -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "test-key"}'
```

### 3. Check Proxy Health
```bash
curl http://localhost:5985/health
```

### 4. List Databases Through Proxy
```bash
TOKEN="your-token-from-step-2"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5985/_all_dbs
```

### 5. Create a Database
```bash
TOKEN="your-token"
curl -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:5985/mydb
```

### 6. Create a Document
```bash
TOKEN="your-token"
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"John","age":30}' \
  http://localhost:5985/mydb
```

## Troubleshooting

### "Connection refused" on port 5984
- CouchDB is not running
- Fix: Run `docker-compose up -d`

### "Connection refused" on port 5985
- Proxy is not running
- Fix: Run `uv run uvicorn main:app --reload --port 5985`

### "Invalid API key" response
- API key "test-key" is not in `config/api_keys.json`
- Fix: Check `config/api_keys.json` and add "test-key" if needed

### JWT token expiration
- Tokens expire after 1 hour
- Fix: Get a new token with the same API key

### Tests pass but can't create documents
- Check CouchDB permissions with admin/admin credentials
- Access Fauxton UI at http://localhost:5984/_utils/

## What Each Test Script Tests

| Feature | test_setup.sh | test_setup.ps1 | test_setup.bat |
|---------|---|---|---|
| CouchDB connectivity | ✓ | ✓ | ✓ |
| Proxy connectivity | ✓ | ✓ | ✓ |
| Health check | ✓ | ✓ | ~ |
| JWT token generation | ✓ | ✓ | ~ |
| Database creation | ✓ | ✓ | - |
| Document creation | ✓ | ✓ | - |
| Document queries | ✓ | ✓ | - |
| Auth rejection | ✓ | ✓ | - |
| Cleanup | ✓ | ✓ | - |

Legend: ✓ = Full support, ~ = Basic support, - = Not supported

## Integration with Roady PWA

Once all tests pass, you can test Roady PWA integration:

1. Update `roady/js/db.js` to use proxy URL instead of direct CouchDB
2. Configure API key in Roady frontend
3. Test data sync through proxy with JWT auth

See [../README.md](../README.md) and [DOCKER_SETUP.md](DOCKER_SETUP.md) for more details.
