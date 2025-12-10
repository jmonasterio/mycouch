#!/usr/bin/env python3
"""
Delete all tenant_user_mapping documents using the DAL.
Works with both memory and HTTP backends.
"""

import asyncio
import os
import sys

async def delete_all_mappings():
    """Query and delete all tenant_user_mapping documents"""
    
    from src.couchdb_jwt_proxy.dal import create_dal
    from src.couchdb_jwt_proxy.couch_sitter_service import CouchSitterService
    
    # Always use memory backend and pass URL directly to service
    backend = "memory"
    print(f"Using {backend} DAL with HTTP service calls")
    
    dal = create_dal(backend=backend)
    service = CouchSitterService(
        couch_sitter_db_url=os.getenv("COUCHDB_URL", "http://localhost:5984/couch-sitter"),
        couchdb_user=os.getenv("COUCHDB_USER", "admin"),
        couchdb_password=os.getenv("COUCHDB_PASSWORD", "password"),
        dal=dal
    )
    
    # Query all tenant_user_mapping documents
    query = {
        "selector": {"type": "tenant_user_mapping"},
        "fields": ["_id", "_rev"]
    }
    
    print(f"Querying for tenant_user_mapping documents...")
    
    try:
        result = await service._make_request("POST", "_find", json=query)
        docs = result.json().get("docs", [])
        print(f"Found {len(docs)} tenant_user_mapping documents")
        
        if not docs:
            print("No documents to delete.")
            return 0, 0
        
        # Delete all documents
        bulk_delete = {
            "docs": [
                {"_id": doc["_id"], "_rev": doc["_rev"], "_deleted": True}
                for doc in docs
            ]
        }
        
        print(f"Deleting {len(docs)} documents...")
        response = await service._make_request("POST", "_bulk_docs", json=bulk_delete)
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
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise

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
