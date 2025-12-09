"""
CouchDB Service for User and Tenant Management

Handles all database operations for user and tenant management in the
couch-sitter database, including automatic creation of users and personal tenants.
"""

import os
import json
import uuid
import time
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List
import httpx
import logging
from unittest.mock import MagicMock

from .user_tenant_cache import UserTenantInfo

logger = logging.getLogger(__name__)

# Well-known tenant ID for couch-sitter administrators
ADMIN_TENANT_ID = "tenant_couch_sitter_admins"


class CouchSitterService:
    """
    Service for managing users and tenants in the couch-sitter database.

    Features:
    - Automatic user and personal tenant creation
    - Thread-safe operations
    - Error handling and logging
    - Integration with user cache
    """

    def __init__(self, couch_sitter_db_url: str, couchdb_user: str = None, couchdb_password: str = None, dal=None):
        """
        Initialize the service with database connection parameters.

        Args:
            couch_sitter_db_url: URL to the couch-sitter database (where users/tenants are stored)
            couchdb_user: Username for CouchDB authentication
            couchdb_password: Password for CouchDB authentication
            dal: Optional DAL instance for testing (defaults to None for HTTP requests)
        """
        self.db_url = couch_sitter_db_url.rstrip('/')
        self.couchdb_user = couchdb_user
        self.couchdb_password = couchdb_password
        self.dal = dal  # Optional DAL for testing

        # Prepare authentication headers if credentials provided
        self.auth_headers = {}
        if couchdb_user and couchdb_password:
            import base64
            credentials = base64.b64encode(f"{couchdb_user}:{couchdb_password}".encode()).decode()
            self.auth_headers["Authorization"] = f"Basic {credentials}"

        self.db_name = self.db_url.split('/')[-1]  # Always 'couch-sitter'
        logger.info(f"CouchSitterService initialized for database: {couch_sitter_db_url} (DB: {self.db_name})")

    async def _make_request(self, method: str, path: str, **kwargs):
        """
        Make a request to CouchDB with authentication.
        Uses DAL when available (testing), otherwise HTTP requests.

        Args:
            method: HTTP method
            path: Database path (relative to database URL)
            **kwargs: Additional arguments

        Returns:
            Response object (httpx.Response for HTTP, mock for DAL)

        Raises:
            httpx.HTTPError: If the request fails
        """
        # Use DAL when available (testing mode)
        if self.dal:
            json_data = kwargs.get('json')

            # For GET and DELETE, no payload needed
            # For PUT and POST, include json_data as payload
            payload = json_data if method in ["PUT", "POST"] else None
            
            # Prepend DB name to path for DAL (which expects full path from root)
            # path passed here is relative to db_url (e.g. "_find" or "docid")
            full_path = f"{self.db_name}/{path.lstrip('/')}"
            
            result = await self.dal.get(full_path, method, payload)

            # Create mock response object for DAL results
            mock_response = MagicMock()
            mock_response.json.return_value = result

            # Handle error responses from DAL
            if isinstance(result, dict) and "error" in result:
                if result.get("error") == "not_found":
                    mock_response.status_code = 404
                else:
                    mock_response.status_code = 400
            else:
                mock_response.status_code = 200

            # Configure raise_for_status to actually raise exceptions for error codes
            def raise_for_status():
                if mock_response.status_code >= 400:
                    import httpx
                    raise httpx.HTTPStatusError(
                        f"HTTP {mock_response.status_code} error",
                        request=MagicMock(),
                        response=mock_response
                    )
            mock_response.raise_for_status = raise_for_status
            return mock_response

        # Otherwise make HTTP request
        url = f"{self.db_url}/{path.lstrip('/')}"
        headers = kwargs.pop('headers', {})
        headers.update(self.auth_headers)

        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response

    def _hash_sub(self, sub: str) -> str:
        """
        Create SHA256 hash of the Clerk sub claim.

        Args:
            sub: Clerk sub claim

        Returns:
            SHA256 hash as hex string
        """
        return hashlib.sha256(sub.encode('utf-8')).hexdigest()

    async def find_user_by_sub_hash(self, sub_hash: str) -> Optional[Dict[str, Any]]:
        """
        Find a user document by the hash of their sub claim.

        Args:
            sub_hash: SHA256 hash of the Clerk sub claim

        Returns:
            User document dict if found, None otherwise
        """
        try:
            # Use couchdb query to find user by sub_hash (stored as user_<sub_hash> in _id field)
            query = {
                "selector": {
                    "type": "user",
                    "_id": f"user_{sub_hash}"
                },
                "limit": 1
            }

            response = await self._make_request("POST", "_find", json=query)
            result = response.json()

            docs = result.get("docs", [])
            if docs:
                user_doc = docs[0]
                logger.debug(f"Found user: {user_doc.get('_id')}")
                return user_doc
            else:
                logger.debug(f"User not found: {sub_hash}")
                return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"User not found: {sub_hash}")
                return None
            else:
                logger.error(f"Error finding user {sub_hash}: {e}")
                raise
        except Exception as e:
            logger.error(f"Unexpected error finding user {sub_hash}: {e}")
            return None

    async def find_application_by_db_name(self, db_name: str) -> Optional[Dict[str, Any]]:
        """
        Find an application document by its database name.

        Args:
            db_name: The database name to search for (e.g. 'roady')

        Returns:
            Application document dict if found, None otherwise
        """
        try:
            # Look for app by databaseName
            query = {
                "selector": {
                    "type": "application",
                    "databaseName": db_name
                },
                "limit": 1
            }

            response = await self._make_request("POST", "_find", json=query)
            result = response.json()

            docs = result.get("docs", [])
            if docs:
                app_doc = docs[0]
                logger.debug(f"Found app for db {db_name}: {app_doc.get('_id')}")
                return app_doc
            
            # Fallback: check if db_name matches name (case insensitive?)
            # Or strict match on name field if databaseName is empty?
            # For now just strict databaseName match as that is how apps are configured.
            logger.debug(f"App not found for db: {db_name}")
            return None

        except Exception as e:
            logger.error(f"Error finding app for db {db_name}: {e}")
            return None

    async def create_user_with_personal_tenant(self, sub: str, email: str = None, name: str = None, requested_db_name: str = None) -> Tuple[Dict, Dict]:
        """
        Creates a user and their personal tenant.

        Args:
            sub: Clerk sub claim
            email: User email (optional)
            name: User name (optional)
            requested_db_name: The database name the user is accessing

        Returns:
            Tuple of (user_document, tenant_document)

        Raises:
            httpx.HTTPError: If database operations fail
        """
        sub_hash = self._hash_sub(sub)
        user_id = f"user_{sub_hash}"
        tenant_id = f"tenant_{self._hash_sub(sub)[:12]}"
        current_time = datetime.now(timezone.utc).isoformat()
        
        # Use requested DB name for applicationId, or default to couch-sitter DB name
        app_id = requested_db_name or self.db_name

        # Create personal tenant document
        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": name if name else f"Personal Tenant for {sub}",
            "applicationId": app_id,
            "isPersonal": True,
            "userId": user_id,
            "userIds": [user_id],
            "createdAt": current_time,
            "metadata": {
                "createdBy": sub,
                "autoCreated": True,
                "originalSub": sub
            }
        }

        # Create user document
        user_doc = {
            "_id": user_id,
            "type": "user",
            "sub": sub,
            "email": email,
            "name": name if name else f"User {sub[:8]}",
            "personalTenantId": tenant_id,
            "tenantIds": [tenant_id],
            "createdAt": current_time,
            "updatedAt": current_time
        }

        try:
            # Create tenant first
            tenant_response = await self._make_request("PUT", tenant_id, json=tenant_doc)
            created_tenant = tenant_response.json()

            # If using DAL (testing), return the original document instead of response
            if self.dal:
                created_tenant = tenant_doc

            # Ensure the created tenant has the _id field
            if "_id" not in created_tenant:
                created_tenant["_id"] = tenant_id
            logger.info(f"Created personal tenant: {tenant_id}")

            # Create user
            user_response = await self._make_request("PUT", user_id, json=user_doc)
            created_user = user_response.json()

            # If using DAL (testing), return the original document instead of response
            if self.dal:
                created_user = user_doc

            # Ensure the created user has the _id field
            if "_id" not in created_user:
                created_user["_id"] = user_id
            logger.info(f"Created user: {user_id}")

            return created_user, created_tenant

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to create user/tenant: {e}")
            # Try to cleanup partially created documents
            try:
                await self._make_request("DELETE", tenant_id)
            except:
                pass
            try:
                await self._make_request("DELETE", user_id)
            except:
                pass
            raise

    async def ensure_personal_tenant_exists(self, user_doc: Dict[str, Any], requested_db_name: str = None) -> str:
        """
        Ensure a user has a personal tenant, creating one if missing.

        Args:
            user_doc: User document from database

        Returns:
            Tenant ID of the personal tenant

        Raises:
            ValueError: If user document is invalid
            httpx.HTTPError: If database operations fail
        """
        user_id = user_doc.get("_id")
        personal_tenant_id = user_doc.get("personalTenantId")
        
        # Use requested DB name for applicationId, or default to couch-sitter DB name
        app_id = requested_db_name or self.db_name

        if personal_tenant_id:
            # Check if the personal tenant actually exists
            try:
                tenant_response = await self._make_request("GET", personal_tenant_id)
                tenant_doc = tenant_response.json()

                if tenant_doc.get("isPersonal", False):
                    logger.debug(f"Personal tenant exists: {personal_tenant_id}")
                    
                    # FIX: Check if applicationId matches requested app (e.g. "roady")
                    # If tenant has "app_test" or "couch-sitter" but user is logging into "roady", update it
                    current_app_id = tenant_doc.get("applicationId")
                    if app_id and app_id != "couch-sitter" and current_app_id != app_id:
                        logger.info(f"Updating tenant {personal_tenant_id} applicationId from '{current_app_id}' to '{app_id}'")
                        tenant_doc["applicationId"] = app_id
                        tenant_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
                        await self._make_request("PUT", personal_tenant_id, json=tenant_doc)
                    
                    return personal_tenant_id
                else:
                    logger.warning(f"User {user_id} has personalTenantId but it's not marked as personal: {personal_tenant_id}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.warning(f"Personal tenant not found for user {user_id}: {personal_tenant_id}")
                else:
                    raise

        # Create missing personal tenant
        logger.warning(f"Creating missing personal tenant for user: {user_id}")
        tenant_id = f"tenant_{uuid.uuid4()}"
        current_time = datetime.now(timezone.utc).isoformat()

        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": user_doc.get("name", f"Personal Tenant for {user_doc.get('sub', 'unknown')}"),
            "applicationId": app_id,
            "isPersonal": True,
            "userId": user_id,
            "userIds": [user_id],
            "createdAt": current_time,
            "metadata": {
                "createdBy": user_doc.get("sub", "unknown"),
                "autoCreated": True,
                "recoveryCreation": True
            }
        }

        # Create tenant
        await self._make_request("PUT", tenant_id, json=tenant_doc)

        # Update user document
        user_doc["personalTenantId"] = tenant_id
        if tenant_id not in user_doc.get("tenantIds", []):
            user_doc.setdefault("tenantIds", []).append(tenant_id)
        user_doc["updatedAt"] = current_time

        await self._make_request("PUT", user_id, json=user_doc)

        logger.info(f"Created missing personal tenant {tenant_id} for user {user_id}")
        return tenant_id

    async def _ensure_admin_tenant_exists(self) -> str:
        """
        Ensure the couch-sitter admin tenant exists, creating if necessary.

        Returns:
            Admin tenant ID

        Raises:
            httpx.HTTPError: If database operations fail
        """
        # Resolve the couch-sitter application ID
        app_doc = await self.find_application_by_db_name("couch-sitter")
        app_id = app_doc.get("_id") if app_doc else "couch-sitter"  # Fallback to db name if not found
        
        try:
            # Try to get existing admin tenant
            response = await self._make_request("GET", ADMIN_TENANT_ID)
            tenant_doc = response.json()
            
            # Validate the document structure
            if tenant_doc.get("type") == "tenant":
                logger.info(f"Admin tenant already exists: {ADMIN_TENANT_ID}")
                return ADMIN_TENANT_ID
            else:
                logger.warning(f"Admin tenant exists but is invalid (type={tenant_doc.get('type')}). Recreating...")
                # Fall through to creation logic (but we need to handle the update since it exists)
                # We can just proceed to the creation logic, but we need to ensure we use the current rev
                # The creation logic below uses PUT. If we want to reuse it, we should probably refactor.
                # Or just handle it here.
                
                current_time = datetime.now(timezone.utc).isoformat()
                admin_tenant = {
                    "_id": ADMIN_TENANT_ID,
                    "type": "tenant",
                    "name": "Couch-Sitter Administrators",
                    "applicationId": app_id,
                    "isPersonal": False,
                    "userIds": [],
                    "createdAt": current_time,
                    "metadata": {
                        "autoCreated": True,
                        "systemTenant": True,
                        "recreated": True
                    }
                }
                
                # Use the revision from the invalid doc to overwrite it
                if "_rev" in tenant_doc:
                    admin_tenant["_rev"] = tenant_doc["_rev"]
                
                await self._make_request("PUT", ADMIN_TENANT_ID, json=admin_tenant)
                logger.info(f"Recreated invalid admin tenant: {ADMIN_TENANT_ID}")
                return ADMIN_TENANT_ID
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Create admin tenant
                current_time = datetime.now(timezone.utc).isoformat()
                admin_tenant = {
                    "_id": ADMIN_TENANT_ID,
                    "type": "tenant",
                    "name": "Couch-Sitter Administrators",
                    "applicationId": app_id,
                    "isPersonal": False,
                    "userIds": [],
                    "createdAt": current_time,
                    "metadata": {
                        "autoCreated": True,
                        "systemTenant": True
                    }
                }

                try:
                    await self._make_request("PUT", ADMIN_TENANT_ID, json=admin_tenant)
                    logger.info(f"Created admin tenant: {ADMIN_TENANT_ID}")
                except httpx.HTTPStatusError as put_error:
                    # Handle 409 Conflict (likely a deleted document tombstone)
                    if put_error.response.status_code == 409:
                        logger.warning(f"Conflict creating admin tenant (likely deleted): {put_error}")
                        # Try to get the latest revision including deleted docs
                        try:
                            # Use _all_docs to find the revision of the deleted document
                            query = {"keys": [ADMIN_TENANT_ID]}
                            rev_response = await self._make_request("POST", "_all_docs", json=query)
                            rows = rev_response.json().get("rows", [])
                            
                            if rows and rows[0].get("value"):
                                current_rev = rows[0]["value"]["rev"]
                                logger.info(f"Found tombstone revision: {current_rev}")
                                admin_tenant["_rev"] = current_rev
                                
                                # Retry PUT with revision
                                await self._make_request("PUT", ADMIN_TENANT_ID, json=admin_tenant)
                                logger.info(f"Restored admin tenant: {ADMIN_TENANT_ID}")
                                return ADMIN_TENANT_ID
                        except Exception as rev_error:
                            logger.error(f"Failed to recover deleted admin tenant: {rev_error}")
                            raise put_error
                    else:
                        raise put_error
                
                return ADMIN_TENANT_ID
            else:
                raise

    async def _add_user_to_admin_tenant(self, user_id: str):
        """
        Add a user to the admin tenant.

        Args:
            user_id: User ID to add

        Raises:
            httpx.HTTPError: If database operations fail
        """
        # Fetch latest admin tenant
        response = await self._make_request("GET", ADMIN_TENANT_ID)
        admin_tenant = response.json()

        # Add user if not already in the list
        user_ids = admin_tenant.get("userIds", [])
        if user_id not in user_ids:
            user_ids.append(user_id)
            admin_tenant["userIds"] = user_ids
            admin_tenant["updatedAt"] = datetime.now(timezone.utc).isoformat()

            await self._make_request("PUT", ADMIN_TENANT_ID, json=admin_tenant)
            logger.info(f"Added user {user_id} to admin tenant")


    async def ensure_user_exists(self, sub: str, email: str = None, name: str = None, requested_db_name: str = None) -> UserTenantInfo:
        """
        Ensure a user exists in the database, creating them with a personal tenant if needed.
        
        Special handling for couch-sitter database: Users are added to a shared admin tenant
        instead of getting their own personal tenant.

        Args:
            sub: Clerk sub claim
            email: User email (optional)
            name: User name (optional)
            requested_db_name: The database name the user is accessing

        Returns:
            UserTenantInfo with user and tenant information

        Raises:
            httpx.HTTPError: If database operations fail
        """
        sub_hash = self._hash_sub(sub)
        
        # Use requested DB name or default to couch-sitter DB name
        app_id = requested_db_name or self.db_name

        # Special case: couch-sitter database uses shared admin tenant
        if app_id == "couch-sitter":
            logger.info(f"Creating/updating couch-sitter admin user: {sub_hash}")
            
            # Ensure admin tenant exists
            admin_tenant_id = await self._ensure_admin_tenant_exists()
            
            # Try to find existing user
            user_doc = await self.find_user_by_sub_hash(sub_hash)
            
            if not user_doc:
                # Create new admin user
                user_id = f"user_{sub_hash}"
                current_time = datetime.now(timezone.utc).isoformat()
                
                user_doc = {
                    "_id": user_id,
                    "type": "user",
                    "sub": sub,
                    "email": email,
                    "name": name or f"Admin {sub[:8]}",
                    "tenants": [
                        {
                            "tenantId": admin_tenant_id,
                            "role": "admin",
                            "personal": False,
                            "joinedAt": current_time
                        }
                    ],
                    "tenantIds": [admin_tenant_id],
                    "activeTenantId": admin_tenant_id,
                    "createdAt": current_time,
                    "updatedAt": current_time
                }
                
                await self._make_request("PUT", user_id, json=user_doc)
                logger.info(f"Created admin user: {user_id}")
            else:
                user_id = user_doc["_id"]
                
                # FIX: Update user name and email if missing/default
                user_updated = False
                current_name = user_doc.get("name", "")
                if name and (not current_name or current_name.startswith("Admin ") or current_name.startswith("User ")):
                    logger.info(f"Updating user name from '{current_name}' to '{name}'")
                    user_doc["name"] = name
                    user_updated = True
                
                current_email = user_doc.get("email")
                if email and not current_email:
                    logger.info(f"Updating user email from None to '{email}'")
                    user_doc["email"] = email
                    user_updated = True
                
                if user_updated:
                    user_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
                    await self._make_request("PUT", user_id, json=user_doc)
            
            # Add user to admin tenant
            await self._add_user_to_admin_tenant(user_id)
            
            return UserTenantInfo(
                user_id=user_id,
                tenant_id=admin_tenant_id,
                sub=sub,
                email=email,
                name=name or user_doc.get("name"),
                is_personal_tenant=False,  # Admin tenant is shared
                cached_at=time.time()
            )

        # Regular app users: create personal tenant
        # Try to find existing user
        user_doc = await self.find_user_by_sub_hash(sub_hash)

        if user_doc:
            # User exists - check if they have the new multi-tenant schema
            tenants = user_doc.get("tenants", [])
            personal_tenant_id = user_doc.get("personalTenantId")

            if tenants:
                # New multi-tenant schema
                logger.info(f"Existing user found with multi-tenant schema: {sub_hash}")
                personal_tenant = next((t for t in tenants if t.get("personal", False)), None)

                if not personal_tenant:
                    # Create personal tenant for this app
                    logger.info(f"No personal tenant found for {sub_hash}, creating one for app: {requested_db_name}")
                    personal_tenant_id = await self.ensure_personal_tenant_exists(user_doc, requested_db_name)
                    personal_tenant = {"tenantId": personal_tenant_id, "role": "owner", "personal": True}
                    tenants.append(personal_tenant)
                    
                    # IMPORTANT: Update user document with new tenant
                    user_doc["tenants"] = tenants
                    user_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
                    await self._make_request("PUT", user_doc["_id"], json=user_doc)
                    logger.info(f"Updated user {user_doc['_id']} with personal tenant {personal_tenant_id}")
                
                # FIX: Update user name if it's a default "Admin" name and we have a better one
                user_updated = False
                current_name = user_doc.get("name", "")
                if name and (not current_name or current_name.startswith("Admin ") or current_name.startswith("User ")):
                    logger.info(f"Updating user name from '{current_name}' to '{name}'")
                    user_doc["name"] = name
                    user_updated = True

                # FIX: Update user email if missing
                current_email = user_doc.get("email")
                if email and not current_email:
                    logger.info(f"Updating user email from None to '{email}'")
                    user_doc["email"] = email
                    user_updated = True

                # FIX: Update personal tenant name if it looks like a generated name
                active_tenant_id = personal_tenant.get("tenantId", personal_tenant_id)
                
                if user_updated:
                    user_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
                    await self._make_request("PUT", user_doc["_id"], json=user_doc)
                
                # Check tenant name and applicationId
                try:
                    tenant_response = await self._make_request("GET", active_tenant_id)
                    tenant_doc = tenant_response.json()
                    tenant_name = tenant_doc.get("name", "")
                    current_app_id = tenant_doc.get("applicationId")
                    
                    tenant_needs_update = False
                    
                    # FIX: Update tenant name if it's a default "Admin" name
                    if name and (tenant_name.startswith("Personal Tenant for") or tenant_name.startswith("Admin ")):
                        # Extract username from email if possible for better name
                        workspace_name = f"{name}'s Workspace"
                        if email:
                            username = email.split('@')[0]
                            workspace_name = f"{username}'s Workspace"
                            
                        logger.info(f"Updating tenant name from '{tenant_name}' to '{workspace_name}'")
                        tenant_doc["name"] = workspace_name
                        tenant_needs_update = True

                    # FIX: Update applicationId if it doesn't match requested app
                    app_id = requested_db_name or self.db_name
                    if app_id and app_id != "couch-sitter" and current_app_id != app_id:
                        logger.info(f"Updating tenant {active_tenant_id} applicationId from '{current_app_id}' to '{app_id}'")
                        tenant_doc["applicationId"] = app_id
                        tenant_needs_update = True
                    
                    if tenant_needs_update:
                        tenant_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
                        await self._make_request("PUT", active_tenant_id, json=tenant_doc)
                        
                except Exception as e:
                    logger.warning(f"Failed to check/update tenant info: {e}")

                try:
                    return UserTenantInfo(
                        user_id=user_doc["_id"],
                        tenant_id=active_tenant_id,
                        sub=sub,
                        email=user_doc.get("email"),
                        name=user_doc.get("name"),
                        is_personal_tenant=True,
                        cached_at=time.time()
                    )
                except Exception as e:
                    logger.error(f"Failed to create UserTenantInfo for existing multi-tenant user: {e}")
                    logger.error(f"User doc: {user_doc}")
                    logger.error(f"Tenant ID: {active_tenant_id}")
                    raise
            else:
                # Old single-tenant schema - migrate it
                logger.info(f"Existing user found with old schema, migrating: {sub_hash}")
                tenant_id = await self.ensure_personal_tenant_exists(user_doc, requested_db_name)

                # Migrate to new schema
                await self._migrate_user_to_multi_tenant(user_doc, tenant_id, sub, email, name)

                try:
                    return UserTenantInfo(
                        user_id=user_doc["_id"],
                        tenant_id=tenant_id,
                        sub=sub,
                        email=user_doc.get("email"),
                        name=user_doc.get("name"),
                        is_personal_tenant=True,
                        cached_at=time.time()
                    )
                except Exception as e:
                    logger.error(f"Failed to create UserTenantInfo for migrated user: {e}")
                    logger.error(f"User doc: {user_doc}")
                    logger.error(f"Tenant ID: {tenant_id}")
                    raise
        else:
            # Create new user with personal tenant using new schema
            logger.info(f"Creating new user with multi-tenant schema: {sub_hash}")
            created_user, created_tenant = await self.create_user_with_personal_tenant_multi_tenant(sub, email, name, requested_db_name)

            try:
                return UserTenantInfo(
                    user_id=created_user["_id"],
                    tenant_id=created_tenant["_id"],
                    sub=sub,
                    email=email,
                    name=name,
                    is_personal_tenant=True,
                    cached_at=time.time()
                )
            except Exception as e:
                logger.error(f"Failed to create UserTenantInfo for new multi-tenant user: {e}")
                logger.error(f"Created user: {created_user}")
                logger.error(f"Created tenant: {created_tenant}")
                raise

    async def ensure_app_exists(self, issuer: str, database_names: List[str], clerk_secret_key: str = None) -> Dict[str, Any]:
        """
        Ensure an App document exists for the given issuer, creating it if necessary.

        Args:
            issuer: The Clerk issuer URL
            database_names: List of database names this issuer can access
            clerk_secret_key: Clerk Secret Key for this app (optional)

        Returns:
            App document

        Raises:
            httpx.HTTPError: If database operations fail
        """
        app_id = f"app_{issuer.replace('https://', '').replace('/', '_').replace('.', '_')}"
        current_time = datetime.now(timezone.utc).isoformat()

        app_doc = {
            "_id": app_id,
            "type": "application",
            "issuer": issuer,
            "name": database_names[0] if database_names else "unknown",
            "databaseNames": database_names,
            "createdAt": current_time,
            "updatedAt": current_time,
            "metadata": {
                "autoCreated": True,
                "createdBy": "jwt_proxy_startup"
            }
        }

        # Add keys if provided
        if clerk_secret_key:
            app_doc["clerkSecretKey"] = clerk_secret_key


        try:
            # Try to get existing app
            response = await self._make_request("GET", app_id)
            response.raise_for_status()  # This will raise for 404 responses
            existing_app = response.json()
            
            # Check if we need to update keys
            needs_update = False
            if clerk_secret_key and existing_app.get("clerkSecretKey") != clerk_secret_key:
                existing_app["clerkSecretKey"] = clerk_secret_key
                needs_update = True

            
            # Also update database names if changed
            if set(existing_app.get("databaseNames", [])) != set(database_names):
                existing_app["databaseNames"] = database_names
                needs_update = True

            if needs_update:
                existing_app["updatedAt"] = current_time
                await self._make_request("PUT", app_id, json=existing_app)
                logger.info(f"Updated app document: {app_id}")
                return existing_app
            
            logger.info(f"App document already exists and is up to date: {app_id}")
            return existing_app
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Create new app document
                response = await self._make_request("PUT", app_id, json=app_doc)
                created_app = response.json()
                logger.info(f"Created app document: {app_id} for issuer: {issuer}")
                # Return the app document we created, not just the DAL response
                return app_doc
            else:
                raise

    async def load_all_apps(self) -> Dict[str, Dict[str, Any]]:
        """
        Load all App documents from the database and return issuer to app config mapping.

        Returns:
            Dictionary mapping issuer URLs to app configuration dict:
            {
                "issuer_url": {
                    "databaseNames": ["db1", "db2"],
                    "clerkSecretKey": "sk_..."
                }
            }

        Raises:
            httpx.HTTPError: If database operations fail
        """
        try:
            # Use couchdb query to find all app documents
            # Support both new "application" type and legacy "app" type
            query = {
                "selector": {
                    "$or": [
                        {"type": "application"},
                        {"type": "app"}
                    ]
                },
                "fields": ["issuer", "clerkIssuerId", "databaseNames", "databaseName", "name", "clerkSecretKey", "deletedAt"]
            }

            response = await self._make_request("POST", "_find", json=query)
            result = response.json()

            apps = {}
            for doc in result.get("docs", []):
                # Skip deleted documents
                if doc.get("deletedAt"):
                    continue
                    
                issuer = doc.get("issuer") or doc.get("clerkIssuerId")
                database_names = doc.get("databaseNames") or ([doc.get("databaseName")] if doc.get("databaseName") else [])
                if issuer and database_names:
                    apps[issuer] = {
                        "databaseNames": database_names,
                        "clerkSecretKey": doc.get("clerkSecretKey")
                    }
                    # Log loaded app (masking secret key)
                    has_key = "Yes" if doc.get("clerkSecretKey") else "No"
                    logger.info(f"Loaded app: {issuer} -> DBs: {database_names}, Has Key: {has_key}")

            logger.info(f"Loaded {len(apps)} applications from database")
            return apps

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to load apps from database: {e}")
            raise

    async def get_user_tenant_info(self, sub: str, email: str = None, name: str = None, requested_db_name: str = None) -> UserTenantInfo:
        """
        Get user and tenant information, creating if necessary.

        This is the main entry point for the JWT proxy to get tenant information.

        Args:
            sub: Clerk sub claim from JWT
            email: User email from JWT (optional)
            name: User name from JWT (optional)
            requested_db_name: The database name the user is accessing

        Returns:
            UserTenantInfo with the user's personal tenant ID

        Raises:
            ValueError: If required fields are missing
            httpx.HTTPError: If database operations fail
        """
        if not sub:
            raise ValueError("Sub claim is required")

        return await self.ensure_user_exists(sub, email, name, requested_db_name)

    async def get_user_tenants(self, sub: str) -> Tuple[List[Dict[str, Any]], str]:
        """
        Get all tenants for a user.

        Args:
            sub: Clerk sub claim

        Returns:
            Tuple of (list of tenant dicts with metadata, personal_tenant_id)

        Raises:
            ValueError: If user not found
            httpx.HTTPError: If database operations fail
        """
        sub_hash = self._hash_sub(sub)
        user_doc = await self.find_user_by_sub_hash(sub_hash)

        if not user_doc:
            raise ValueError(f"User not found for sub: {sub}")

        tenant_ids = user_doc.get("tenantIds", [])
        personal_tenant_id = user_doc.get("personalTenantId")
        tenants = []

        for tenant_id in tenant_ids:
            try:
                response = await self._make_request("GET", tenant_id)
                tenant_doc = response.json()
                
                # Skip deleted tenants
                if tenant_doc.get("deletedAt"):
                    continue
                
                tenants.append({
                    "tenantId": tenant_id,
                    "name": tenant_doc.get("name", f"Tenant {tenant_id}"),
                    "role": "owner" if tenant_doc.get("isPersonal") else "member",
                    "personal": tenant_doc.get("isPersonal", False),
                    "applicationId": tenant_doc.get("applicationId")
                })
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.warning(f"Tenant {tenant_id} not found for user {user_doc['_id']}")
                else:
                    logger.error(f"Error fetching tenant {tenant_id}: {e}")

        return tenants, personal_tenant_id


    async def create_user_with_personal_tenant_multi_tenant(self, sub: str, email: str = None, name: str = None, requested_db_name: str = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Create a new user and their personal tenant using the new multi-tenant schema.

        Args:
            sub: Clerk sub claim
            email: User email (optional)
            name: User name (optional)
            requested_db_name: The database name the user is accessing

        Returns:
            Tuple of (user_document, tenant_document)

        Raises:
            httpx.HTTPError: If database operations fail
        """
        sub_hash = self._hash_sub(sub)
        user_id = f"user_{sub_hash}"
        tenant_id = f"tenant_{uuid.uuid4()}"
        current_time = datetime.now(timezone.utc).isoformat()
        
        # Use requested DB name for applicationId, or default to couch-sitter DB name
        app_id = requested_db_name or self.db_name

        # Create personal tenant document
        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": name if name else f"Personal Tenant for {sub}",
            "applicationId": app_id,
            "isPersonal": True,
            "userId": user_id,
            "userIds": [user_id],
            "createdAt": current_time,
            "metadata": {
                "createdBy": sub,
                "autoCreated": True,
                "originalSub": sub
            }
        }

        # Create user document with new multi-tenant schema
        user_doc = {
            "_id": user_id,
            "type": "user",
            "sub": sub,
            "email": email,
            "name": name,
            "tenants": [
                {
                    "tenantId": tenant_id,
                    "role": "owner",
                    "personal": True,
                    "joinedAt": current_time
                }
            ],
            "personalTenantId": tenant_id,
            "tenantIds": [tenant_id],
            "createdAt": current_time,
            "updatedAt": current_time,
            "activeTenantId": tenant_id  # Start with personal tenant as active
        }

        try:
            # Create tenant first
            tenant_response = await self._make_request("PUT", tenant_id, json=tenant_doc)
            created_tenant = tenant_response.json()
            logger.info(f"Created personal tenant (multi-tenant): {tenant_id}")

            # Create user
            user_response = await self._make_request("PUT", user_id, json=user_doc)
            created_user = user_response.json()
            logger.info(f"Created user (multi-tenant): {user_id}")

            # Return the documents we created, not just the DAL responses
            return user_doc, tenant_doc

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to create user/tenant (multi-tenant): {e}")
            # Try to cleanup partially created documents
            try:
                await self._make_request("DELETE", tenant_id)
            except:
                pass
            try:
                await self._make_request("DELETE", user_id)
            except:
                pass
            raise

    async def _migrate_user_to_multi_tenant(self, user_doc: Dict[str, Any], tenant_id: str, sub: str, email: str = None, name: str = None) -> Dict[str, Any]:
        """
        Migrate a user from old single-tenant schema to new multi-tenant schema.

        Args:
            user_doc: Existing user document with old schema
            tenant_id: Personal tenant ID
            sub: Clerk sub claim
            email: User email (optional)
            name: User name (optional)

        Returns:
            Updated user document with new multi-tenant schema

        Raises:
            httpx.HTTPError: If database operations fail
        """
        current_time = datetime.now(timezone.utc).isoformat()

        # Update user document with new multi-tenant schema
        user_doc.update({
            "tenants": [
                {
                    "tenantId": tenant_id,
                    "role": "owner",
                    "personal": True,
                    "joinedAt": current_time
                }
            ],
            "personalTenantId": tenant_id,
            "tenantIds": [tenant_id],
            "updatedAt": current_time,
            "activeTenantId": tenant_id  # Start with personal tenant as active
        })

        # Update email and name if provided
        if email:
            user_doc["email"] = email
        if name:
            user_doc["name"] = name

        try:
            # Save the updated user document
            response = await self._make_request("PUT", user_doc["_id"], json=user_doc)
            updated_user = response.json()
            # Return the user document we updated, not just the DAL response
            logger.info(f"Migrated user to multi-tenant schema: {user_doc['_id']}")
            return user_doc

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to migrate user to multi-tenant schema: {e}")
            raise

    async def create_workspace_tenant(self, user_id: str, name: str, application_id: str) -> Dict[str, Any]:
        """
        Create a new workspace tenant (not personal).

        Args:
            user_id: ID of the owner (creator)
            name: Tenant name
            application_id: Application ID (e.g., 'roady')

        Returns:
            Created tenant document

        Raises:
            httpx.HTTPError: If database operation fails
        """
        tenant_id = f"tenant_{uuid.uuid4()}"
        current_time = datetime.now(timezone.utc).isoformat()

        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": name,
            "applicationId": application_id,
            "userId": user_id,
            "userIds": [user_id],
            "createdAt": current_time,
            "metadata": {
                "createdBy": user_id,
                "autoCreated": False
            }
        }

        try:
            response = await self._make_request("PUT", tenant_id, json=tenant_doc)
            created = response.json()
            logger.info(f"Created workspace tenant: {tenant_id} owned by {user_id}")

            # Create tenant_user_mapping for owner
            mapping_id = f"tenant_user_mapping:{tenant_id}:{user_id}"
            mapping_doc = {
                "_id": mapping_id,
                "type": "tenant_user_mapping",
                "tenantId": tenant_id,
                "userId": user_id,
                "role": "owner",
                "joinedAt": current_time
            }
            
            await self._make_request("PUT", mapping_id, json=mapping_doc)
            logger.info(f"Created owner mapping: {mapping_id}")

            # Update user's tenantIds list (multi-tenant schema)
            user_doc = await self.find_user_by_sub_hash(self._hash_sub(user_id.replace("user_", "")))
            if user_doc:
                tenant_ids = user_doc.get("tenantIds", [])
                if tenant_id not in tenant_ids:
                    tenant_ids.append(tenant_id)
                    user_doc["tenantIds"] = tenant_ids
                    user_doc["updatedAt"] = current_time
                    await self._make_request("PUT", user_doc["_id"], json=user_doc)
                    logger.info(f"Added tenant {tenant_id} to user {user_id}'s tenantIds")

            return tenant_doc

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to create workspace tenant: {e}")
            raise

    async def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a tenant document by ID.
        
        Deleted tenants (with deletedAt field) are treated as not found.

        Args:
            tenant_id: Tenant ID

        Returns:
            Tenant document if found and not deleted, None otherwise
        """
        try:
            response = await self._make_request("GET", tenant_id)
            response.raise_for_status()
            doc = response.json()
            
            # Treat deleted tenants as not found
            if doc.get("deletedAt"):
                logger.debug(f"Tenant is deleted: {tenant_id}")
                return None
            
            logger.debug(f"Found tenant: {tenant_id}")
            return doc
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"Tenant not found: {tenant_id}")
                return None
            logger.error(f"Error fetching tenant {tenant_id}: {e}")
            raise

    async def add_user_to_tenant(
        self,
        tenant_id: str,
        user_id: str,
        role: str = "member"
    ) -> Dict[str, Any]:
        """
        Add a user to a tenant.

        Args:
            tenant_id: Tenant ID
            user_id: User ID to add
            role: Role to assign (member, admin, owner)

        Returns:
            Updated tenant document

        Raises:
            httpx.HTTPError: If database operation fails
        """
        try:
            tenant = await self.get_tenant(tenant_id)
            if not tenant:
                raise ValueError(f"Tenant not found: {tenant_id}")

            # Add user to userIds if not already present
            user_ids = tenant.get("userIds", [])
            if user_id not in user_ids:
                user_ids.append(user_id)
                tenant["userIds"] = user_ids
                tenant["updatedAt"] = datetime.now(timezone.utc).isoformat()
                
                response = await self._make_request("PUT", tenant_id, json=tenant)
                updated = response.json()
                logger.info(f"Added user {user_id} to tenant {tenant_id}")

            # Create tenant_user_mapping
            mapping_id = f"tenant_user_mapping:{tenant_id}:{user_id}"
            current_time = datetime.now(timezone.utc).isoformat()
            
            mapping_doc = {
                "_id": mapping_id,
                "type": "tenant_user_mapping",
                "tenantId": tenant_id,
                "userId": user_id,
                "role": role,
                "joinedAt": current_time,
                "acceptedAt": current_time
            }

            await self._make_request("PUT", mapping_id, json=mapping_doc)
            logger.info(f"Created mapping: {mapping_id} with role {role}")

            return tenant

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to add user to tenant: {e}")
            raise

    async def get_tenant_user_mapping(self, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a tenant_user_mapping document.

        Args:
            tenant_id: Tenant ID
            user_id: User ID

        Returns:
            Mapping document if found, None otherwise
        """
        mapping_id = f"tenant_user_mapping:{tenant_id}:{user_id}"
        try:
            response = await self._make_request("GET", mapping_id)
            doc = response.json()
            logger.debug(f"Found mapping: {mapping_id}")
            return doc
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"Mapping not found: {mapping_id}")
                return None
            logger.error(f"Error fetching mapping {mapping_id}: {e}")
            raise