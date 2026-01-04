#!/usr/bin/env python3
"""
Ultra-minimal HTTP server - no FastAPI, no uvicorn, just raw sockets.

Run with: .venv/Scripts/python test_raw_server.py
Then try: curl http://127.0.0.1:5985/
And:      Open browser to http://127.0.0.1:5985/
"""
import socket
import threading

HOST = '127.0.0.1'
PORT = 5985

RESPONSE = b"""HTTP/1.1 200 OK\r
Content-Type: application/json\r
Access-Control-Allow-Origin: *\r
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS\r
Access-Control-Allow-Headers: authorization, content-type\r
Content-Length: 25\r
\r
{"status":"raw-server"}"""

OPTIONS_RESPONSE = b"""HTTP/1.1 200 OK\r
Access-Control-Allow-Origin: *\r
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS\r
Access-Control-Allow-Headers: authorization, content-type\r
Content-Length: 0\r
\r
"""

def handle_client(conn, addr):
    try:
        data = conn.recv(4096)
        if data:
            request_line = data.split(b'\r\n')[0].decode()
            print(f"[{addr[1]}] {request_line}")

            if request_line.startswith('OPTIONS'):
                conn.sendall(OPTIONS_RESPONSE)
            else:
                conn.sendall(RESPONSE)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

def main():
    print(f"Raw HTTP server on {HOST}:{PORT}")
    print("No FastAPI, no uvicorn - just raw sockets")
    print("Press Ctrl+C to stop\n")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)

    request_count = 0
    try:
        while True:
            conn, addr = server.accept()
            request_count += 1
            print(f"[{request_count}] Connection from {addr}")
            thread = threading.Thread(target=handle_client, args=(conn, addr))
            thread.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.close()

if __name__ == "__main__":
    main()
