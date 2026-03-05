import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
import pytest_asyncio

from couchdb_jwt_proxy.main import app, TENANT_FIELD, dal

# Test fixtures
@pytest_asyncio.fixture
async def async_client():
    """FastAPI TestClient for async testing"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
class TestCouchSitterVisibility:
    """Test that couch-sitter admin app can see all documents"""

    async def test_couch_sitter_sees_all_docs(self, async_client):
        """Test that couch-sitter app sees docs even without tenant ID or with different tenant ID"""

        with patch('couchdb_jwt_proxy.main.verify_session_token', return_value={'pubkey': 'a' * 64, 'user_id': 'user_admin123'}), \
             patch('couchdb_jwt_proxy.main.extract_tenant', new_callable=AsyncMock, return_value='tenant_personal_123'), \
             patch('couchdb_jwt_proxy.main.is_couch_sitter_app', return_value=True):

            personal_tenant_id = "tenant_personal_123"

            # Populate Memory DAL with various docs
            # 1. App doc (no tenant ID)
            await dal.get("/couch-sitter/app_1", "PUT", {"_id": "app_1", "type": "application", "name": "App 1"})

            # 2. User doc (different tenant ID)
            await dal.get("/couch-sitter/user_2", "PUT", {"_id": "user_2", "type": "user", "name": "User 2", TENANT_FIELD: "tenant_other"})

            # 3. Tenant doc (different tenant ID)
            await dal.get("/couch-sitter/tenant_3", "PUT", {"_id": "tenant_3", "type": "tenant", "name": "Tenant 3", TENANT_FIELD: "tenant_other"})

            # 4. Personal doc (matching tenant ID)
            await dal.get("/couch-sitter/doc_4", "PUT", {"_id": "doc_4", "type": "note", "name": "My Note", TENANT_FIELD: personal_tenant_id})

            # Make request to _all_docs
            response = await async_client.get(
                "/couch-sitter/_all_docs?include_docs=true",
                headers={"Authorization": "Bearer valid-token"}
            )

            assert response.status_code == 200
            data = response.json()

            # Check what was returned
            returned_ids = [row["id"] for row in data["rows"]]
            print(f"Returned IDs: {returned_ids}")

            # Assert that ALL docs are present
            assert "app_1" in returned_ids, "Couch-sitter should see app docs (no tenant ID)"
            assert "user_2" in returned_ids, "Couch-sitter should see other users"
            assert "tenant_3" in returned_ids, "Couch-sitter should see other tenants"
            assert "doc_4" in returned_ids, "Couch-sitter should see personal docs"
