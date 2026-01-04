#!/bin/bash
# Start CouchDB locally using nerdctl
# Usage: ./start-couchdb.sh

set -e

CONTAINER_NAME="mycouch-couchdb"

# Check if container already exists
if nerdctl ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Container ${CONTAINER_NAME} already exists."

    # Check if it's running
    if nerdctl ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "✅ CouchDB is already running"
    else
        echo "Starting existing container..."
        nerdctl start ${CONTAINER_NAME}
        echo "✅ CouchDB started"
    fi
else
    echo "Creating and starting CouchDB container..."
    nerdctl run -d \
        --name ${CONTAINER_NAME} \
        -p 5984:5984 \
        -e COUCHDB_USER=admin \
        -e COUCHDB_PASSWORD=admin \
        -v couchdb_data:/opt/couchdb/data \
        couchdb:latest
    echo "✅ CouchDB container created and started"
fi

# Wait for CouchDB to be ready
echo "Waiting for CouchDB to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:5984/ > /dev/null 2>&1; then
        echo "✅ CouchDB is ready!"
        echo ""
        echo "CouchDB URL: http://localhost:5984/"
        echo "Fauxton UI:  http://localhost:5984/_utils/"
        echo "Credentials: admin / admin"
        exit 0
    fi
    sleep 1
done

echo "❌ CouchDB did not become ready in time"
exit 1
