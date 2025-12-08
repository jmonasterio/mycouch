import httpx
import json
import base64

creds = base64.b64encode(b"admin:admin").decode()
headers = {
    "Authorization": f"Basic {creds}",
    "Content-Type": "application/json"
}

# Create design document with Map/Reduce views
design_doc = {
    "_id": "_design/auth_logs",
    "views": {
        "by_timestamp": {
            "map": "function(doc) { if (doc.type === 'auth_event') emit(doc.timestamp, {action: doc.action, status: doc.status, user_id: doc.user_id}); }"
        },
        "by_action_timestamp": {
            "map": "function(doc) { if (doc.type === 'auth_event') emit([doc.action, doc.timestamp], null); }"
        },
        "by_status_timestamp": {
            "map": "function(doc) { if (doc.type === 'auth_event') emit([doc.status, doc.timestamp], null); }"
        },
        "by_action_status_timestamp": {
            "map": "function(doc) { if (doc.type === 'auth_event') emit([doc.action, doc.status, doc.timestamp], null); }"
        }
    }
}

response = httpx.put(
    "http://localhost:5984/couch-sitter-logs/_design/auth_logs",
    json=design_doc,
    headers=headers
)
print(f"Design doc: {response.status_code} - {response.json()}")
