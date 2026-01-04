#!/usr/bin/env python3
"""
MyCouch CLI - Bootstrap and management commands

Usage:
    python -m couchdb_jwt_proxy.cli init     # Initialize databases and default apps
    python -m couchdb_jwt_proxy.cli status   # Check database status
"""

import asyncio
import argparse
import httpx
import os
import sys
from dotenv import load_dotenv

# Fix Windows console encoding for Unicode
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Load environment variables
load_dotenv()

COUCHDB_URL = os.getenv("COUCHDB_INTERNAL_URL", "http://localhost:5984")
COUCHDB_USER = os.getenv("COUCHDB_USER", "admin")
COUCHDB_PASSWORD = os.getenv("COUCHDB_PASSWORD", "admin")
CLERK_ISSUER_URL = os.getenv("CLERK_ISSUER_URL", "")


def get_auth():
    """Get basic auth tuple for CouchDB"""
    if COUCHDB_USER and COUCHDB_PASSWORD:
        return (COUCHDB_USER, COUCHDB_PASSWORD)
    return None


async def ensure_database(client: httpx.AsyncClient, db_name: str) -> bool:
    """Ensure a database exists, create if missing"""
    # Check if exists
    response = await client.head(f"{COUCHDB_URL}/{db_name}")
    if response.status_code == 200:
        print(f"  ✓ Database '{db_name}' exists")
        return True

    # Create it
    response = await client.put(f"{COUCHDB_URL}/{db_name}")
    if response.status_code in (201, 202):
        print(f"  ✓ Created database '{db_name}'")
        return True
    else:
        print(f"  ✗ Failed to create '{db_name}': {response.status_code} {response.text}")
        return False


async def ensure_app_document(client: httpx.AsyncClient, app_id: str, app_doc: dict) -> bool:
    """Ensure an application document exists"""
    db_url = f"{COUCHDB_URL}/couch-sitter"

    # Check if exists
    response = await client.get(f"{db_url}/{app_id}")
    if response.status_code == 200:
        print(f"  ✓ App '{app_id}' exists")
        return True

    # Create it
    response = await client.put(
        f"{db_url}/{app_id}",
        json=app_doc,
        headers={"Content-Type": "application/json"}
    )
    if response.status_code in (201, 202):
        print(f"  ✓ Created app '{app_id}'")
        return True
    else:
        print(f"  ✗ Failed to create '{app_id}': {response.status_code} {response.text}")
        return False


async def cmd_init():
    """Initialize MyCouch databases and default applications"""
    print("=" * 60)
    print("MyCouch Initialization")
    print("=" * 60)
    print(f"CouchDB URL: {COUCHDB_URL}")
    print(f"Clerk Issuer: {CLERK_ISSUER_URL or '(not set)'}")
    print()

    async with httpx.AsyncClient(auth=get_auth(), timeout=30.0) as client:
        # Test CouchDB connection
        print("Checking CouchDB connection...")
        try:
            response = await client.get(f"{COUCHDB_URL}/")
            if response.status_code != 200:
                print(f"  ✗ Cannot connect to CouchDB: {response.status_code}")
                return False
            info = response.json()
            print(f"  ✓ Connected to CouchDB {info.get('version', 'unknown')}")
        except Exception as e:
            print(f"  ✗ Cannot connect to CouchDB: {e}")
            return False

        print()
        print("Ensuring databases exist...")

        # Required databases
        databases = ["couch-sitter", "couch-sitter-log", "roady"]
        for db in databases:
            await ensure_database(client, db)

        print()
        print("Ensuring application documents exist...")

        # Default apps - roady and couch-sitter
        if not CLERK_ISSUER_URL:
            print("  ⚠ CLERK_ISSUER_URL not set - using placeholder")
            print("    Set this in your .env file for JWT authentication to work")
            issuer = "https://your-clerk-instance.clerk.accounts.dev"
        else:
            issuer = CLERK_ISSUER_URL

        # Roady app
        await ensure_app_document(client, "app_roady", {
            "_id": "app_roady",
            "type": "application",
            "name": "roady",
            "issuer": issuer,
            "databaseNames": ["roady"],
            "description": "Band equipment checklist app",
            "createdAt": "2025-01-01T00:00:00Z"
        })

        # Couch-sitter app (admin)
        await ensure_app_document(client, "app_couch-sitter", {
            "_id": "app_couch-sitter",
            "type": "application",
            "name": "couch-sitter",
            "issuer": issuer,
            "databaseNames": ["couch-sitter"],
            "description": "Admin dashboard for managing apps, tenants, and users",
            "createdAt": "2025-01-01T00:00:00Z"
        })

        print()
        print("=" * 60)
        print("Initialization complete!")
        print()
        print("Next steps:")
        print("  1. Set CLERK_ISSUER_URL in .env (if not already set)")
        print("  2. Start MyCouch: python -m uvicorn couchdb_jwt_proxy.main:app --port 5985")
        print("=" * 60)
        return True


async def cmd_status():
    """Check database and app status"""
    print("=" * 60)
    print("MyCouch Status")
    print("=" * 60)
    print(f"CouchDB URL: {COUCHDB_URL}")
    print()

    async with httpx.AsyncClient(auth=get_auth(), timeout=30.0) as client:
        # Test CouchDB connection
        try:
            response = await client.get(f"{COUCHDB_URL}/")
            if response.status_code != 200:
                print(f"CouchDB: ✗ Not responding ({response.status_code})")
                return
            info = response.json()
            print(f"CouchDB: ✓ v{info.get('version', 'unknown')}")
        except Exception as e:
            print(f"CouchDB: ✗ Cannot connect ({e})")
            return

        print()
        print("Databases:")
        databases = ["couch-sitter", "couch-sitter-log", "roady"]
        for db in databases:
            response = await client.get(f"{COUCHDB_URL}/{db}")
            if response.status_code == 200:
                info = response.json()
                print(f"  ✓ {db}: {info.get('doc_count', 0)} docs")
            else:
                print(f"  ✗ {db}: not found")

        print()
        print("Applications:")
        response = await client.post(
            f"{COUCHDB_URL}/couch-sitter/_find",
            json={"selector": {"type": "application"}, "fields": ["_id", "name", "issuer"]},
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 200:
            result = response.json()
            docs = result.get("docs", [])
            if docs:
                for doc in docs:
                    print(f"  ✓ {doc.get('name', doc.get('_id'))}: {doc.get('issuer', 'no issuer')}")
            else:
                print("  ✗ No applications found")
        else:
            print(f"  ✗ Cannot query applications: {response.status_code}")


def main():
    parser = argparse.ArgumentParser(
        description="MyCouch CLI - Bootstrap and management commands",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m couchdb_jwt_proxy.cli init      Initialize databases and apps
  python -m couchdb_jwt_proxy.cli status    Check current status
        """
    )
    parser.add_argument(
        "command",
        choices=["init", "status"],
        help="Command to run"
    )

    args = parser.parse_args()

    if args.command == "init":
        asyncio.run(cmd_init())
    elif args.command == "status":
        asyncio.run(cmd_status())


if __name__ == "__main__":
    main()
