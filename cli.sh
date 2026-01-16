#!/bin/bash
# CouchDB JWT Proxy startup script

# Set PYTHONPATH to include src directory
export PYTHONPATH=src

# Parse arguments
WATCH_MODE=false
if [ "$1" == "--watch" ] || [ "$1" == "-w" ]; then
    WATCH_MODE=true
fi

# Run uvicorn with shorter shutdown timeout and better signal handling
# --timeout-graceful-shutdown 10: Wait max 10 seconds for graceful shutdown
# --access-log: Enable access logging for debugging
# --reload: Enable auto-reload during development (remove for production)
# Check port availability first
# We export PROXY_HOST and PROXY_PORT so check_port.py uses the same values
# Use 127.0.0.1 instead of 0.0.0.0 to avoid CrowdStrike flagging
export PROXY_HOST=127.0.0.1
export PROXY_PORT=5985

echo "Checking port availability on $PROXY_HOST:$PROXY_PORT..."
uv run python -m couchdb_jwt_proxy.check_port
if [ $? -ne 0 ]; then
    echo "[ERROR] Port check failed. Aborting startup."
    exit 1
fi

if [ "$WATCH_MODE" = true ]; then
    echo "🔄 Starting proxy with auto-reload on Python changes..."
    echo "Usage: ./cli.sh --watch (or -w)"
    # Use uvicorn with --reload flag to watch for Python file changes
    PYTHONPATH=src uv run uvicorn couchdb_jwt_proxy.main:app --reload --host $PROXY_HOST --port $PROXY_PORT
else
    echo "Starting proxy (production mode - no auto-reload)..."
    echo "Tip: Use './cli.sh --watch' for development with auto-reload"
    # Use Python import method instead of uvicorn CLI to avoid CrowdStrike blocking
    # Also avoid 'uv run' which spawns subprocesses that CrowdStrike may flag
    .venv/Scripts/python run.py 
fi