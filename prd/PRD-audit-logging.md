# Audit Logging for Couch-Sitter

**Version:** 1.0  
**Date:** 2025-12-07  
**Status:** Draft  
**Priority:** Medium (operations/compliance)

---

## Executive Summary

Implement audit logging for couch-sitter to track user authentication, tenant management, and administrative actions. Logs will be stored in a dedicated `couch-sitter-log` database (internal access only) with query patterns for security investigations and compliance reporting.

**Key Benefit:** Complete audit trail for compliance, security investigations, and troubleshooting.

---

## Problem Statement

Currently, couch-sitter has no audit trail. When issues occur:
- Can't determine who made a change
- Can't see when users logged in/out
- Can't verify compliance with security policies
- Can't investigate suspicious activity

This makes it difficult to:
1. Debug issues (who created this tenant?)
2. Support compliance requirements (who accessed what data?)
3. Investigate security incidents
4. Audit administrative actions

---

## Solution Overview

Create internal audit logging in a dedicated CouchDB database (`couch-sitter-log`) that records:
- User authentication events (login, logout, failed attempts)
- Tenant operations (create, update, delete, user additions)
- Administrative actions (metadata changes, JWT updates)
- API access patterns

**Key Design Decisions:**
- ✅ Internal database (no external access through proxy)
- ✅ MyCouch writes logs directly to CouchDB
- ✅ Each event is a single document
- ✅ Query patterns designed for reporting
- ✅ Log retention policy (configurable)
- ✅ No personally identifiable data (only IDs)

---

## Detailed Requirements

### 1. Log Entry Structure

Each log entry is a separate CouchDB document with this structure:

```json
{
  "_id": "log:2025-12-07T10:30:45.123Z:auth:user_abc",
  "type": "log",
  "eventType": "user_login",
  "timestamp": "2025-12-07T10:30:45.123Z",
  "userId": "user_abc",
  "issuer": "https://roady.clerk.accounts.dev",
  "app": "roady",
  "action": "login",
  "status": "success",
  "details": {
    "sessionId": "session_xyz",
    "ipAddress": "192.168.1.100",
    "userAgent": "Mozilla/5.0..."
  },
  "metadata": {
    "requestId": "req_abc123"
  },
  "createdAt": "2025-12-07T10:30:45.123Z"
}
```

### 2. Event Types to Log

#### Authentication Events
```
- user_login (success/failure)
- user_logout
- token_refresh
- invalid_token_attempt
- auth_failure (expired, invalid signature, etc.)
```

#### Tenant Operations
```
- tenant_created
- tenant_updated
- tenant_deleted (soft delete)
- user_added_to_tenant
- user_removed_from_tenant
- tenant_user_role_changed
```

#### User Operations
```
- user_created
- user_updated
- user_metadata_changed
- user_deleted (soft delete)
```

#### Administrative Actions
```
- active_tenant_set
- session_metadata_updated
- jwt_template_validated
- jwt_claim_validation_failed
- admin_action (manual override, etc.)
```

### 3. Log Entry Fields

**Required Fields:**
- `_id`: Unique identifier (timestamp + event type + user + nonce)
- `type`: Always "log"
- `eventType`: Specific event (user_login, tenant_created, etc.)
- `timestamp`: ISO 8601 timestamp (when event occurred)
- `userId`: Clerk user ID (required for most events)
- `app`: App identifier ("roady", "couch-sitter", etc.)
- `action`: Action performed (login, create, update, delete)
- `status`: success/failure/warning
- `createdAt`: When log was written (same as timestamp)

**Optional Fields:**
- `issuer`: Clerk issuer URL
- `sessionId`: Clerk session ID
- `tenantId`: Affected tenant (if applicable)
- `targetUserId`: User being acted upon (if different from userId)
- `details`: Additional context (IP, user agent, error message, etc.)
- `metadata`: Structured data for querying (requestId, correlationId, etc.)
- `error`: Error details if status=failure
- `duration`: Operation duration in ms (if applicable)

