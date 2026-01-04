#!/usr/bin/env python3
"""
Simulate PouchDB/couch-sitter traffic patterns to find CrowdStrike trigger.

Run server first: .venv/Scripts/python test_mycouch_minimal.py
Then run this:    .venv/Scripts/python test_pouchdb_sim.py
"""
import asyncio
import httpx
import sys

BASE_URL = "http://127.0.0.1:5985"

async def simulate_pouchdb_sync():
    """Simulate what PouchDB does during sync"""
    async with httpx.AsyncClient(timeout=30.0) as client:

        print("=== Phase 1: Initial connection (like PouchDB) ===")
        # PouchDB first checks the database exists
        r = await client.get(f"{BASE_URL}/couch-sitter/")
        print(f"GET /couch-sitter/ -> {r.status_code}")

        print("\n=== Phase 2: Get changes (like PouchDB sync) ===")
        # PouchDB gets changes feed
        r = await client.get(f"{BASE_URL}/couch-sitter/_changes?style=all_docs&since=0&limit=100")
        print(f"GET /_changes -> {r.status_code}")

        print("\n=== Phase 3: Concurrent requests (like PouchDB bulk) ===")
        # PouchDB makes many concurrent requests
        tasks = []
        for i in range(10):
            tasks.append(client.get(f"{BASE_URL}/couch-sitter/_local/test{i}"))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"  Request {i}: ERROR - {r}")
            else:
                print(f"  Request {i}: {r.status_code}")

        print("\n=== Phase 4: Rapid sequential requests ===")
        for i in range(20):
            r = await client.get(f"{BASE_URL}/")
            print(f"  Request {i}: {r.status_code}")

        print("\n=== Phase 5: Mixed concurrent burst ===")
        tasks = [
            client.get(f"{BASE_URL}/"),
            client.get(f"{BASE_URL}/couch-sitter/"),
            client.get(f"{BASE_URL}/couch-sitter/_changes?since=0"),
            client.get(f"{BASE_URL}/1-basic"),
            client.get(f"{BASE_URL}/2-sync-couchdb"),
            client.get(f"{BASE_URL}/3-async-couchdb"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"  Mixed {i}: ERROR - {r}")
            else:
                print(f"  Mixed {i}: {r.status_code}")

        print("\n=== Phase 6: Heavy concurrent load (50 requests) ===")
        tasks = [client.get(f"{BASE_URL}/") for _ in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = sum(1 for r in results if not isinstance(r, Exception) and r.status_code == 200)
        errors = len(results) - success
        print(f"  50 concurrent: {success} success, {errors} errors")

        print("\n=== DONE - Server survived! ===")

if __name__ == "__main__":
    print("Simulating PouchDB traffic patterns...")
    print("Make sure test_mycouch_minimal.py is running first!\n")
    asyncio.run(simulate_pouchdb_sync())
