"""
Cleanup Service Module

Periodically deletes expired session documents from couch-sitter database.
Runs nightly to clean up old session entries.
"""

import logging
from datetime import datetime
from typing import Dict, Any
import asyncio

logger = logging.getLogger(__name__)


class CleanupService:
    """Manages cleanup of expired session documents."""

    def __init__(self, dal, cleanup_interval_hours: int = 24):
        """
        Initialize CleanupService.
        
        Args:
            dal: Data Access Layer instance for CouchDB operations
            cleanup_interval_hours: How often to run cleanup (default 24 hours)
        """
        self.dal = dal
        self.cleanup_interval_hours = cleanup_interval_hours
        self._cleanup_task = None

    async def cleanup_expired_sessions(self) -> Dict[str, Any]:
        """
        Delete expired session documents from couch-sitter.
        
        Queries for sessions with expiresAt < now, then deletes them.
        
        Returns:
            Dict with cleanup stats: {deleted_count, errors}
        """
        now = datetime.utcnow().isoformat() + "Z"
        deleted_count = 0
        errors = []

        try:
            # Query: Find all session docs that have expired
            query = {
                "selector": {
                    "type": "session",
                    "expiresAt": {"$lt": now}
                }
            }

            logger.info(f"[CleanupService] Querying for expired sessions (before {now})")
            result = await self.dal.query_documents("couch-sitter", query)
            expired_docs = result.get("docs", [])

            logger.info(f"[CleanupService] Found {len(expired_docs)} expired session documents")

            # Delete each expired document
            for doc in expired_docs:
                doc_id = doc.get("_id")
                rev = doc.get("_rev")

                if not doc_id or not rev:
                    errors.append(f"Missing _id or _rev for document: {doc_id}")
                    continue

                try:
                    await self.dal.delete_document("couch-sitter", doc_id, rev)
                    deleted_count += 1
                    logger.debug(f"[CleanupService] Deleted expired session: {doc_id}")
                except Exception as e:
                    error_msg = f"Failed to delete {doc_id}: {e}"
                    errors.append(error_msg)
                    logger.warning(f"[CleanupService] {error_msg}")

            # Log results
            if deleted_count > 0:
                logger.info(f"[CleanupService] ✓ Cleanup complete: deleted {deleted_count} expired sessions")
            
            if errors:
                logger.warning(f"[CleanupService] Cleanup had {len(errors)} errors")

            return {
                "deleted_count": deleted_count,
                "errors": errors,
                "success": len(errors) == 0
            }

        except Exception as e:
            logger.error(f"[CleanupService] Cleanup failed: {e}", exc_info=True)
            return {
                "deleted_count": 0,
                "errors": [str(e)],
                "success": False
            }

    def start_periodic_cleanup(self):
        """
        Start periodic cleanup task (runs in background).
        
        Cleanup runs every N hours (default 24).
        This should be called during application startup.
        """
        if self._cleanup_task:
            logger.warning(f"[CleanupService] Cleanup task already running")
            return

        async def cleanup_loop():
            """Infinite loop that runs cleanup periodically."""
            interval_seconds = self.cleanup_interval_hours * 3600
            
            while True:
                try:
                    logger.info(f"[CleanupService] Running cleanup (every {self.cleanup_interval_hours} hours)")
                    result = await self.cleanup_expired_sessions()
                    logger.info(f"[CleanupService] Cleanup result: {result}")
                except Exception as e:
                    logger.error(f"[CleanupService] Cleanup loop error: {e}", exc_info=True)
                
                # Sleep until next cleanup
                logger.debug(f"[CleanupService] Sleeping for {interval_seconds}s until next cleanup")
                await asyncio.sleep(interval_seconds)

        # Create and store the task
        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info(f"[CleanupService] Started periodic cleanup (interval: {self.cleanup_interval_hours}h)")

    async def stop_periodic_cleanup(self):
        """Stop the periodic cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info(f"[CleanupService] Stopped periodic cleanup")
