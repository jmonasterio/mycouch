import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, Response, ASGITransport
import pytest_asyncio

from couchdb_jwt_proxy.main import (
    app,
    COUCHDB_INTERNAL_URL
)

# Test fixtures
@pytest_asyncio.fixture
async def async_client():
    """FastAPI TestClient for async testing"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.fixture
def mock_clerk_jwt_payload():
    """Mock Clerk JWT payload for testing"""
    return {
        "sub": "user_abc123def456",
        "email": "user@example.com",
        "iss": "https://test-clerk-instance.clerk.accounts.dev",
        "aud": "test-app-id",
        "iat": 1699561200,
        "exp": 1699564800
    }

@pytest.fixture
def mock_clerk_jwt_payload_with_tenant():
    """Mock Clerk JWT payload with tenant_id for multi-tenant testing"""
    return {
        "sub": "user_abc123def456",
        "email": "user@example.com",
        "iss": "https://test-clerk-instance.clerk.accounts.dev",
        "aud": "test-app-id",
        "iat": 1699561200,
        "exp": 1699564800,
        "tenant_id": "tenant-a"
    }

# CouchDB Proxy Endpoint Tests
@pytest.mark.asyncio
class TestProxyEndpoint:
    """Test the CouchDB proxy endpoint"""

    async def test_proxy_request_without_auth_header(self, async_client):
        """Test that requests without auth header return 401"""
        response = await async_client.get("/_all_dbs")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    async def test_proxy_request_with_invalid_token(self, async_client):
        """Test that requests with invalid token return 401"""
        response = await async_client.get(
            "/_all_dbs",
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401

    async def test_proxy_auth_header_format_missing_bearer(self, async_client):
        """Test that auth header without Bearer prefix returns 401"""
        response = await async_client.get(
            "/_all_dbs",
            headers={"Authorization": "some-token"}
        )
        assert response.status_code == 401

    async def test_proxy_with_valid_clerk_token(self, async_client, mock_clerk_jwt_payload):
        """Test proxying with valid Clerk JWT token"""
        with patch('couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify:
            mock_verify.return_value = (mock_clerk_jwt_payload, None)

            # Mock the httpx response at a higher level
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'["db1", "db2"]'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.stream = AsyncMock()

            with patch('couchdb_jwt_proxy.main.httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                response = await async_client.get(
                    "/_all_dbs",
                    headers={"Authorization": "Bearer valid-token"}
                )

                assert response.status_code == 200

# Health Check and Root Endpoints
@pytest.mark.asyncio
class TestHealthAndRoot:
    """Test health check and root endpoints"""

    async def test_health_check(self, async_client):
        """Test health check endpoint"""
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "couchdb-jwt-proxy"

    async def test_root_endpoint(self, async_client):
        """Test root endpoint"""
        response = await async_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "endpoints" in data

# Tenant Enforcement Tests
@pytest.mark.asyncio
class TestTenantEnforcement:
    """Test multi-tenant enforcement features"""

    def test_extract_tenant_from_jwt(self, mock_clerk_jwt_payload_with_tenant):
        """Test extracting tenant from Clerk JWT payload"""
        from couchdb_jwt_proxy.main import extract_tenant
        tenant = extract_tenant(mock_clerk_jwt_payload_with_tenant)
        assert tenant == "tenant-a"

    def test_extract_tenant_missing(self, mock_clerk_jwt_payload):
        """Test handling missing tenant in JWT"""
        from couchdb_jwt_proxy.main import extract_tenant, ENABLE_TENANT_MODE
        # This test only meaningful when tenant mode is enabled
        if ENABLE_TENANT_MODE:
            tenant = extract_tenant(mock_clerk_jwt_payload)
            assert tenant is None

    def test_filter_document_for_tenant(self):
        """Test filtering document by tenant"""
        from couchdb_jwt_proxy.main import filter_document_for_tenant, ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            doc = {"_id": "doc1", "name": "Test", "tenant_id": "tenant-a"}
            result = filter_document_for_tenant(doc, "tenant-a")
            assert result == doc

            # Should return None for wrong tenant
            result = filter_document_for_tenant(doc, "tenant-b")
            assert result is None

    def test_inject_tenant_into_doc(self):
        """Test injecting tenant into document"""
        from couchdb_jwt_proxy.main import inject_tenant_into_doc, ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            doc = {"_id": "doc1", "name": "Test"}
            result = inject_tenant_into_doc(doc, "tenant-a")
            assert result["tenant_id"] == "tenant-a"
            assert result["name"] == "Test"

    def test_rewrite_find_query(self):
        """Test rewriting _find query with tenant filter"""
        from couchdb_jwt_proxy.main import rewrite_find_query, ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            query = {"selector": {"type": "task"}}
            result = rewrite_find_query(query, "tenant-a")
            assert result["selector"]["tenant_id"] == "tenant-a"
            assert result["selector"]["type"] == "task"

    def test_rewrite_bulk_docs(self):
        """Test injecting tenant into bulk docs"""
        from couchdb_jwt_proxy.main import rewrite_bulk_docs, ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            body = {"docs": [{"name": "Doc1"}, {"name": "Doc2"}]}
            result = rewrite_bulk_docs(body, "tenant-a")
            assert all(doc.get("tenant_id") == "tenant-a" for doc in result["docs"])

    def test_filter_response_documents(self):
        """Test filtering documents in response"""
        from couchdb_jwt_proxy.main import filter_response_documents, ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            response = {
                "total_rows": 2,
                "rows": [
                    {"id": "doc1", "doc": {"_id": "doc1", "tenant_id": "tenant-a"}},
                    {"id": "doc2", "doc": {"_id": "doc2", "tenant_id": "tenant-b"}}
                ]
            }
            content = json.dumps(response).encode()
            filtered = filter_response_documents(content, "tenant-a")
            result = json.loads(filtered)
            assert len(result["rows"]) == 1
            assert result["rows"][0]["id"] == "doc1"

# Clerk JWT Validation Tests
@pytest.mark.asyncio
class TestClerkJWTValidation:
    """Test Clerk JWT validation"""

    async def test_clerk_jwt_validation_success(self, async_client, mock_clerk_jwt_payload):
        """Test successful Clerk JWT validation"""
        with patch('couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify:
            mock_verify.return_value = (mock_clerk_jwt_payload, None)

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'[]'
            mock_response.headers = {"content-type": "application/json"}

            with patch('couchdb_jwt_proxy.main.httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                response = await async_client.get(
                    "/_all_dbs",
                    headers={"Authorization": "Bearer valid-clerk-token"}
                )

                assert response.status_code == 200
                mock_verify.assert_called_once_with("valid-clerk-token")

    async def test_clerk_jwt_validation_failure(self, async_client):
        """Test failed Clerk JWT validation"""
        with patch('couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify:
            mock_verify.return_value = (None, "clerk_token_expired")

            response = await async_client.get(
                "/_all_dbs",
                headers={"Authorization": "Bearer expired-clerk-token"}
            )

            assert response.status_code == 401
            data = response.json()
            assert "expired" in data["detail"] or "Invalid" in data["detail"]

    async def test_clerk_jwt_missing_issuer(self, async_client):
        """Test Clerk JWT with missing issuer"""
        with patch('couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify:
            mock_verify.return_value = (None, "clerk_jwks_unavailable")

            response = await async_client.get(
                "/_all_dbs",
                headers={"Authorization": "Bearer some-token"}
            )

            assert response.status_code == 401

# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
