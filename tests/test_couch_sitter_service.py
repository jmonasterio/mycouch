"""
Couch Sitter Service tests.

Tests user and tenant management, database operations using Memory DAL.
"""

import pytest
import json
import time
import hashlib
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta

# Import service modules
from couchdb_jwt_proxy.couch_sitter_service import CouchSitterService
from couchdb_jwt_proxy.user_tenant_cache import UserTenantInfo
from couchdb_jwt_proxy.dal import create_dal


@pytest.fixture
def memory_dal():
    """Memory DAL for testing"""
    return create_dal(backend="memory")


class TestCouchSitterService:
    """Test CouchSitterService functionality"""

    @pytest.fixture
    def couch_sitter_service(self, memory_dal):
        """Create CouchSitterService instance for testing"""
        # Create service with memory DAL for testing
        # Note: couch_sitter_db_url should always be couch-sitter DB
        # requested_db_name is what app the user is accessing
        service = CouchSitterService(
            couch_sitter_db_url="http://localhost:5984/couch-sitter",
            couchdb_user="admin",
            couchdb_password="password",
            dal=memory_dal
        )
        return service

    def test_service_initialization(self):
        """Test CouchSitterService initialization"""
        service = CouchSitterService(
            couch_sitter_db_url="http://localhost:5984/couch-sitter",
            couchdb_user="admin",
            couchdb_password="password"
        )

        assert service.db_url == "http://localhost:5984/couch-sitter"
        assert service.couchdb_user == "admin"
        assert service.couchdb_password == "password"
        assert "Authorization" in service.auth_headers

    def test_service_initialization_no_auth(self):
        """Test CouchSitterService initialization without auth"""
        service = CouchSitterService(
            couch_sitter_db_url="http://localhost:5984/couch-sitter"
        )

        assert service.db_url == "http://localhost:5984/couch-sitter"
        assert service.couchdb_user is None
        assert service.couchdb_password is None
        assert service.auth_headers == {}

    def test_hash_sub(self):
        """Test SHA256 hashing of sub claim"""
        service = CouchSitterService("http://localhost:5984/test")

        sub = "user_test123"
        hash_result = service._hash_sub(sub)

        # Should be SHA256 hash
        assert len(hash_result) == 64  # SHA256 produces 64-char hex string
        assert hash_result != sub

        # Should be consistent
        hash_result2 = service._hash_sub(sub)
        assert hash_result == hash_result2

        # Different subs should produce different hashes
        different_hash = service._hash_sub("different_sub")
        assert hash_result != different_hash

    @pytest.mark.asyncio
    async def test_find_user_by_sub_hash_not_found(self, couch_sitter_service):
        """Test finding user when not found"""
        sub_hash = "nonexistent_hash"
        result = await couch_sitter_service.find_user_by_sub_hash(sub_hash)

        assert result is None

    @pytest.mark.asyncio
    async def test_create_user_with_personal_tenant(self, couch_sitter_service):
        """Test creating user and personal tenant"""
        sub = "user_test123"
        email = "test@example.com"
        name = "Test User"

        user_doc, tenant_doc = await couch_sitter_service.create_user_with_personal_tenant(sub, email, name, requested_db_name="test-db")

        # Verify user document
        assert user_doc is not None
        assert user_doc["type"] == "user"
        assert user_doc["sub"] == sub
        assert user_doc["email"] == email
        assert user_doc["name"] == name
        assert "personalTenantId" in user_doc
        assert "tenantIds" in user_doc

        # Verify tenant document
        assert tenant_doc is not None
        assert tenant_doc["type"] == "tenant"
        assert tenant_doc["applicationId"] == "test-db"
        assert tenant_doc["isPersonal"] is True
        assert tenant_doc["name"] == name

        # Verify relationship
        assert user_doc["personalTenantId"] == tenant_doc["_id"]
        assert user_doc["tenantIds"][0] == tenant_doc["_id"]
        assert tenant_doc["userIds"][0] == user_doc["_id"]

    @pytest.mark.asyncio
    async def test_create_user_with_personal_tenant_minimal(self, couch_sitter_service):
        """Test creating user with minimal information"""
        sub = "minimal_user"

        user_doc, tenant_doc = await couch_sitter_service.create_user_with_personal_tenant(sub, requested_db_name="test-db")

        # Verify user document
        assert user_doc["sub"] == sub
        assert user_doc["type"] == "user"
        assert user_doc["email"] is None
        assert user_doc["name"] is not None  # Should be auto-generated

        # Verify tenant document
        assert tenant_doc["type"] == "tenant"
        assert tenant_doc["name"] is not None  # Should be auto-generated

    @pytest.mark.asyncio
    async def test_ensure_user_exists_new_user(self, couch_sitter_service):
        """Test ensuring user exists when user is new"""
        sub = "new_user_123"
        email = "newuser@example.com"
        name = "New User"

        result = await couch_sitter_service.ensure_user_exists(sub, email, name, requested_db_name="test-db")

        assert isinstance(result, UserTenantInfo)
        assert result.sub == sub
        assert result.email == email
        assert result.name == name
        assert result.is_personal_tenant is True
        assert result.user_id.startswith("user_")
        assert result.tenant_id.startswith("tenant_")

    @pytest.mark.asyncio
    async def test_ensure_user_exists_existing_user_new_schema(self, couch_sitter_service):
        """Test ensuring user exists when user exists with new schema"""
        sub = "existing_user_456"
        sub_hash = hashlib.sha256(sub.encode()).hexdigest()

        # Create existing user with new schema
        user_doc = {
            "_id": f"user_{sub_hash}",
            "type": "user",
            "sub": sub,
            "email": "existing@example.com",
            "name": "Existing User",
            "tenants": [
                {
                    "tenantId": "existing_tenant_123",
                    "role": "owner",
                    "personal": True,
                    "joinedAt": datetime.now().isoformat()
                }
            ],
            "personalTenantId": "existing_tenant_123",
            "tenantIds": ["existing_tenant_123"],
            "createdAt": datetime.now().isoformat(),
            "updatedAt": datetime.now().isoformat()
        }

        # Store in memory DAL
        await couch_sitter_service.dal.get(f"/test-db/{user_doc['_id']}", "PUT", user_doc)

        result = await couch_sitter_service.ensure_user_exists(sub, requested_db_name="test-db")

        assert isinstance(result, UserTenantInfo)
        assert result.sub == sub
        assert result.user_id == user_doc["_id"]
        assert result.tenant_id == "existing_tenant_123"

    @pytest.mark.asyncio
    async def test_ensure_app_exists_new_app(self, couch_sitter_service):
        """Test ensuring app exists when app is new"""
        issuer = "https://test-clerk.clerk.accounts.dev"
        database_names = ["roady", "couch-sitter"]

        result = await couch_sitter_service.ensure_app_exists(issuer, database_names)

        assert result is not None
        assert result["type"] == "application"
        assert result["issuer"] == issuer
        assert result["databaseNames"] == database_names
        assert result["name"] == database_names[0]

    @pytest.mark.asyncio
    async def test_ensure_app_exists_existing_app(self, couch_sitter_service):
        """Test ensuring app exists when app already exists"""
        issuer = "https://test-clerk.clerk.accounts.dev"
        database_names = ["roady", "couch-sitter"]

        # Create existing app
        app_id = f"app_{issuer.replace('https://', '').replace('/', '_').replace('.', '_')}"
        existing_app = {
            "_id": app_id,
            "type": "application",
            "issuer": issuer,
            "name": "roady",
            "databaseNames": ["roady", "couch-sitter"],
            "createdAt": datetime.now().isoformat(),
            "updatedAt": datetime.now().isoformat()
        }

        # Store in memory DAL
        await couch_sitter_service.dal.get(f"/test-db/{app_id}", "PUT", existing_app)

        result = await couch_sitter_service.ensure_app_exists(issuer, database_names)

        assert result is not None
        assert result["_id"] == app_id
        assert result["issuer"] == issuer

    @pytest.mark.asyncio
    async def test_load_all_apps(self, couch_sitter_service):
        """Test loading all apps from database"""
        # Create multiple apps
        apps = [
            {
                "_id": "app_test1_clerk_accounts_dev",
                "type": "application",
                "issuer": "https://test1.clerk.accounts.dev",
                "databaseNames": ["roady"]
            },
            {
                "_id": "app_test2_clerk_accounts_dev",
                "type": "application",
                "issuer": "https://test2.clerk.accounts.dev",
                "databaseNames": ["couch-sitter"]
            }
        ]

        # Store in memory DAL
        for app in apps:
            await couch_sitter_service.dal.get(f"/test-db/{app['_id']}", "PUT", app)

        result = await couch_sitter_service.load_all_apps()

        assert isinstance(result, dict)
        assert len(result) == 2
        assert "https://test1.clerk.accounts.dev" in result
        assert "https://test2.clerk.accounts.dev" in result
        assert result["https://test1.clerk.accounts.dev"] == ["roady"]
        assert result["https://test2.clerk.accounts.dev"] == ["couch-sitter"]

    @pytest.mark.asyncio
    async def test_get_user_tenant_info(self, couch_sitter_service):
        """Test getting user tenant info (main entry point)"""
        sub = "main_entry_user"
        email = "main@example.com"
        name = "Main User"

        result = await couch_sitter_service.get_user_tenant_info(sub, email, name, requested_db_name="test-db")

        assert isinstance(result, UserTenantInfo)
        assert result.sub == sub
        assert result.email == email
        assert result.name == name
        assert result.is_personal_tenant is True

    @pytest.mark.asyncio
    async def test_get_user_tenant_info_missing_sub(self, couch_sitter_service):
        """Test getting user tenant info with missing sub"""
        with pytest.raises(ValueError, match="Sub claim is required"):
            await couch_sitter_service.get_user_tenant_info("", requested_db_name="test-db")

    @pytest.mark.asyncio
    async def test_create_user_with_personal_tenant_multi_tenant(self, couch_sitter_service):
        """Test creating user with personal tenant using multi-tenant schema"""
        sub = "multi_tenant_user"
        email = "multi@example.com"
        name = "Multi User"

        user_doc, tenant_doc = await couch_sitter_service.create_user_with_personal_tenant_multi_tenant(sub, email, name, requested_db_name="test-db")

        # Verify user document has new schema
        assert user_doc["type"] == "user"
        assert user_doc["sub"] == sub
        assert "tenants" in user_doc
        assert len(user_doc["tenants"]) == 1
        assert user_doc["tenants"][0]["personal"] is True
        assert user_doc["tenants"][0]["role"] == "owner"
        assert user_doc["personalTenantId"] == tenant_doc["_id"]
        assert "activeTenantId" in user_doc

        # Verify tenant document
        assert tenant_doc["type"] == "tenant"
        assert tenant_doc["isPersonal"] is True
        assert tenant_doc["userIds"][0] == user_doc["_id"]

    @pytest.mark.asyncio
    async def test_ensure_personal_tenant_exists_existing(self, couch_sitter_service):
        """Test ensuring personal tenant exists when it already exists"""
        # Create user with existing personal tenant
        sub = "user_with_tenant"
        sub_hash = hashlib.sha256(sub.encode()).hexdigest()
        user_id = f"user_{sub_hash}"
        tenant_id = "existing_tenant_123"

        user_doc = {
            "_id": user_id,
            "type": "user",
            "sub": sub,
            "personalTenantId": tenant_id,
            "tenants": [{"tenantId": tenant_id, "personal": True, "role": "owner"}]
        }

        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": "Existing Tenant",
            "isPersonal": True,
            "userId": user_id,
            "userIds": [user_id]
        }

        # Store in memory DAL
        await couch_sitter_service.dal.get(f"/test-db/{user_id}", "PUT", user_doc)
        await couch_sitter_service.dal.get(f"/test-db/{tenant_id}", "PUT", tenant_doc)

        result = await couch_sitter_service.ensure_personal_tenant_exists(user_doc, requested_db_name="test-db")

        assert result == tenant_id

    @pytest.mark.asyncio
    async def test_ensure_personal_tenant_exists_missing(self, couch_sitter_service):
        """Test ensuring personal tenant exists when it's missing"""
        # Create user without personal tenant
        sub = "user_without_tenant"
        sub_hash = hashlib.sha256(sub.encode()).hexdigest()
        user_id = f"user_{sub_hash}"

        user_doc = {
            "_id": user_id,
            "type": "user",
            "sub": sub,
            "name": "User Without Tenant"
        }

        # Store in memory DAL
        await couch_sitter_service.dal.get(f"/test-db/{user_id}", "PUT", user_doc)

        result = await couch_sitter_service.ensure_personal_tenant_exists(user_doc, requested_db_name="test-db")

        assert result is not None
        assert result.startswith("tenant_")

        # Verify tenant was created
        tenant_doc = await couch_sitter_service.dal.get(f"/test-db/{result}", "GET")
        assert tenant_doc["type"] == "tenant"
        assert tenant_doc["isPersonal"] is True

        # Verify user was updated
        updated_user = await couch_sitter_service.dal.get(f"/test-db/{user_id}", "GET")
        assert updated_user["personalTenantId"] == result

    @pytest.mark.asyncio
    async def test_migrate_user_to_multi_tenant(self, couch_sitter_service):
        """Test migrating user to multi-tenant schema"""
        sub_hash = "abc123hash"
        user_id = f"user_{sub_hash}"
        tenant_id = "migration_tenant_123"

        # Create user with old schema
        user_doc = {
            "_id": user_id,
            "type": "user",
            "sub": "migration_user",
            "email": "migration@example.com",
            "name": "Migration User",
            "personalTenantId": tenant_id
        }

        # Create tenant
        tenant_doc = {
            "_id": tenant_id,
            "type": "tenant",
            "name": "Migration Tenant",
            "isPersonal": True
        }

        # Store in memory DAL
        await couch_sitter_service.dal.get(f"/test-db/{user_id}", "PUT", user_doc)
        await couch_sitter_service.dal.get(f"/test-db/{tenant_id}", "PUT", tenant_doc)

        updated_user = await couch_sitter_service._migrate_user_to_multi_tenant(
            user_doc, tenant_id, "migration_user", "updated@example.com", "Updated Name"
        )

        # Verify migration
        assert "tenants" in updated_user
        assert len(updated_user["tenants"]) == 1
        assert updated_user["tenants"][0]["tenantId"] == tenant_id
        assert updated_user["tenants"][0]["personal"] is True
        assert updated_user["tenants"][0]["role"] == "owner"
        assert updated_user["personalTenantId"] == tenant_id
        assert updated_user["activeTenantId"] == tenant_id
        assert updated_user["email"] == "updated@example.com"
        assert updated_user["name"] == "Updated Name"


