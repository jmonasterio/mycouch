"""
Core proxy endpoint tests — post Nostr NIP-98 migration.
Auth is now Bearer session tokens issued by POST /auth/session.
"""
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response

# Session secret must be set before importing app
os.environ.setdefault("SESSION_SECRET", "test-session-secret-that-is-long-enough-here")
os.environ.setdefault("APPLICATION_ID", "roady")

from couchdb_jwt_proxy.main import app, COUCHDB_INTERNAL_URL


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def async_client():
    """FastAPI async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def make_session_token(pubkey: str = "a" * 64, user_id: str = "user_abc123") -> str:
    """Issue a real session token for test use."""
    from couchdb_jwt_proxy.core.auth import issue_session_token
    data = issue_session_token(pubkey, user_id, ttl=3600)
    return data["token"]


@pytest.fixture
def mock_session_payload():
    """Mock session payload returned by verify_session_token."""
    return {
        "pubkey": "a" * 64,
        "user_id": "user_abc123",
    }


@pytest.fixture
def session_token(mock_session_payload):
    """Valid Bearer session token."""
    return make_session_token(
        pubkey=mock_session_payload["pubkey"],
        user_id=mock_session_payload["user_id"],
    )


# ---------------------------------------------------------------------------
# Proxy endpoint auth tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestProxyEndpoint:
    async def test_proxy_request_without_auth_header(self, async_client):
        response = await async_client.get("/_all_dbs")
        assert response.status_code == 401

    async def test_proxy_request_with_invalid_token(self, async_client):
        response = await async_client.get(
            "/_all_dbs",
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401

    async def test_proxy_auth_header_format_missing_bearer(self, async_client):
        response = await async_client.get(
            "/_all_dbs",
            headers={"Authorization": "some-token"}
        )
        assert response.status_code == 401

    async def test_proxy_with_valid_session_token(self, async_client, mock_session_payload):
        token = make_session_token(**mock_session_payload)
        with patch("couchdb_jwt_proxy.core.auth.verify_session_token",
                   return_value=mock_session_payload), \
             patch("couchdb_jwt_proxy.main.extract_tenant",
                   new_callable=AsyncMock, return_value="test-tenant-123"):

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'["db1", "db2"]'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.stream = AsyncMock()

            with patch("couchdb_jwt_proxy.main.httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                response = await async_client.get(
                    "/_all_dbs",
                    headers={"Authorization": f"Bearer {token}"}
                )
                assert response.status_code == 200


# ---------------------------------------------------------------------------
# Health and root endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHealthAndRoot:
    async def test_health_check(self, async_client):
        with patch("couchdb_jwt_proxy.main.dal") as mock_dal:
            mock_dal.get = AsyncMock(return_value={
                "status": "ok",
                "service": "couchdb-jwt-proxy",
                "couchdb": "connected",
                "version": "3.3.3",
            })
            response = await async_client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["service"] == "couchdb-jwt-proxy"
            assert data["couchdb"] == "connected"

            mock_dal.get.side_effect = Exception("Connection refused")
            response = await async_client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "error"
            assert data["couchdb"] == "unavailable"

    async def test_root_endpoint(self, async_client):
        response = await async_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "endpoints" in data


# ---------------------------------------------------------------------------
# Tenant enforcement tests (pure logic, no DB)
# ---------------------------------------------------------------------------

class TestTenantEnforcement:
    def test_filter_document_for_tenant(self):
        from couchdb_jwt_proxy.main import filter_document_for_tenant, TENANT_FIELD
        doc = {"_id": "doc1", "name": "Test", TENANT_FIELD: "tenant-a"}
        assert filter_document_for_tenant(doc, "tenant-a") == doc
        assert filter_document_for_tenant(doc, "tenant-b") is None

    def test_inject_tenant_into_doc(self):
        from couchdb_jwt_proxy.main import inject_tenant_into_doc, TENANT_FIELD
        doc1 = {"_id": "doc1", "name": "Test"}
        result1 = inject_tenant_into_doc(doc1, "tenant-a", is_multi_tenant_app=True)
        assert result1[TENANT_FIELD] == "tenant-a"

        doc2 = {"_id": "doc2", "name": "Test"}
        result2 = inject_tenant_into_doc(doc2, "tenant-a", is_multi_tenant_app=False)
        assert TENANT_FIELD not in result2

    def test_rewrite_find_query(self):
        from couchdb_jwt_proxy.main import rewrite_find_query, TENANT_FIELD
        query1 = {"selector": {"type": "task"}}
        result1 = rewrite_find_query(query1, "tenant-a", is_multi_tenant_app=True)
        assert result1["selector"][TENANT_FIELD] == "tenant-a"

        query2 = {"selector": {"type": "task"}}
        result2 = rewrite_find_query(query2, "tenant-a", is_multi_tenant_app=False)
        assert TENANT_FIELD not in result2["selector"]

    def test_rewrite_bulk_docs(self):
        from couchdb_jwt_proxy.main import rewrite_bulk_docs, TENANT_FIELD
        body1 = {"docs": [{"name": "Doc1"}, {"name": "Doc2"}]}
        result1 = rewrite_bulk_docs(body1, "tenant-a", is_multi_tenant_app=True)
        assert all(doc.get(TENANT_FIELD) == "tenant-a" for doc in result1["docs"])

        body2 = {"docs": [{"name": "Doc1"}]}
        result2 = rewrite_bulk_docs(body2, "tenant-a", is_multi_tenant_app=False)
        assert all(TENANT_FIELD not in doc for doc in result2["docs"])

    def test_filter_response_documents(self):
        from couchdb_jwt_proxy.main import filter_response_documents, TENANT_FIELD
        response = {
            "total_rows": 2,
            "rows": [
                {"id": "doc1", "doc": {"_id": "doc1", TENANT_FIELD: "tenant-a"}},
                {"id": "doc2", "doc": {"_id": "doc2", TENANT_FIELD: "tenant-b"}},
            ],
        }
        content = json.dumps(response).encode()
        filtered = filter_response_documents(content, "tenant-a")
        result = json.loads(filtered)
        assert len(result["rows"]) == 1
        assert result["rows"][0]["id"] == "doc1"


# ---------------------------------------------------------------------------
# Session token validation tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSessionTokenValidation:
    async def test_valid_session_token_passes(self, async_client, mock_session_payload):
        token = make_session_token(**mock_session_payload)
        with patch("couchdb_jwt_proxy.main.extract_tenant",
                   new_callable=AsyncMock, return_value="test-tenant-123"):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"[]"
            mock_response.headers = {"content-type": "application/json"}

            with patch("couchdb_jwt_proxy.main.httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                response = await async_client.get(
                    "/_all_dbs",
                    headers={"Authorization": f"Bearer {token}"}
                )
                assert response.status_code == 200

    async def test_expired_session_token_rejected(self, async_client):
        from couchdb_jwt_proxy.core.auth import issue_session_token
        data = issue_session_token("a" * 64, "user_abc", ttl=-1)
        response = await async_client.get(
            "/_all_dbs",
            headers={"Authorization": f"Bearer {data['token']}"}
        )
        assert response.status_code == 401

    async def test_tampered_token_rejected(self, async_client):
        response = await async_client.get(
            "/_all_dbs",
            headers={"Authorization": "Bearer eyJhbGciOiJub25lIn0.tampered.sig"}
        )
        assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
