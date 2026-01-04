#!/usr/bin/env python3
"""
Standard library HTTP server - no external dependencies.

Run with: .venv/Scripts/python test_stdlib_server.py
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

HOST = '127.0.0.1'
PORT = 5985

class SimpleHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{self.client_address[1]}] {format % args}")

    def send_cors_headers(self):
        # Must use specific origin (not *) when credentials are included
        self.send_header('Access-Control-Allow-Origin', 'http://localhost:4000')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'authorization, content-type')
        self.send_header('Access-Control-Allow-Credentials', 'true')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_cors_headers()
        self.end_headers()

        response = {"status": "stdlib-server", "path": self.path}
        self.wfile.write(json.dumps(response).encode())

    def do_POST(self):
        self.do_GET()

    def do_PUT(self):
        self.do_GET()

    def do_DELETE(self):
        self.do_GET()

def main():
    print(f"Standard library HTTP server on {HOST}:{PORT}")
    print("Using http.server module - no FastAPI/uvicorn")
    print("Press Ctrl+C to stop\n")

    server = HTTPServer((HOST, PORT), SimpleHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")

if __name__ == "__main__":
    main()
