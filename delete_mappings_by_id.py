#!/usr/bin/env python3
"""
Delete all tenant_user_mapping documents using _all_docs query by ID prefix.
"""

import asyncio
import os
import sys
import httpx

async def delete_all_mappings():
    """Query and delete all tenant_user_mapping documents by ID prefix"""
    
    db_url = os.getenv("COUCHDB_URL", "http://localhost:5984/couch-sitter")
    db_user = os.getenv("COUCHDB_USER", "admin")
    db_password = os.getenv("COUCHDB_PASSWORD", "admin")
    
    auth = (db_user, db_password)
    
    async with httpx.AsyncClient(auth=auth, timeout=30.0) as client:
        # Query all documents with ID starting with "tenant_user_mapping:"
        # First get the list without docs
        params = {
            "startkey": '"tenant_user_mapping:"',
            "endkey": '"tenant_user_mapping:zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"'
        }
        
        print(f"Querying {db_url} for tenant_user_mapping documents...")
        response = await client.get(
            f"{db_url}/_all_docs",
            params=params
        )
        response.raise_for_status()
        result = response.json()
        
        rows = result.get("rows", [])
        doc_ids = [row["id"] for row in rows]
        print(f"Found {len(doc_ids)} mapping document IDs")
        
        if not doc_ids:
            print("No documents to delete.")
            return 0, 0
        
        # Now get full documents with revisions
        print("Fetching documents with revisions...")
        bulk_get = {
            "docs": [{"id": doc_id} for doc_id in doc_ids]
        }
        
        response = await client.post(
            f"{db_url}/_bulk_get",
            json=bulk_get
        )
        response.raise_for_status()
        bulk_result = response.json()
        
        docs = []
        for result_item in bulk_result.get("results", []):
            if "docs" in result_item:
                for doc_result in result_item["docs"]:
                    if "ok" in doc_result:
                        docs.append(doc_result["ok"])
        
        print(f"Retrieved {len(docs)} documents with revisions")
        
        print(f"Found {len(docs)} tenant_user_mapping documents")
        
        if not docs:
            print("No documents to delete.")
            return 0, 0
        
        # Show first few
        print("\nFirst few documents:")
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
        
        print(f"\nDeleting {len(docs)} documents...")
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
            for r in delete_result:
                if r.get("error"):
                    print(f"  {r.get('id')}: {r.get('error')} - {r.get('reason')}")
        
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
