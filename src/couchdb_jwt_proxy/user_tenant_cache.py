"""
User Tenant Cache Module

Provides in-memory caching of user and tenant information to reduce
database queries and improve performance of the JWT proxy.
"""

import os
import sys
import time
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class UserTenantInfo:
    """Data class representing user and tenant information"""
    user_id: str  # CouchDB user document _id (user_<sub_hash>)
    tenant_id: str  # CouchDB tenant document _id (tenant_<uuid>)
    sub: str  # Original Clerk sub claim
    email: Optional[str] = None
    name: Optional[str] = None
    is_personal_tenant: bool = True
    cached_at: float = None

    def __post_init__(self):
        if self.cached_at is None:
            self.cached_at = time.time()


class UserTenantCache:
    """
    Thread-safe in-memory cache for user and tenant information.

    Features:
    - Thread-safe operations using threading.Lock
    - TTL (time-to-live) support with automatic cleanup
    - Simple dictionary-based lookup by sub_hash
    - Logging for debugging and monitoring
    """

    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize the cache.

        Args:
            ttl_seconds: Time-to-live for cache entries (default: 5 minutes)
        """
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, UserTenantInfo] = {}
        self._lock = threading.RLock()
        logger.info(f"UserTenantCache initialized with TTL={ttl_seconds}s")

    def _is_expired(self, info: UserTenantInfo) -> bool:
        """Check if a cache entry has expired."""
        return time.time() - info.cached_at > self.ttl_seconds

    def _cleanup_expired(self):
        """Remove expired entries from the cache."""
        current_time = time.time()
        expired_keys = []

        for key, info in self._cache.items():
            if current_time - info.cached_at > self.ttl_seconds:
                expired_keys.append(key)

        for key in expired_keys:
            del self._cache[key]
            logger.debug(f"Removed expired cache entry: {key}")

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

    def get_user_by_sub_hash(self, sub_hash: str) -> Optional[UserTenantInfo]:
        """
        Get user and tenant information by sub_hash.

        Args:
            sub_hash: SHA256 hash of the Clerk sub claim

        Returns:
            UserTenantInfo if found and not expired, None otherwise
        """
        with self._lock:
            info = self._cache.get(sub_hash)

            if info is None:
                logger.debug(f"Cache miss for sub_hash: {sub_hash}")
                return None

            if self._is_expired(info):
                logger.debug(f"Cache expired for sub_hash: {sub_hash}")
                del self._cache[sub_hash]
                return None

            logger.debug(f"Cache hit for sub_hash: {sub_hash} -> user_id={info.user_id}, tenant_id={info.tenant_id}")
            return info

    def set_user(self, sub_hash: str, info: UserTenantInfo) -> None:
        """
        Store user and tenant information in the cache.

        Args:
            sub_hash: SHA256 hash of the Clerk sub claim
            info: UserTenantInfo to cache
        """
        with self._lock:
            # Update cache timestamp
            info.cached_at = time.time()
            self._cache[sub_hash] = info
            logger.debug(f"Cached user info for sub_hash: {sub_hash} -> user_id={info.user_id}, tenant_id={info.tenant_id}")

    def invalidate(self, sub_hash: str) -> bool:
        """
        Remove a specific entry from the cache.

        Args:
            sub_hash: SHA256 hash of the Clerk sub claim to remove

        Returns:
            True if entry was removed, False if not found
        """
        with self._lock:
            if sub_hash in self._cache:
                del self._cache[sub_hash]
                logger.debug(f"Invalidated cache entry for sub_hash: {sub_hash}")
                return True
            return False

    def clear_all(self) -> int:
        """
        Clear all entries from the cache.

        Returns:
            Number of entries that were removed
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cleared all cache entries ({count} removed)")
            return count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            current_time = time.time()
            total_entries = len(self._cache)
            expired_count = sum(1 for info in self._cache.values() if self._is_expired(info))

            return {
                "total_entries": total_entries,
                "expired_entries": expired_count,
                "valid_entries": total_entries - expired_count,
                "ttl_seconds": self.ttl_seconds,
                "memory_usage_kb": sys.getsizeof(self._cache) / 1024 if 'sys' in globals() else "unknown"
            }

    def cleanup_expired_entries(self) -> int:
        """
        Manually trigger cleanup of expired entries.

        Returns:
            Number of entries that were removed
        """
        with self._lock:
            self._cleanup_expired()
            return len(self._cache)


# Global cache instance
_cache_instance: Optional[UserTenantCache] = None
_cache_lock = threading.Lock()


def get_cache() -> UserTenantCache:
    """
    Get the global cache instance, creating it if necessary.

    Returns:
        Global UserTenantCache instance
    """
    global _cache_instance

    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                env_value = os.getenv("USER_CACHE_TTL_SECONDS")
                ttl = int(env_value) if env_value is not None else 300
                _cache_instance = UserTenantCache(ttl_seconds=ttl)

    return _cache_instance


def reset_cache() -> None:
    """Reset the global cache instance (mainly for testing)."""
    global _cache_instance

    with _cache_lock:
        _cache_instance = None