"""
Unit tests for SessionService
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from couchdb_jwt_proxy.session_service import SessionService


class TestSessionService:
    """Test SessionService functionality."""

    @pytest.fixture
    def mock_dal(self):
        """Create a mock DAL."""
        dal = AsyncMock()
        return dal

    @pytest.fixture
    def session_service(self, mock_dal):
        """Create a SessionService instance."""
        return SessionService(mock_dal)

    @pytest.mark.asyncio
    async def test_create_session(self, session_service, mock_dal):
        """Test creating a new session."""
        # Mock DAL response
        mock_dal.put_document.return_value = {
            "_id": "session_sess123",
            "_rev": "1-abc"
        }

        # Create session
        result = await session_service.create_session(
            sid="sess123",
            user_id="user_hash123",
            active_tenant_id="band-456"
        )

        # Verify CouchDB call
        mock_dal.put_document.assert_called_once()
        call_args = mock_dal.put_document.call_args
        assert call_args[0][0] == "couch-sitter"
        assert call_args[0][1] == "sess123"

        doc = call_args[0][2]
        assert doc["type"] == "session"
        assert doc["sid"] == "sess123"
        assert doc["user_id"] == "user_hash123"
        assert doc["active_tenant_id"] == "band-456"
        assert "expiresAt" in doc
        assert "created_at" in doc

        # Verify result
        assert result["sid"] == "sess123"
        assert result["active_tenant_id"] == "band-456"
        assert result["_rev"] == "1-abc"

    @pytest.mark.asyncio
    async def test_create_session_with_ttl(self, session_service, mock_dal):
        """Test that session has proper TTL (24 hours from now)."""
        mock_dal.put_document.return_value = {"_rev": "1-abc"}

        now_before = datetime.utcnow()
        await session_service.create_session(
            sid="sess123",
            user_id="user_hash",
            active_tenant_id="band-1"
        )
        now_after = datetime.utcnow()

        call_args = mock_dal.put_document.call_args
        doc = call_args[0][2]
        # Parse ISO format string, removing the "Z" suffix which indicates UTC
        expires_at_str = doc["expiresAt"].replace("Z", "")
        expires_at = datetime.fromisoformat(expires_at_str)
        
        # Average the before/after times
        elapsed = (now_after - now_before).total_seconds() / 2
        now_avg = now_before + timedelta(seconds=elapsed)

        # Should expire in ~24 hours
        ttl = (expires_at - now_avg).total_seconds()
        assert 86300 < ttl < 86500  # ~24 hours (±100 seconds tolerance)

    @pytest.mark.asyncio
    async def test_get_active_tenant_cache_hit(self, session_service, mock_dal):
        """Test cache hit for get_active_tenant."""
        # Populate cache directly
        sid = "sess123"
        session_service._cache[sid] = {
            "active_tenant_id": "band-999",
            "cached_at": time.time()
        }

        # Get active tenant - should use cache
        result = await session_service.get_active_tenant(sid)

        # DAL should NOT be called
        mock_dal.get_document.assert_not_called()
        assert result == "band-999"

    @pytest.mark.asyncio
    async def test_get_active_tenant_cache_miss_couchdb_hit(self, session_service, mock_dal):
        """Test cache miss, CouchDB hit."""
        # Mock CouchDB response
        mock_dal.get_document.return_value = {
            "_id": "session_sess123",
            "type": "session",
            "active_tenant_id": "band-456"
        }

        # Get active tenant
        result = await session_service.get_active_tenant("sess123")

        # Verify CouchDB was queried
        mock_dal.get_document.assert_called_once_with("couch-sitter", "session_sess123")
        assert result == "band-456"

        # Verify cache was populated
        assert "sess123" in session_service._cache
        assert session_service._cache["sess123"]["active_tenant_id"] == "band-456"

    @pytest.mark.asyncio
    async def test_get_active_tenant_not_found(self, session_service, mock_dal):
        """Test session not found in CouchDB."""
        # Mock 404 error
        mock_dal.get_document.side_effect = Exception("not_found")

        result = await session_service.get_active_tenant("sess123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_tenant_cache_expired(self, session_service, mock_dal):
        """Test that expired cache entries are ignored."""
        sid = "sess123"
        # Put expired entry in cache
        session_service._cache[sid] = {
            "active_tenant_id": "band-old",
            "cached_at": time.time() - 4000  # 1+ hour old
        }

        # Mock CouchDB response
        mock_dal.get_document.return_value = {
            "active_tenant_id": "band-new"
        }

        result = await session_service.get_active_tenant(sid)

        # Should query CouchDB (cache expired)
        mock_dal.get_document.assert_called_once()
        assert result == "band-new"

        # Cache should be updated
        assert session_service._cache[sid]["active_tenant_id"] == "band-new"

    @pytest.mark.asyncio
    async def test_delete_session(self, session_service, mock_dal):
        """Test deleting a session."""
        sid = "sess123"

        # Put something in cache
        session_service._cache[sid] = {
            "active_tenant_id": "band-1",
            "cached_at": time.time()
        }

        # Mock CouchDB responses
        mock_dal.get_document.return_value = {
            "_id": "session_sess123",
            "_rev": "1-abc"
        }
        mock_dal.delete_document.return_value = {"ok": True}

        result = await session_service.delete_session(sid)

        # Verify
        assert result is True
        mock_dal.get_document.assert_called_once_with("couch-sitter", "session_sess123")
        mock_dal.delete_document.assert_called_once_with("couch-sitter", "session_sess123", "1-abc")

        # Verify cache was cleared
        assert sid not in session_service._cache

    @pytest.mark.asyncio
    async def test_delete_session_not_found(self, session_service, mock_dal):
        """Test deleting a non-existent session."""
        mock_dal.get_document.side_effect = Exception("not_found")

        result = await session_service.delete_session("sess123")

        assert result is False

    def test_cleanup_expired_cache(self, session_service):
        """Test cleaning up expired cache entries."""
        now = time.time()

        # Add mix of fresh and expired entries
        session_service._cache = {
            "fresh1": {
                "active_tenant_id": "band-1",
                "cached_at": now - 100  # Fresh (100 seconds old)
            },
            "fresh2": {
                "active_tenant_id": "band-2",
                "cached_at": now - 1000  # Fresh (1000 seconds old)
            },
            "expired1": {
                "active_tenant_id": "band-3",
                "cached_at": now - 4000  # Expired (4000 seconds old)
            },
            "expired2": {
                "active_tenant_id": "band-4",
                "cached_at": now - 5000  # Expired (5000 seconds old)
            },
        }

        session_service.cleanup_expired_cache()

        # Verify only fresh entries remain
        assert "fresh1" in session_service._cache
        assert "fresh2" in session_service._cache
        assert "expired1" not in session_service._cache
        assert "expired2" not in session_service._cache

    def test_get_cache_stats(self, session_service):
        """Test cache statistics."""
        session_service._cache = {
            "sess1": {"active_tenant_id": "band-1", "cached_at": time.time()},
            "sess2": {"active_tenant_id": "band-2", "cached_at": time.time()},
        }

        stats = session_service.get_cache_stats()

        assert stats["cache_size"] == 2
        assert stats["cache_ttl_seconds"] == 3600
        assert len(stats["cached_sids"]) == 2
        assert "sess1" in stats["cached_sids"]
        assert "sess2" in stats["cached_sids"]

    @pytest.mark.asyncio
    async def test_create_session_couchdb_failure(self, session_service, mock_dal):
        """Test handling of CouchDB errors during session creation."""
        mock_dal.put_document.side_effect = Exception("CouchDB error")

        with pytest.raises(Exception) as exc_info:
            await session_service.create_session("sess123", "user_hash", "band-1")

        assert "CouchDB error" in str(exc_info.value)
        # Cache should not be populated on failure
        assert "sess123" not in session_service._cache

    @pytest.mark.asyncio
    async def test_multiple_session_isolation(self, session_service, mock_dal):
        """Test that multiple sessions don't interfere with each other."""
        mock_dal.put_document.return_value = {"_rev": "1-abc"}

        # Create two sessions
        await session_service.create_session("sess1", "user1", "band-1")
        await session_service.create_session("sess2", "user2", "band-2")

        # Verify both are in cache
        assert session_service._cache["sess1"]["active_tenant_id"] == "band-1"
        assert session_service._cache["sess2"]["active_tenant_id"] == "band-2"

        # Update first session
        await session_service.create_session("sess1", "user1", "band-999")

        # Verify both are updated correctly
        assert session_service._cache["sess1"]["active_tenant_id"] == "band-999"
        assert session_service._cache["sess2"]["active_tenant_id"] == "band-2"
