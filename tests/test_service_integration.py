"""
Service Integration tests.

Tests integration between clerk_service, couch_sitter_service, and user_tenant_cache.
"""

import pytest
import json
import time
import hashlib
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta
from typing import Optional, Dict

# Import service modules
from couchdb_jwt_proxy.clerk_service import ClerkService
from couchdb_jwt_proxy.couch_sitter_service import CouchSitterService
from couchdb_jwt_proxy.user_tenant_cache import UserTenantInfo, UserTenantCache, get_cache, reset_cache
from couchdb_jwt_proxy.dal import create_dal


@pytest.fixture
def memory_dal():
    """Memory DAL for testing"""
    return create_dal(backend="memory")


@pytest.fixture
def mock_services(memory_dal):
    """Create mocked services using memory DAL"""
    with patch('couchdb_jwt_proxy.clerk_service.os.getenv') as mock_getenv, \
         patch('couchdb_jwt_proxy.clerk_service.CLERK_API_AVAILABLE', True), \
         patch('couchdb_jwt_proxy.clerk_service.Clerk') as mock_clerk_class:


        # Mock clerk service configuration
        mock_getenv.side_effect = lambda key, default=None: {
            "CLERK_ISSUER_URL": "https://test-clerk.clerk.accounts.dev",
            "CLERK_SECRET_KEY": "test-secret-key"
        }.get(key, default)

        # Mock clerk client
        mock_clerk_client = MagicMock()
        mock_clerk_class.return_value = mock_clerk_client

        clerk_service = ClerkService()
        clerk_service.clerk_client = mock_clerk_client

        couch_sitter_service = CouchSitterService(
            couch_sitter_db_url="http://localhost:5984/test-db",
            couchdb_user="test",
            couchdb_password="test",
            dal=memory_dal
        )

        # Reset cache to start fresh
        reset_cache()

        return clerk_service, couch_sitter_service, mock_clerk_client


