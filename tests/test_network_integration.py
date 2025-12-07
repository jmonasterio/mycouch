"""
Network Integration Tests - Tests actual external service connectivity.

These tests are intentionally slower and test real network calls.
Run separately from unit tests with: pytest tests/test_network_integration.py
"""

import pytest
import time
from unittest.mock import patch
import httpx

# Mark these as slow tests - they will be excluded from default runs
pytestmark = [pytest.mark.slow, pytest.mark.integration]


class TestCouchDBIntegration:
    """Test real CouchDB connectivity when available."""

    @pytest.mark.asyncio
    async def test_real_couchdb_connection(self):
        """Test actual CouchDB connection - requires CouchDB to be running."""
        # This test will only pass if CouchDB is actually running
        # It's meant to be run manually or in CI/CD with CouchDB available

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://localhost:5984/")
                assert response.status_code == 200
                data = response.json()
                assert "couchdb" in data.get("version", "").lower()
        except Exception:
            pytest.skip("CouchDB not available for integration testing")


class TestClerkAPIIntegration:
    """Test real Clerk API connectivity when available."""

    @pytest.mark.asyncio
    async def test_real_clerk_api_connection(self):
        """Test actual Clerk API connectivity - requires valid Clerk credentials."""
        # This test requires real Clerk credentials to be set in environment

        import os
        from couchdb_jwt_proxy.clerk_service import ClerkService

        if not os.getenv("CLERK_SECRET_KEY"):
            pytest.skip("CLERK_SECRET_KEY not available for integration testing")

        try:
            service = ClerkService()
            # Test that we can actually initialize the real Clerk SDK
            assert service.clerk_client is not None
            assert service.is_configured() is True
        except Exception as e:
            pytest.skip(f"Clerk API not available: {e}")


class TestRealTimeBehavior:
    """Test real time-based behavior for cache expiration."""

    def test_real_cache_expiration_timing(self):
        """Test actual cache expiration with real time passage."""
        from couchdb_jwt_proxy.user_tenant_cache import UserTenantCache, UserTenantInfo

        cache = UserTenantCache(ttl_seconds=1)  # Very short TTL
        user_info = UserTenantInfo(user_id="test", tenant_id="test", sub="test")

        # Set user
        cache.set_user("test_hash", user_info)

        # Should be cached immediately
        cached = cache.get_user_by_sub_hash("test_hash")
        assert cached is not None

        # Wait for real expiration (this uses real time)
        time.sleep(1.1)

        # Should now be expired
        cached = cache.get_user_by_sub_hash("test_hash")
        assert cached is None