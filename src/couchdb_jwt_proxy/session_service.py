"""
Session Service Module

Manages session documents in couch-sitter with per-session tenant mapping.
Uses in-memory cache (1-hour TTL) to avoid repeated CouchDB queries.

Schema (couch-sitter):
{
  "_id": "sess_abc123xyz",           # Clerk session ID (no prefix needed)
  "type": "session",
  "sid": "sess_abc123xyz",           # Clerk session ID (for consistency)
  "user_id": "user_hash",            # User hash (for queries)
  "app_id": "https://my-app.clerk.accounts.dev",  # Clerk issuer (app identifier)
  "active_tenant_id": "band-123",    # Current tenant for this session
  "created_at": "2025-01-01T12:00Z",
  "expiresAt": "2025-01-02T12:00Z"   # TTL for cleanup (24 hrs)
}
"""

import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SessionService:
    """Manage session documents with in-memory cache."""

    def __init__(self, dal):
        """
        Initialize SessionService.
        
        Args:
            dal: Data Access Layer instance for CouchDB operations
        """
        self.dal = dal
        self._cache: Dict[str, Dict[str, Any]] = {}  # sid → {active_tenant_id, cached_at}
        self._cache_ttl = 3600  # 1 hour TTL for cache entries

    async def create_session(
        self,
        sid: str,
        user_id: str,
        active_tenant_id: str,
        app_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create or update a session document in CouchDB and cache.
        
        Args:
            sid: Clerk session ID (e.g., "sess_abc123xyz")
            user_id: User ID hash (from JWT sub)
            active_tenant_id: Current tenant for this session
            app_id: Clerk issuer/app identifier (e.g., "https://my-app.clerk.accounts.dev")
            
        Returns:
            Session document that was created/updated
            
        Raises:
            Exception: If CouchDB operation fails
        """
        doc_id = sid  # Use sid directly as _id (already has "sess_" prefix)
        now = datetime.utcnow().isoformat() + "Z"
        expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
        
        # Check if session already exists (for updating)
        existing_doc = None
        try:
            existing_doc = await self.dal.get_document("couch-sitter", doc_id)
        except Exception:
            pass  # Document doesn't exist, will create new
        
        session_doc = {
            "_id": doc_id,
            "type": "session",
            "sid": sid,
            "user_id": user_id,
            "app_id": app_id,
            "active_tenant_id": active_tenant_id,
            "created_at": existing_doc.get("created_at") if existing_doc else now,  # Preserve original creation time
            "expiresAt": expires_at
        }
        
        # If updating, include the revision
        if existing_doc and "_rev" in existing_doc:
            session_doc["_rev"] = existing_doc["_rev"]
        
        # Store in CouchDB
        try:
            result = await self.dal.put_document("couch-sitter", doc_id, session_doc)
            logger.info(f"[SessionService] Created/updated session: {sid} → {active_tenant_id}")
            session_doc["_rev"] = result.get("_rev")
        except Exception as e:
            logger.error(f"[SessionService] Failed to create session {sid}: {e}")
            raise
        
        # Update in-memory cache
        self._cache[sid] = {
            "active_tenant_id": active_tenant_id,
            "cached_at": time.time()
        }
        
        return session_doc

    async def get_active_tenant(self, sid: str) -> Optional[str]:
        """
        Get active tenant ID for a session (cache-first, fallback to CouchDB).
        
        Args:
            sid: Clerk session ID
            
        Returns:
            Active tenant ID string, or None if session not found
        """
        # Check cache first (fast path)
        cached = self._cache.get(sid)
        if cached:
            age = time.time() - cached["cached_at"]
            if age < self._cache_ttl:
                logger.debug(f"[SessionService] Cache hit for {sid}: {cached['active_tenant_id']} (age: {age:.1f}s)")
                return cached["active_tenant_id"]
            else:
                # Cache expired, remove it
                logger.debug(f"[SessionService] Cache expired for {sid} (age: {age:.1f}s > {self._cache_ttl}s)")
                self._cache.pop(sid, None)
        
        # Cache miss or expired: query CouchDB
        doc_id = f"session_{sid}"
        try:
            doc = await self.dal.get_document("couch-sitter", doc_id)
            active_tenant_id = doc.get("active_tenant_id")
            
            # Update cache with fresh data
            self._cache[sid] = {
                "active_tenant_id": active_tenant_id,
                "cached_at": time.time()
            }
            
            logger.debug(f"[SessionService] CouchDB hit for {sid}: {active_tenant_id}")
            return active_tenant_id
        except Exception as e:
            # Session document not found or other error
            logger.warning(f"[SessionService] Could not find session {sid} in CouchDB: {e}")
            return None

    async def delete_session(self, sid: str) -> bool:
        """
        Delete a session document from cache and CouchDB.
        
        Args:
            sid: Clerk session ID
            
        Returns:
            True if deleted, False if not found
        """
        # Remove from cache
        self._cache.pop(sid, None)
        
        # Remove from CouchDB
        doc_id = f"session_{sid}"
        try:
            doc = await self.dal.get_document("couch-sitter", doc_id)
            await self.dal.delete_document("couch-sitter", doc_id, doc.get("_rev"))
            logger.info(f"[SessionService] Deleted session: {sid}")
            return True
        except Exception as e:
            logger.warning(f"[SessionService] Could not delete session {sid}: {e}")
            return False

    def cleanup_expired_cache(self):
        """
        Remove stale entries from in-memory cache.
        Called periodically to prevent unbounded memory growth.
        """
        now = time.time()
        expired = [
            sid for sid, entry in self._cache.items()
            if (now - entry["cached_at"]) > self._cache_ttl
        ]
        
        if expired:
            for sid in expired:
                self._cache.pop(sid)
            logger.info(f"[SessionService] Cleaned {len(expired)} expired cache entries")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics (for monitoring/debugging).
        
        Returns:
            Dict with cache size, TTL, etc.
        """
        return {
            "cache_size": len(self._cache),
            "cache_ttl_seconds": self._cache_ttl,
            "cached_sids": list(self._cache.keys())
        }
