# Local CouchDB Setup with Docker

This guide shows how to run CouchDB locally in Docker for development.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop) installed and running
- Or Docker and Docker Compose installed on Linux

## Quick Start

### 1. Start CouchDB Container

Option A: Using docker-compose (recommended):
```bash
docker-compose up -d
```

Option B: Using docker directly:
```bash
docker run -d \
  --name couchdb \
  -p 5984:5984 \
  -e COUCHDB_USER=admin \
  -e COUCHDB_PASSWORD=admin \
  couchdb:3
```

### 2. Verify CouchDB is Running

```bash
curl http://localhost:5984/
```

Should return:
```json
{
  "couchdb": "Welcome",
  "version": "3.3.0",
  ...
}
```

### 3. Setup Proxy

```bash
# Install uv
pip install uv

# Install proxy dependencies
uv sync --all-extras

# Copy environment
cp .env.example .env

# .env already has correct settings for local Docker CouchDB
# (COUCHDB_INTERNAL_URL=http://localhost:5984, PROXY_PORT=5985)
```

### 4. Start the Proxy

```bash
# Development mode with auto-reload
uv run uvicorn main:app --reload --port 5985
```

Proxy runs on: **http://localhost:5985**
CouchDB runs on: **http://localhost:5984** (internal)

## Testing

### 1. Get a JWT Token

```bash
curl -X POST http://localhost:5985/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "test-key"}'
```

Response:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

### 2. Check Health

```bash
curl http://localhost:5985/health
```

Response:
```json
{
  "status": "ok",
  "service": "couchdb-jwt-proxy",
  "couchdb": "connected"
}
```

### 3. List Databases Through Proxy

```bash
TOKEN="your-token-here"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5985/_all_dbs
```

### 4. Create a Database Through Proxy

```bash
TOKEN="your-token-here"
curl -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:5985/testdb
```

### 5. Access CouchDB Fauxton UI

You can also access CouchDB's web UI directly:
- **URL:** http://localhost:5984/_utils/
- **Username:** admin
- **Password:** admin

## Docker Commands

### View CouchDB Logs
```bash
docker logs -f mycouch-couchdb
```

### Stop CouchDB
```bash
docker-compose down
```

### Stop and Remove Data
```bash
docker-compose down -v
```

### Restart CouchDB
```bash
docker-compose restart
```

## Environment Variables for CouchDB

The docker-compose.yml configures:
- **COUCHDB_USER:** admin
- **COUCHDB_PASSWORD:** admin

To change these, edit `docker-compose.yml` and restart:
```bash
docker-compose down
docker-compose up -d
```

## Accessing CouchDB

### From Proxy (JWT required)
- **URL:** http://localhost:5985 (with Bearer token)
- **Auth:** JWT token in Authorization header

### Directly (admin credentials)
- **URL:** http://localhost:5984 (no token needed)
- **Auth:** admin/admin
- **UI:** http://localhost:5984/_utils/

## Troubleshooting

### "Connection refused" Error
- Check if Docker is running: `docker ps`
- Check if container is running: `docker-compose ps`
- Verify port 5984 is not in use: `netstat -an | grep 5984`

### "Port 5984 already in use"
- Change the port in docker-compose.yml: `"5985:5984"`
- Then update `COUCHDB_INTERNAL_URL` in `.env`

### "CouchDB unavailable" from Health Check
- Check container logs: `docker logs mycouch-couchdb`
- Verify container is healthy: `docker-compose ps`
- Give it a few seconds to start: `sleep 5` then test again

### Cannot login to Fauxton UI
- Default credentials are: `admin` / `admin`
- Check docker-compose.yml for correct credentials

## Network Access

By default, CouchDB is accessible from:
- **Local machine:** localhost:5984 or 127.0.0.1:5984
- **Other machines on network:** {your-ip}:5984
- **Docker containers:** localhost:5984 or host.docker.internal:5984 (Mac/Windows)

To restrict access, change the port binding in docker-compose.yml from `"5984:5984"` to `"127.0.0.1:5984:5984"`

## Next Steps

1. Create test databases through the proxy
2. Add documents via proxy API
3. Query documents with CouchDB API
4. Experiment with JWT token expiration
5. Test with your Roady PWA frontend

See [README.md](README.md) for full proxy documentation.
