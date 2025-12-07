import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import pytest
from unittest.mock import MagicMock, AsyncMock
from couchdb_jwt_proxy.couch_sitter_service import CouchSitterService

@pytest.mark.asyncio
async def test_verify_admin_naming_fix():
    # Setup
    mock_dal = MagicMock()
    service = CouchSitterService("http://mock-db", dal=mock_dal)
    
    # Simulate existing user with "Admin" name
    sub = "user_123"
    sub_hash = service._hash_sub(sub)
    user_id = f"user_{sub_hash}"
    admin_tenant_id = "tenant_couch_sitter_admins"
    personal_tenant_id = "tenant_personal_123"
    
    existing_user_doc = {
        "_id": user_id,
        "type": "user",
        "sub": sub,
        "name": f"Admin {sub[:8]}", # Bad name
        "personalTenantId": personal_tenant_id,
        "tenants": [
            {
                "tenantId": personal_tenant_id,
                "role": "owner",
                "personal": True
            }
        ],
        "tenantIds": [personal_tenant_id],
        "activeTenantId": personal_tenant_id
    }
    
    existing_tenant_doc = {
        "_id": personal_tenant_id,
        "type": "tenant",
        "name": f"Admin {sub[:8]}", # Bad tenant name
        "isPersonal": True
    }
    
    # Mock DAL responses
    async def mock_get(path, method, payload=None):
        print(f"Mock DAL called: {method} {path}")
        if path.endswith("_find"):
            return {"docs": [existing_user_doc]}
        if path.endswith(personal_tenant_id):
            return existing_tenant_doc
        return {}

    mock_dal.get = AsyncMock(side_effect=mock_get)
    
    # Act: Call ensure_user_exists with better info
    better_name = "Real User"
    better_email = "real@example.com"
    
    user_info = await service.ensure_user_exists(
        sub=sub,
        email=better_email,
        name=better_name,
        requested_db_name="roady"
    )
    
    # Assert
    # We expect PUT calls to update user and tenant
    
    put_calls = [
        args for args, _ in mock_dal.get.call_args_list 
        if args[1] == "PUT"
    ]
    
    user_updates = [args for args in put_calls if args[0].endswith(user_id)]
    tenant_updates = [args for args in put_calls if args[0].endswith(personal_tenant_id)]
    
    print(f"PUT calls to user: {len(user_updates)}")
    print(f"PUT calls to tenant: {len(tenant_updates)}")
    
    assert len(user_updates) > 0, "Expected user update"
    assert len(tenant_updates) > 0, "Expected tenant update"
    
    # Verify content of updates
    user_update_doc = user_updates[-1][2] # payload is 3rd arg
    tenant_update_doc = tenant_updates[-1][2]
    
    assert user_update_doc["name"] == better_name
    assert "Real User's Workspace" in tenant_update_doc["name"] or "real's Workspace" in tenant_update_doc["name"]
    
    # Verify applicationId update
    assert tenant_update_doc.get("applicationId") == "roady", f"Expected applicationId 'roady', got {tenant_update_doc.get('applicationId')}"
    print("✅ Verified applicationId updated to 'roady'")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_verify_admin_naming_fix())