class TestCouchSitterServiceIntegration:
    """Integration tests for CouchSitterService"""

    @pytest.mark.asyncio
    async def test_full_user_creation_workflow(self, memory_dal):
        """Test complete user creation workflow"""
        # Service uses DAL directly - no HTTP mocking needed
        service = CouchSitterService("http://localhost:5984/test-db", dal=memory_dal)

        # Execute workflow
        sub = "workflow_user"
        email = "workflow@example.com"
        name = "Workflow User"

        result = await service.get_user_tenant_info(sub, email, name)

        # Verify results
        assert isinstance(result, UserTenantInfo)
        assert result.sub == sub
        assert result.email == email
        assert result.name == name
        assert result.is_personal_tenant is True

        # Verify documents were created in memory DAL
        user_id = result.user_id
        tenant_id = result.tenant_id

        user_doc = await memory_dal.get(f"/test-db/{user_id}", "GET")
        tenant_doc = await memory_dal.get(f"/test-db/{tenant_id}", "GET")

        assert user_doc is not None
        assert user_doc["sub"] == sub
        assert user_doc["type"] == "user"

        assert tenant_doc is not None
        assert tenant_doc["type"] == "tenant"
        assert tenant_doc["isPersonal"] is True

    @pytest.mark.asyncio
    async def test_user_exists_workflow(self, memory_dal):
        """Test workflow when user already exists"""
        with patch('couchdb_jwt_proxy.couch_sitter_service.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Pre-create user in memory DAL
            sub = "existing_workflow_user"
            sub_hash = hashlib.sha256(sub.encode()).hexdigest()
            user_id = f"user_{sub_hash}"
            tenant_id = "existing_tenant_456"

            user_doc = {
                "_id": user_id,
                "type": "user",
                "sub": sub,
                "tenants": [
                    {
                        "tenantId": tenant_id,
                        "personal": True,
                        "role": "owner",
                        "joinedAt": datetime.now().isoformat()
                    }
                ],
                "personalTenantId": tenant_id,
                "activeTenantId": tenant_id
            }

            tenant_doc = {
                "_id": tenant_id,
                "type": "tenant",
                "name": "Existing Tenant",
                "isPersonal": True
            }

            await memory_dal.get(f"/test-db/{user_id}", "PUT", user_doc)
            await memory_dal.get(f"/test-db/{tenant_id}", "PUT", tenant_doc)

            # Mock requests to use memory DAL
            def mock_request(method, url, headers=None, json=None):
                response = MagicMock()
                response.raise_for_status = MagicMock()

                if method == "POST" and "_find" in url:
                    # Find user query
                    selector = json.get("selector", {})
                    if selector.get("_id") == user_id:
                        response.json.return_value = {"docs": [user_doc]}
                    else:
                        response.json.return_value = {"docs": []}
                elif method == "GET":
                    doc_id = url.split("/")[-1]
                    if doc_id == tenant_id:
                        response.json.return_value = tenant_doc
                    else:
                        response.status_code = 404
                        raise Exception("404 Not Found")

                return response

            mock_client.request = mock_request

            service = CouchSitterService("http://localhost:5984/test-db", dal=memory_dal)

            # Execute workflow
            result = await service.get_user_tenant_info(sub)

            # Verify results - should use existing user
            assert isinstance(result, UserTenantInfo)
            assert result.sub == sub
            assert result.user_id == user_id
            assert result.tenant_id == tenant_id
            assert result.is_personal_tenant is True

    @pytest.mark.asyncio
    async def test_error_handling_workflow(self, memory_dal):
        """Test workflow with error handling"""
        with patch('couchdb_jwt_proxy.couch_sitter_service.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock requests to always fail
            mock_client.request.side_effect = Exception("Database error")

            service = CouchSitterService("http://localhost:5984/test-db")

            # Should handle errors gracefully
            with pytest.raises(Exception):
                await service.get_user_tenant_info("error_user")

    @pytest.mark.asyncio
    async def test_app_management_workflow(self, memory_dal):
        """Test application management workflow"""
        with patch('couchdb_jwt_proxy.couch_sitter_service.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock requests to use memory DAL
            async def mock_request(method, url, headers=None, json=None):
                response = MagicMock()
                response.raise_for_status = MagicMock()

                if method == "POST" and "_find" in url:
                    # Use memory DAL for find
                    result = await memory_dal.get("/test-db/_find", "POST", json)
                    response.json.return_value = result
                elif method == "PUT":
                    doc_id = url.split("/")[-1]
                    result = await memory_dal.get(f"/test-db/{doc_id}", "PUT", json)
                    response.json.return_value = result
                    response.status_code = 201
                elif method == "GET":
                    doc_id = url.split("/")[-1]
                    result = await memory_dal.get(f"/test-db/{doc_id}", "GET")
                    if result.get("error") == "not_found":
                        import httpx
                        response.status_code = 404
                        raise httpx.HTTPStatusError(
                            f"HTTP {response.status_code} error",
                            request=MagicMock(),
                            response=response
                        )
                    else:
                        response.json.return_value = result

                return response

            mock_client.request = mock_request

            service = CouchSitterService("http://localhost:5984/test-db", dal=memory_dal)

            # Test app creation
            issuer = "https://test-app.clerk.accounts.dev"
            database_names = ["roady", "test-app"]

            app = await service.ensure_app_exists(issuer, database_names)

            assert app is not None
            assert app["type"] == "application"
            assert app["issuer"] == issuer
            assert app["databaseNames"] == database_names

            # Test loading all apps
            apps = await service.load_all_apps()

            assert isinstance(apps, dict)
            assert issuer in apps
            assert apps[issuer] == database_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])