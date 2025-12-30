#!/usr/bin/env python
"""Debug JWT token claims"""

import os
import json
import base64
from pathlib import Path

# Load .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[OK] Loaded .env")
except:
    pass

JWT_TOKEN = os.getenv("JWT_TOKEN", "")

if not JWT_TOKEN:
    print("ERROR: JWT_TOKEN not set in .env")
    exit(1)

# Decode JWT without verification
try:
    parts = JWT_TOKEN.split(".")
    if len(parts) != 3:
        print(f"ERROR: Invalid JWT format (expected 3 parts, got {len(parts)})")
        exit(1)
    
    payload = parts[1]
    # Add padding if needed
    padding = 4 - (len(payload) % 4)
    if padding != 4:
        payload += "=" * padding
    
    decoded = json.loads(base64.urlsafe_b64decode(payload))
    
    print("JWT Payload:")
    print(json.dumps(decoded, indent=2))
    
    print(f"\nKey claims:")
    print(f"  sub: {decoded.get('sub')}")
    print(f"  iss: {decoded.get('iss')}")
    print(f"  email: {decoded.get('email')}")
    
except Exception as e:
    print(f"ERROR: {e}")
    exit(1)
