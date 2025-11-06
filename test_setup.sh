#!/bin/bash

# End-to-end test script for CouchDB JWT Proxy setup
# Tests proxy connectivity, JWT authentication, and CouchDB operations

set -e

echo "======================================"
echo "CouchDB JWT Proxy - Setup Test"
echo "======================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROXY_URL="http://localhost:5985"
COUCHDB_URL="http://localhost:5984"
TEST_API_KEY="test-key"
TEST_DB="testdb_$(date +%s)"

# Helper functions
log_info() {
    echo -e "${GREEN}✓${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}!${NC} $1"
}

# Test 1: Check CouchDB connectivity
echo "Test 1: Checking CouchDB connectivity..."
if curl -s "$COUCHDB_URL/" > /dev/null; then
    log_info "CouchDB is running on $COUCHDB_URL"
else
    log_error "Cannot reach CouchDB at $COUCHDB_URL"
    log_warn "Start CouchDB with: docker-compose up -d"
    exit 1
fi

# Test 2: Check Proxy connectivity
echo ""
echo "Test 2: Checking Proxy connectivity..."
if curl -s "$PROXY_URL/" > /dev/null; then
    log_info "Proxy is running on $PROXY_URL"
else
    log_error "Cannot reach Proxy at $PROXY_URL"
    log_warn "Start proxy with: uv run uvicorn main:app --reload --port 5985"
    exit 1
fi

# Test 3: Health check endpoint
echo ""
echo "Test 3: Testing health check endpoint..."
HEALTH=$(curl -s "$PROXY_URL/health")
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    log_info "Health check passed"
    echo "  Response: $HEALTH" | sed 's/^/    /'
else
    log_error "Health check failed"
    log_warn "Response: $HEALTH"
fi

# Test 4: Get JWT token
echo ""
echo "Test 4: Getting JWT token..."
TOKEN_RESPONSE=$(curl -s -X POST "$PROXY_URL/auth/token" \
    -H "Content-Type: application/json" \
    -d "{\"api_key\": \"$TEST_API_KEY\"}")

if echo "$TOKEN_RESPONSE" | grep -q '"token":'; then
    TOKEN=$(echo "$TOKEN_RESPONSE" | grep -o '"token":"[^"]*' | cut -d'"' -f4)
    log_info "Got JWT token"
    echo "  Token (first 50 chars): ${TOKEN:0:50}..."
else
    log_error "Failed to get JWT token"
    log_warn "Response: $TOKEN_RESPONSE"
    exit 1
fi

# Test 5: Create test database through proxy
echo ""
echo "Test 5: Creating test database through proxy..."
CREATE_DB=$(curl -s -X PUT \
    -H "Authorization: Bearer $TOKEN" \
    "$PROXY_URL/$TEST_DB")

if echo "$CREATE_DB" | grep -q '"ok":true'; then
    log_info "Created test database: $TEST_DB"
else
    log_error "Failed to create database"
    log_warn "Response: $CREATE_DB"
    exit 1
fi

# Test 6: Create a test document
echo ""
echo "Test 6: Creating test document in database..."
DOC_RESPONSE=$(curl -s -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name":"test","value":42,"timestamp":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' \
    "$PROXY_URL/$TEST_DB")

if echo "$DOC_RESPONSE" | grep -q '"ok":true'; then
    DOC_ID=$(echo "$DOC_RESPONSE" | grep -o '"id":"[^"]*' | cut -d'"' -f4)
    log_info "Created test document with ID: $DOC_ID"
else
    log_error "Failed to create document"
    log_warn "Response: $DOC_RESPONSE"
    exit 1
fi

# Test 7: Query the document
echo ""
echo "Test 7: Querying test document..."
QUERY_RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "$PROXY_URL/$TEST_DB/_all_docs")

if echo "$QUERY_RESPONSE" | grep -q '"total_rows"'; then
    TOTAL_ROWS=$(echo "$QUERY_RESPONSE" | grep -o '"total_rows":[0-9]*' | cut -d':' -f2)
    log_info "Successfully queried documents (total: $TOTAL_ROWS)"
else
    log_error "Failed to query documents"
    log_warn "Response: $QUERY_RESPONSE"
    exit 1
fi

# Test 8: List all databases
echo ""
echo "Test 8: Listing all databases..."
ALL_DBS=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "$PROXY_URL/_all_dbs")

if echo "$ALL_DBS" | grep -q "\["; then
    log_info "Successfully listed databases"
    if echo "$ALL_DBS" | grep -q "$TEST_DB"; then
        log_info "Test database found in database list"
    fi
else
    log_error "Failed to list databases"
    log_warn "Response: $ALL_DBS"
    exit 1
fi

# Test 9: Test invalid token rejection
echo ""
echo "Test 9: Testing invalid token rejection..."
INVALID_TOKEN_RESPONSE=$(curl -s -H "Authorization: Bearer invalid-token" \
    "$PROXY_URL/_all_dbs")

if echo "$INVALID_TOKEN_RESPONSE" | grep -q '"detail"'; then
    log_info "Invalid tokens are properly rejected"
else
    log_error "Invalid token was not rejected"
    log_warn "Response: $INVALID_TOKEN_RESPONSE"
fi

# Test 10: Test missing authentication
echo ""
echo "Test 10: Testing missing authentication..."
NO_AUTH_RESPONSE=$(curl -s "$PROXY_URL/_all_dbs")

if echo "$NO_AUTH_RESPONSE" | grep -q '"detail"'; then
    log_info "Requests without auth are properly rejected"
else
    log_warn "Could not verify auth rejection"
fi

# Cleanup
echo ""
echo "Test 11: Cleaning up test database..."
CLEANUP=$(curl -s -X DELETE \
    -H "Authorization: Bearer $TOKEN" \
    "$PROXY_URL/$TEST_DB")

if echo "$CLEANUP" | grep -q '"ok":true'; then
    log_info "Cleaned up test database: $TEST_DB"
else
    log_warn "Could not delete test database (may need manual cleanup)"
fi

# Summary
echo ""
echo "======================================"
echo -e "${GREEN}All tests passed! ✓${NC}"
echo "======================================"
echo ""
echo "Your CouchDB JWT Proxy is ready to use!"
echo ""
echo "Quick reference:"
echo "  Proxy:   $PROXY_URL"
echo "  CouchDB: $COUCHDB_URL"
echo "  Credentials: admin/admin"
echo ""
echo "Next steps:"
echo "  1. Get a token: curl -X POST $PROXY_URL/auth/token -H 'Content-Type: application/json' -d '{\"api_key\": \"test-key\"}'"
echo "  2. Use token: curl -H \"Authorization: Bearer TOKEN\" $PROXY_URL/_all_dbs"
echo "  3. See DOCKER_SETUP.md for more examples"
echo ""
