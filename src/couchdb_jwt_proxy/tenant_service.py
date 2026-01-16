"""
Tenant Service

Handles tenant initialization and creation for users with no tenants.
"""

import uuid
import logging
import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TenantService:
    """Service for creating and initializing user tenants"""

    def __init__(self, couchdb_url: str, username: str, password: str):
        """
        Initialize the tenant service.

        Args:
            couchdb_url: Base CouchDB URL
            username: CouchDB username
            password: CouchDB password
        """
        self.couchdb_url = couchdb_url.rstrip('/')
        self.username = username
        self.password = password

    async def create_tenant(
        self,
        user_hash: str,
        user_name: Optional[str] = None,
        database: str = "roady"
    ) -> Dict[str, Any]:
        """
        Create a new tenant for a user.

        Args:
            user_hash: User ID hash (from JWT sub claim)
            user_name: User's display name for tenant naming
            database: Database to create tenant in (default: roady)

        Returns:
            Dict with tenant_id and full tenant document

        Raises:
            HTTPException: If tenant creation fails
        """
        try:
            # Generate unique tenant ID
            tenant_uuid = str(uuid.uuid4())
            tenant_id = f"tenant_{tenant_uuid}"

            # Friendly name for the tenant
            tenant_name = f"{user_name or 'User'}'s Band" if user_name else "My Band"

            # Create tenant document
            tenant_doc = {
                "_id": tenant_id,
                "type": "tenant",
                "name": tenant_name,
                "owner_id": user_hash,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": "system",
            }

            # Store tenant in user's database
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    f"{self.couchdb_url}/{database}/{tenant_id}",
                    json=tenant_doc,
                    auth=(self.username, self.password),
                )

                if response.status_code in (200, 201):
                    logger.info(
                        f"✅ Created tenant {tenant_id} for user {user_hash} in {database}"
                    )
                    return {
                        "tenant_id": tenant_uuid,  # Return without prefix for virtual ID
                        "doc": tenant_doc,
                    }
                else:
                    logger.error(
                        f"❌ Failed to create tenant: {response.status_code} {response.text}"
                    )
                    raise Exception(f"CouchDB error: {response.status_code}")

        except Exception as e:
            logger.error(f"❌ Error creating tenant: {e}", exc_info=True)
            raise

    async def set_user_default_tenant(
        self,
        user_hash: str,
        tenant_id: str,
        database: str = "couch-sitter"
    ) -> Dict[str, Any]:
        """
        Set a user's default active_tenant_id in their user document.

        Args:
            user_hash: User ID hash
            tenant_id: Tenant ID (without prefix)
            database: User database (default: couch-sitter)

        Returns:
            Updated user document

        Raises:
            Exception: If update fails
        """
        try:
            user_doc_id = f"user_{user_hash}"

            async with httpx.AsyncClient() as client:
                # Get current user doc to preserve _rev
                get_response = await client.get(
                    f"{self.couchdb_url}/{database}/{user_doc_id}",
                    auth=(self.username, self.password),
                )

                if get_response.status_code != 200:
                    logger.error(
                        f"⚠️  Could not get user doc {user_doc_id}: {get_response.status_code}"
                    )
                    return {}

                user_doc = get_response.json()

                # Update active_tenant_id
                user_doc["active_tenant_id"] = tenant_id

                # Put updated document back
                put_response = await client.put(
                    f"{self.couchdb_url}/{database}/{user_doc_id}",
                    json=user_doc,
                    auth=(self.username, self.password),
                )

                if put_response.status_code in (200, 201):
                    logger.info(
                        f"✅ Set default tenant {tenant_id} for user {user_hash}"
                    )
                    return user_doc
                else:
                    logger.warning(
                        f"⚠️  Failed to set default tenant: {put_response.status_code}"
                    )
                    return user_doc  # Return anyway, will be retried

        except Exception as e:
            logger.error(f"❌ Error setting default tenant: {e}", exc_info=True)
            raise

    async def query_user_tenants(
        self,
        user_hash: str,
        database: str = "roady"
    ) -> List[Dict[str, Any]]:
        """
        Query all tenants owned by a user.

        Args:
            user_hash: User ID hash
            database: Database to query (default: roady)

        Returns:
            List of tenant documents ordered by creation time

        Raises:
            Exception: If query fails
        """
        try:
            query = {
                "selector": {
                    "type": "tenant",
                    "owner_id": user_hash,
                },
                "sort": ["created_at"],
                "limit": 100,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.couchdb_url}/{database}/_find",
                    json=query,
                    auth=(self.username, self.password),
                )

                if response.status_code == 200:
                    result = await response.json()
                    docs = result.get("docs", [])
                    logger.debug(f"Found {len(docs)} tenants for user {user_hash}")
                    return docs
                else:
                    logger.error(f"⚠️  Query failed: {response.status_code}")
                    return []

        except Exception as e:
            logger.error(f"❌ Error querying user tenants: {e}", exc_info=True)
            return []
