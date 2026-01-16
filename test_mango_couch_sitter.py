"""
Test Mango queries against the actual couch-sitter database
to understand why the query returns 0 results.
"""

import httpx
import json
import asyncio

COUCH_URL = "http://localhost:5984"
COUCH_USER = "admin"
COUCH_PASS = "admin"
TEST_DB = "couch-sitter"

# User from the logs
SEARCH_USER = "user_517db1c13a8d598590822ae376af277261ee7c16228e9ec4a58a1d99e9a38ce7"

client = httpx.AsyncClient(auth=(COUCH_USER, COUCH_PASS), timeout=10)


async def test_queries():
    """Test various query patterns against couch-sitter."""
    
    print(f"\n{'='*70}")
    print(f"Testing queries against: {TEST_DB}")
    print(f"Searching for user: {SEARCH_USER[:30]}...")
    print(f"{'='*70}\n")
    
    # TEST 1: Simple query - find documents with this user in array
    print("TEST 1: userIds contains specific user (using Python filter)")
    print("-" * 70)
    try:
        response = await client.post(
            f"{COUCH_URL}/{TEST_DB}/_all_docs",
            json={"include_docs": True}
        )
        
        if response.status_code == 200:
            data = response.json()
            all_docs = data.get("rows", [])
            print(f"Total documents in {TEST_DB}: {len(all_docs)}")
            
            # Filter in Python
            matching = []
            for row in all_docs:
                doc = row.get("doc", {})
                user_ids = doc.get("userIds", [])
                if SEARCH_USER in user_ids:
                    matching.append(doc.get("_id"))
            
            print(f"Documents with user in userIds: {len(matching)}")
            for doc_id in matching:
                print(f"  - {doc_id}")
        else:
            print(f"ERROR: {response.status_code}")
    except Exception as e:
        print(f"EXCEPTION: {e}")
    
    # TEST 2: Query with find (proper Mango)
    print("\n\nTEST 2: Mango query with $elemMatch (no filters)")
    print("-" * 70)
    query = {
        "selector": {
            "userIds": {"$elemMatch": {"$eq": SEARCH_USER}}
        }
    }
    print(f"Query: {json.dumps(query, indent=2)}")
    try:
        response = await client.post(
            f"{COUCH_URL}/{TEST_DB}/_find",
            json=query,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            docs = data.get("docs", [])
            print(f"Results: {len(docs)} documents found")
            for doc in docs:
                print(f"  - {doc.get('_id')}")
        else:
            print(f"ERROR {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"EXCEPTION: {e}")
    
    # TEST 3: Simpler query - exists check
    print("\n\nTEST 3: Simple exists query (userIds exists)")
    print("-" * 70)
    query = {
        "selector": {
            "userIds": {"$exists": True}
        }
    }
    print(f"Query: {json.dumps(query, indent=2)}")
    try:
        response = await client.post(
            f"{COUCH_URL}/{TEST_DB}/_find",
            json=query,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            docs = data.get("docs", [])
            print(f"Results: {len(docs)} documents have userIds field")
        else:
            print(f"ERROR {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"EXCEPTION: {e}")
    
    # TEST 4: Query type=tenant
    print("\n\nTEST 4: Type constraint only")
    print("-" * 70)
    query = {
        "selector": {
            "type": "tenant"
        }
    }
    print(f"Query: {json.dumps(query, indent=2)}")
    try:
        response = await client.post(
            f"{COUCH_URL}/{TEST_DB}/_find",
            json=query,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            docs = data.get("docs", [])
            print(f"Results: {len(docs)} tenant documents")
            
            # Check which ones have the user
            matching = [d for d in docs if SEARCH_USER in d.get("userIds", [])]
            print(f"Of these, {len(matching)} contain the user:")
            for doc in matching:
                print(f"  - {doc.get('_id')}")
        else:
            print(f"ERROR {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"EXCEPTION: {e}")
    
    # TEST 5: Show first few tenant docs
    print("\n\nTEST 5: Showing first 3 tenant documents")
    print("-" * 70)
    try:
        response = await client.post(
            f"{COUCH_URL}/{TEST_DB}/_find",
            json={
                "selector": {"type": "tenant"},
                "limit": 3
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            docs = data.get("docs", [])
            for doc in docs:
                print(f"\n{doc.get('_id')}:")
                print(f"  userIds: {doc.get('userIds', [])}")
                print(f"  type: {doc.get('type')}")
        else:
            print(f"ERROR {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"EXCEPTION: {e}")
    
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(test_queries())