### 4. Log ID Generation

Log `_id` should be queryable and include timestamp for sorting:

```
Format: log:{timestamp}:{eventType}:{userId}:{nonce}

Examples:
- log:2025-12-07T10:30:45.123Z:user_login:user_abc:abc123
- log:2025-12-07T10:31:20.456Z:tenant_created:user_def:def456
- log:2025-12-07T10:32:15.789Z:user_added_to_tenant:user_ghi:ghi789
```

**Advantages:**
- ✅ Sortable by timestamp (CouchDB sorts by _id)
- ✅ Easy to query by eventType
- ✅ Easy to query by userId
- ✅ Unique (timestamp + nonce prevents duplicates)

---

## Query Patterns for Reporting

### Pattern 1: All logins for a user

```
startkey: "log:0000:user_login:user_abc:"
endkey:   "log:9999:user_login:user_abc:\uffff"
```

Returns all login events for `user_abc` in chronological order.

### Pattern 2: All events in a time range

```
startkey: "log:2025-12-07T00:00:00Z"
endkey:   "log:2025-12-07T23:59:59Z"
```

Returns all events on a specific date.

### Pattern 3: All tenant events

```
type: "log"
eventType: "tenant_*"
```

Use CouchDB view to filter by eventType prefix.

### Pattern 4: Failed authentication attempts

```
status: "failure"
eventType: "user_login"
```

Returns all failed login attempts (potential security issue).

### Pattern 5: Specific user's actions

```
userId: "user_abc"
timestamp: { $gt: "2025-12-01", $lt: "2025-12-31" }
```

User activity audit trail.

---

## Design: CouchDB Views for Reporting

Create design document `_design/logs` with views:

```javascript
{
  "_id": "_design/logs",
  "views": {
    // View 1: Events by user and timestamp
    "by_user": {
      "map": "function(doc) {
        if (doc.type === 'log') {
          emit([doc.userId, doc.timestamp], {
            eventType: doc.eventType,
            action: doc.action,
            status: doc.status,
            tenantId: doc.tenantId
          });
        }
      }"
    },
    
    // View 2: Events by type
    "by_event_type": {
      "map": "function(doc) {
        if (doc.type === 'log') {
          emit([doc.eventType, doc.timestamp], {
            userId: doc.userId,
            status: doc.status,
            action: doc.action
          });
        }
      }"
    },
    
    // View 3: Failed events
    "by_status": {
      "map": "function(doc) {
        if (doc.type === 'log' && doc.status === 'failure') {
          emit([doc.eventType, doc.timestamp], {
            userId: doc.userId,
            error: doc.error,
            details: doc.details
          });
        }
      }"
    },
    
    // View 4: Tenant events
    "by_tenant": {
      "map": "function(doc) {
        if (doc.type === 'log' && doc.tenantId) {
          emit([doc.tenantId, doc.timestamp], {
            eventType: doc.eventType,
            userId: doc.userId,
            action: doc.action
          });
        }
      }"
    },
    
    // View 5: Recent events (last 1000)
    "recent": {
      "map": "function(doc) {
        if (doc.type === 'log') {
          emit(doc.timestamp, doc);
        }
      }",
      "reduce": "_count"
    }
  }
}
```

---

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)

**Task 1.1: Create couch-sitter-log database**
- Create database in CouchDB (no proxy access)
- Set `_security` to admin-only read/write
- Create design document with views

**Task 1.2: Add logging module to MyCouch**
- Create `src/couchdb_jwt_proxy/audit_logger.py`
- Implement methods:
  - `log_authentication_event(eventType, userId, status, details)`
  - `log_tenant_event(eventType, userId, tenantId, action, details)`
  - `log_user_event(eventType, userId, action, targetUserId, details)`
  - `log_admin_event(eventType, userId, action, details)`

