@echo off
REM CouchDB JWT Proxy - Batch runner script
REM Usage: run.bat [command]

setlocal enabledelayedexpansion

set "COMMAND=%1"
if "%COMMAND%"=="" set "COMMAND=help"

goto %COMMAND%

:help
echo CouchDB JWT Proxy - uv commands
echo.
echo Setup ^& Installation:
echo   run.bat install       Install dependencies
echo   run.bat dev          Install with dev dependencies
echo.
echo Running:
echo   run.bat run          Run the proxy server
echo   run.bat dev-run      Run with auto-reload
echo.
echo Testing:
echo   run.bat test         Run all tests
echo   run.bat test-cov     Run tests with coverage report
echo.
echo Utilities:
echo   run.bat clean        Remove cache and build files
echo   run.bat env-setup    Create .env file from .env.example
echo   run.bat help         Show this help message
echo.
goto end

:install
echo Installing dependencies...
call uv sync
if %ERRORLEVEL% equ 0 (
    echo [OK] Dependencies installed
) else (
    echo [ERROR] Installation failed
    exit /b 1
)
goto end

:dev
echo Installing dependencies with dev extras...
call uv sync --all-extras
if %ERRORLEVEL% equ 0 (
    echo [OK] Dev dependencies installed
) else (
    echo [ERROR] Installation failed
    exit /b 1
)
goto end

:run
echo Checking port availability...
set PYTHONPATH=src
call uv run python -m couchdb_jwt_proxy.check_port
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Port check failed. Aborting startup.
    exit /b 1
)

echo Starting CouchDB JWT Proxy...
call uv run python -m couchdb_jwt_proxy.main
goto end



:dev-run
echo Checking port availability...
set PYTHONPATH=src
call uv run python -m couchdb_jwt_proxy.check_port
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Port check failed. Aborting startup.
    exit /b 1
)

echo Starting proxy with auto-reload...
REM Default to 127.0.0.1 if PROXY_HOST is not set, to match uvicorn default
if "%PROXY_HOST%"=="" set PROXY_HOST=127.0.0.1
call uv run uvicorn couchdb_jwt_proxy.main:app --reload --host %PROXY_HOST% --port 5985
goto end

:test
echo Running tests...
call uv run pytest tests -v
goto end

:test-cov
echo Running tests with coverage...
call uv run pytest tests -v --cov=couchdb_jwt_proxy --cov-report=html --cov-report=term-missing
echo.
echo [OK] Coverage report: htmlcov/index.html
goto end

:clean
echo Cleaning up...
for /d /r . %%d in (__pycache__ .pytest_cache .uv htmlcov) do @if exist "%%d" rd /s /q "%%d"
for /r . %%f in (.coverage) do @if exist "%%f" del "%%f"
echo [OK] Cleanup complete
goto end

:env-setup
if exist ".env" (
    echo .env file already exists
) else (
    copy ".env.example" ".env"
    echo [OK] .env file created. Please update with your settings.
)
goto end

:end