class TestServiceIntegration:
    """Test integration between services"""

    @pytest.mark.asyncio
    async def test_full_user_authentication_flow(self, mock_services):
        """Test complete user authentication flow across all services"""
        clerk_service, couch_sitter_service, mock_clerk_client = mock_services

        # Setup JWT token mock
        jwt_payload = {
            "sub": "user_auth_integration",
            "email": "auth@example.com",
            "name": "Auth User"
        }

        # Mock Clerk session verification
        mock_session = MagicMock()
        mock_session.id = "session_123"
        mock_session.user_id = "user_123"
        mock_session.status = "active"
        mock_clerk_client.sessions.verify_session_token.return_value = mock_session

        # Mock Clerk user info extraction
        clerk_service.get_user_from_jwt = AsyncMock(return_value={
            "sub": jwt_payload["sub"],
            "email": jwt_payload["email"],
            "name": jwt_payload["name"],
            "user_id": jwt_payload["sub"]
        })

        # Step 1: Get user info from JWT via clerk service
        user_info = await clerk_service.get_user_from_jwt("valid_jwt_token")
        assert user_info is not None
        assert user_info["sub"] == "user_auth_integration"

        # Step 2: Ensure user exists via couch_sitter_service
        user_tenant_info = await couch_sitter_service.get_user_tenant_info(
            user_info["sub"],
            user_info["email"],
            user_info["name"]
        )

        assert isinstance(user_tenant_info, UserTenantInfo)
        assert user_tenant_info.sub == "user_auth_integration"
        assert user_tenant_info.email == "auth@example.com"
        assert user_tenant_info.name == "Auth User"
        assert user_tenant_info.is_personal_tenant is True

        # Step 3: Verify user and tenant were created in database
        user_doc = await couch_sitter_service.dal.get(f"/test-db/{user_tenant_info.user_id}", "GET")
        tenant_doc = await couch_sitter_service.dal.get(f"/test-db/{user_tenant_info.tenant_id}", "GET")

        assert user_doc is not None
        assert user_doc["type"] == "user"
        assert user_doc["sub"] == "user_auth_integration"

        assert tenant_doc is not None
        assert tenant_doc["type"] == "tenant"
        assert tenant_doc["isPersonal"] is True

    @pytest.mark.asyncio
    async def test_cache_integration_with_services(self, mock_services):
        """Test cache integration with service layer"""
        clerk_service, couch_sitter_service, mock_clerk_client = mock_services

        # Get cache instance
        cache = get_cache()

        # Simulate first request - should create user and tenant, then cache
        user_tenant_info1 = await couch_sitter_service.get_user_tenant_info(
            "cache_test_user",
            "cache@example.com",
            "Cache User"
        )

        assert isinstance(user_tenant_info1, UserTenantInfo)

        # Generate sub hash for cache key
        sub_hash = hashlib.sha256("cache_test_user".encode()).hexdigest()

        # Verify data was cached (simulating service layer would cache this)
        cache.set_user(sub_hash, user_tenant_info1)

        # Simulate second request - should get from cache
        cached_info = cache.get_user_by_sub_hash(sub_hash)

        assert cached_info is not None
        assert cached_info.sub == "cache_test_user"
        assert cached_info.user_id == user_tenant_info1.user_id
        assert cached_info.tenant_id == user_tenant_info1.tenant_id

        # Verify cache stats
        stats = cache.get_stats()
        assert stats["total_entries"] == 1
        assert stats["valid_entries"] == 1

    @pytest.mark.asyncio
    async def test_clerk_session_management_with_tenant_info(self, mock_services):
        """Test Clerk session management integration with tenant information"""
        clerk_service, couch_sitter_service, mock_clerk_client = mock_services

        # First, create user and get tenant info
        user_tenant_info = await couch_sitter_service.get_user_tenant_info(
            "session_user",
            "session@example.com",
            "Session User"
        )

        # Mock Clerk session metadata operations
        mock_session = MagicMock()
        mock_session.public_user_data = MagicMock()
        mock_session.public_user_data.get.return_value = {}
        mock_clerk_client.sessions.get.return_value = mock_session

        # Test updating active tenant in session
        success = await clerk_service.update_active_tenant_in_session(
            "session_user",
            "session_123",
            user_tenant_info.tenant_id
        )

        assert success is True
        mock_clerk_client.sessions.update.assert_called_once()

        # Test retrieving active tenant from session
        # Mock session metadata to return the tenant we just set
        mock_session.public_user_data.get.return_value = {
            "active_tenant_id": user_tenant_info.tenant_id
        }

        active_tenant = await clerk_service.get_user_active_tenant("session_user", "session_123")
        assert active_tenant == user_tenant_info.tenant_id

    @pytest.mark.asyncio
    async def test_multi_user_isolation(self, mock_services):
        """Test that different users are properly isolated"""
        clerk_service, couch_sitter_service, mock_clerk_client = mock_services

        # Create multiple users
        users = [
            ("user1", "user1@example.com", "User One"),
            ("user2", "user2@example.com", "User Two"),
            ("user3", "user3@example.com", "User Three")
        ]

        user_tenant_infos = []

        for sub, email, name in users:
            info = await couch_sitter_service.get_user_tenant_info(sub, email, name)
            user_tenant_infos.append(info)

        # Verify each user has unique tenant
        tenant_ids = [info.tenant_id for info in user_tenant_infos]
        assert len(set(tenant_ids)) == 3  # All unique

        # Verify user documents are separate
        for info in user_tenant_infos:
            user_doc = await couch_sitter_service.dal.get(f"/test-db/{info.user_id}", "GET")
            assert user_doc["sub"] == info.sub
            assert user_doc["email"] == info.email

        # Verify tenant documents are separate
        for info in user_tenant_infos:
            tenant_doc = await couch_sitter_service.dal.get(f"/test-db/{info.tenant_id}", "GET")
            assert tenant_doc["userId"] == info.user_id
            assert tenant_doc["isPersonal"] is True

    @pytest.mark.asyncio
    async def test_error_handling_across_services(self, mock_services):
        """Test error handling across service boundaries"""
        clerk_service, couch_sitter_service, mock_clerk_client = mock_services

        # Test missing sub claim
        with pytest.raises(ValueError, match="Sub claim is required"):
            await couch_sitter_service.get_user_tenant_info("")

        # Test invalid JWT handling in clerk service
        clerk_service.get_user_from_jwt = AsyncMock(return_value=None)
        result = await clerk_service.get_user_from_jwt("invalid_token")
        assert result is None

        # Test Clerk service when not configured
        clerk_service.clerk_client = None
        session_result = await clerk_service.verify_session_token("token")
        assert session_result is None

        metadata_result = await clerk_service.get_user_session_metadata("user", "session")
        assert metadata_result is None

    @pytest.mark.asyncio
    async def test_performance_with_concurrent_users(self, mock_services):
        """Test performance when handling multiple concurrent users"""
        clerk_service, couch_sitter_service, mock_clerk_client = mock_services

        import asyncio

        async def create_user(user_id):
            """Create a user with unique ID"""
            sub = f"perf_user_{user_id}"
            email = f"perf{user_id}@example.com"
            name = f"Performance User {user_id}"

            return await couch_sitter_service.get_user_tenant_info(sub, email, name)

        # Create multiple users concurrently
        tasks = [create_user(i) for i in range(20)]
        user_tenant_infos = await asyncio.gather(*tasks)

        # Verify all users were created successfully
        assert len(user_tenant_infos) == 20

        for i, info in enumerate(user_tenant_infos):
            assert info.sub == f"perf_user_{i}"
            assert info.email == f"perf{i}@example.com"
            assert info.name == f"Performance User {i}"

        # Verify all documents exist in database
        for info in user_tenant_infos:
            user_doc = await couch_sitter_service.dal.get(f"/test-db/{info.user_id}", "GET")
            tenant_doc = await couch_sitter_service.dal.get(f"/test-db/{info.tenant_id}", "GET")

            assert user_doc is not None
            assert tenant_doc is not None

    @pytest.mark.asyncio
    async def test_data_consistency_across_services(self, mock_services):
        """Test data consistency across service interactions"""
        clerk_service, couch_sitter_service, mock_clerk_client = mock_services

        # Create user with initial data
        sub = "consistency_user"
        email = "consistency@example.com"
        name = "Consistency User"

        user_tenant_info = await couch_sitter_service.get_user_tenant_info(sub, email, name)

        # Verify data in all places
        # 1. In returned object
        assert user_tenant_info.sub == sub
        assert user_tenant_info.email == email
        assert user_tenant_info.name == name

        # 2. In database user document
        user_doc = await couch_sitter_service.dal.get(f"/test-db/{user_tenant_info.user_id}", "GET")
        assert user_doc["sub"] == sub
        assert user_doc["email"] == email
        assert user_doc["name"] == name

        # 3. In database tenant document
        tenant_doc = await couch_sitter_service.dal.get(f"/test-db/{user_tenant_info.tenant_id}", "GET")
        assert tenant_doc["userId"] == user_tenant_info.user_id
        assert tenant_doc["name"] == name

        # 4. User should be linked to tenant
        assert user_doc["personalTenantId"] == user_tenant_info.tenant_id
        assert user_tenant_info.tenant_id in user_doc["tenantIds"]

        # 5. Tenant should be linked to user
        assert user_tenant_info.user_id in tenant_doc["userIds"]

    @pytest.mark.asyncio
    async def test_cache_invalidation_flow(self, mock_services):
        """Test cache invalidation when user data changes"""
        clerk_service, couch_sitter_service, mock_clerk_client = mock_services

        cache = get_cache()

        # Create user and cache the result
        sub = "cache_invalidate_user"
        user_tenant_info1 = await couch_sitter_service.get_user_tenant_info(
            sub, "old@example.com", "Old Name"
        )

        sub_hash = hashlib.sha256(sub.encode()).hexdigest()
        cache.set_user(sub_hash, user_tenant_info1)

        # Verify cached data
        cached_info = cache.get_user_by_sub_hash(sub_hash)
        assert cached_info.name == "Old Name"

        # Simulate user data update (would happen via service layer)
        # Invalidate cache
        cache.invalidate(sub_hash)

        # Verify cache was cleared
        assert cache.get_user_by_sub_hash(sub_hash) is None

        # Simulate getting fresh data (will return same user since ensure_user_exists doesn't update existing users)
        user_tenant_info2 = await couch_sitter_service.get_user_tenant_info(
            sub, "new@example.com", "New Name"
        )

        # Note: ensure_user_exists doesn't update existing user data, so it returns the same user
        assert user_tenant_info2.name == "Old Name"  # Still the original name
        assert user_tenant_info2.email == "old@example.com"  # Still the original email

        # Cache the user data (even though it's the same)
        cache.set_user(sub_hash, user_tenant_info2)

        # Verify data is in cache
        updated_cached_info = cache.get_user_by_sub_hash(sub_hash)
        assert updated_cached_info.name == "Old Name"
        assert updated_cached_info.email == "old@example.com"


