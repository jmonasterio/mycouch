import httpx
import json
import base64

creds = base64.b64encode(b"admin:admin").decode()
headers = {
    "Authorization": f"Basic {creds}",
    "Content-Type": "application/json"
}

indexes = [
    {"index": {"fields": ["type", "action", "status", "timestamp"]}, "name": "type-action-status-timestamp"},
    {"index": {"fields": ["type", "action", "timestamp"]}, "name": "type-action-timestamp"},
    {"index": {"fields": ["type", "status", "timestamp"]}, "name": "type-status-timestamp"},
    {"index": {"fields": ["action", "timestamp"]}, "name": "action-timestamp"},
    {"index": {"fields": ["user_id", "timestamp"]}, "name": "user-timestamp"},
    {"index": {"fields": ["status", "timestamp"]}, "name": "status-timestamp"},
    {"index": {"fields": ["type", "timestamp"]}, "name": "type-timestamp"},
]

for idx in indexes:
    response = httpx.post(
        "http://localhost:5984/couch-sitter-logs/_index",
        json=idx,
        headers=headers
    )
    print(f"{idx['name']}: {response.status_code} - {response.json()}")
