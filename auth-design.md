# Authentication and Tenant Management Design

This document describes the comprehensive authentication and tenant management system implemented in the mycouch JWT proxy.

## Overview

The mycouch JWT proxy provides automatic user and tenant management for multi-tenant CouchDB applications. It seamlessly integrates with Clerk authentication while ensuring complete data isolation between tenants.

## Architecture

```
┌─────────────┐    JWT    ┌──────────────┐    Lookup    ┌─────────────────┐
│   Client    │ ────────> │ JWT Proxy    │ ───────────> │ User Cache      │
│ (Clerk App) │           │              │             │ (In-Memory)     │
└─────────────┘           └──────────────┘             └─────────────────┘
                                  │                             │
                                  │ Cache Miss                  │ Cache Hit
                                  ▼                             ▼
                         ┌──────────────┐              ┌──────────────┐
                         │ Couch-Sitter │              │ Return       │
                         │ Database     │              │ Tenant ID    │
                         └──────────────┘              └──────────────┘
```

## Key Components

### 1. JWT Proxy (`main.py`)
- **Function**: Authenticates requests and enforces tenant isolation
- **Features**:
  - Clerk JWT validation (RS256)
  - Automatic user/tenant creation
  - Tenant injection in all CouchDB operations
  - Response filtering for tenant data
  - Database-driven application management
  - Startup application initialization

### 2. Application Management
- **Function**: Manages application configurations stored in database
- **Features**:
  - Automatic creation of default applications at startup
  - Loading of all applications from couch-sitter database
  - In-memory caching for fast runtime access
  - Fallback to hardcoded defaults if database unavailable

### 3. User Tenant Cache (`user_tenant_cache.py`)
- **Function**: In-memory caching of user and tenant information
- **Features**:
  - Thread-safe operations with RLock
  - TTL (Time-To-Live) support (default: 5 minutes)
  - Automatic cleanup of expired entries
  - Performance optimization to reduce database queries

### 4. Couch-Sitter Service (`couch_sitter_service.py`)
- **Function**: Database operations for user and tenant management
- **Features**:
  - Automatic user creation with personal tenant
  - Tenant recovery for existing users
  - Error handling and cleanup
  - Integration with cache layer

## Data Flow

### New User First Access

1. **Client Request**: Client sends JWT with `sub` claim to protected endpoint
2. **JWT Validation**: Proxy validates JWT signature and extracts claims
3. **Cache Lookup**: Checks if user exists in memory cache
4. **Database Lookup**: Queries couch-sitter database for user document
5. **User Creation**: Creates new user and personal tenant documents
6. **Cache Storage**: Stores user/tenant info in cache
7. **Tenant Injection**: Injects tenant ID into CouchDB request
8. **Response**: Returns proxied response with tenant-isolated data

### Existing User Access

1. **Client Request**: Client sends JWT to protected endpoint
2. **JWT Validation**: Validates JWT and extracts claims
3. **Cache Hit**: Returns tenant ID from cache (fast path)
4. **Tenant Injection**: Injects tenant ID into request
5. **Response**: Returns tenant-isolated response

### Cache Refresh

1. **TTL Expiration**: Cache entries expire after 5 minutes
2. **Database Refresh**: Next request triggers database lookup
3. **Cache Update**: Fresh data stored in cache
4. **Continue**: Normal processing with updated data

## Database Schema

### Application Document
```json
{
  "_id": "app_https_desired_lab_27_clerk_accounts_dev",
  "type": "app",
  "issuer": "https://desired-lab-27.clerk.accounts.dev",
  "name": "roady",
  "databaseNames": ["roady"],
  "createdAt": "2025-01-08T12:00:00Z",
  "updatedAt": "2025-01-08T12:00:00Z",
  "metadata": {
    "autoCreated": true,
    "createdBy": "jwt_proxy_startup"
  }
}
```

