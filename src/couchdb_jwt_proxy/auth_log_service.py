"""
Auth Log Service for Security Audit Logging

Logs all authentication events to the couch-sitter-log database for
security auditing, monitoring, and reporting.
"""

import uuid
import base64
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger(__name__)


class AuthLogService:
    """
    Service for logging authentication events to CouchDB.
    
    Logs events like:
    - login (user authenticated)
    - tenant_switch (user changed active tenant)
    - access_denied (unauthorized access attempt)
    - rate_limited (rate limit exceeded)
    """

    def __init__(self, log_db_url: str, couchdb_user: str = None, couchdb_password: str = None):
        """
        Initialize the auth log service.

        Args:
            log_db_url: URL to the couch-sitter-log database
            couchdb_user: Username for CouchDB authentication
            couchdb_password: Password for CouchDB authentication
        """
        self.db_url = log_db_url.rstrip('/')
        self.couchdb_user = couchdb_user
        self.couchdb_password = couchdb_password

        self.auth_headers = {}
        if couchdb_user and couchdb_password:
            credentials = base64.b64encode(f"{couchdb_user}:{couchdb_password}".encode()).decode()
            self.auth_headers["Authorization"] = f"Basic {credentials}"

        self.db_name = self.db_url.split('/')[-1]
        logger.info(f"AuthLogService initialized for database: {log_db_url}")

    async def _make_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make a request to CouchDB with authentication."""
        url = f"{self.db_url}/{path.lstrip('/')}"
        headers = kwargs.pop('headers', {})
        headers.update(self.auth_headers)

        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            return response

    async def ensure_database_exists(self) -> bool:
        """
        Ensure the log database exists, creating it if necessary.
        
        Returns:
            True if database exists or was created, False on error
        """
        try:
            base_url = self.db_url.rsplit('/', 1)[0]
            async with httpx.AsyncClient() as client:
                headers = self.auth_headers.copy()
                
                response = await client.head(self.db_url, headers=headers)
                if response.status_code == 200:
                    logger.info(f"Log database exists: {self.db_name}")
                    # Ensure indexes exist
                    await self._create_indexes()
                    return True
                elif response.status_code == 404:
                    create_response = await client.put(self.db_url, headers=headers)
                    if create_response.status_code in (201, 202):
                        logger.info(f"Created log database: {self.db_name}")
                        # Create indexes on new database
                        await self._create_indexes()
                        return True
                    else:
                        logger.error(f"Failed to create log database: {create_response.status_code} {create_response.text}")
                        return False
                else:
                    logger.error(f"Unexpected response checking log database: {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"Error ensuring log database exists: {e}")
            return False

    async def _create_indexes(self) -> bool:
        """Create indexes for efficient querying of auth logs"""
        try:
            async with httpx.AsyncClient() as client:
                headers = self.auth_headers.copy()
                headers["Content-Type"] = "application/json"
                
                indexes = [
                    # Index on type and timestamp
                    {
                        "index": {"fields": ["type", "timestamp"]},
                        "name": "type-timestamp"
                    },
                    # Index on action and timestamp (for filtering by action like "login")
                    {
                        "index": {"fields": ["action", "timestamp"]},
                        "name": "action-timestamp"
                    },
                    # Index on user_id and timestamp (for user-specific queries)
                    {
                        "index": {"fields": ["user_id", "timestamp"]},
                        "name": "user-timestamp"
                    },
                    # Index on status and timestamp (for success/failed queries)
                    {
                        "index": {"fields": ["status", "timestamp"]},
                        "name": "status-timestamp"
                    }
                ]
                
                for index_def in indexes:
                    response = await client.post(
                        f"{self.db_url}/_index",
                        json=index_def,
                        headers=headers
                    )
                    
                    if response.status_code in (200, 201):
                        logger.info(f"Created/verified index: {index_def['name']}")
                    else:
                        logger.warning(f"Failed to create index {index_def['name']}: {response.status_code} {response.text}")
                
                return True
        except Exception as e:
            logger.warning(f"Error creating indexes: {e}")
            # Don't fail if index creation fails
            return True

    async def log_auth_event(
        self,
        action: str,
        status: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        issuer: Optional[str] = None,
        error_reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log an authentication event.

        Args:
            action: Type of action (login, tenant_switch, access_denied, rate_limited, token_validation)
            status: Result status (success, failed)
            user_id: User ID (if known)
            tenant_id: Tenant ID (if applicable)
            endpoint: API endpoint accessed
            ip: Client IP address
            user_agent: Client user agent
            issuer: JWT issuer
            error_reason: Reason for failure (if status=failed)
            metadata: Additional metadata

        Returns:
            True if logged successfully, False on error
        """
        timestamp = datetime.now(timezone.utc)
        doc_id = f"log_{timestamp.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"

        doc = {
            "_id": doc_id,
            "type": "auth_event",
            "action": action,
            "status": status,
            "timestamp": timestamp.isoformat(),
            "date": timestamp.strftime("%Y-%m-%d"),
            "hour": timestamp.hour,
        }

        if user_id:
            doc["user_id"] = user_id
        if tenant_id:
            doc["tenant_id"] = tenant_id
        if endpoint:
            doc["endpoint"] = endpoint
        if ip:
            doc["ip"] = ip
        if user_agent:
            doc["user_agent"] = user_agent[:500] if user_agent else None
        if issuer:
            doc["issuer"] = issuer
        if error_reason:
            doc["error_reason"] = error_reason
        if metadata:
            doc["metadata"] = metadata

        try:
            response = await self._make_request("PUT", doc_id, json=doc)
            if response.status_code in (200, 201, 202):
                logger.debug(f"Logged auth event: {action}/{status} for user={user_id} tenant={tenant_id}")
                return True
            else:
                logger.warning(f"Failed to log auth event: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error logging auth event: {e}")
            return False

    async def log_login(
        self,
        user_id: str,
        tenant_id: str,
        success: bool,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        issuer: Optional[str] = None,
        error_reason: Optional[str] = None
    ) -> bool:
        """Log a login/authentication event."""
        return await self.log_auth_event(
            action="login",
            status="success" if success else "failed",
            user_id=user_id,
            tenant_id=tenant_id,
            endpoint="/my-tenants",
            ip=ip,
            user_agent=user_agent,
            issuer=issuer,
            error_reason=error_reason
        )

    async def log_tenant_switch(
        self,
        user_id: str,
        from_tenant_id: Optional[str],
        to_tenant_id: str,
        success: bool,
        ip: Optional[str] = None,
        error_reason: Optional[str] = None
    ) -> bool:
        """Log a tenant switch event."""
        return await self.log_auth_event(
            action="tenant_switch",
            status="success" if success else "failed",
            user_id=user_id,
            tenant_id=to_tenant_id,
            endpoint="/choose-tenant",
            ip=ip,
            error_reason=error_reason,
            metadata={"from_tenant_id": from_tenant_id} if from_tenant_id else None
        )

    async def log_access_denied(
        self,
        user_id: Optional[str],
        tenant_id: Optional[str],
        endpoint: str,
        reason: str,
        ip: Optional[str] = None
    ) -> bool:
        """Log an access denied event."""
        return await self.log_auth_event(
            action="access_denied",
            status="failed",
            user_id=user_id,
            tenant_id=tenant_id,
            endpoint=endpoint,
            ip=ip,
            error_reason=reason
        )

    async def log_rate_limited(
        self,
        ip: str,
        endpoint: str,
        user_id: Optional[str] = None
    ) -> bool:
        """Log a rate limit exceeded event."""
        return await self.log_auth_event(
            action="rate_limited",
            status="failed",
            user_id=user_id,
            endpoint=endpoint,
            ip=ip,
            error_reason="rate_limit_exceeded"
        )

    async def log_token_validation(
        self,
        success: bool,
        ip: Optional[str] = None,
        issuer: Optional[str] = None,
        error_reason: Optional[str] = None,
        endpoint: Optional[str] = None
    ) -> bool:
        """Log a token validation event (for failed validations)."""
        return await self.log_auth_event(
            action="token_validation",
            status="success" if success else "failed",
            ip=ip,
            issuer=issuer,
            endpoint=endpoint,
            error_reason=error_reason
        )
