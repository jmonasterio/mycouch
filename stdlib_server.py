#!/usr/bin/env python3
"""
CouchDB JWT Proxy using Python stdlib http.server.

This bypasses FastAPI/uvicorn to avoid CrowdStrike kills.
Uses synchronous http.server with shared core modules.

Run with: .venv/Scripts/python stdlib_server.py
"""
import json
import logging
import threading
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, Tuple

# Import shared core modules
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from couchdb_jwt_proxy.core import (
    Config,
    setup_logging,
    verify_jwt,
    extract_bearer_token,
    load_applications,
    proxy_request,
    handle_create_tenant,
    handle_list_tenants,
    handle_get_tenant,
    handle_update_tenant,
    handle_delete_tenant,
    handle_get_user,
    handle_update_user,
    handle_delete_user,
)

# Setup logging
logger = setup_logging()

# Application configuration (loaded from couch-sitter db)
APPLICATIONS: Dict[str, Dict[str, Any]] = {}

# CORS configuration
ALLOWED_ORIGINS = Config.get_allowed_origins()
logger.info(f"CORS allowed origins: {ALLOWED_ORIGINS}")


class CouchDBProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler that proxies to CouchDB with JWT auth."""

    timeout = 300  # Long-polling support

    def log_message(self, format, *args):
        logger.info(f"[{self.client_address[0]}] {format % args}")

    def get_cors_origin(self) -> Optional[str]:
        """Get allowed CORS origin from request."""
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            return origin
        if origin.rstrip("/") in [o.rstrip("/") for o in ALLOWED_ORIGINS]:
            return origin
        return None

    def send_cors_headers(self, origin: Optional[str] = None):
        """Send CORS headers."""
        self.send_header("Access-Control-Allow-Origin", origin or "http://localhost:4000")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Accept, X-Requested-With")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def send_json_response(self, status: int, data: Any, origin: Optional[str] = None):
        """Send JSON response with CORS headers."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_cors_headers(origin)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def send_error_response(self, status: int, message: str, origin: Optional[str] = None):
        """Send JSON error response."""
        self.send_json_response(status, {"error": message}, origin)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        origin = self.get_cors_origin()
        self.send_response(200)
        self.send_cors_headers(origin)
        self.end_headers()

    def verify_authorization(self) -> Tuple[Optional[Dict], Optional[str]]:
        """Verify JWT from Authorization header."""
        auth_header = self.headers.get("Authorization", "")
        token = extract_bearer_token(auth_header)

        if not token:
            return None, "Missing or invalid Authorization header"

        payload, error = verify_jwt(token, APPLICATIONS)
        if not payload:
            return None, f"JWT validation failed: {error}"

        return payload, None

    def read_body(self) -> bytes:
        """Read request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(content_length) if content_length > 0 else b""

    def read_json_body(self) -> Dict:
        """Read and parse JSON body."""
        body = self.read_body()
        if not body:
            return {}
        try:
            return json.loads(body.decode())
        except json.JSONDecodeError:
            return {}

    def handle_virtual_tables(self, method: str) -> bool:
        """Handle virtual table endpoints. Returns True if handled."""
        path = self.path.split("?")[0]
        origin = self.get_cors_origin()

        if not path.startswith("/__tenants") and not path.startswith("/__users"):
            return False

        # Verify JWT
        payload, error = self.verify_authorization()
        if error:
            logger.warning(f"Virtual table auth failed: {error}")
            self.send_error_response(401, error, origin)
            return True

        user_id = payload.get("sub")
        if not user_id:
            self.send_error_response(400, "Missing 'sub' in JWT", origin)
            return True

        body_data = self.read_json_body() if method in ("POST", "PUT") else {}

        try:
            # /__tenants endpoints
            if path == "/__tenants":
                if method == "GET":
                    status, result = handle_list_tenants(user_id)
                elif method == "POST":
                    status, result = handle_create_tenant(user_id, body_data)
                else:
                    self.send_error_response(405, f"Method {method} not allowed", origin)
                    return True
                self.send_json_response(status, result, origin)
                return True

            # /__tenants/<id>
            tenant_match = re.match(r'^/__tenants/([^/]+)$', path)
            if tenant_match:
                tenant_id = tenant_match.group(1)
                if method == "GET":
                    status, result = handle_get_tenant(tenant_id, user_id)
                elif method == "PUT":
                    status, result = handle_update_tenant(tenant_id, user_id, body_data)
                elif method == "DELETE":
                    active = payload.get("active_tenant_id")
                    status, result = handle_delete_tenant(tenant_id, user_id, active)
                else:
                    self.send_error_response(405, f"Method {method} not allowed", origin)
                    return True
                self.send_json_response(status, result, origin)
                return True

            # /__users/<id>
            user_match = re.match(r'^/__users/([^/]+)$', path)
            if user_match:
                user_hash = user_match.group(1)
                if method == "GET":
                    status, result = handle_get_user(user_hash, user_id)
                elif method == "PUT":
                    status, result = handle_update_user(user_hash, user_id, body_data)
                elif method == "DELETE":
                    status, result = handle_delete_user(user_hash, user_id)
                else:
                    self.send_error_response(405, f"Method {method} not allowed", origin)
                    return True
                self.send_json_response(status, result, origin)
                return True

            self.send_error_response(404, f"Virtual endpoint not found: {path}", origin)
            return True

        except Exception as e:
            logger.error(f"Virtual table error: {e}")
            self.send_error_response(500, f"Internal error: {e}", origin)
            return True

    def proxy_to_couchdb(self, method: str):
        """Proxy request to CouchDB."""
        origin = self.get_cors_origin()
        path = self.path

        # Root path is public (health check)
        is_public = (method == "GET" and path == "/")

        if not is_public:
            payload, error = self.verify_authorization()
            if error:
                logger.warning(f"Auth failed: {error}")
                self.send_error_response(401, error, origin)
                return
            logger.info(f"Authenticated user: {payload.get('sub', 'unknown')}")

        # Read body and force application/json for POST/PUT
        body = self.read_body()
        if method in ("POST", "PUT") and body:
            # PouchDB sends text/plain, CouchDB needs application/json
            pass  # proxy_request handles Content-Type

        # Detect long-polling
        is_long_poll = "_changes" in path and ("feed=longpoll" in path or "feed=continuous" in path)
        timeout = 300 if is_long_poll else 30

        # Proxy the request
        content, status, content_type = proxy_request(path, method, body, timeout)

        # Send response
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_cors_headers(origin)
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if not self.handle_virtual_tables("GET"):
            self.proxy_to_couchdb("GET")

    def do_POST(self):
        if not self.handle_virtual_tables("POST"):
            self.proxy_to_couchdb("POST")

    def do_PUT(self):
        if not self.handle_virtual_tables("PUT"):
            self.proxy_to_couchdb("PUT")

    def do_DELETE(self):
        if not self.handle_virtual_tables("DELETE"):
            self.proxy_to_couchdb("DELETE")


class ThreadedHTTPServer(HTTPServer):
    """HTTP server that handles each request in a new thread."""

    def process_request(self, request, client_address):
        thread = threading.Thread(target=self.process_request_thread, args=(request, client_address))
        thread.daemon = True
        thread.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def main():
    global APPLICATIONS

    print("=" * 60)
    print("  CouchDB JWT Proxy (stdlib version)")
    print("  Bypasses FastAPI/uvicorn to avoid CrowdStrike kills")
    print("=" * 60)
    print(f"  Host: {Config.PROXY_HOST}")
    print(f"  Port: {Config.PROXY_PORT}")
    print(f"  CouchDB: {Config.COUCHDB_INTERNAL_URL}")
    print(f"  Log Level: {Config.LOG_LEVEL}")
    print("=" * 60)

    # Load application configurations
    logger.info("Loading applications from couch-sitter...")
    APPLICATIONS = load_applications()

    # Create threaded server
    server = ThreadedHTTPServer((Config.PROXY_HOST, Config.PROXY_PORT), CouchDBProxyHandler)

    print(f"\nStdlib HTTP server listening on http://{Config.PROXY_HOST}:{Config.PROXY_PORT}")
    print("Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
