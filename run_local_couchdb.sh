#!/bin/bash

export COUCHDB_CHttpd_EnableCors=true
export COUCHDB_Cors_Origins=*
export COUCHDB_Cors_Credentials=true
export COUCHDB_Cors_Methods="GET, PUT, POST, HEAD, DELETE"
export COUCHDB_Cors_Headers="accept, authorization, content-type, origin, referer, x-csrf-token"

# Start local CouchDB container for development
# RUN IN PARTY MODE!
docker rm couchdb
docker run -d --name couchdb -e COUCHDB_USER=admin -e COUCHDB_PASSWORD=admin -p 5984:5984 couchdb:3

echo "CouchDB container started"
echo "Waiting for CouchDB to be ready..."
sleep 5

# Check if CouchDB is responding
if curl -s http://localhost:5984/ > /dev/null; then
    echo "✓ CouchDB is ready at http://localhost:5984"
    echo "  Admin credentials: admin/admin"
    echo "  Fauxton UI: http://localhost:5984/_utils/"
else
    echo "✗ CouchDB not responding yet, may still be starting..."
fi
