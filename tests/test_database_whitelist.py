"""
Tests for database whitelist protection in the JWT proxy.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from couchdb_jwt_proxy.main import app


@pytest.fixture
def mock_clerk_jwt():
    """Mock Clerk JWT validation to return a valid payload."""
    with patch('couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify:
        mock_verify.return_value = (
            {
                'sub': 'user_123',
                'iss': 'https://enabled-hawk-56.clerk.accounts.dev',
                'email': 'test@example.com',
                'tenant_id': 'tenant_abc'
            },
            None
        )
        yield mock_verify


@pytest.fixture
def mock_extract_tenant():
    """Mock tenant extraction."""
    with patch('couchdb_jwt_proxy.main.extract_tenant') as mock_extract:
        mock_extract.return_value = 'tenant_abc'
        yield mock_extract


import asyncio
from couchdb_jwt_proxy.main import dal, initialize_applications

@pytest.fixture
def setup_memory_dal():
    """Populate Memory DAL with test data."""
    # Create Application document
    app_doc = {
        "_id": "app_test_1",
        "type": "application",
        "issuer": "https://enabled-hawk-56.clerk.accounts.dev",
        "name": "roady",
        "databaseNames": ["roady"]
    }
    
    async def populate():
        # Clear existing data
        if hasattr(dal.backend, '_docs'):
            dal.backend._docs.clear()
            
        # Add app doc
        await dal.get("couch-sitter/app_test_1", "PUT", app_doc)
        
        # Add a dummy document for other tests
        await dal.get("couch-sitter/doc123", "PUT", {'ok': True, 'id': 'doc123', 'rev': '1-abc'})
        
        # Initialize applications to load from DAL
        await initialize_applications()

    asyncio.run(populate())
    yield
    # Cleanup
    if hasattr(dal.backend, '_docs'):
        dal.backend._docs.clear()


class TestDatabaseWhitelist:
    """Test database access whitelist protection."""

    def test_blocks_access_to_non_whitelisted_database(self, mock_clerk_jwt, mock_extract_tenant, setup_memory_dal):
        """Should block access to databases not in whitelist."""
        client = TestClient(app)
        
        # Try to access a tenant database directly
        response = client.get(
            '/tenant_12345/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()
        assert 'tenant_12345' in response.json()['detail']

    def test_blocks_access_to_user_database(self, mock_clerk_jwt, mock_extract_tenant, setup_memory_dal):
        """Should block access to user databases."""
        client = TestClient(app)
        
        response = client.get(
            '/user_abc123/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()

    def test_blocks_access_to_app_database(self, mock_clerk_jwt, mock_extract_tenant, setup_memory_dal):
        """Should block access to app databases."""
        client = TestClient(app)
        
        response = client.get(
            '/app_some_issuer/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()

    def test_allows_access_to_couch_sitter(self, mock_clerk_jwt, mock_extract_tenant, setup_memory_dal):
        """Should allow access to couch-sitter database."""
        client = TestClient(app)
        
        response = client.get(
            '/couch-sitter/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        
        # Should not be blocked by whitelist
        # It might return 200 (if empty) or 404 (if not found/implemented in memory DAL for this path)
        # But definitely NOT 403
        assert response.status_code != 403

    def test_allows_access_to_roady(self, mock_clerk_jwt, mock_extract_tenant, setup_memory_dal):
        """Should allow access to roady database."""
        client = TestClient(app)
        
        response = client.get(
            '/roady/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        
        # Should not be blocked by whitelist
        assert response.status_code != 403

    def test_blocks_database_creation_via_put(self, mock_clerk_jwt, mock_extract_tenant, setup_memory_dal):
        """Should block PUT requests that would create databases."""
        client = TestClient(app)
        
        # Try to create a database with PUT /dbname
        response = client.put(
            '/couch-sitter',
            headers={'Authorization': 'Bearer fake_token'}
        )
        
        assert response.status_code == 403
        assert 'database creation' in response.json()['detail'].lower()

    def test_allows_document_creation_via_put(self, mock_clerk_jwt, mock_extract_tenant, setup_memory_dal):
        """Should allow PUT requests to create documents (not databases)."""
        client = TestClient(app)
        
        # PUT with document ID should be allowed
        response = client.put(
            '/couch-sitter/doc123',
            headers={'Authorization': 'Bearer fake_token'},
            json={'name': 'test'}
        )
        
        # Should not be blocked by database creation check
        assert response.status_code != 403
        # It might be 200 or 201
        assert response.status_code in [200, 201]

    def test_error_message_includes_allowed_databases(self, mock_clerk_jwt, mock_extract_tenant, setup_memory_dal):
        """Error message should list allowed databases."""
        client = TestClient(app)
        
        response = client.get(
            '/invalid_db/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        
        assert response.status_code == 403
        detail = response.json()['detail']
        assert 'couch-sitter' in detail
        assert 'roady' in detail
