#!/usr/bin/env python3
"""
Quick debug script to test JWT endpoints
Shows actual responses without complex test framework
"""

import os
import sys
import json
import httpx
import hashlib
from pathlib import Path

# Load .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✓ Loaded .env from {env_path}")
except ImportError:
    pass

JWT_TOKEN = os.getenv("JWT_TOKEN", "")
PROXY_URL = os.getenv("PROXY_URL", "http://localhost:5985")

if not JWT_TOKEN:
    print("\n❌ JWT_TOKEN not set in .env or environment")
    sys.exit(1)

print(f"\n📍 Proxy: {PROXY_URL}")
print(f"🔑 Token: {JWT_TOKEN[:50]}...\n")

# Extract and hash sub from token
import base64
try:
    parts = JWT_TOKEN.split(".")
    payload = parts[1]
    padding = 4 - (len(payload) % 4)
    if padding != 4:
        payload += "=" * padding
    decoded = json.loads(base64.urlsafe_b64decode(payload))
    sub = decoded.get("sub")
    sub_hash = hashlib.sha256(sub.encode('utf-8')).hexdigest()
    print(f"👤 User sub: {sub}")
    print(f"🔐 Sub hash: {sub_hash}\n")
except Exception as e:
    print(f"❌ Could not parse JWT: {e}")
    sys.exit(1)

# Test endpoints
headers = {"Authorization": f"Bearer {JWT_TOKEN}"}
client = httpx.Client(timeout=30.0)

print("=" * 60)
print("TESTING ENDPOINTS")
print("=" * 60)

# Test 1: Get user
print("\n[1] GET /__users/{sub_hash}")
try:
    response = client.get(f"{PROXY_URL}/__users/{sub_hash}", headers=headers)
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(f"Response:\n{json.dumps(data, indent=2)}")
    except:
        print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")

# Test 2: List tenants
print("\n[2] GET /__tenants")
try:
    response = client.get(f"{PROXY_URL}/__tenants", headers=headers)
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(f"Response:\n{json.dumps(data, indent=2)}")
    except:
        print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")

# Test 3: Create tenant
print("\n[3] POST /__tenants")
try:
    response = client.post(
        f"{PROXY_URL}/__tenants",
        headers=headers,
        json={"name": "Debug Test Tenant"}
    )
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(f"Response:\n{json.dumps(data, indent=2)}")
    except:
        print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")

# Test 4: Health check
print("\n[4] GET /health (no auth)")
try:
    response = client.get(f"{PROXY_URL}/health")
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(f"Response:\n{json.dumps(data, indent=2)}")
    except:
        print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 60)
print("Done!")
