#!/usr/bin/env python3
"""
Delete all tenant_user_mapping documents using _find query.
"""

import asyncio
import os
import sys
import httpx

async def delete_all_mappings():
    """Query and delete all tenant_user_mapping documents"""
    
    db_url = os.getenv("COUCHDB_URL", "http://localhost:5984/couch-sitter")
    db_user = os.getenv("COUCHDB_USER", "admin")
    db_password = os.getenv("COUCHDB_PASSWORD", "admin")
    
    auth = (db_user, db_password)
    
    async with httpx.AsyncClient(auth=auth, timeout=30.0) as client:
        # Query all tenant_user_mapping documents
        query = {
            "selector": {
                "_id": {"$regex": "^tenant_user_mapping:"}
            },
            "fields": ["_id", "_rev"],
            "limit": 10000
        }
        
        print(f"Querying {db_url}/_find for tenant_user_mapping documents...")
        try:
            response = await client.post(
                f"{db_url}/_find",
                json=query,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            result = response.json()
        except Exception as e:
            print(f"_find failed: {e}")
            print("Trying with type selector instead...")
            
            query = {
                "selector": {
                    "type": "tenant_user_mapping"
                },
                "fields": ["_id", "_rev"],
                "limit": 10000
            }
            
            response = await client.post(
                f"{db_url}/_find",
                json=query
            )
            response.raise_for_status()
            result = response.json()
        
        docs = result.get("docs", [])
        print(f"Found {len(docs)} tenant_user_mapping documents")
        
        if not docs:
            print("No documents to delete.")
            return 0, 0
        
        # Show first few
        print("\nFirst few document IDs:")
        for doc in docs[:3]:
            print(f"  - {doc['_id']}")
        if len(docs) > 3:
            print(f"  ... and {len(docs) - 3} more")
        
        # Delete all documents
        bulk_delete = {
            "docs": [
                {"_id": doc["_id"], "_rev": doc["_rev"], "_deleted": True}
                for doc in docs
            ]
        }
        
        print(f"\nDeleting {len(docs)} documents via _bulk_docs...")
        response = await client.post(
            f"{db_url}/_bulk_docs",
            json=bulk_delete
        )
        response.raise_for_status()
        delete_result = response.json()
        
        # Check results
        successful = sum(1 for r in delete_result if not r.get("error"))
        failed = sum(1 for r in delete_result if r.get("error"))
        
        print(f"\nDeletion complete:")
        print(f"  Successful: {successful}")
        print(f"  Failed: {failed}")
        
        if failed > 0:
            print("\nFailures:")
            for r in delete_result[:10]:
                if r.get("error"):
                    print(f"  {r.get('id')}: {r.get('error')} - {r.get('reason', '')}")
            if failed > 10:
                print(f"  ... and {failed - 10} more failures")
        
        return successful, failed

async def main():
    try:
        successful, failed = await delete_all_mappings()
        if failed > 0:
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
