# Getting Started with CouchDB JWT Proxy

This guide will help you get the CouchDB JWT Proxy running locally on your Windows machine with Docker.

## Prerequisites

- **Docker Desktop** installed and running
  - Download from: https://www.docker.com/products/docker-desktop
  - Make sure Docker is running before starting

- **Python 3.9+** installed
  - Download from: https://www.python.org
  - Add to PATH during installation

- **uv** package manager
  - Install with: `pip install uv` or `pipx install uv`
  - Or download from: https://github.com/astral-sh/uv

## Step-by-Step Setup (5 minutes)

### Step 1: Start CouchDB on Docker

Open a terminal/PowerShell and run:

```bash
docker-compose up -d
```

Or use the startup script:

```bash
./run_local_couchdb.sh
```

Or the raw docker command:

```bash
docker run -d --name couchdb -e COUCHDB_USER=admin -e COUCHDB_PASSWORD=admin -p 5984:5984 couchdb:3
```

**Verify CouchDB is running:**
```bash
curl http://localhost:5984/
```

You should see a JSON response with CouchDB version information.

### Step 2: Set Up Python Environment

In the project directory, install dependencies:

```bash
uv sync --all-extras
```

### Step 3: Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Review `.env` - it should contain:
```bash
JWT_SECRET=your-super-secret-key-change-this-in-production
COUCHDB_INTERNAL_URL=http://localhost:5984
PROXY_PORT=5985
LOG_LEVEL=INFO
```

The defaults are already correct for local Docker setup.

### Step 4: Start the Proxy

In the project directory, run:

```bash
uv run uvicorn main:app --reload --port 5985
```

You should see output like:
```
INFO:     Uvicorn running on http://0.0.0.0:5985
INFO:     Application startup complete
```

### Step 5: Test the Setup

Open another terminal and run:

**For Windows PowerShell:**
```powershell
.\test_setup.ps1
```

**For Windows Command Prompt:**
```cmd
test_setup.bat
```

**For Linux/macOS or WSL:**
```bash
./test_setup.sh
```

## Quick Manual Test

If the test scripts don't work, try manual testing:

### 1. Get a JWT Token
```bash
curl -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "test-key"}'
```

**Response:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

### 2. Check Proxy Health
```bash
curl http://localhost:5985/health
```

**Response:**
```json
{
  "status": "ok",
  "service": "couchdb-jwt-proxy",
  "couchdb": "connected"
}
```

### 3. List Databases Through Proxy

Replace `YOUR_TOKEN` with the token from step 1:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:5985/_all_dbs
```

## Architecture

```
Your Application
    ↓
Proxy (port 5985) ← Requires JWT token
    ↓
CouchDB (port 5984) ← Internal only
    ↓
Data
```

## Important Ports

- **Proxy:** http://localhost:5985 (what your app connects to)
- **CouchDB:** http://localhost:5984 (internal only, not exposed)
- **CouchDB UI:** http://localhost:5984/_utils/ (for admin access)

## Common Tasks

### Create a Database

```bash
TOKEN="your-token-here"
curl -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:5985/mydb
```

### Create a Document

```bash
TOKEN="your-token-here"
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"John","age":30}' \
  http://localhost:5985/mydb
```

### Query Documents

```bash
TOKEN="your-token-here"
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5985/mydb/_all_docs
```

## Stopping Services

### Stop the Proxy

Press `Ctrl+C` in the terminal where the proxy is running.

### Stop CouchDB

```bash
docker-compose down
```

To remove data as well:

```bash
docker-compose down -v
```

## Accessing CouchDB Admin Interface

You can access CouchDB's web UI for admin tasks:

- **URL:** http://localhost:5984/_utils/
- **Username:** admin
- **Password:** admin

## Credentials

- **CouchDB Admin:** admin/admin
- **API Key for Proxy:** test-key (defined in `config/api_keys.json`)
- **JWT Secret:** defined in `.env` file

## Troubleshooting

### "Connection refused" on port 5984
**Problem:** CouchDB is not running
**Solution:**
```bash
docker ps  # Check if container is running
docker-compose up -d  # Start CouchDB
```

### "Connection refused" on port 5985
**Problem:** Proxy is not running
**Solution:**
```bash
# In your project directory:
uv run uvicorn main:app --reload --port 5985
```

### "Invalid API key" error
**Problem:** API key "test-key" not found
**Solution:** Check `config/api_keys.json` contains "test-key"

### "Invalid or expired token"
**Problem:** Token has expired (tokens last 1 hour)
**Solution:** Get a new token with the same API key

### Can't connect to CouchDB from proxy
**Problem:** Network connectivity issue
**Solution:**
```bash
curl http://localhost:5984/  # Test CouchDB directly
# If this fails, CouchDB isn't running properly
```

## Next Steps

1. **Test with Roady PWA:** Update Roady to use proxy instead of direct CouchDB
2. **Add more API keys:** Edit `config/api_keys.json` for other clients
3. **Production setup:** See README.md for production configuration
4. **Security:** Change JWT_SECRET in `.env` for production

## File Structure

```
mycouch/
├── main.py                      # FastAPI application
├── test_main.py                 # Unit tests
├── config/
│   └── api_keys.json           # API key mappings
├── .env.example                 # Environment template
├── .env                         # Your local configuration
├── docker-compose.yml           # CouchDB Docker setup
├── run_local_couchdb.sh        # Start CouchDB script
├── test_setup.sh               # Test script (Linux/macOS/WSL)
├── test_setup.ps1              # Test script (PowerShell)
├── test_setup.bat              # Test script (CMD)
├── README.md                    # Full documentation
├── DOCKER_SETUP.md             # Docker setup guide
├── TEST_SCRIPTS.md             # Test script documentation
├── GETTING_STARTED.md          # This file
└── pyproject.toml              # Python project config
```

## Getting Help

- See [README.md](README.md) for full API documentation
- See [DOCKER_SETUP.md](DOCKER_SETUP.md) for Docker-specific help
- See [TEST_SCRIPTS.md](TEST_SCRIPTS.md) for testing help
- Check test scripts for detailed examples

## Success Checklist

- [ ] Docker is installed and running
- [ ] CouchDB container is running on port 5984
- [ ] `uv sync --all-extras` completed successfully
- [ ] `.env` file is configured
- [ ] Proxy starts without errors on port 5985
- [ ] Health check returns "ok" status
- [ ] Can get JWT token with API key
- [ ] Can list databases through proxy
- [ ] Tests pass successfully

Once you've completed all items, your proxy is ready to use!
