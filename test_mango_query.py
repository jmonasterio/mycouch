"""
Test different Mango query syntaxes for querying array fields in CouchDB.
Tests against local CouchDB at localhost:5984 with admin/admin credentials.
"""

import httpx
import json
import asyncio
from typing import Dict, Any, List
import sys
import io

# Force UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# CouchDB connection
COUCH_URL = "http://localhost:5984"
COUCH_USER = "admin"
COUCH_PASS = "admin"
TEST_DB = "test_mango_queries"

# Test user IDs
USER_1 = "user_alice"
USER_2 = "user_bob"
USER_3 = "user_charlie"
SEARCH_USER = "user_bob"

client = httpx.AsyncClient(auth=(COUCH_USER, COUCH_PASS))


async def setup_db():
    """Create test database and populate with sample tenant documents."""
    print("\n=== SETUP: Creating test database ===")
    
    # Delete test DB if it exists
    try:
        await client.delete(f"{COUCH_URL}/{TEST_DB}")
        print("Deleted existing test_mango_queries")
    except:
        pass
    
    # Create test DB
    response = await client.put(f"{COUCH_URL}/{TEST_DB}")
    print("Created test_mango_queries")
    
    # Create indexes on fields used in queries
    indexes = [
        {
            "index": {
                "fields": ["userIds"]
            },
            "name": "idx-userIds",
            "type": "json"
        },
        {
            "index": {
                "fields": ["type", "userIds"]
            },
            "name": "idx-type-userIds",
            "type": "json"
        },
        {
            "index": {
                "fields": ["deletedAt"]
            },
            "name": "idx-deletedAt",
            "type": "json"
        }
    ]
    
    for idx in indexes:
        try:
            response = await client.post(f"{COUCH_URL}/{TEST_DB}/_index", json=idx)
            print(f"Created index: {idx['name']}")
        except Exception as e:
            print(f"Index creation: {e}")
    
    # Create sample documents
    docs = [
        {
            "_id": "tenant_00001",
            "type": "tenant",
            "name": "Band A",
            "userIds": [USER_1, USER_3],
            "createdAt": "2025-01-01T00:00:00Z"
        },
        {
            "_id": "tenant_00002",
            "type": "tenant",
            "name": "Band B",
            "userIds": [USER_2, USER_3],
            "createdAt": "2025-01-02T00:00:00Z"
        },
        {
            "_id": "tenant_00003",
            "type": "tenant",
            "name": "Band C",
            "userIds": [USER_1, USER_2],
            "createdAt": "2025-01-03T00:00:00Z"
        },
        {
            "_id": "tenant_00004",
            "type": "tenant",
            "name": "Band D (deleted)",
            "userIds": [USER_2],
            "deletedAt": "2025-01-04T00:00:00Z",
            "createdAt": "2025-01-04T00:00:00Z"
        },
        {
            "_id": "tenant_old_format_00005",
            "name": "Old Band (no type)",
            "userIds": [USER_1, USER_2],
            "createdAt": "2025-01-05T00:00:00Z"
        }
    ]
    
    for doc in docs:
        response = await client.put(f"{COUCH_URL}/{TEST_DB}/{doc['_id']}", json=doc)
        print(f"Created {doc['_id']}")
    
    print("\nDocuments in test DB:")
    for doc in docs:
        print(f"  - {doc['_id']}: userIds={doc.get('userIds', [])}, deletedAt={doc.get('deletedAt')}")


