import pytest
import jwt
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, Response

from main import (
    app,
    create_jwt_token,
    verify_jwt_token,
    JWT_SECRET,
    API_KEYS,
    COUCHDB_INTERNAL_URL
)

# Test fixtures
@pytest.fixture
def test_api_key():
    """Valid test API key"""
    return "test-key"

@pytest.fixture
def test_client_id():
    """Client ID for test API key"""
    return "test-client"

@pytest.fixture
def valid_jwt_token():
    """Generate a valid JWT token"""
    now = datetime.now(timezone.utc)
    expiration = now + timedelta(seconds=3600)
    payload = {
        "sub": "test-client",
        "iat": int(now.timestamp()),
        "exp": int(expiration.timestamp()),
        "scope": ""
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

@pytest.fixture
def expired_jwt_token():
    """Generate an expired JWT token"""
    now = datetime.now(timezone.utc)
    expiration = now - timedelta(seconds=3600)  # Expired 1 hour ago
    payload = {
        "sub": "test-client",
        "iat": int((now - timedelta(seconds=7200)).timestamp()),
        "exp": int(expiration.timestamp()),
        "scope": ""
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

@pytest.fixture
async def async_client():
    """FastAPI TestClient for async testing"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

# JWT Function Tests
class TestJWTFunctions:
    """Test JWT token creation and validation"""

    def test_create_jwt_token(self):
        """Test creating a valid JWT token"""
        token = create_jwt_token("test-client")
        assert token is not None
        assert isinstance(token, str)

        # Decode and verify
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        assert payload["sub"] == "test-client"
        assert payload["scope"] == ""
        assert "iat" in payload
        assert "exp" in payload

    def test_jwt_token_expiration(self):
        """Test that JWT token has correct expiration"""
        token = create_jwt_token("test-client", expires_in=3600)
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])

        iat = payload["iat"]
        exp = payload["exp"]
        assert exp - iat == 3600

    def test_verify_valid_jwt_token(self, valid_jwt_token):
        """Test verifying a valid JWT token"""
        payload = verify_jwt_token(valid_jwt_token)
        assert payload is not None
        assert payload["sub"] == "test-client"
        assert payload["scope"] == ""

    def test_verify_expired_jwt_token(self, expired_jwt_token):
        """Test that expired tokens return None"""
        payload = verify_jwt_token(expired_jwt_token)
        assert payload is None

    def test_verify_invalid_jwt_token(self):
        """Test that invalid tokens return None"""
        invalid_token = "invalid.token.here"
        payload = verify_jwt_token(invalid_token)
        assert payload is None

    def test_verify_wrong_secret(self, valid_jwt_token):
        """Test that tokens signed with wrong secret fail"""
        # Create token with different secret
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "test-client",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=3600)).timestamp()),
            "scope": ""
        }
        wrong_secret_token = jwt.encode(payload, "wrong-secret", algorithm="HS256")

        # Verification should fail
        result = verify_jwt_token(wrong_secret_token)
        assert result is None

# Token Generation Endpoint Tests
@pytest.mark.asyncio
class TestTokenEndpoint:
    """Test the /auth/token endpoint"""

    async def test_token_generation_valid_api_key(self, async_client, test_api_key):
        """Test generating token with valid API key"""
        response = await async_client.post(
            "/auth/token",
            json={"api_key": test_api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] == 3600

        # Verify token is valid
        payload = verify_jwt_token(data["token"])
        assert payload is not None

    async def test_token_generation_invalid_api_key(self, async_client):
        """Test generating token with invalid API key"""
        response = await async_client.post(
            "/auth/token",
            json={"api_key": "invalid-key-xyz"}
        )

        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    async def test_token_generation_empty_api_key(self, async_client):
        """Test generating token with empty API key"""
        response = await async_client.post(
            "/auth/token",
            json={"api_key": ""}
        )

        assert response.status_code == 401

    async def test_token_generation_missing_api_key(self, async_client):
        """Test generating token without api_key field"""
        response = await async_client.post(
            "/auth/token",
            json={}
        )

        assert response.status_code == 422  # Pydantic validation error

    async def test_token_response_format(self, async_client, test_api_key):
        """Test token response has correct format"""
        response = await async_client.post(
            "/auth/token",
            json={"api_key": test_api_key}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert set(data.keys()) == {"token", "token_type", "expires_in"}
        assert isinstance(data["token"], str)
        assert data["token_type"] == "Bearer"
        assert isinstance(data["expires_in"], int)
        assert data["expires_in"] == 3600

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

    async def test_proxy_request_with_expired_token(self, async_client, expired_jwt_token):
        """Test that requests with expired token return 401"""
        response = await async_client.get(
            "/_all_dbs",
            headers={"Authorization": f"Bearer {expired_jwt_token}"}
        )
        assert response.status_code == 401

    async def test_proxy_auth_header_format_missing_bearer(self, async_client, valid_jwt_token):
        """Test that auth header without Bearer prefix returns 401"""
        response = await async_client.get(
            "/_all_dbs",
            headers={"Authorization": valid_jwt_token}
        )
        assert response.status_code == 401

    async def test_proxy_get_request_with_valid_token(self, async_client, valid_jwt_token):
        """Test proxying GET request with valid token"""
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            # Mock CouchDB response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.content = b'["mydb", "otherdb"]'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            response = await async_client.get(
                "/_all_dbs",
                headers={"Authorization": f"Bearer {valid_jwt_token}"}
            )

            assert response.status_code == 200
            # Verify the proxy made a request to CouchDB
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["method"] == "GET"
            assert COUCHDB_INTERNAL_URL in call_args[1]["url"]

    async def test_proxy_post_request_with_valid_token(self, async_client, valid_jwt_token):
        """Test proxying POST request with valid token"""
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 201
            mock_response.content = b'{"ok":true}'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            response = await async_client.post(
                "/mydb",
                json={"name": "test"},
                headers={"Authorization": f"Bearer {valid_jwt_token}"}
            )

            assert response.status_code == 201
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["method"] == "POST"

    async def test_proxy_put_request_with_valid_token(self, async_client, valid_jwt_token):
        """Test proxying PUT request with valid token"""
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 201
            mock_response.content = b'{"ok":true}'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            response = await async_client.put(
                "/mydb",
                headers={"Authorization": f"Bearer {valid_jwt_token}"}
            )

            assert response.status_code == 201
            call_args = mock_request.call_args
            assert call_args[1]["method"] == "PUT"

    async def test_proxy_delete_request_with_valid_token(self, async_client, valid_jwt_token):
        """Test proxying DELETE request with valid token"""
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.content = b'{"ok":true}'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            response = await async_client.delete(
                "/mydb",
                headers={"Authorization": f"Bearer {valid_jwt_token}"}
            )

            assert response.status_code == 200
            call_args = mock_request.call_args
            assert call_args[1]["method"] == "DELETE"

    async def test_proxy_path_with_query_string(self, async_client, valid_jwt_token):
        """Test that query strings are preserved"""
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.content = b'[]'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            response = await async_client.get(
                "/_all_dbs?skip=10&limit=20",
                headers={"Authorization": f"Bearer {valid_jwt_token}"}
            )

            assert response.status_code == 200
            call_args = mock_request.call_args
            # Check that query string is in the URL
            assert "skip=10" in call_args[1]["url"]
            assert "limit=20" in call_args[1]["url"]

    async def test_proxy_removes_auth_header(self, async_client, valid_jwt_token):
        """Test that Authorization header is removed before proxying"""
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.content = b'[]'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            response = await async_client.get(
                "/_all_dbs",
                headers={"Authorization": f"Bearer {valid_jwt_token}"}
            )

            call_args = mock_request.call_args
            headers = call_args[1]["headers"]
            assert "authorization" not in headers.lower() or headers.get("authorization") is None

    async def test_proxy_couchdb_error_passthrough(self, async_client, valid_jwt_token):
        """Test that CouchDB errors are passed through"""
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 404
            mock_response.content = b'{"error":"not_found"}'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            response = await async_client.get(
                "/nonexistent",
                headers={"Authorization": f"Bearer {valid_jwt_token}"}
            )

            assert response.status_code == 404
            assert b"not_found" in response.content

    async def test_proxy_couchdb_unavailable(self, async_client, valid_jwt_token):
        """Test handling when CouchDB is unavailable"""
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = Exception("Connection refused")

            response = await async_client.get(
                "/_all_dbs",
                headers={"Authorization": f"Bearer {valid_jwt_token}"}
            )

            assert response.status_code == 503

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

# Integration Tests
@pytest.mark.asyncio
class TestIntegration:
    """Integration tests combining multiple components"""

    async def test_full_workflow_get_token_then_access_couchdb(self, async_client, test_api_key):
        """Test full workflow: get token, then access CouchDB"""
        # Step 1: Get token
        token_response = await async_client.post(
            "/auth/token",
            json={"api_key": test_api_key}
        )
        assert token_response.status_code == 200
        token = token_response.json()["token"]

        # Step 2: Access CouchDB with token
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.content = b'["mydb"]'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            db_response = await async_client.get(
                "/_all_dbs",
                headers={"Authorization": f"Bearer {token}"}
            )

            assert db_response.status_code == 200
            assert b"mydb" in db_response.content

    async def test_invalid_token_then_get_new_token(self, async_client, test_api_key, expired_jwt_token):
        """Test that expired token is rejected and new one can be obtained"""
        # Try with expired token
        response = await async_client.get(
            "/_all_dbs",
            headers={"Authorization": f"Bearer {expired_jwt_token}"}
        )
        assert response.status_code == 401

        # Get new token
        token_response = await async_client.post(
            "/auth/token",
            json={"api_key": test_api_key}
        )
        assert token_response.status_code == 200

        # Use new token
        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.content = b'[]'
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value = mock_response

            new_token = token_response.json()["token"]
            response = await async_client.get(
                "/_all_dbs",
                headers={"Authorization": f"Bearer {new_token}"}
            )
            assert response.status_code == 200

# Tenant Enforcement Tests
@pytest.mark.asyncio
class TestTenantEnforcement:
    """Test multi-tenant enforcement features"""

    @pytest.fixture
    def tenant_token(self):
        """Generate a JWT token with tenant_id claim"""
        now = datetime.now(timezone.utc)
        expiration = now + timedelta(seconds=3600)
        payload = {
            "sub": "test-client",
            "iat": int(now.timestamp()),
            "exp": int(expiration.timestamp()),
            "tenant_id": "tenant-a"
        }
        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    @pytest.fixture
    def tenant_token_b(self):
        """Generate a JWT token for a different tenant"""
        now = datetime.now(timezone.utc)
        expiration = now + timedelta(seconds=3600)
        payload = {
            "sub": "test-client",
            "iat": int(now.timestamp()),
            "exp": int(expiration.timestamp()),
            "tenant_id": "tenant-b"
        }
        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    def test_extract_tenant_from_jwt(self, tenant_token):
        """Test extracting tenant from JWT payload"""
        from main import extract_tenant, verify_jwt_token
        payload = verify_jwt_token(tenant_token)
        tenant = extract_tenant(payload)
        assert tenant == "tenant-a"

    def test_extract_tenant_missing(self, valid_jwt_token):
        """Test handling missing tenant in JWT"""
        from main import extract_tenant, verify_jwt_token, ENABLE_TENANT_MODE
        # This test only meaningful when tenant mode is enabled
        if ENABLE_TENANT_MODE:
            payload = verify_jwt_token(valid_jwt_token)
            tenant = extract_tenant(payload)
            assert tenant is None

    def test_filter_document_for_tenant(self):
        """Test filtering document by tenant"""
        from main import filter_document_for_tenant, ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            doc = {"_id": "doc1", "name": "Test", "tenant_id": "tenant-a"}
            result = filter_document_for_tenant(doc, "tenant-a")
            assert result == doc

            # Should return None for wrong tenant
            result = filter_document_for_tenant(doc, "tenant-b")
            assert result is None

    def test_inject_tenant_into_doc(self):
        """Test injecting tenant into document"""
        from main import inject_tenant_into_doc, ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            doc = {"_id": "doc1", "name": "Test"}
            result = inject_tenant_into_doc(doc, "tenant-a")
            assert result["tenant_id"] == "tenant-a"
            assert result["name"] == "Test"

    def test_rewrite_find_query(self):
        """Test rewriting _find query with tenant filter"""
        from main import rewrite_find_query, ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            query = {"selector": {"type": "task"}}
            result = rewrite_find_query(query, "tenant-a")
            assert result["selector"]["tenant_id"] == "tenant-a"
            assert result["selector"]["type"] == "task"

    def test_rewrite_bulk_docs(self):
        """Test injecting tenant into bulk docs"""
        from main import rewrite_bulk_docs, ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            body = {"docs": [{"name": "Doc1"}, {"name": "Doc2"}]}
            result = rewrite_bulk_docs(body, "tenant-a")
            assert all(doc.get("tenant_id") == "tenant-a" for doc in result["docs"])

    def test_filter_response_documents(self):
        """Test filtering documents in response"""
        from main import filter_response_documents, ENABLE_TENANT_MODE
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

    async def test_tenant_isolation_all_docs(self, async_client, tenant_token):
        """Test _all_docs endpoint with tenant filtering"""
        from main import ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
                mock_response = AsyncMock()
                mock_response.status_code = 200
                mock_response.content = json.dumps({
                    "rows": [
                        {"id": "doc1", "doc": {"_id": "doc1", "tenant_id": "tenant-a"}},
                        {"id": "doc2", "doc": {"_id": "doc2", "tenant_id": "tenant-a"}},
                        {"id": "doc3", "doc": {"_id": "doc3", "tenant_id": "tenant-b"}}
                    ]
                }).encode()
                mock_response.headers = {"content-type": "application/json"}
                mock_request.return_value = mock_response

                response = await async_client.get(
                    "/_all_docs",
                    headers={"Authorization": f"Bearer {tenant_token}"}
                )

                assert response.status_code == 200
                data = response.json()
                # Should only see tenant-a documents
                assert len(data["rows"]) == 2

    async def test_endpoint_blocked_in_tenant_mode(self, async_client, tenant_token):
        """Test that disallowed endpoints return 403 in tenant mode"""
        from main import ENABLE_TENANT_MODE
        if ENABLE_TENANT_MODE:
            # Try to access a disallowed endpoint
            response = await async_client.get(
                "/_design/docs",
                headers={"Authorization": f"Bearer {tenant_token}"}
            )
            # Should be rejected in tenant mode
            assert response.status_code in [403, 404]

# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=main", "--cov-report=html"])
