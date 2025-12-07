"""
Tests for admin tenant protection in the JWT proxy.
"""
import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from couchdb_jwt_proxy.main import app, dal

ADMIN_TENANT_ID = "tenant_couch_sitter_admins"

@pytest.fixture
def mock_auth():
    """Mock Clerk JWT validation and tenant extraction."""
    with patch('couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify, \
         patch('couchdb_jwt_proxy.main.extract_tenant') as mock_extract:
        
        # Mock successful auth
        mock_verify.return_value = (
            {
                'sub': 'user_123',
                'iss': 'https://enabled-hawk-56.clerk.accounts.dev',
                'email': 'test@example.com'
            },
            None
        )
        mock_extract.return_value = 'tenant_abc'
        yield

@pytest.fixture
def setup_memory_dal():
    """Populate Memory DAL with test data."""
    async def populate():
        # Clear existing data
        if hasattr(dal.backend, '_docs'):
            dal.backend._docs.clear()
            
        # Add admin tenant doc
        admin_doc = {
            "_id": ADMIN_TENANT_ID,
            "type": "tenant",
            "name": "Couch-Sitter Administrators"
        }
        await dal.get(f"couch-sitter/{ADMIN_TENANT_ID}", "PUT", admin_doc)
        
        # Add a dummy doc
        await dal.get("couch-sitter/other_doc", "PUT", {"_id": "other_doc", "type": "doc"})

    asyncio.run(populate())
    yield
    # Cleanup
    if hasattr(dal.backend, '_docs'):
        dal.backend._docs.clear()

class TestAdminTenantProtection:
    """Test protection against deleting the admin tenant."""

    def test_blocks_direct_delete(self, mock_auth, setup_memory_dal):
        """Should block DELETE requests to admin tenant."""
        client = TestClient(app)
        
        response = client.delete(
            f'/couch-sitter/{ADMIN_TENANT_ID}',
            headers={'Authorization': 'Bearer fake_token'}
        )
        
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()

    def test_blocks_put_soft_delete(self, mock_auth, setup_memory_dal):
        """Should block PUT requests with deletedAt (soft delete)."""
        client = TestClient(app)
        
        response = client.put(
            f'/couch-sitter/{ADMIN_TENANT_ID}',
            headers={'Authorization': 'Bearer fake_token'},
            json={
                '_id': ADMIN_TENANT_ID,
                'type': 'tenant',
                'deletedAt': '2025-01-01T00:00:00Z'
            }
        )
        
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()

    def test_blocks_put_hard_delete(self, mock_auth, setup_memory_dal):
        """Should block PUT requests with _deleted: true (hard delete)."""
        client = TestClient(app)
        
        response = client.put(
            f'/couch-sitter/{ADMIN_TENANT_ID}',
            headers={'Authorization': 'Bearer fake_token'},
            json={
                '_id': ADMIN_TENANT_ID,
                'type': 'tenant',
                '_deleted': True
            }
        )
        
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()

    def test_blocks_bulk_delete(self, mock_auth, setup_memory_dal):
        """Should block _bulk_docs requests containing admin tenant deletion."""
        client = TestClient(app)
        
        response = client.post(
            '/couch-sitter/_bulk_docs',
            headers={'Authorization': 'Bearer fake_token'},
            json={
                'docs': [
                    {
                        '_id': 'other_doc',
                        '_deleted': True
                    },
                    {
                        '_id': ADMIN_TENANT_ID,
                        '_deleted': True
                    }
                ]
            }
        )
        
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()

    def test_allows_normal_update(self, mock_auth, setup_memory_dal):
        """Should allow normal updates to admin tenant."""
        client = TestClient(app)
        
        response = client.put(
            f'/couch-sitter/{ADMIN_TENANT_ID}',
            headers={'Authorization': 'Bearer fake_token'},
            json={
                '_id': ADMIN_TENANT_ID,
                'type': 'tenant',
                'name': 'Updated Name'
                # No deletedAt or _deleted
            }
        )
        
        # Should be 200 or 201
        assert response.status_code in [200, 201]

