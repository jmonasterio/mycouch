import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
import pytest_asyncio

from couchdb_jwt_proxy.main import app, initialize_applications

# Test fixtures
@pytest_asyncio.fixture
async def async_client():
    """FastAPI TestClient for async testing"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
class TestLegacyAppSupport:
    """Test support for legacy 'app' type documents"""

    async def test_load_legacy_apps(self):
        """Test that load_all_apps handles legacy 'type: app' documents"""
        
        # Mock dependencies
        with patch('couchdb_jwt_proxy.main.couch_sitter_service') as mock_couch_sitter:
            
            # Mock the _make_request method to return legacy app data
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "docs": [
                    {
                        "_id": "app_legacy",
                        "type": "app",  # Legacy type
                        "issuer": "https://legacy-issuer.clerk.accounts.dev",
                        "databaseNames": ["legacy-db"]
                    },
                    {
                        "_id": "app_new",
                        "type": "application",  # New type
                        "issuer": "https://new-issuer.clerk.accounts.dev",
                        "databaseNames": ["new-db"]
                    }
                ]
            }
            
            # We need to mock the internal _make_request of the service instance
            # But since we're patching the service instance in main, we need to access it there
            # Or better, we can test the service method directly if we instantiate it
            
            from couchdb_jwt_proxy.couch_sitter_service import CouchSitterService
            service = CouchSitterService("http://mock", "user", "pass")
            service._make_request = AsyncMock(return_value=mock_response)
            
            apps = await service.load_all_apps()
            
            assert "https://legacy-issuer.clerk.accounts.dev" in apps
            assert "https://new-issuer.clerk.accounts.dev" in apps
            assert apps["https://legacy-issuer.clerk.accounts.dev"]["databaseNames"] == ["legacy-db"]

    async def test_access_with_legacy_app(self, async_client):
        """Test access to a database defined in a legacy app"""
        
        legacy_issuer = "https://legacy-issuer.clerk.accounts.dev"
        
        # Mock dependencies
        with patch('couchdb_jwt_proxy.main.verify_clerk_jwt') as mock_verify, \
             patch('couchdb_jwt_proxy.main.couch_sitter_service') as mock_couch_sitter, \
             patch('couchdb_jwt_proxy.main.clerk_service') as mock_clerk_service, \
             patch('couchdb_jwt_proxy.main.APPLICATIONS', {legacy_issuer: {"databaseNames": ["legacy-db"], "clerkSecretKey": None}}):

            # Mock JWT
            mock_verify.return_value = ({
                "sub": "user_123",
                "iss": legacy_issuer,
                "active_tenant_id": "tenant_123"  # Required for multi-tenant apps
            }, None)

            # Mock tenant extraction
            mock_couch_sitter.get_user_tenant_info = AsyncMock(return_value=MagicMock(
                tenant_id="tenant_123",
                user_id="user_123",
                sub="user_123"
            ))

            # Mock CouchDB response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"ok": true}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.stream = AsyncMock()

            with patch('couchdb_jwt_proxy.main.httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                # Make request to legacy db
                response = await async_client.get(
                    "/legacy-db/_all_docs",
                    headers={"Authorization": "Bearer valid-token"}
                )

                assert response.status_code == 200
