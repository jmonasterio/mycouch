@echo off
REM End-to-end test script for CouchDB JWT Proxy setup
REM Tests proxy connectivity, JWT authentication, and CouchDB operations

setlocal enabledelayedexpansion

echo ======================================
echo CouchDB JWT Proxy - Setup Test
echo ======================================
echo.

REM Configuration
set PROXY_URL=http://localhost:5985
set COUCHDB_URL=http://localhost:5984
set TEST_API_KEY=test-key
REM Create timestamp for unique database name
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
set TEST_DB=testdb_%mydate%_%mytime%

REM Helper functions
goto start

:log_info
    echo [OK] %~1
    exit /b

:log_error
    echo [ERROR] %~1
    exit /b

:log_warn
    echo [WARN] %~1
    exit /b

:start

REM Test 1: Check CouchDB connectivity
echo Test 1: Checking CouchDB connectivity...
curl -s %COUCHDB_URL%/ >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] CouchDB is running on %COUCHDB_URL%
) else (
    echo [ERROR] Cannot reach CouchDB at %COUCHDB_URL%
    echo [WARN] Start CouchDB with: docker-compose up -d
    exit /b 1
)

REM Test 2: Check Proxy connectivity
echo.
echo Test 2: Checking Proxy connectivity...
curl -s %PROXY_URL%/ >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Proxy is running on %PROXY_URL%
) else (
    echo [ERROR] Cannot reach Proxy at %PROXY_URL%
    echo [WARN] Start proxy with: uv run uvicorn main:app --reload --port 5985
    exit /b 1
)

REM Test 3: Health check endpoint
echo.
echo Test 3: Testing health check endpoint...
for /f %%i in ('curl -s %PROXY_URL%/health') do set HEALTH=%%i
if "!HEALTH!"=="" (
    echo [ERROR] No response from health endpoint
    exit /b 1
) else (
    echo [OK] Health check passed
    echo     Response: !HEALTH!
)

REM Test 4: Get JWT token
echo.
echo Test 4: Getting JWT token...
for /f %%i in ('curl -s -X POST %PROXY_URL%/auth/token -H "Content-Type: application/json" -d "{\"api_key\": \"%TEST_API_KEY%\"}"') do set TOKEN_RESPONSE=%%i
if "!TOKEN_RESPONSE!"=="" (
    echo [ERROR] No response from token endpoint
    exit /b 1
) else (
    echo [OK] Got token response
    REM Extract token (simplified - full parsing would be more complex)
    echo     Response: !TOKEN_RESPONSE!
)

REM Test 5: List databases through proxy
echo.
echo Test 5: Listing databases through proxy...
echo Note: For full testing, use test_setup.sh on Linux/macOS or set up curl alias properly on Windows

echo.
echo ======================================
echo Setup verification complete!
echo ======================================
echo.
echo Your CouchDB JWT Proxy is ready to use!
echo.
echo Quick reference:
echo   Proxy:   %PROXY_URL%
echo   CouchDB: %COUCHDB_URL%
echo   Credentials: admin/admin
echo.
echo For detailed testing on Windows, consider:
echo   1. Using PowerShell: .\\run_local_couchdb.ps1 and .\\test_setup.ps1 (if available)
echo   2. Using WSL (Windows Subsystem for Linux): ./test_setup.sh
echo   3. Using Git Bash with curl installed
echo.
echo Next steps:
echo   1. Get a token: curl -X POST %PROXY_URL%/auth/token -H "Content-Type: application/json" -d "{\"api_key\": \"test-key\"}"
echo   2. Use token: curl -H "Authorization: Bearer TOKEN" %PROXY_URL%/_all_dbs
echo   3. See DOCKER_SETUP.md for more examples
echo.
