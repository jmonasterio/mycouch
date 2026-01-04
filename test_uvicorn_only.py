#!/usr/bin/env python3
"""
Test uvicorn WITHOUT FastAPI - pure ASGI app.
This isolates whether the issue is uvicorn or FastAPI.

Run with: .venv/Scripts/python test_uvicorn_only.py
"""
import json
import uvicorn

HOST = '127.0.0.1'
PORT = 5985

async def app(scope, receive, send):
    """Minimal ASGI application - no FastAPI"""
    if scope['type'] == 'http':
        method = scope['method']
        path = scope['path']

        # Handle CORS preflight
        if method == 'OPTIONS':
            await send({
                'type': 'http.response.start',
                'status': 200,
                'headers': [
                    [b'access-control-allow-origin', b'http://localhost:4000'],
                    [b'access-control-allow-methods', b'GET, POST, PUT, DELETE, OPTIONS'],
                    [b'access-control-allow-headers', b'authorization, content-type'],
                    [b'access-control-allow-credentials', b'true'],
                ],
            })
            await send({
                'type': 'http.response.body',
                'body': b'',
            })
            return

        # Handle all other requests
        response = {"status": "uvicorn-only", "path": path, "method": method}
        body = json.dumps(response).encode()

        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [
                [b'content-type', b'application/json'],
                [b'access-control-allow-origin', b'http://localhost:4000'],
                [b'access-control-allow-methods', b'GET, POST, PUT, DELETE, OPTIONS'],
                [b'access-control-allow-headers', b'authorization, content-type'],
                [b'access-control-allow-credentials', b'true'],
            ],
        })
        await send({
            'type': 'http.response.body',
            'body': body,
        })

if __name__ == "__main__":
    print("=" * 60)
    print("Uvicorn-only test (NO FastAPI)")
    print("=" * 60)
    print(f"Running on {HOST}:{PORT}")
    print("If this gets killed, the issue is UVICORN")
    print("If this survives, the issue is FASTAPI")
    print()
    uvicorn.run(app, host=HOST, port=PORT)
