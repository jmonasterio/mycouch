#!/usr/bin/env python3
"""
Delete all tenant_user_mapping documents from couch-sitter database.
"""

import asyncio
import os
import sys
import httpx
from typing import List, Dict, Any

async def delete_all_mappings():
    """Query and delete all tenant_user_mapping documents"""
    
    db_url = os.getenv("COUCHDB_URL", "http://localhost:5984/couch-sitter")
    db_user = os.getenv("COUCHDB_USER", "admin")
    db_password = os.getenv("COUCHDB_PASSWORD", "password")
    
    auth = (db_user, db_password)
    
    async with httpx.AsyncClient(auth=auth, timeout=30.0) as client:
        # Query all tenant_user_mapping documents
        query = {
            "selector": {"type": "tenant_user_mapping"},
            "fields": ["_id", "_rev"]
        }
        
        print(f"Querying couch-sitter for tenant_user_mapping documents...")
        response = await client.post(
            f"{db_url}/_find",
            json=query
        )
        response.raise_for_status()
        result = response.json()
        
        docs = result.get("docs", [])
        print(f"Found {len(docs)} tenant_user_mapping documents to delete")
        
        if not docs:
            print("No documents to delete.")
            return
        
        # Delete all documents
        bulk_delete = {
            "docs": [
                {"_id": doc["_id"], "_rev": doc["_rev"], "_deleted": True}
                for doc in docs
            ]
        }
        
        print(f"Deleting {len(docs)} documents...")
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
                    print(f"  {r.get('id')}: {r.get('error')}")
        
        return successful, failed

async def main():
    try:
        successful, failed = await delete_all_mappings()
        if failed > 0:
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
