#!/bin/bash
# CouchDB JWT Proxy startup script

# Set PYTHONPATH to include src directory
export PYTHONPATH=src

# Run uvicorn with shorter shutdown timeout and better signal handling
# --timeout-graceful-shutdown 10: Wait max 10 seconds for graceful shutdown
# --access-log: Enable access logging for debugging
# --reload: Enable auto-reload during development (remove for production)
# Check port availability first
# We export PROXY_HOST and PROXY_PORT so check_port.py uses the same values
export PROXY_HOST=0.0.0.0
export PROXY_PORT=5985

echo "Checking port availability on $PROXY_HOST:$PROXY_PORT..."
uv run python -m couchdb_jwt_proxy.check_port
if [ $? -ne 0 ]; then
    echo "[ERROR] Port check failed. Aborting startup."
    exit 1
fi

echo "Starting proxy..."
uv run uvicorn couchdb_jwt_proxy.main:app \
    --host $PROXY_HOST \
    --port $PROXY_PORT \
    --timeout-graceful-shutdown 1 \
    --access-log \
    --reload \
    --reload-dir src