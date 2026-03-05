import pytest
import json
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
import pytest_asyncio

from couchdb_jwt_proxy.main import app, dal

# Test fixtures
@pytest_asyncio.fixture
async def async_client():
    """FastAPI TestClient for async testing"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
class TestLocalDocs:
    """Test access to _local documents"""

    async def test_get_local_doc(self, async_client):
        """Test GET /dbname/_local/docid"""

        with patch('couchdb_jwt_proxy.main.verify_session_token', return_value={'pubkey': 'a' * 64, 'user_id': 'user_admin123'}), \
             patch('couchdb_jwt_proxy.main.extract_tenant', new_callable=AsyncMock, return_value='tenant_admin_123'):

            # Populate Memory DAL with local doc
            # Note: The doc_id in the URL will be URL-encoded, but we store it decoded
            doc_id_encoded = "bYxg4wx2CFPpDakNrACmCA%3D%3D"
            doc_id_decoded = "bYxg4wx2CFPpDakNrACmCA=="
            local_doc = {"_id": f"_local/{doc_id_decoded}", "rev": "1-abc"}

            await dal.get(f"/couch-sitter/_local/{doc_id_decoded}", "PUT", local_doc)

            # Make request to _local doc (URL will have encoded version)
            response = await async_client.get(
                f"/couch-sitter/_local/{doc_id_encoded}",
                headers={"Authorization": "Bearer valid-token"}
            )

            assert response.status_code == 200, f"Expected 200, got {response.status_code}. Body: {response.text}"
            # The response should have the decoded ID
            assert "_local" in response.json()["_id"]