### User Document
```json
{
  "_id": "user_<sub_hash>",
  "type": "user",
  "sub": "user_<clerk_sub>",
  "email": "user@example.com",
  "name": "User Name",
  "personalTenantId": "tenant_<uuid>",
  "tenantIds": ["tenant_<uuid>"],
  "createdAt": "2025-01-08T12:00:00Z",
  "updatedAt": "2025-01-08T12:00:00Z"
}
```

### Personal Tenant Document
```json
{
  "_id": "tenant_<uuid>",
  "type": "tenant",
  "name": "User's Personal Tenant",
  "appId": "roady",
  "isPersonal": true,
  "userId": "user_<sub_hash>",
  "userIds": ["user_<sub_hash>"],
  "createdAt": "2025-01-08T12:00:00Z",
  "metadata": {
    "createdBy": "user_<clerk_sub>",
    "autoCreated": true,
    "originalSub": "user_<clerk_sub>"
  }
}
```

## Configuration

### Environment Variables

```bash
# CouchDB Configuration
COUCHDB_INTERNAL_URL=http://localhost:5984
COUCHDB_USER=admin
COUCHDB_PASSWORD=your_secure_password

# Couch-Sitter Database
COUCH_SITTER_DB_URL=http://localhost:5984/couch-sitter
USER_CACHE_TTL_SECONDS=300

# Clerk Authentication
CLERK_ISSUER_URL=https://your-app.clerk.accounts.dev

# Tenant Configuration
TENANT_FIELD=tenant_id

# Proxy Configuration
PROXY_HOST=0.0.0.0
PROXY_PORT=5985
LOG_LEVEL=INFO
```

### Application Management

The proxy now uses database-driven application management instead of hardcoded configuration.

#### Startup Application Initialization

1. **Default Applications**: The proxy starts with default applications defined in code
2. **Database Creation**: On startup, default applications are created in the couch-sitter database if they don't exist
3. **Database Loading**: All applications are loaded from the database into memory
4. **Fallback**: If database loading fails, the proxy falls back to default configuration

#### Application Document Structure

Applications are stored as `type="app"` documents in the couch-sitter database:

```json
{
  "_id": "app_https_your_app_clerk_accounts_dev",
  "type": "app",
  "issuer": "https://your-app.clerk.accounts.dev",
  "name": "your_database",
  "databaseNames": ["your_database"],
  "createdAt": "2025-01-08T12:00:00Z",
  "updatedAt": "2025-01-08T12:00:00Z"
}
```

#### Runtime Application Access

