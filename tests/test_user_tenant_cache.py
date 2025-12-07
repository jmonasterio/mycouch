"""
User Tenant Cache tests.

Tests TTL functionality, thread safety, and cache operations using Memory DAL.
"""

import pytest
import time
import threading
from unittest.mock import patch, MagicMock, AsyncMock
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

# Import cache modules
from couchdb_jwt_proxy.user_tenant_cache import (
    UserTenantCache,
    UserTenantInfo,
    get_cache,
    reset_cache
)
from couchdb_jwt_proxy.dal import create_dal


class TestUserTenantInfo:
    """Test UserTenantInfo dataclass"""

    def test_user_tenant_info_creation(self):
        """Test UserTenantInfo creation with all fields"""
        info = UserTenantInfo(
            user_id="user_abc123",
            tenant_id="tenant_def456",
            sub="sub_ghi789",
            email="test@example.com",
            name="Test User",
            is_personal_tenant=True,
            cached_at=1640995200.0  # Fixed timestamp
        )

        assert info.user_id == "user_abc123"
        assert info.tenant_id == "tenant_def456"
        assert info.sub == "sub_ghi789"
        assert info.email == "test@example.com"
        assert info.name == "Test User"
        assert info.is_personal_tenant is True
        assert info.cached_at == 1640995200.0

    def test_user_tenant_info_defaults(self):
        """Test UserTenantInfo with default values"""
        info = UserTenantInfo(
            user_id="user_abc123",
            tenant_id="tenant_def456",
            sub="sub_ghi789"
        )

        assert info.user_id == "user_abc123"
        assert info.tenant_id == "tenant_def456"
        assert info.sub == "sub_ghi789"
        assert info.email is None
        assert info.name is None
        assert info.is_personal_tenant is True  # Default value
        assert info.cached_at is not None  # Should be auto-generated

    def test_user_tenant_info_post_init(self):
        """Test UserTenantInfo post_init sets cached_at if not provided"""
        info = UserTenantInfo(
            user_id="user_abc123",
            tenant_id="tenant_def456",
            sub="sub_ghi789"
        )

        # cached_at should be set to current time
        current_time = time.time()
        assert abs(info.cached_at - current_time) < 1.0  # Within 1 second

    def test_user_tenant_info_preserves_cached_at(self):
        """Test UserTenantInfo preserves provided cached_at"""
        custom_time = 1640995200.0
        info = UserTenantInfo(
            user_id="user_abc123",
            tenant_id="tenant_def456",
            sub="sub_ghi789",
            cached_at=custom_time
        )

        assert info.cached_at == custom_time


