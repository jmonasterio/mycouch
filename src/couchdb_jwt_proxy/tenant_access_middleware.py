"""
Tenant Access Control Middleware

Validates that documents being written to app databases:
1. Include a 'tenant' field
2. That tenant belongs to the authenticated user

This is added to main.py as a middleware layer.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from fastapi import Request
from fastapi.responses import JSONResponse
import jwt

logger = logging.getLogger(__name__)


class TenantAccessMiddleware:
    """Middleware that validates tenant access for document writes"""
    
    def __init__(self, app, couch_sitter_service):
        self.app = app
        self.couch_sitter_service = couch_sitter_service
        self._user_tenant_cache = {}  # Simple cache to avoid repeated queries
    
    async def __call__(self, request: Request, call_next):
        """
        Intercept requests and validate tenant access for writes.
        """
        
        # Only validate writes to app databases
        if request.method not in ['PUT', 'POST']:
            return await call_next(request)
        
        path = request.url.path
        
        # Skip validation for couch-sitter and system endpoints
        if self._should_skip_validation(path):
            return await call_next(request)
        
        # Get authenticated user
        try:
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                # Not authenticated - let it through (will fail at auth layer)
                return await call_next(request)
            
            token = auth_header[7:]  # Remove "Bearer "
            # Decode JWT to get user_id (no verification here - that's done by auth_middleware)
            decoded = jwt.decode(token, options={"verify_signature": False})
            user_id = decoded.get('sub')
            
            if not user_id:
                logger.warning("No user_id in JWT during tenant validation")
                return await call_next(request)
        except Exception as e:
            logger.debug(f"Could not extract user from JWT: {e}")
            return await call_next(request)
        
        # Read request body
        try:
            body = await request.body()
            if not body:
                return await call_next(request)
            
            data = json.loads(body)
        except Exception as e:
            logger.debug(f"Could not parse request body for tenant validation: {e}")
            return await call_next(request)
        
        # Validate tenant access
        try:
            if '_bulk_docs' in path:
                await self._validate_bulk_docs(data, user_id, path)
            else:
                await self._validate_document(data, user_id, path)
        except ValueError as e:
            logger.warning(f"Tenant validation failed: {e}")
            return JSONResponse(
                status_code=403,
                content={"error": "Forbidden", "reason": str(e)}
            )
        
        # Validation passed - continue with request
        # Need to restore body since we read it
        async def receive():
            return {"type": "http.request", "body": body}
        
        request._receive = receive
        return await call_next(request)
    
    async def _validate_document(self, doc: Dict[str, Any], user_id: str, path: str) -> None:
        """Validate a single document"""
        
        # Skip if deleting
        if doc.get('_deleted'):
            return
        
        # Get user's authorized tenants
        user_tenants = await self._get_user_tenants(user_id)
        if not user_tenants:
            raise ValueError(
                "You have no authorized tenants. Create one via /api/tenants first."
            )
        
        doc_type = doc.get('type', '')
        doc_id = doc.get('_id', '')
        
        # Special handling for band-info
        if doc_type == 'band-info':
            if doc_id.startswith('band-info_'):
                tenant_id = doc_id.split('_', 1)[1]
                if tenant_id not in user_tenants:
                    raise ValueError(
                        f"Cannot write band-info for tenant '{tenant_id}'. "
                        f"You have access to: {user_tenants}"
                    )
                # Add tenant field for consistency
                doc['tenant'] = tenant_id
            else:
                raise ValueError(
                    "band-info documents must follow naming: band-info_{tenantId}"
                )
            return
        
        # All other documents need explicit tenant field
        tenant_id = doc.get('tenant')
        
        if not tenant_id:
            raise ValueError(
                f"Document missing required 'tenant' field. "
                f"You have access to: {user_tenants}"
            )
        
        if tenant_id not in user_tenants:
            raise ValueError(
                f"Cannot write to tenant '{tenant_id}'. "
                f"You have access to: {user_tenants}"
            )
        
        logger.info(f"✅ Validation passed: user={user_id}, tenant={tenant_id}, doc_id={doc_id}")
    
    async def _validate_bulk_docs(self, data: Dict[str, Any], user_id: str, path: str) -> None:
        """Validate all documents in bulk write"""
        
        docs = data.get('docs', [])
        if not docs:
            return
        
        # Get user's authorized tenants once
        user_tenants = await self._get_user_tenants(user_id)
        if not user_tenants:
            raise ValueError(
                "You have no authorized tenants. Create one via /api/tenants first."
            )
        
        # Validate each document
        for i, doc in enumerate(docs):
            # Skip deleted documents
            if doc.get('_deleted'):
                continue
            
            try:
                doc_type = doc.get('type', '')
                doc_id = doc.get('_id', '')
                
                if doc_type == 'band-info':
                    if doc_id.startswith('band-info_'):
                        tenant_id = doc_id.split('_', 1)[1]
                        if tenant_id not in user_tenants:
                            raise ValueError(
                                f"Cannot write band-info for tenant '{tenant_id}'"
                            )
                    else:
                        raise ValueError("band-info must follow naming: band-info_{tenantId}")
                else:
                    tenant_id = doc.get('tenant')
                    if not tenant_id:
                        raise ValueError(f"Document {i} missing 'tenant' field")
                    if tenant_id not in user_tenants:
                        raise ValueError(
                            f"Document {i}: cannot write to tenant '{tenant_id}'"
                        )
            except ValueError as e:
                raise ValueError(f"Bulk doc {i} failed: {str(e)}")
        
        logger.info(
            f"✅ Bulk validation passed: user={user_id}, docs={len(docs)}, "
            f"tenants={user_tenants}"
        )
    
    async def _get_user_tenants(self, user_id: str) -> List[str]:
        """Get list of tenant IDs user has access to"""
        
        # Check cache first
        if user_id in self._user_tenant_cache:
            return self._user_tenant_cache[user_id]
        
        try:
            tenants, _ = await self.couch_sitter_service.get_user_tenants(user_id)
            tenant_ids = [t.get("_id") for t in tenants if t and t.get("_id")]
            
            # Cache for 5 minutes
            self._user_tenant_cache[user_id] = tenant_ids
            
            return tenant_ids
        except Exception as e:
            logger.error(f"Failed to get user tenants: {e}")
            # Return empty list - request will be rejected with "no tenants" error
            return []
    
    def _should_skip_validation(self, path: str) -> bool:
        """Check if request should skip tenant validation"""
        
        # Skip couch-sitter (central registry)
        if 'couch-sitter' in path:
            return True
        
        # Skip _users database (system)
        if '_users' in path:
            return True
        
        # Skip system endpoints
        skip_patterns = [
            '/_all_dbs',
            '/_dbs',
            '/_uuids',
            '/_active_tasks',
            '/_admin',
            '/api/',  # API endpoints (they handle auth separately)
            '/__users',  # Virtual endpoints
            '/__tenants'  # Virtual endpoints
        ]
        
        for pattern in skip_patterns:
            if pattern in path:
                return True
        
        return False


def create_tenant_access_middleware(app, couch_sitter_service):
    """Factory function to create the middleware"""
    return TenantAccessMiddleware(app, couch_sitter_service)
