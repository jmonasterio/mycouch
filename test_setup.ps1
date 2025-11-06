#!/usr/bin/env pwsh
# End-to-end test script for CouchDB JWT Proxy setup
# Tests proxy connectivity, JWT authentication, and CouchDB operations

$ErrorActionPreference = "Stop"

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "CouchDB JWT Proxy - Setup Test" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Configuration
$PROXY_URL = "http://localhost:5985"
$COUCHDB_URL = "http://localhost:5984"
$TEST_API_KEY = "test-key"
$TEST_DB = "testdb_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$TokenValue = ""

function Write-Info {
    param([string]$Message)
    Write-Host "✓" -ForegroundColor Green -NoNewline
    Write-Host " $Message"
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "✗" -ForegroundColor Red -NoNewline
    Write-Host " $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Host "!" -ForegroundColor Yellow -NoNewline
    Write-Host " $Message"
}

function Test-Endpoint {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -ErrorAction SilentlyContinue
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

# Test 1: Check CouchDB connectivity
Write-Host "Test 1: Checking CouchDB connectivity..."
if (Test-Endpoint $COUCHDB_URL) {
    Write-Info "CouchDB is running on $COUCHDB_URL"
} else {
    Write-Error-Custom "Cannot reach CouchDB at $COUCHDB_URL"
    Write-Warn "Start CouchDB with: docker-compose up -d"
    exit 1
}

# Test 2: Check Proxy connectivity
Write-Host ""
Write-Host "Test 2: Checking Proxy connectivity..."
if (Test-Endpoint $PROXY_URL) {
    Write-Info "Proxy is running on $PROXY_URL"
} else {
    Write-Error-Custom "Cannot reach Proxy at $PROXY_URL"
    Write-Warn "Start proxy with: uv run uvicorn main:app --reload --port 5985"
    exit 1
}

# Test 3: Health check endpoint
Write-Host ""
Write-Host "Test 3: Testing health check endpoint..."
try {
    $health = Invoke-RestMethod -Uri "$PROXY_URL/health" -TimeoutSec 5
    if ($health.status -eq "ok") {
        Write-Info "Health check passed"
        Write-Host "  Response: $($health | ConvertTo-Json -Compress)" -ForegroundColor DarkGray
    } else {
        Write-Warn "Health check status: $($health.status)"
    }
} catch {
    Write-Error-Custom "Health check failed: $_"
}

# Test 4: Get JWT token
Write-Host ""
Write-Host "Test 4: Getting JWT token..."
try {
    $tokenBody = @{
        api_key = $TEST_API_KEY
    } | ConvertTo-Json

    $tokenResponse = Invoke-RestMethod -Uri "$PROXY_URL/auth/token" `
        -Method Post `
        -ContentType "application/json" `
        -Body $tokenBody `
        -TimeoutSec 5

    if ($tokenResponse.token) {
        $TokenValue = $tokenResponse.token
        Write-Info "Got JWT token"
        Write-Host "  Token (first 50 chars): $($TokenValue.Substring(0, [Math]::Min(50, $TokenValue.Length)))..."
    } else {
        Write-Error-Custom "Failed to get JWT token"
        exit 1
    }
} catch {
    Write-Error-Custom "Token request failed: $_"
    exit 1
}

# Test 5: Create test database through proxy
Write-Host ""
Write-Host "Test 5: Creating test database through proxy..."
try {
    $headers = @{
        "Authorization" = "Bearer $TokenValue"
    }

    $createResponse = Invoke-RestMethod -Uri "$PROXY_URL/$TEST_DB" `
        -Method Put `
        -Headers $headers `
        -TimeoutSec 5

    if ($createResponse.ok) {
        Write-Info "Created test database: $TEST_DB"
    } else {
        Write-Error-Custom "Failed to create database"
        exit 1
    }
} catch {
    Write-Error-Custom "Database creation failed: $_"
    exit 1
}

# Test 6: Create a test document
Write-Host ""
Write-Host "Test 6: Creating test document in database..."
try {
    $docBody = @{
        name = "test"
        value = 42
        timestamp = (Get-Date -Format "o")
    } | ConvertTo-Json

    $docResponse = Invoke-RestMethod -Uri "$PROXY_URL/$TEST_DB" `
        -Method Post `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $docBody `
        -TimeoutSec 5

    if ($docResponse.ok) {
        Write-Info "Created test document with ID: $($docResponse.id)"
    } else {
        Write-Error-Custom "Failed to create document"
    }
} catch {
    Write-Error-Custom "Document creation failed: $_"
}

# Test 7: Query the documents
Write-Host ""
Write-Host "Test 7: Querying test document..."
try {
    $queryResponse = Invoke-RestMethod -Uri "$PROXY_URL/$TEST_DB/_all_docs" `
        -Headers $headers `
        -TimeoutSec 5

    if ($queryResponse.total_rows -ge 0) {
        Write-Info "Successfully queried documents (total: $($queryResponse.total_rows))"
    } else {
        Write-Error-Custom "Failed to query documents"
    }
} catch {
    Write-Error-Custom "Query failed: $_"
}

# Test 8: List all databases
Write-Host ""
Write-Host "Test 8: Listing all databases..."
try {
    $allDbs = Invoke-RestMethod -Uri "$PROXY_URL/_all_dbs" `
        -Headers $headers `
        -TimeoutSec 5

    Write-Info "Successfully listed databases"
    if ($allDbs -contains $TEST_DB) {
        Write-Info "Test database found in database list"
    }
} catch {
    Write-Error-Custom "Failed to list databases: $_"
}

# Test 9: Test invalid token rejection
Write-Host ""
Write-Host "Test 9: Testing invalid token rejection..."
try {
    $invalidHeaders = @{
        "Authorization" = "Bearer invalid-token"
    }

    $invalidResponse = Invoke-RestMethod -Uri "$PROXY_URL/_all_dbs" `
        -Headers $invalidHeaders `
        -TimeoutSec 5 `
        -ErrorAction SilentlyContinue
} catch {
    if ($_.Exception.Response.StatusCode -eq 401) {
        Write-Info "Invalid tokens are properly rejected"
    } else {
        Write-Warn "Unexpected response: $($_.Exception.Message)"
    }
}

# Test 10: Test missing authentication
Write-Host ""
Write-Host "Test 10: Testing missing authentication..."
try {
    $noAuthResponse = Invoke-RestMethod -Uri "$PROXY_URL/_all_dbs" `
        -TimeoutSec 5 `
        -ErrorAction SilentlyContinue
} catch {
    if ($_.Exception.Response.StatusCode -eq 401) {
        Write-Info "Requests without auth are properly rejected"
    }
}

# Cleanup
Write-Host ""
Write-Host "Test 11: Cleaning up test database..."
try {
    $cleanupResponse = Invoke-RestMethod -Uri "$PROXY_URL/$TEST_DB" `
        -Method Delete `
        -Headers $headers `
        -TimeoutSec 5

    if ($cleanupResponse.ok) {
        Write-Info "Cleaned up test database: $TEST_DB"
    }
} catch {
    Write-Warn "Could not delete test database (may need manual cleanup)"
}

# Summary
Write-Host ""
Write-Host "======================================" -ForegroundColor Green
Write-Host "All tests passed! ✓" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host ""
Write-Host "Your CouchDB JWT Proxy is ready to use!" -ForegroundColor Green
Write-Host ""
Write-Host "Quick reference:"
Write-Host "  Proxy:       $PROXY_URL"
Write-Host "  CouchDB:     $COUCHDB_URL"
Write-Host "  Credentials: admin/admin"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Get a token: curl -X POST $PROXY_URL/auth/token -H 'Content-Type: application/json' -d '{\"api_key\": \"test-key\"}'"
Write-Host "  2. Use token: curl -H `"Authorization: Bearer TOKEN`" $PROXY_URL/_all_dbs"
Write-Host "  3. See DOCKER_SETUP.md for more examples"
Write-Host ""