async def test_query(name: str, query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute a Mango query and return results."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"QUERY: {json.dumps(query, indent=2)}")
    print("-" * 60)
    
    try:
        response = await client.post(
            f"{COUCH_URL}/{TEST_DB}/_find",
            json=query,
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"ERROR {response.status_code}: {response.text}")
            return []
        
        data = response.json()
        docs = data.get("docs", [])
        
        print("Query executed successfully")
        print(f"Results: {len(docs)} documents found")
        
        for doc in docs:
            print(f"  - {doc.get('_id')}: userIds={doc.get('userIds', [])}")
        
        return docs
        
    except Exception as e:
        print(f"EXCEPTION: {e}")
        return []


async def run_tests():
    """Run all Mango query syntax tests."""
    await setup_db()
    
    results = {}
    
    # TEST 1: $elemMatch with $eq (current approach)
    docs = await test_query(
        "$elemMatch with $eq operator",
        {
            "selector": {
                "userIds": {"$elemMatch": {"$eq": SEARCH_USER}},
                "$and": [
                    {"deletedAt": {"$exists": False}},
                    {"deleted": {"$ne": True}}
                ]
            }
        }
    )
    results["elemMatch_eq"] = len(docs)
    
    # TEST 2: Direct value match (without operators)
    docs = await test_query(
        "Direct value match (userIds: value)",
        {
            "selector": {
                "userIds": SEARCH_USER,
                "$and": [
                    {"deletedAt": {"$exists": False}},
                    {"deleted": {"$ne": True}}
                ]
            }
        }
    )
    results["direct_value"] = len(docs)
    
    # TEST 3: $in operator (original approach)
    docs = await test_query(
        "$in operator (original broken approach)",
        {
            "selector": {
                "userIds": {"$in": [SEARCH_USER]},
                "$and": [
                    {"deletedAt": {"$exists": False}},
                    {"deleted": {"$ne": True}}
                ]
            }
        }
    )
    results["in_operator"] = len(docs)
    
    # TEST 4: $elemMatch with regex
    docs = await test_query(
        "$elemMatch with $regex",
        {
            "selector": {
                "userIds": {"$elemMatch": {"$regex": f"^{SEARCH_USER}$"}},
                "$and": [
                    {"deletedAt": {"$exists": False}},
                    {"deleted": {"$ne": True}}
                ]
            }
        }
    )
    results["elemMatch_regex"] = len(docs)
    
    # TEST 5: $allMatch (if supported)
    docs = await test_query(
        "$allMatch operator",
        {
            "selector": {
                "userIds": {"$allMatch": {"$eq": SEARCH_USER}},
                "$and": [
                    {"deletedAt": {"$exists": False}},
                    {"deleted": {"$ne": True}}
                ]
            }
        }
    )
    results["allMatch"] = len(docs)
    
    # TEST 6: No deletion filter to test basic query
    docs = await test_query(
        "$elemMatch without deletion filter",
        {
            "selector": {
                "userIds": {"$elemMatch": {"$eq": SEARCH_USER}}
            }
        }
    )
    results["elemMatch_no_filter"] = len(docs)
    
    # TEST 7: Type constraint + elemMatch
    docs = await test_query(
        "Type constraint + $elemMatch",
        {
            "selector": {
                "type": "tenant",
                "userIds": {"$elemMatch": {"$eq": SEARCH_USER}},
                "$and": [
                    {"deletedAt": {"$exists": False}},
                    {"deleted": {"$ne": True}}
                ]
            }
        }
    )
    results["type_elemMatch"] = len(docs)
    
    # TEST 8: Manual fetch all (should return all non-deleted)
    docs = await test_query(
        "Fetch all non-deleted docs (no user filter)",
        {
            "selector": {
                "$and": [
                    {"deletedAt": {"$exists": False}},
                    {"deleted": {"$ne": True}}
                ]
            }
        }
    )
    results["fetch_all"] = len(docs)
    
    # SUMMARY
    print(f"\n\n{'='*60}")
    print("SUMMARY OF RESULTS")
    print(f"{'='*60}")
    print(f"Expected: 3 documents should match user '{SEARCH_USER}'")
    print(f"(tenant_00002, tenant_00003, tenant_old_format_00005)\n")
    
    for test_name, count in results.items():
        status = "WORKS" if count == 3 else "FAILS"
        print(f"{test_name:30} -> {count:2} docs {status}")
    
    # Cleanup
    print(f"\n{'='*60}")
    print("CLEANUP")
    await client.delete(f"{COUCH_URL}/{TEST_DB}")
    print("Deleted test_mango_queries")


if __name__ == "__main__":
    asyncio.run(run_tests())
