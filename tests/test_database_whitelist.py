"""
Tests for database whitelist protection in the JWT proxy.
"""
import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from couchdb_jwt_proxy.main import app, dal


@pytest.fixture
def mock_auth():
    """Mock session token verification and tenant extraction."""
    with patch('couchdb_jwt_proxy.main.verify_session_token', return_value={'pubkey': 'a' * 64, 'user_id': 'user_abc123'}), \
         patch('couchdb_jwt_proxy.main.extract_tenant', new_callable=AsyncMock, return_value='tenant_abc'):
        yield


@pytest.fixture
def setup_memory_dal():
    """Populate Memory DAL with test data."""
    app_doc = {
        "_id": "app_test_1",
        "type": "application",
        "issuer": "https://enabled-hawk-56.clerk.accounts.dev",
        "name": "roady",
        "databaseNames": ["roady"]
    }

    async def populate():
        if hasattr(dal.backend, '_docs'):
            dal.backend._docs.clear()
        await dal.get("couch-sitter/app_test_1", "PUT", app_doc)
        await dal.get("couch-sitter/doc123", "PUT", {'ok': True, 'id': 'doc123', 'rev': '1-abc'})

    asyncio.run(populate())
    yield
    if hasattr(dal.backend, '_docs'):
        dal.backend._docs.clear()


class TestDatabaseWhitelist:
    """Test database access whitelist protection."""

    def test_blocks_access_to_non_whitelisted_database(self, mock_auth, setup_memory_dal):
        """Should block access to databases not in whitelist."""
        client = TestClient(app)
        response = client.get(
            '/tenant_12345/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()
        assert 'tenant_12345' in response.json()['detail']

    def test_blocks_access_to_user_database(self, mock_auth, setup_memory_dal):
        """Should block access to user databases."""
        client = TestClient(app)
        response = client.get(
            '/user_abc123/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()

    def test_blocks_access_to_app_database(self, mock_auth, setup_memory_dal):
        """Should block access to app databases."""
        client = TestClient(app)
        response = client.get(
            '/app_some_issuer/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        assert response.status_code == 403
        assert 'not allowed' in response.json()['detail'].lower()

    def test_allows_access_to_couch_sitter(self, mock_auth, setup_memory_dal):
        """Should allow access to couch-sitter database."""
        client = TestClient(app)
        response = client.get(
            '/couch-sitter/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        # Should not be blocked by whitelist — might be 200 or 404 but not 403
        assert response.status_code != 403

    def test_allows_access_to_roady(self, mock_auth, setup_memory_dal):
        """Should allow access to roady database."""
        client = TestClient(app)
        response = client.get(
            '/roady/_all_docs',
            headers={'Authorization': 'Bearer fake_token'}
        )
        assert response.status_code != 403

    def test_blocks_database_creation_via_put(self, mock_auth, setup_memory_dal):
        """Should block PUT requests that would create databases."""
        client = TestClient(app)
        response = client.put(
            '/couch-sitter',
            headers={'Authorization': 'Bearer fake_token'}
        )
        assert response.status_code == 403
        assert 'database creation' in response.json()['detail'].lower()

    def test_allows_document_creation_via_put(self, mock_auth, setup_memory_dal):
        """Should allow PUT requests to create documents (not databases)."""
        client = TestClient(app)
        response = client.put(
            '/couch-sitter/doc123',
            headers={'Authorization': 'Bearer fake_token'},
            json={'name': 'test'}
        )
        assert response.status_code != 403
        assert response.status_code in [200, 201]

    def test_error_message_includes_allowed_databases(self, mock_auth, setup_memory_dal):
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