**Task 1.3: Integrate logging into key endpoints**
- `/choose-tenant` → log active_tenant_set
- `/my-tenants` → log tenant_list_requested (if suspicious access)
- Authentication failures → log auth_failure
- User creation → log user_created
- Tenant operations → log tenant_* events

### Phase 2: Event Coverage (Week 2)

**Task 2.1: Authentication events**
- Log all login attempts (success/failure)
- Log logouts
- Log token refresh
- Log invalid token attempts

**Task 2.2: Tenant management events**
- Log tenant creation/updates/deletions
- Log user additions/removals
- Log role changes

**Task 2.3: User management events**
- Log user creation/updates
- Log metadata changes
- Log user deletions

### Phase 3: Reporting Interface (Week 3)

**Task 3.1: Create reporting utilities**
- Python script to query logs: `scripts/query-audit-logs.py`
- Patterns:
  - User activity: `python scripts/query-audit-logs.py --user user_abc`
  - Date range: `python scripts/query-audit-logs.py --from 2025-12-01 --to 2025-12-31`
  - Event type: `python scripts/query-audit-logs.py --event user_login`
  - Failed events: `python scripts/query-audit-logs.py --status failure`

**Task 3.2: Create example reports**
- Daily login report
- User activity summary
- Failed auth attempts
- Tenant change audit trail
- Admin action log

### Phase 4: Log Retention & Cleanup (Week 4)

**Task 4.1: Implement log rotation**
- Configuration: `LOG_RETENTION_DAYS` (default: 90)
- Cron job to delete logs older than retention period
- Archive option to export old logs to R2 before deletion

**Task 4.2: Add log metrics**
- Monitor log growth
- Alert if suspicious pattern detected
- Monitor disk usage

---

## Database Setup

### Create couch-sitter-log database

```bash
# Via curl (admin user required)
curl -X PUT http://admin:password@localhost:5984/couch-sitter-log

# Set _security (admin-only read/write)
curl -X PUT http://admin:password@localhost:5984/couch-sitter-log/_security \
  -H "Content-Type: application/json" \
  -d '{
    "admins": {
      "names": ["admin_user"],
      "roles": []
    },
    "members": {
      "names": [],
      "roles": []
    }
  }'

# MyCouch admin credentials used to read/write logs
# (separate from CouchDB admin, managed in .env)
COUCH_SITTER_LOG_DB_URL=http://admin:password@localhost:5984/couch-sitter-log
```

---

## Security & Privacy

### What NOT to log
- ❌ Passwords or tokens
- ❌ Personal identifiable information (email addresses)
- ❌ Request/response bodies (only metadata)
- ❌ JWT tokens

### What to log
- ✅ User IDs (Clerk sub)
- ✅ Tenant IDs
- ✅ Action type and result
- ✅ Timestamp
- ✅ IP address (if available)
- ✅ Error messages (sanitized)

### Access Control
- ✅ Log database only accessible to MyCouch (internal)
- ✅ Logs not exposed through proxy
- ✅ Reporting tools require admin credentials
- ✅ Logs cannot be deleted by users (only admins)

---

## Environment Configuration

Add to `.env`:

```
# Audit Logging
AUDIT_LOGGING_ENABLED=true
COUCH_SITTER_LOG_DB_URL=http://admin:password@localhost:5984/couch-sitter-log
LOG_RETENTION_DAYS=90
LOG_BATCH_SIZE=100  # Batch writes for performance
```

---

## Performance Considerations

### Write Performance
- Batch writes: Buffer 100 events, write once per 5 seconds
- Async logging: Don't block request on log write
- Circuit breaker: If logging fails, don't fail the request

### Read Performance
- Views indexed by timestamp (fast range queries)
- Limit queries to reasonable time windows
- Archive old logs to reduce database size

### Storage
- Estimate: ~2KB per log entry
- 1000 events/day = ~2MB/day
- 90-day retention = ~180MB
- Annual = ~730MB

---

## Example Log Entries

