"""
Tests for admin tenant protection in the JWT proxy.
The admin tenant (tenant_couch_sitter_admins) must never be deletable.
"""
import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

os.environ.setdefault("SESSION_SECRET", "test-session-secret-that-is-long-enough-here")
os.environ.setdefault("APPLICATION_ID", "roady")

from couchdb_jwt_proxy.main import app, dal

ADMIN_TENANT_ID = "tenant_couch_sitter_admins"


@pytest.fixture
def mock_auth():
    """Mock session token verification and tenant extraction."""
    session_payload = {"pubkey": "a" * 64, "user_id": "user_abc123"}
    with patch("couchdb_jwt_proxy.main.verify_session_token",
               return_value=session_payload), \
         patch("couchdb_jwt_proxy.main.extract_tenant",
               new_callable=AsyncMock, return_value="tenant_abc"):
        yield


@pytest.fixture
def setup_memory_dal():
    """Populate Memory DAL with test data."""
    async def populate():
        if hasattr(dal.backend, "_docs"):
            dal.backend._docs.clear()

        admin_doc = {
            "_id": ADMIN_TENANT_ID,
            "type": "tenant",
            "name": "Couch-Sitter Administrators",
        }
        await dal.get(f"couch-sitter/{ADMIN_TENANT_ID}", "PUT", admin_doc)
        await dal.get("couch-sitter/other_doc", "PUT", {"_id": "other_doc", "type": "doc"})

    asyncio.run(populate())
    yield
    if hasattr(dal.backend, "_docs"):
        dal.backend._docs.clear()


class TestAdminTenantProtection:
    """Protection against deleting the admin tenant."""

    def test_blocks_direct_delete(self, mock_auth, setup_memory_dal):
        client = TestClient(app)
        response = client.delete(
            f"/couch-sitter/{ADMIN_TENANT_ID}",
            headers={"Authorization": "Bearer fake_token"},
        )
        assert response.status_code == 403
        assert "not allowed" in response.json()["detail"].lower()

    def test_blocks_put_soft_delete(self, mock_auth, setup_memory_dal):
        client = TestClient(app)
        response = client.put(
            f"/couch-sitter/{ADMIN_TENANT_ID}",
            headers={"Authorization": "Bearer fake_token"},
            json={"_id": ADMIN_TENANT_ID, "type": "tenant", "deletedAt": "2025-01-01T00:00:00Z"},
        )
        assert response.status_code == 403
        assert "not allowed" in response.json()["detail"].lower()

    def test_blocks_put_hard_delete(self, mock_auth, setup_memory_dal):
        client = TestClient(app)
        response = client.put(
            f"/couch-sitter/{ADMIN_TENANT_ID}",
            headers={"Authorization": "Bearer fake_token"},
            json={"_id": ADMIN_TENANT_ID, "type": "tenant", "_deleted": True},
        )
        assert response.status_code == 403
        assert "not allowed" in response.json()["detail"].lower()

    def test_blocks_bulk_delete(self, mock_auth, setup_memory_dal):
        client = TestClient(app)
        response = client.post(
            "/couch-sitter/_bulk_docs",
            headers={"Authorization": "Bearer fake_token"},
            json={
                "docs": [
                    {"_id": "other_doc", "_deleted": True},
                    {"_id": ADMIN_TENANT_ID, "_deleted": True},
                ]
            },
        )
        assert response.status_code == 403
        assert "not allowed" in response.json()["detail"].lower()

    def test_allows_normal_update(self, mock_auth, setup_memory_dal):
        client = TestClient(app)
        response = client.put(
            f"/couch-sitter/{ADMIN_TENANT_ID}",
            headers={"Authorization": "Bearer fake_token"},
            json={"_id": ADMIN_TENANT_ID, "type": "tenant", "name": "Updated Name"},
        )
        assert response.status_code in [200, 201]
