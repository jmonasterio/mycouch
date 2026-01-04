#!/usr/bin/env python3
"""
Run MyCouch server.

Usage:
    python run.py              # FastAPI/uvicorn (production)
    python run.py --stdlib     # stdlib http.server (CrowdStrike-safe for dev)

    # or with venv
    .venv/Scripts/python run.py
    .venv/Scripts/python run.py --stdlib
"""
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def run_fastapi():
    """Run with FastAPI/uvicorn (production performance)"""
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()
    host = os.getenv("PROXY_HOST", "127.0.0.1")
    port = int(os.getenv("PROXY_PORT", "5985"))
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    print(f"Starting FastAPI/uvicorn server on {host}:{port}")
    print("  Options: http=h11 (HTTP/1.1 only), ws=none (no WebSocket)")
    uvicorn.run(
        'couchdb_jwt_proxy.main:app',
        host=host,
        port=port,
        log_level=log_level,
        http='h11',   # Force HTTP/1.1 only (disable HTTP/2)
        ws='none',    # Disable WebSocket support
    )


def run_stdlib():
    """Run with stdlib http.server (CrowdStrike-safe)"""
    from stdlib_server import main as stdlib_main
    stdlib_main()


if __name__ == "__main__":
    use_stdlib = "--stdlib" in sys.argv or "-s" in sys.argv

    if use_stdlib:
        print("=" * 60)
        print("  MODE: stdlib http.server (CrowdStrike-safe)")
        print("  Note: Use FastAPI in production for better performance")
        print("=" * 60)
        run_stdlib()
    else:
        run_fastapi()