### User Login Success
```json
{
  "_id": "log:2025-12-07T10:30:45.123Z:user_login:user_abc:abc123",
  "type": "log",
  "eventType": "user_login",
  "timestamp": "2025-12-07T10:30:45.123Z",
  "userId": "user_abc",
  "issuer": "https://roady.clerk.accounts.dev",
  "app": "roady",
  "action": "login",
  "status": "success",
  "details": {
    "sessionId": "session_xyz",
    "ipAddress": "192.168.1.100"
  },
  "createdAt": "2025-12-07T10:30:45.123Z"
}
```

### Tenant Created
```json
{
  "_id": "log:2025-12-07T10:35:20.456Z:tenant_created:user_def:def456",
  "type": "log",
  "eventType": "tenant_created",
  "timestamp": "2025-12-07T10:35:20.456Z",
  "userId": "user_def",
  "tenantId": "tenant_new_band",
  "app": "roady",
  "action": "create",
  "status": "success",
  "details": {
    "tenantName": "Blue Notes"
  },
  "createdAt": "2025-12-07T10:35:20.456Z"
}
```

### Failed Login Attempt
```json
{
  "_id": "log:2025-12-07T10:40:15.789Z:user_login:user_xyz:xyz789",
  "type": "log",
  "eventType": "user_login",
  "timestamp": "2025-12-07T10:40:15.789Z",
  "userId": "user_xyz",
  "issuer": "https://roady.clerk.accounts.dev",
  "app": "roady",
  "action": "login",
  "status": "failure",
  "error": "clerk_token_expired",
  "details": {
    "ipAddress": "203.0.113.50",
    "attemptNumber": 3
  },
  "createdAt": "2025-12-07T10:40:15.789Z"
}
```

---

## Reporting Examples

### Daily login report
```
python scripts/query-audit-logs.py --event user_login --from 2025-12-07 --to 2025-12-08
```

Output:
```
Date: 2025-12-07

Successful Logins: 42
Failed Logins: 3
Unique Users: 15

Failed Attempts by IP:
  203.0.113.50: 2 attempts (user_xyz, user_abc)
  198.51.100.40: 1 attempt (user_def)

Peak Login Time: 09:00 AM (8 logins in 1 minute)
```

### User activity audit
```
python scripts/query-audit-logs.py --user user_abc --from 2025-12-01 --to 2025-12-31
```

Output:
```
User: user_abc (user@example.com)
Period: 2025-12-01 to 2025-12-31

Events: 127
- Logins: 25 (3+ per day, peak 5 on 2025-12-07)
- Tenant creations: 2
- User invites sent: 5
- Metadata updates: 8

Last Activity: 2025-12-07 10:30:45 UTC
```

---

## Success Criteria

- ✅ All authentication events logged with < 10ms overhead
- ✅ Tenant operations logged completely
- ✅ Audit trail available for last 90 days
- ✅ Reporting tools can generate reports in < 5 seconds
- ✅ No user data exposed in logs
- ✅ Logs cannot be modified/deleted by users

---

## Compliance & Standards

- **SOC 2:** Required for Type II certification
- **GDPR:** User data minimized (only IDs, not PII)
- **HIPAA:** If handling health data, logs must be encrypted
- **Audit trail:** 90 days minimum recommended

---

## Future Enhancements

1. **Real-time alerts:** Trigger alerts on suspicious patterns
2. **Dashboard:** Web UI to view recent logs
3. **Log export:** Export logs to CSV/JSON for compliance
4. **ML detection:** Detect anomalous patterns automatically
5. **Log encryption:** Encrypt logs at rest for sensitive deployments
6. **Multi-region:** Replicate logs to backup location

---

## References

- OWASP: https://owasp.org/www-community/attacks/
- CWE-778: Insufficient Logging
- NIST: https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-92.pdf

---

**Status:** Ready for implementation  
**Priority:** Medium (good to have, not blocking)  
**Effort:** 3-4 weeks for full implementation
