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

@pytest.fixture
def mock_couch_sitter_jwt_payload():
    """Mock Clerk JWT payload for couch-sitter admin app"""
    return {
        "sub": "user_admin123",
        "email": "admin@example.com",
        "iss": "https://enabled-hawk-56.clerk.accounts.dev", # Known couch-sitter issuer
        "aud": "couch-sitter",
        "iat": 1699561200,
        "exp": 1699564800
    }

@pytest.mark.asyncio
class TestLocalDocs:
    """Test access to _local documents"""

    async def test_get_local_doc(self, async_client, mock_couch_sitter_jwt_payload):
        """Test GET /dbname/_local/docid"""
        
        # Mock dependencies
        with patch('couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify, \
             patch('couchdb_jwt_proxy.main.couch_sitter_service') as mock_couch_sitter, \
             patch('couchdb_jwt_proxy.main.clerk_service') as mock_clerk_service, \
             patch('couchdb_jwt_proxy.main.APPLICATIONS', {"https://enabled-hawk-56.clerk.accounts.dev": ["couch-sitter"]}):

            mock_verify.return_value = (mock_couch_sitter_jwt_payload, None)

            # Mock tenant extraction
            mock_couch_sitter.get_user_tenant_info = AsyncMock(return_value=MagicMock(
                tenant_id="tenant_123",
                user_id="user_admin123",
                sub=mock_couch_sitter_jwt_payload["sub"]
            ))
            
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
