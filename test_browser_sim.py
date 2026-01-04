#!/usr/bin/env python3
"""
Simulate BROWSER traffic patterns with proper headers.

Run server first: .venv/Scripts/python test_mycouch_minimal.py
Then run this:    .venv/Scripts/python test_browser_sim.py
"""
import asyncio
import httpx

BASE_URL = "http://127.0.0.1:5985"

# Simulate browser headers
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": "http://localhost:4000",
    "Referer": "http://localhost:4000/",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

async def test_phase(name: str, requests_fn):
    print(f"\n=== {name} ===")
    try:
        await requests_fn()
        print("  OK - Survived")
        return True
    except Exception as e:
        print(f"  FAILED: {e}")
        return False

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:

        # Phase 1: Just browser User-Agent
        async def phase1():
            headers = {"User-Agent": BROWSER_HEADERS["User-Agent"]}
            r = await client.get(f"{BASE_URL}/", headers=headers)
            print(f"  GET / with User-Agent -> {r.status_code}")
        await test_phase("Phase 1: Browser User-Agent only", phase1)

        await asyncio.sleep(2)

        # Phase 2: Add Origin header (CORS trigger)
        async def phase2():
            headers = {
                "User-Agent": BROWSER_HEADERS["User-Agent"],
                "Origin": "http://localhost:4000",
            }
            r = await client.get(f"{BASE_URL}/", headers=headers)
            print(f"  GET / with Origin -> {r.status_code}")
        await test_phase("Phase 2: With Origin header", phase2)

        await asyncio.sleep(2)

        # Phase 3: OPTIONS preflight (like browser CORS)
        async def phase3():
            headers = {
                "Origin": "http://localhost:4000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            }
            r = await client.options(f"{BASE_URL}/couch-sitter/", headers=headers)
            print(f"  OPTIONS preflight -> {r.status_code}")
        await test_phase("Phase 3: CORS preflight OPTIONS", phase3)

        await asyncio.sleep(2)

        # Phase 4: Full browser headers
        async def phase4():
            r = await client.get(f"{BASE_URL}/", headers=BROWSER_HEADERS)
            print(f"  GET / with full browser headers -> {r.status_code}")
        await test_phase("Phase 4: Full browser headers", phase4)

        await asyncio.sleep(2)

        # Phase 5: Multiple concurrent with browser headers
        async def phase5():
            tasks = [client.get(f"{BASE_URL}/", headers=BROWSER_HEADERS) for _ in range(10)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success = sum(1 for r in results if not isinstance(r, Exception))
            print(f"  10 concurrent browser requests: {success}/10 success")
        await test_phase("Phase 5: Concurrent browser requests", phase5)

        await asyncio.sleep(2)

        # Phase 6: Simulate PouchDB with browser headers
        async def phase6():
            # OPTIONS then GET pattern
            opt_headers = {
                "Origin": "http://localhost:4000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            }
            await client.options(f"{BASE_URL}/couch-sitter/", headers=opt_headers)

            get_headers = {**BROWSER_HEADERS, "Authorization": "Bearer fake-jwt-token"}
            r = await client.get(f"{BASE_URL}/couch-sitter/", headers=get_headers)
            print(f"  OPTIONS + GET with Auth header -> {r.status_code}")
        await test_phase("Phase 6: OPTIONS + GET with Authorization", phase6)

        print("\n=== ALL PHASES COMPLETE - Server survived browser simulation! ===")

if __name__ == "__main__":
    print("Simulating BROWSER traffic patterns...")
    print("Make sure test_mycouch_minimal.py is running first!\n")
    asyncio.run(main())
