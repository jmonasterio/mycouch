"""
Index Bootstrap Service

Creates required indexes on CouchDB databases during startup.
Ensures indexes exist on couch-sitter and couch-sitter-logs databases.
"""

import httpx
import logging
import base64
import json
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class IndexBootstrap:
    """Service for creating indexes on startup"""

    def __init__(self, couchdb_url: str, username: str, password: str):
        """
        Initialize the index bootstrap service.

        Args:
            couchdb_url: Base CouchDB URL (e.g., http://localhost:5984)
            username: CouchDB username
            password: CouchDB password
        """
        self.couchdb_url = couchdb_url.rstrip('/')
        self.username = username
        self.password = password

        self.auth_headers = {}
        if username and password:
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            self.auth_headers["Authorization"] = f"Basic {credentials}"
            self.auth_headers["Content-Type"] = "application/json"

    async def create_indexes(self, database: str, indexes: List[Dict[str, Any]]) -> bool:
        """
        Create indexes on a database.

        Args:
            database: Database name
            indexes: List of index definitions (Mango format)

        Returns:
            True if all indexes created/verified, False on error
        """
        try:
            async with httpx.AsyncClient() as client:
                for index_def in indexes:
                    db_url = f"{self.couchdb_url}/{database}"
                    url = f"{db_url}/_index"

                    response = await client.post(
                        url,
                        json=index_def,
                        headers=self.auth_headers
                    )

                    index_name = index_def.get("name", "unnamed")
                    if response.status_code in (200, 201):
                        logger.info(f"✓ Index '{index_name}' on {database}: OK")
                    elif response.status_code == 400:
                        # Index already exists - this is OK
                        logger.info(f"✓ Index '{index_name}' on {database}: already exists")
                    else:
                        logger.warning(
                            f"⚠ Index '{index_name}' on {database}: "
                            f"{response.status_code} {response.text}"
                        )

            return True
        except Exception as e:
            logger.error(f"Error creating indexes on {database}: {e}")
            return False

    async def bootstrap_all(self) -> bool:
        """Bootstrap all required indexes on startup"""
        logger.info("=" * 60)
        logger.info("🔧 STARTING INDEX BOOTSTRAP")
        logger.info("=" * 60)

        success = True

        # Indexes for couch-sitter
        couch_sitter_indexes = [
            {
                "index": {"fields": ["type", "_id"]},
                "name": "type-id",
            },
            {
                "index": {"fields": ["type", "createdAt"]},
                "name": "type-created",
            },
            {
                "index": {"fields": ["sub", "type"]},
                "name": "sub-type",
            },
            {
                "index": {"fields": ["email"]},
                "name": "email",
            },
            {
                "index": {"fields": ["active_tenant_id"]},
                "name": "active-tenant",
            },
            {
                "index": {"fields": ["issuer"]},
                "name": "issuer",
            },
            {
                "index": {"fields": ["user_id", "status"]},
                "name": "user-status",
            },
            {
                "index": {"fields": ["type", "owner_id"]},
                "name": "tenant-owner",
            },
            {
                "index": {"fields": ["type", "sid"]},
                "name": "session-sid",
            },
            {
                "index": {"fields": ["type", "expiresAt"]},
                "name": "session-expiry",
            },
            {
                "index": {"fields": ["userIds"]},
                "name": "userIds",
            },
        ]

        logger.info("📦 Creating indexes on 'couch-sitter'...")
        if not await self.create_indexes("couch-sitter", couch_sitter_indexes):
            success = False

        # Indexes for couch-sitter-logs
        logs_indexes = [
            {
                "index": {"fields": ["type", "timestamp"]},
                "name": "type-timestamp",
            },
            {
                "index": {"fields": ["action", "timestamp"]},
                "name": "action-timestamp",
            },
            {
                "index": {"fields": ["user_id", "timestamp"]},
                "name": "user-timestamp",
            },
            {
                "index": {"fields": ["status", "timestamp"]},
                "name": "status-timestamp",
            },
            {
                "index": {"fields": ["tenant_id", "timestamp"]},
                "name": "tenant-timestamp",
            },
        ]

        logger.info("📦 Creating indexes on 'couch-sitter-logs'...")
        if not await self.create_indexes("couch-sitter-logs", logs_indexes):
            success = False

        logger.info("=" * 60)
        if success:
            logger.info("✅ INDEX BOOTSTRAP COMPLETE")
        else:
            logger.warning("⚠️  INDEX BOOTSTRAP COMPLETED WITH WARNINGS")
        logger.info("=" * 60)

        return success