class TestUserTenantCache:
    """Test UserTenantCache functionality"""

    @pytest.fixture
    def cache(self):
        """Create UserTenantCache instance for testing"""
        cache = UserTenantCache(ttl_seconds=300)
        return cache

    def test_cache_initialization(self):
        """Test UserTenantCache initialization"""
        cache = UserTenantCache(ttl_seconds=600)

        assert cache.ttl_seconds == 600
        assert isinstance(cache._cache, dict)
        assert isinstance(cache._lock, type(threading.RLock()))
        assert len(cache._cache) == 0

    def test_cache_default_ttl(self):
        """Test UserTenantCache default TTL"""
        cache = UserTenantCache()  # No TTL specified

        assert cache.ttl_seconds == 300  # Default value

    def test_set_and_get_user(self, cache):
        """Test setting and getting user data"""
        sub_hash = "abc123hash"
        user_info = UserTenantInfo(
            user_id="user_abc123",
            tenant_id="tenant_def456",
            sub="sub_ghi789",
            email="test@example.com"
        )

        # Set user
        cache.set_user(sub_hash, user_info)

        # Get user
        cached_info = cache.get_user_by_sub_hash(sub_hash)

        assert cached_info is not None
        assert cached_info.user_id == "user_abc123"
        assert cached_info.tenant_id == "tenant_def456"
        assert cached_info.sub == "sub_ghi789"
        assert cached_info.email == "test@example.com"

    def test_get_nonexistent_user(self, cache):
        """Test getting non-existent user"""
        cached_info = cache.get_user_by_sub_hash("nonexistent_hash")

        assert cached_info is None

    def test_get_expired_user(self, cache):
        """Test getting expired user"""
        sub_hash = "expired_hash"
        user_info = UserTenantInfo(
            user_id="user_expired",
            tenant_id="tenant_expired",
            sub="sub_expired"
        )

        # Set user with old timestamp - directly set in cache to override set_user's timestamp update
        user_info.cached_at = time.time() - 400  # 400 seconds ago (expired for 300s TTL)
        cache._cache[sub_hash] = user_info  # Direct cache access to preserve old timestamp

        # Should return None due to expiration
        cached_info = cache.get_user_by_sub_hash(sub_hash)
        assert cached_info is None

        # Should also be removed from cache
        assert sub_hash not in cache._cache

    def test_set_updates_cached_at(self, cache):
        """Test that set_user updates cached_at timestamp"""
        sub_hash = "timestamp_test"
        user_info = UserTenantInfo(
            user_id="user_timestamp",
            tenant_id="tenant_timestamp",
            sub="sub_timestamp",
            cached_at=1000.0  # Old timestamp
        )

        # Set user
        cache.set_user(sub_hash, user_info)

        # cached_at should be updated to current time
        current_time = time.time()
        assert abs(user_info.cached_at - current_time) < 1.0

    def test_invalidate_user(self, cache):
        """Test invalidating a specific user"""
        sub_hash = "invalidate_test"
        user_info = UserTenantInfo(
            user_id="user_invalidate",
            tenant_id="tenant_invalidate",
            sub="sub_invalidate"
        )

        # Set user
        cache.set_user(sub_hash, user_info)
        assert cache.get_user_by_sub_hash(sub_hash) is not None

        # Invalidate user
        result = cache.invalidate(sub_hash)

        assert result is True
        assert cache.get_user_by_sub_hash(sub_hash) is None

    def test_invalidate_nonexistent_user(self, cache):
        """Test invalidating non-existent user"""
        result = cache.invalidate("nonexistent_hash")
        assert result is False

    def test_clear_all(self, cache):
        """Test clearing all cache entries"""
        # Set multiple users
        for i in range(5):
            sub_hash = f"hash_{i}"
            user_info = UserTenantInfo(
                user_id=f"user_{i}",
                tenant_id=f"tenant_{i}",
                sub=f"sub_{i}"
            )
            cache.set_user(sub_hash, user_info)

        # Verify entries exist
        assert len(cache._cache) == 5

        # Clear all
        removed_count = cache.clear_all()

        assert removed_count == 5
        assert len(cache._cache) == 0

        # Verify all entries are gone
        for i in range(5):
            assert cache.get_user_by_sub_hash(f"hash_{i}") is None

    def test_get_stats(self, cache):
        """Test cache statistics"""
        # Add some entries
        current_time = time.time()

        # Valid entry
        valid_info = UserTenantInfo(
            user_id="user_valid",
            tenant_id="tenant_valid",
            sub="sub_valid",
            cached_at=current_time
        )
        cache.set_user("valid_hash", valid_info)

        # Expired entry
        expired_info = UserTenantInfo(
            user_id="user_expired",
            tenant_id="tenant_expired",
            sub="sub_expired",
            cached_at=current_time - 400  # Expired for 300s TTL
        )
        cache._cache["expired_hash"] = expired_info

        stats = cache.get_stats()

        assert stats["total_entries"] == 2
        assert stats["expired_entries"] == 1
        assert stats["valid_entries"] == 1
        assert stats["ttl_seconds"] == 300

    def test_cleanup_expired_entries(self, cache):
        """Test cleanup of expired entries"""
        current_time = time.time()

        # Add valid and expired entries
        valid_info = UserTenantInfo(
            user_id="user_valid",
            tenant_id="tenant_valid",
            sub="sub_valid",
            cached_at=current_time
        )
        cache.set_user("valid_hash", valid_info)

        expired_info = UserTenantInfo(
            user_id="user_expired",
            tenant_id="tenant_expired",
            sub="sub_expired",
            cached_at=current_time - 400  # Expired
        )
        cache._cache["expired_hash"] = expired_info

        # Verify both exist
        assert len(cache._cache) == 2

        # Cleanup expired entries
        remaining_count = cache.cleanup_expired_entries()

        # Should have only valid entry left
        assert remaining_count == 1
        assert len(cache._cache) == 1
        assert "valid_hash" in cache._cache
        assert "expired_hash" not in cache._cache

    def test_thread_safety_concurrent_access(self, cache):
        """Test thread safety with concurrent cache access"""
        results = []
        errors = []

        def worker(worker_id):
            try:
                for i in range(100):
                    sub_hash = f"worker_{worker_id}_{i}"
                    user_info = UserTenantInfo(
                        user_id=f"user_{worker_id}_{i}",
                        tenant_id=f"tenant_{worker_id}_{i}",
                        sub=f"sub_{worker_id}_{i}"
                    )

                    # Set user
                    cache.set_user(sub_hash, user_info)

                    # Get user
                    cached_info = cache.get_user_by_sub_hash(sub_hash)

                    results.append((worker_id, i, cached_info is not None))
            except Exception as e:
                errors.append((worker_id, e))

        # Start multiple threads
        threads = []
        for worker_id in range(5):
            thread = threading.Thread(target=worker, args=(worker_id,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify no errors occurred
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Verify all operations completed successfully
        assert len(results) == 500  # 5 workers * 100 operations each

        # Verify all operations succeeded
        for worker_id, i, success in results:
            assert success is True

        # Verify cache contains all entries
        assert len(cache._cache) == 500

    def test_thread_safety_mixed_operations(self, cache):
        """Test thread safety with mixed cache operations"""
        errors = []

        def set_worker(worker_id):
            try:
                for i in range(50):
                    sub_hash = f"set_{worker_id}_{i}"
                    user_info = UserTenantInfo(
                        user_id=f"user_{worker_id}_{i}",
                        tenant_id=f"tenant_{worker_id}_{i}",
                        sub=f"sub_{worker_id}_{i}"
                    )
                    cache.set_user(sub_hash, user_info)
            except Exception as e:
                errors.append(f"set_worker_{worker_id}: {e}")

        def get_worker(worker_id):
            try:
                for i in range(50):
                    sub_hash = f"set_{worker_id}_{i}"
                    cache.get_user_by_sub_hash(sub_hash)
            except Exception as e:
                errors.append(f"get_worker_{worker_id}: {e}")

        def invalidate_worker(worker_id):
            try:
                for i in range(50):
                    sub_hash = f"set_{worker_id}_{i}"
                    cache.invalidate(sub_hash)
            except Exception as e:
                errors.append(f"invalidate_worker_{worker_id}: {e}")

        # Start multiple threads with different operations
        threads = []
        for worker_id in range(3):
            set_thread = threading.Thread(target=set_worker, args=(worker_id,))
            get_thread = threading.Thread(target=get_worker, args=(worker_id,))
            invalidate_thread = threading.Thread(target=invalidate_worker, args=(worker_id,))

            threads.extend([set_thread, get_thread, invalidate_thread])
            set_thread.start()
            get_thread.start()
            invalidate_thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify no errors occurred
        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_cache_isolation(self):
        """Test that different cache instances are isolated"""
        cache1 = UserTenantCache(ttl_seconds=100)
        cache2 = UserTenantCache(ttl_seconds=200)

        sub_hash = "isolation_test"
        user_info1 = UserTenantInfo(
            user_id="user_cache1",
            tenant_id="tenant_cache1",
            sub="sub_cache1"
        )
        user_info2 = UserTenantInfo(
            user_id="user_cache2",
            tenant_id="tenant_cache2",
            sub="sub_cache2"
        )

        # Set same key in both caches with different values
        cache1.set_user(sub_hash, user_info1)
        cache2.set_user(sub_hash, user_info2)

        # Each cache should return its own value
        cached1 = cache1.get_user_by_sub_hash(sub_hash)
        cached2 = cache2.get_user_by_sub_hash(sub_hash)

        assert cached1.user_id == "user_cache1"
        assert cached2.user_id == "user_cache2"

        # Verify separate TTL settings
        assert cache1.ttl_seconds == 100
        assert cache2.ttl_seconds == 200


class TestUserTenantCacheGlobal:
    """Test global cache instance functionality"""

    def test_get_cache_singleton(self):
        """Test that get_cache returns the same instance"""
        with patch('couchdb_jwt_proxy.user_tenant_cache.os.getenv') as mock_getenv:
            mock_getenv.return_value = "300"

            cache1 = get_cache()
            cache2 = get_cache()

            assert cache1 is cache2
            assert isinstance(cache1, UserTenantCache)

    def test_get_cache_with_custom_ttl(self):
        """Test get_cache with custom TTL from environment"""
        with patch('couchdb_jwt_proxy.user_tenant_cache.os.getenv') as mock_getenv:
            mock_getenv.return_value = "600"

            # Reset the global cache first
            reset_cache()

            cache = get_cache()

            assert cache.ttl_seconds == 600

            # Clean up
            reset_cache()

    def test_get_cache_default_ttl(self):
        """Test get_cache with default TTL when environment variable not set"""
        with patch('couchdb_jwt_proxy.user_tenant_cache.os.getenv') as mock_getenv:
            mock_getenv.return_value = None

            cache = get_cache()

            assert cache.ttl_seconds == 300  # Default value

    def test_reset_cache(self):
        """Test reset_cache functionality"""
        with patch('couchdb_jwt_proxy.user_tenant_cache.os.getenv') as mock_getenv:
            mock_getenv.return_value = "300"

            # Get initial cache instance
            cache1 = get_cache()
            cache1.set_user("test", UserTenantInfo("user", "tenant", "sub"))

            # Reset cache
            reset_cache()

            # Get new cache instance
            cache2 = get_cache()

            # Should be different instances
            assert cache1 is not cache2
            assert len(cache2._cache) == 0  # Should be empty

    def test_get_cache_thread_safety(self):
        """Test get_cache thread safety"""
        caches = []

        def worker():
            cache = get_cache()
            caches.append(cache)

        # Start multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All threads should get the same cache instance
        assert len(set(caches)) == 1
        assert all(isinstance(cache, UserTenantCache) for cache in caches)


class TestUserTenantCacheIntegration:
    """Integration tests for UserTenantCache"""

    @pytest.mark.asyncio
    async def test_cache_with_service_simulation(self):
        """Test cache behavior simulating service layer usage"""
        cache = UserTenantCache(ttl_seconds=60)

        # Simulate user login - cache user data
        user_info = UserTenantInfo(
            user_id="user_login_test",
            tenant_id="tenant_login_test",
            sub="sub_login_test",
            email="login@example.com",
            name="Login User"
        )
        cache.set_user("login_hash", user_info)

        # Simulate authentication check - should get from cache
        cached_info = cache.get_user_by_sub_hash("login_hash")
        assert cached_info is not None
        assert cached_info.email == "login@example.com"

        # Simulate user logout - invalidate cache
        success = cache.invalidate("login_hash")
        assert success is True

        # Simulate post-logout check - should not be in cache
        cached_info = cache.get_user_by_sub_hash("login_hash")
        assert cached_info is None

    def test_cache_performance_with_large_dataset(self):
        """Test cache performance with large dataset"""
        cache = UserTenantCache(ttl_seconds=3600)  # 1 hour

        # Create large dataset (reduced from 1000 to 100 for faster unit tests)
        large_dataset = [
            UserTenantInfo(
                user_id=f"user_{i}",
                tenant_id=f"tenant_{i}",
                sub=f"sub_{i}",
                email=f"user_{i}@example.com"
            )
            for i in range(100)
        ]

        # Time cache operations
        start_time = time.time()

        # Cache all users
        for i, user_info in enumerate(large_dataset):
            sub_hash = f"hash_{i}"
            cache.set_user(sub_hash, user_info)

        set_time = time.time() - start_time

        # Retrieve all users
        start_time = time.time()
        for i in range(100):  # Match the dataset size
            sub_hash = f"hash_{i}"
            cached_info = cache.get_user_by_sub_hash(sub_hash)
            assert cached_info is not None
            assert cached_info.user_id == f"user_{i}"

        get_time = time.time() - start_time

        # Performance should be reasonable
        assert set_time < 1.0  # Should complete in under 1 second
        assert get_time < 0.5  # Retrieval should be faster

        # Verify cache size (should match dataset size)
        assert len(cache._cache) == 100

    def test_cache_memory_usage(self):
        """Test cache memory usage tracking"""
        cache = UserTenantCache()

        # Add some entries
        for i in range(100):
            user_info = UserTenantInfo(
                user_id=f"user_{i}",
                tenant_id=f"tenant_{i}",
                sub=f"sub_{i}",
                email=f"user_{i}@example.com"
            )
            cache.set_user(f"hash_{i}", user_info)

        stats = cache.get_stats()

        assert stats["total_entries"] == 100
        assert stats["valid_entries"] == 100
        assert stats["expired_entries"] == 0
        assert stats["ttl_seconds"] == 300

        # Memory usage should be reported
        assert "memory_usage_kb" in stats

    def test_cache_ttl_behavior(self):
        """Test cache TTL behavior with different times"""
        from unittest.mock import patch
        cache = UserTenantCache(ttl_seconds=2)  # Very short TTL for testing

        user_info = UserTenantInfo(
            user_id="user_ttl_test",
            tenant_id="tenant_ttl_test",
            sub="sub_ttl_test"
        )

        with patch('time.time') as mock_time:
            # Mock time progression
            mock_time.side_effect = [0, 1, 5]  # Initial, set time, expired time

            # Set user (time = 0)
            cache.set_user("ttl_hash", user_info)

            # Should be cached immediately (time = 1)
            cached_info = cache.get_user_by_sub_hash("ttl_hash")
            assert cached_info is not None

            # Simulate time passing to expiration (time = 5)
            cached_info = cache.get_user_by_sub_hash("ttl_hash")
            assert cached_info is None  # Expired

    def test_cache_edge_cases(self):
        """Test cache edge cases"""
        cache = UserTenantCache()

        # Test with None values
        user_info = UserTenantInfo(
            user_id="user_edge",
            tenant_id="tenant_edge",
            sub="sub_edge",
            email=None,
            name=None
        )
        cache.set_user("edge_hash", user_info)

        cached_info = cache.get_user_by_sub_hash("edge_hash")
        assert cached_info is not None
        assert cached_info.email is None
        assert cached_info.name is None

        # Test with empty strings
        user_info2 = UserTenantInfo(
            user_id="user_edge2",
            tenant_id="tenant_edge2",
            sub="sub_edge2",
            email="",
            name=""
        )
        cache.set_user("edge_hash2", user_info2)

        cached_info2 = cache.get_user_by_sub_hash("edge_hash2")
        assert cached_info2 is not None
        assert cached_info2.email == ""
        assert cached_info2.name == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])