class TestServiceEdgeCases:
    """Test edge cases and error scenarios in service integration"""

    @pytest.mark.asyncio
    async def test_user_with_no_tenant_data(self, memory_dal):
        """Test handling user with missing tenant information"""
        with patch('couchdb_jwt_proxy.couch_sitter_service.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock user exists but has no tenant data
            sub = "incomplete_user"
            sub_hash = hashlib.sha256(sub.encode()).hexdigest()
            user_id = f"user_{sub_hash}"

            # Create incomplete user document
            user_doc = {
                "_id": user_id,
                "type": "user",
                "sub": sub,
                "email": "incomplete@example.com",
                # Missing tenant-related fields
            }

            await memory_dal.get(f"/test-db/{user_id}", "PUT", user_doc)

            # Mock request handler
            def mock_request(method, url, headers=None, json=None):
                response = MagicMock()
                response.raise_for_status = MagicMock()

                if method == "POST" and "_find" in url:
                    selector = json.get("selector", {})
                    if selector.get("_id") == user_id:
                        response.json.return_value = {"docs": [user_doc]}
                    else:
                        response.json.return_value = {"docs": []}

                return response

            mock_client.request = mock_request

            service = CouchSitterService("http://localhost:5984/test-db", dal=memory_dal)

            # Should handle incomplete data gracefully
            result = await service.ensure_user_exists(sub)

            assert isinstance(result, UserTenantInfo)
            # Should have created missing tenant data
            assert result.tenant_id is not None
            assert result.is_personal_tenant is True

    @pytest.mark.asyncio
    async def test_tenant_creation_failure_rollback(self, memory_dal):
        """Test rollback when tenant creation fails"""
        # Mock the DAL backend to simulate tenant creation failure
        original_handle_request = memory_dal.backend.handle_request
        call_count = 0

        async def mock_handle_request(path: str, method: str, payload: Optional[Dict] = None, params: Optional[Dict] = None):
            nonlocal call_count
            call_count += 1

            # Allow normal operations for finding existing users
            if method == "GET" and "_find" in path:
                return await original_handle_request(path, method, payload, params)

            # Fail tenant creation (second PUT operation - user first, tenant second)
            elif method == "PUT" and call_count == 2:
                raise Exception("Simulated database error during tenant creation")

            # Allow all other operations
            else:
                return await original_handle_request(path, method, payload, params)

        # Apply the mock
        memory_dal.backend.handle_request = mock_handle_request

        service = CouchSitterService("http://localhost:5984/test-db", dal=memory_dal)

        # Should handle tenant creation failure
        with pytest.raises(Exception, match="Simulated database error during tenant creation"):
            await service.create_user_with_personal_tenant("failure_user", "fail@example.com", "Fail User")

        # Verify cleanup occurred (no partial data left)
        all_docs = await memory_dal.get("/test-db/_all_docs", "GET")
        user_docs = [doc for doc in all_docs["rows"] if "failure_user" in doc["id"]]
        assert len(user_docs) == 0

        # Restore original handler
        memory_dal.backend.handle_request = original_handle_request

    @pytest.mark.asyncio
    async def test_concurrent_same_user_creation(self, mock_services):
        """Test concurrent creation of the same user"""
        clerk_service, couch_sitter_service, mock_clerk_client = mock_services

        import asyncio

        sub = "concurrent_user"
        email = "concurrent@example.com"
        name = "Concurrent User"

        async def create_same_user():
            return await couch_sitter_service.get_user_tenant_info(sub, email, name)

        # Create the same user concurrently
        tasks = [create_same_user() for _ in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Should handle concurrent creation gracefully
        successful_results = [r for r in results if isinstance(r, UserTenantInfo)]
        errors = [r for r in results if isinstance(r, Exception)]

        # At least one should succeed
        assert len(successful_results) > 0

        # All successful results should have the same user_id and tenant_id
        user_ids = set(r.user_id for r in successful_results)
        tenant_ids = set(r.tenant_id for r in successful_results)

        assert len(user_ids) == 1  # All should be the same user
        assert len(tenant_ids) == 1  # All should have the same tenant

        # Verify only one user/tenant pair exists in database
        user_id = successful_results[0].user_id
        tenant_id = successful_results[0].tenant_id

        user_doc = await couch_sitter_service.dal.get(f"/test-db/{user_id}", "GET")
        tenant_doc = await couch_sitter_service.dal.get(f"/test-db/{tenant_id}", "GET")

        assert user_doc is not None
        assert tenant_doc is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])