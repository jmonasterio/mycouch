#!/bin/bash
# CouchDB JWT Proxy startup script

# Set PYTHONPATH to include src directory
export PYTHONPATH=src

# Run uvicorn with shorter shutdown timeout and better signal handling
# --timeout-graceful-shutdown 10: Wait max 10 seconds for graceful shutdown
# --access-log: Enable access logging for debugging
# --reload: Enable auto-reload during development (remove for production)
uv run uvicorn couchdb_jwt_proxy.main:app \
    --host 0.0.0.0 \
    --port 5985 \
    --timeout-graceful-shutdown 2 \
    --access-log \
    --reload