- **In-Memory Map`: Applications are stored in `APPLICATIONS` dictionary for fast access
- **No Database Queries**: After startup, no database queries are needed for application lookups
- **Dynamic Updates**: To add new applications, add documents to the database and restart the proxy

#### Default Applications

The proxy includes these default applications that are auto-created:

```python
DEFAULT_APPLICATIONS = {
    "https://desired-lab-27.clerk.accounts.dev": ["roady"],
    "https://clerk.jmonasterio.github.io": ["roady"],
    "https://enabled-hawk-56.clerk.accounts.dev": ["couch-sitter"],
}
```

## Security Features

### 1. Complete Tenant Isolation
- All documents automatically include `tenant_id` field
- Query parameters rewritten to filter by tenant
- Responses filtered to remove cross-tenant data
- No possibility of data leakage between tenants

### 2. Automatic User Management
- Users created automatically on first access
- Personal tenant assigned to every user
- No manual user provisioning required
- Graceful handling of missing data

### 3. Caching and Performance
- In-memory cache reduces database load
- TTL ensures data freshness
- Thread-safe operations
- Cache statistics and monitoring

### 4. Error Handling
- Comprehensive error logging
- Automatic cleanup on failures
- Graceful degradation for missing tenants
- Detailed error responses

## API Endpoints

### Public Endpoints (No Authentication)
- `GET /` - CouchDB welcome message
- `GET /health` - Health check endpoint

### Authenticated Endpoints (JWT Required)
- `GET /{database}/*` - All CouchDB operations with tenant isolation
- `POST /{database}/*` - All CouchDB operations with tenant isolation
- `PUT /{database}/*` - All CouchDB operations with tenant isolation
- `DELETE /{database}/*` - All CouchDB operations with tenant isolation

### Special Endpoints
- `GET /_changes` - Changes feed for user's personal tenant
- `POST /_find` - Database queries with tenant filtering
- `GET /_all_docs` - Document listing with tenant filtering

## Tenant Enforcement

### Request Processing
1. **JWT Validation**: Verify token signature and extract claims
2. **User Lookup**: Find or create user in couch-sitter database
3. **Tenant Resolution**: Get user's personal tenant ID
4. **Request Injection**: Add tenant ID to CouchDB requests
5. **Query Rewriting**: Modify queries to filter by tenant
6. **Response Filtering**: Remove non-tenant data from responses

### Document Operations
- **Create**: Documents automatically include `tenant_id`
- **Read**: Only documents matching tenant ID returned
- **Update**: Only tenant documents can be modified
- **Delete**: Only tenant documents can be deleted

### Query Operations
- **_find**: Selector automatically includes tenant filter
- **_all_docs**: Key range limited to tenant documents
- **_changes**: Feed filtered by tenant ID
- **Views**: Results filtered by tenant field

## Implementation Details

### Cache Implementation
```python
class UserTenantCache:
    def __init__(self, ttl_seconds=300):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, UserTenantInfo] = {}
        self._lock = threading.RLock()
```

### Service Integration
```python
async def extract_tenant(payload: Dict[str, Any]) -> str:
    # Cache lookup
    cached_info = user_cache.get_user_by_sub_hash(sub_hash)
    if cached_info:
        return cached_info.tenant_id

    # Database lookup with automatic creation
    user_tenant_info = await couch_sitter_service.get_user_tenant_info(
        sub=sub, email=email, name=name
    )

    # Cache result
    user_cache.set_user(sub_hash, user_tenant_info)
    return user_tenant_info.tenant_id
```

## Deployment Considerations

### Production Setup
1. **Database Security**: Use CouchDB authentication
2. **Network Security**: Deploy behind firewall
3. **SSL/TLS**: Enable HTTPS for all endpoints
4. **Monitoring**: Enable comprehensive logging
5. **Backup**: Regular backups of couch-sitter database

### Scaling
- **Horizontal Scaling**: Multiple proxy instances possible
- **Cache Locality**: Each instance has its own cache
- **Database Load**: Consider connection pooling
- **Memory Usage**: Monitor cache memory consumption

### Performance Tuning
- **TTL Adjustment**: Balance freshness vs performance
- **Cache Size**: Monitor cache hit rates
- **Database Indexing**: Optimize couch-sitter queries
- **Connection Limits**: Configure appropriate limits

## Troubleshooting

### Common Issues

1. **403 Forbidden Errors**
   - Check `ALLOWED_ENDPOINTS` configuration
   - Verify JWT issuer is in `APPLICATIONS` mapping
   - Ensure CouchDB credentials are correct

2. **User Creation Failures**
   - Verify couch-sitter database exists
   - Check database connectivity and permissions
   - Review error logs for specific issues

3. **Cache Issues**
   - Monitor cache TTL settings
   - Check for memory constraints
   - Review cache hit rates

4. **Tenant Isolation Problems**
   - Verify `TENANT_FIELD` configuration
   - Check document filtering logic
   - Review query rewriting rules

### Debug Logging

Enable debug logging for detailed troubleshooting:

```bash
LOG_LEVEL=DEBUG
```

Debug logs include:
- Cache hit/miss information
- Database operation details
- Tenant injection process
- Request/response filtering

## Future Enhancements

### Planned Features
1. **Multi-Tenant Support**: Support for non-personal tenants
2. **Role-Based Access**: Fine-grained permissions within tenants
3. **Audit Logging**: Comprehensive audit trail
4. **Performance Metrics**: Detailed monitoring and metrics
5. **Cache Clustering**: Shared cache across proxy instances

### Extensibility
- Plugin architecture for custom tenant logic
- Configurable document filtering rules
- Custom authentication providers
- External cache integration (Redis, etc.)

This authentication system provides a robust foundation for multi-tenant CouchDB applications with automatic user management and complete data isolation.