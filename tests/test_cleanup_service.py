"""
Unit tests for CleanupService
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from couchdb_jwt_proxy.cleanup_service import CleanupService


class TestCleanupService:
    """Test CleanupService functionality."""

    @pytest.fixture
    def mock_dal(self):
        """Create a mock DAL."""
        dal = AsyncMock()
        return dal

    @pytest.fixture
    def cleanup_service(self, mock_dal):
        """Create a CleanupService instance."""
        return CleanupService(mock_dal, cleanup_interval_hours=1)

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, cleanup_service, mock_dal):
        """Test cleaning up expired session documents."""
        # Create mock expired sessions
        now = datetime.utcnow().isoformat() + "Z"
        yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"

        expired_docs = [
            {
                "_id": "session_sess1",
                "_rev": "1-abc",
                "type": "session",
                "sid": "sess1",
                "active_tenant_id": "band-1",
                "expiresAt": yesterday
            },
            {
                "_id": "session_sess2",
                "_rev": "1-def",
                "type": "session",
                "sid": "sess2",
                "active_tenant_id": "band-2",
                "expiresAt": yesterday
            }
        ]

        # Mock the query and delete responses
        mock_dal.query_documents.return_value = {"docs": expired_docs}
        mock_dal.delete_document.return_value = {"ok": True}

        # Run cleanup
        result = await cleanup_service.cleanup_expired_sessions()

        # Verify
        assert result["deleted_count"] == 2
        assert result["success"] is True
        assert len(result["errors"]) == 0

        # Verify delete was called for each doc
        assert mock_dal.delete_document.call_count == 2

        # Verify query was called with correct selector
        mock_dal.query_documents.assert_called_once()
        call_args = mock_dal.query_documents.call_args
        query = call_args[0][1]
        assert query["selector"]["type"] == "session"
        assert "$lt" in query["selector"]["expiresAt"]

    @pytest.mark.asyncio
    async def test_cleanup_no_expired_sessions(self, cleanup_service, mock_dal):
        """Test cleanup when no sessions are expired."""
        mock_dal.query_documents.return_value = {"docs": []}

        result = await cleanup_service.cleanup_expired_sessions()

        assert result["deleted_count"] == 0
        assert result["success"] is True
        mock_dal.delete_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_delete_error(self, cleanup_service, mock_dal):
        """Test cleanup handling delete errors gracefully."""
        expired_doc = {
            "_id": "session_sess1",
            "_rev": "1-abc",
            "type": "session",
            "expiresAt": (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
        }

        mock_dal.query_documents.return_value = {"docs": [expired_doc]}
        mock_dal.delete_document.side_effect = Exception("CouchDB error")

        result = await cleanup_service.cleanup_expired_sessions()

        assert result["deleted_count"] == 0
        assert result["success"] is False
        assert len(result["errors"]) == 1
        assert "CouchDB error" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_cleanup_missing_rev(self, cleanup_service, mock_dal):
        """Test cleanup handling documents with missing _rev."""
        expired_doc = {
            "_id": "session_sess1",
            # Missing _rev
            "type": "session",
            "expiresAt": (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
        }

        mock_dal.query_documents.return_value = {"docs": [expired_doc]}

        result = await cleanup_service.cleanup_expired_sessions()

        assert result["deleted_count"] == 0
        assert result["success"] is False
        assert len(result["errors"]) == 1
        assert "Missing _id or _rev" in result["errors"][0]
        mock_dal.delete_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_query_failure(self, cleanup_service, mock_dal):
        """Test cleanup when query fails."""
        mock_dal.query_documents.side_effect = Exception("Query failed")

        result = await cleanup_service.cleanup_expired_sessions()

        assert result["deleted_count"] == 0
        assert result["success"] is False
        assert len(result["errors"]) == 1
        assert "Query failed" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_start_periodic_cleanup(self, cleanup_service, mock_dal):
        """Test starting periodic cleanup."""
        # Mock the cleanup method to avoid actual cleanup
        with patch.object(cleanup_service, 'cleanup_expired_sessions', new_callable=AsyncMock) as mock_cleanup:
            mock_cleanup.return_value = {"deleted_count": 0, "success": True, "errors": []}

            # Start cleanup (not async)
            cleanup_service.start_periodic_cleanup()
            
            # Wait a bit for task to start
            await asyncio.sleep(0.1)

            # Task should be created
            assert cleanup_service._cleanup_task is not None
            assert not cleanup_service._cleanup_task.done()

            # Stop cleanup to clean up
            await cleanup_service.stop_periodic_cleanup()

    @pytest.mark.asyncio
    async def test_stop_periodic_cleanup(self, cleanup_service):
        """Test stopping periodic cleanup."""
        # Start cleanup (not async)
        cleanup_service.start_periodic_cleanup()
        assert cleanup_service._cleanup_task is not None

        # Stop cleanup
        await cleanup_service.stop_periodic_cleanup()
        assert cleanup_service._cleanup_task is None

    @pytest.mark.asyncio
    async def test_cleanup_mixed_success_and_errors(self, cleanup_service, mock_dal):
        """Test cleanup with some successes and some errors."""
        expired_docs = [
            {
                "_id": "session_sess1",
                "_rev": "1-abc",
                "type": "session"
            },
            {
                "_id": "session_sess2",
                "_rev": "1-def",
                "type": "session"
            },
            {
                "_id": "session_sess3",
                "_rev": "1-ghi",
                "type": "session"
            }
        ]

        mock_dal.query_documents.return_value = {"docs": expired_docs}

        # First delete succeeds, second fails, third succeeds
        mock_dal.delete_document.side_effect = [
            {"ok": True},
            Exception("Delete failed"),
            {"ok": True}
        ]

        result = await cleanup_service.cleanup_expired_sessions()

        assert result["deleted_count"] == 2
        assert result["success"] is False  # Has errors
        assert len(result["errors"]) == 1
        assert "Delete failed" in result["errors"][0]
