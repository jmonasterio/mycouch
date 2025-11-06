# CouchDB JWT Proxy - PRD

## Overview

Build a Python-based HTTP proxy that sits in front of CouchDB, providing JWT-based authentication and request forwarding. This allows secure access to CouchDB with token-based authentication instead of exposing the database directly.

## Problem Statement

CouchDB doesn't have built-in JWT support. We need a proxy that:
1. Issues JWTs to authenticated clients (via API key)
2. Validates JWTs on CouchDB requests
3. Forwards validated requests to the actual CouchDB instance
4. Keeps CouchDB hidden behind the proxy on internal port (5983)

## Architecture

```
Client
  ↓
Proxy (port 5984)
├── POST /auth/token          → Generate JWT from API key
├── GET/POST/PUT/DELETE /* → Validate JWT → Forward to CouchDB (5983)
└── CouchDB (port 5983)
```

## API Specification

### 1. Token Generation Endpoint

**Endpoint:** `POST /auth/token`

**Authentication:** None required

**Request Body:**
```json
{
  "api_key": "my-secret-key"
}
```

**Success Response (200):**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**Error Response (401):**
```json
{
  "detail": "Invalid API key"
}
```

### 2. CouchDB Proxy Endpoint

**Endpoint:** Any request to `/*` (excluding `/auth/*`)

**Authentication:** Required - Bearer token in Authorization header

**Request Example:**
```bash
curl -H "Authorization: Bearer <jwt_token>" http://localhost:5984/_all_dbs
```

**Behavior:**
- Validates JWT token from Authorization header
- Forwards request to internal CouchDB at `http://localhost:5983/<path>`
- Returns CouchDB response directly to client
- Returns 401 if no token or invalid token

## JWT Token Structure

**Claims:**
```javascript
{
  "sub": "client-id",           // Subject: identifies the API key user
  "iat": 1234567890,            // Issued at timestamp
  "exp": 1234571490,            // Expiration timestamp (iat + 3600)
  "scope": ""                   // Scope (reserved for future use)
}
```

**Signing:**
- Algorithm: HS256 (HMAC with SHA-256)
- Secret: `JWT_SECRET` environment variable
- No external key rotation in MVP

## Configuration

### Environment Variables

```bash
JWT_SECRET=your-super-secret-key-change-this
COUCHDB_INTERNAL_URL=http://localhost:5983
PROXY_PORT=5984
```

### API Keys Configuration

File: `config/api_keys.json`
```json
{
  "api_key_1": "client-a",
  "api_key_2": "client-b",
  "test-key": "test-client"
}
```

## Security Considerations

### JWT Signing
- Uses HS256 with shared secret (symmetric)
- Secret must be kept secure in environment
- Eventually: consider RS256 for key rotation

### API Key Storage
- Stored in config file (MVP)
- Never transmitted after initial setup
- No logging of keys
- Future: vault/secrets management

### Token Expiration
- All tokens expire in 1 hour
- No token refresh endpoint (MVP)
- Client must re-authenticate to get new token

### CouchDB Isolation
- Internal CouchDB runs on port 5983 (not exposed)
- Only accessible through proxy
- All traffic passes through JWT validation

## Endpoints & Methods

All HTTP methods are proxied:
- GET: Query databases, documents
- POST: Create documents, use _find, _explain
- PUT: Update documents
- DELETE: Delete documents
- HEAD: Check existence
- COPY: Copy documents (if CouchDB supports)

## Error Handling

| Scenario | HTTP Code | Response |
|----------|-----------|----------|
| Invalid/missing JWT | 401 | `{"detail": "Invalid token"}` |
| Expired JWT | 401 | `{"detail": "Token expired"}` |
| Invalid API key | 401 | `{"detail": "Invalid API key"}` |
| CouchDB error | varies | CouchDB error response |
| Invalid request | 400 | CouchDB error response |

## Deployment

### Development
```bash
python -m uvicorn main:app --reload --port 5984
```

### Production
```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:5984 main:app
```

## Testing Checklist

- [ ] POST /auth/token with valid API key returns JWT
- [ ] POST /auth/token with invalid API key returns 401
- [ ] GET request without token returns 401
- [ ] GET request with invalid token returns 401
- [ ] GET request with valid token proxies to CouchDB
- [ ] CouchDB response passed through correctly
- [ ] Expired token (manually set) returns 401
- [ ] All HTTP methods (GET, POST, PUT, DELETE) proxy correctly

## Future Enhancements

### Phase 2: Scopes
- Add `scope` claim to JWT
- Support read-only vs read-write access
- Database-specific scopes

### Phase 3: Audit & Logging
- Log all API key usage
- Log failed authentication attempts
- Log CouchDB operations (with scope)

### Phase 4: Advanced Auth
- Token refresh/rotation endpoint
- API key expiration
- Client credentials flow
- User management UI

### Phase 5: Rate Limiting
- Per-client rate limits
- Per-endpoint rate limits
- Token bucket algorithm

## Implementation Notes

- Use FastAPI for async performance
- Use `httpx` for async HTTP proxying to CouchDB
- Use `PyJWT` for token generation/validation
- Middleware for JWT validation on protected routes
- Keep config simple (JSON files in MVP)
