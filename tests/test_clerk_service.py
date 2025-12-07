"""
Clerk Service tests.

Tests session metadata handling and user management functionality.
"""

import pytest
import json
import time
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta

# Import service modules
from couchdb_jwt_proxy.clerk_service import ClerkService

# Try to import jwt for testing, but don't fail if not available
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False


@pytest.fixture
def mock_config():
    """Mock configuration for testing"""
    return {
        "CLERK_ISSUER_URL": "https://test-clerk.clerk.accounts.dev",
        "CLERK_SECRET_KEY": "test-secret-key"
    }


@pytest.fixture
def clerk_service(mock_config):
    """Create ClerkService instance for testing"""
    with patch('couchdb_jwt_proxy.clerk_service.os.getenv') as mock_getenv, \
         patch('couchdb_jwt_proxy.clerk_service.Clerk') as mock_clerk:

        mock_getenv.side_effect = lambda key, default=None: mock_config.get(key, default)
        mock_clerk.return_value = MagicMock()  # Mock Clerk client to avoid slow initialization
        service = ClerkService()
        return service


@pytest.fixture
def clerk_service_with_client(mock_config):
    """Create ClerkService instance with mocked client"""
    with patch('couchdb_jwt_proxy.clerk_service.os.getenv') as mock_getenv, \
         patch('couchdb_jwt_proxy.clerk_service.CLERK_API_AVAILABLE', True), \
         patch('couchdb_jwt_proxy.clerk_service.Clerk') as mock_clerk_class:

        mock_getenv.side_effect = lambda key, default=None: mock_config.get(key, default)
        mock_client = MagicMock()
        mock_clerk_class.return_value = mock_client

        service = ClerkService()
        service.clerk_client = mock_client
        return service, mock_client


@pytest.fixture
def valid_jwt_token():
    """Create a valid JWT token for testing"""
    # This is a mock JWT token for testing - in reality this would be cryptographically signed
    return "eyJhbGciOiJSUzI1NiIsImtpZCI6InRlc3Qta2V5LWlkIn0.eyJzdWIiOiJ1c2VyX3Rlc3QxMjMiLCJ1c2VyX2lkIjoidXNlcl90ZXN0MTIzIiwiZW1haWwiOiJ0ZXN0QGV4YW1wbGUuY29tIiwidGVuYW50X2lkIjoidGVuYW50LXRlc3QtMTIzIiwiZXhwIjo5OTk5OTk5OTk5LCJpc3MiOiJodHRwczovL3Rlc3QtY2xlcmsuY2xlcmsuYWNjb3VudHMuZGV2In0.mock-signature"


class TestClerkService:
    """Test ClerkService functionality"""


    def test_clerk_service_initialization(self, clerk_service):
        """Test ClerkService initialization"""
        assert clerk_service.issuer_url == "https://test-clerk.clerk.accounts.dev"
        assert clerk_service.secret_key == "test-secret-key"

    def test_clerk_service_missing_issuer_url(self):
        """Test ClerkService initialization with missing issuer URL"""
        with patch('couchdb_jwt_proxy.clerk_service.os.getenv', return_value=None):
            with pytest.raises(ValueError, match="CLERK_ISSUER_URL is required"):
                ClerkService()

    def test_clerk_service_no_api_available(self):
        """Test ClerkService when Clerk Backend API is not available"""
        with patch('couchdb_jwt_proxy.clerk_service.os.getenv') as mock_getenv, \
             patch('couchdb_jwt_proxy.clerk_service.CLERK_API_AVAILABLE', False):

            mock_getenv.side_effect = lambda key, default=None: "test-value" if key == "CLERK_ISSUER_URL" else None

            service = ClerkService()
            assert service.clerk_client is None

    def test_clerk_service_no_secret_key(self):
        """Test ClerkService when secret key is missing"""
        with patch('couchdb_jwt_proxy.clerk_service.os.getenv') as mock_getenv, \
             patch('couchdb_jwt_proxy.clerk_service.CLERK_API_AVAILABLE', True):

            mock_getenv.side_effect = lambda key, default=None: "test-value" if key == "CLERK_ISSUER_URL" else None

            service = ClerkService()
            assert service.clerk_client is None

    def test_is_configured(self, clerk_service):
        """Test is_configured method"""
        # When API is not available
        with patch('couchdb_jwt_proxy.clerk_service.CLERK_API_AVAILABLE', False), \
             patch('couchdb_jwt_proxy.clerk_service.os.getenv') as mock_getenv:
            mock_getenv.return_value = "https://test-clerk.clerk.accounts.dev"
            service = ClerkService()
            assert service.is_configured() is False

        # When client is not initialized
        with patch('couchdb_jwt_proxy.clerk_service.CLERK_API_AVAILABLE', True), \
             patch('couchdb_jwt_proxy.clerk_service.os.getenv') as mock_getenv, \
             patch('couchdb_jwt_proxy.clerk_service.Clerk') as mock_clerk:
            mock_getenv.return_value = "https://test-clerk.clerk.accounts.dev"
            mock_clerk.return_value = MagicMock()
            service = ClerkService()
            service.clerk_client = None
            assert service.is_configured() is False

        # When properly configured
        with patch('couchdb_jwt_proxy.clerk_service.os.getenv') as mock_getenv, \
             patch('couchdb_jwt_proxy.clerk_service.Clerk') as mock_clerk:
            mock_getenv.return_value = "https://test-clerk.clerk.accounts.dev"
            mock_clerk.return_value = MagicMock()
            service = ClerkService()
            service.clerk_client = MagicMock()
            assert service.is_configured() is True

    @pytest.mark.asyncio
    async def test_verify_session_token_no_client(self, clerk_service):
        """Test session verification when client is not configured"""
        clerk_service.clerk_client = None

        result = await clerk_service.verify_session_token("test-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_session_token_success(self, clerk_service_with_client):
        """Test successful session token verification"""
        service, mock_client = clerk_service_with_client

        mock_session = MagicMock()
        mock_session.id = "session_123"
        mock_session.user_id = "user_123"
        mock_session.expire_at = datetime.now() + timedelta(hours=1)
        mock_session.status = "active"

        mock_client.sessions.verify_session_token.return_value = mock_session

        result = await service.verify_session_token("valid-token")

        assert result is not None
        assert result["session_id"] == "session_123"
        assert result["user_id"] == "user_123"
        assert result["status"] == "active"
        mock_client.sessions.verify_session_token.assert_called_once_with("valid-token")

    @pytest.mark.asyncio
    async def test_verify_session_token_failure(self, clerk_service_with_client):
        """Test session token verification failure"""
        service, mock_client = clerk_service_with_client

        mock_client.sessions.verify_session_token.side_effect = Exception("Invalid token")

        result = await service.verify_session_token("invalid-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_session_metadata_no_client(self, clerk_service):
        """Test getting session metadata when client is not configured"""
        clerk_service.clerk_client = None

        result = await clerk_service.get_user_session_metadata("user_123", "session_123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_session_metadata_success(self, clerk_service_with_client):
        """Test successful session metadata retrieval"""
        service, mock_client = clerk_service_with_client

        mock_session = MagicMock()
        mock_session.public_user_data = MagicMock()
        mock_session.public_user_data.get.return_value = {
            "active_tenant_id": "tenant_123",
            "preferences": {"theme": "dark"}
        }

        mock_client.sessions.get.return_value = mock_session

        result = await service.get_user_session_metadata("user_123", "session_123")

        assert result is not None
        assert result["active_tenant_id"] == "tenant_123"
        assert result["preferences"]["theme"] == "dark"
        mock_client.sessions.get.assert_called_once_with(session_id="session_123")

    @pytest.mark.asyncio
    async def test_get_user_session_metadata_no_metadata(self, clerk_service_with_client):
        """Test session metadata retrieval when no metadata exists"""
        service, mock_client = clerk_service_with_client

        mock_session = MagicMock()
        mock_session.public_user_data = None

        mock_client.sessions.get.return_value = mock_session

        result = await service.get_user_session_metadata("user_123", "session_123")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_user_session_metadata_failure(self, clerk_service_with_client):
        """Test session metadata retrieval failure"""
        service, mock_client = clerk_service_with_client

        mock_client.sessions.get.side_effect = Exception("Session not found")

        result = await service.get_user_session_metadata("user_123", "session_123")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_active_tenant_in_session_no_client(self, clerk_service):
        """Test updating active tenant when client is not configured"""
        clerk_service.clerk_client = None

        result = await clerk_service.update_active_tenant_in_session("user_123", "session_123", "tenant_456")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_active_tenant_in_session_success(self, clerk_service_with_client):
        """Test successful active tenant update"""
        service, mock_client = clerk_service_with_client

        # Mock getting current metadata
        mock_session = MagicMock()
        mock_session.public_user_data = MagicMock()
        mock_session.public_user_data.get.return_value = {"existing": "metadata"}
        mock_client.sessions.get.return_value = mock_session

        result = await service.update_active_tenant_in_session("user_123", "session_123", "tenant_456")

        assert result is True
        mock_client.sessions.update.assert_called_once()
        call_args = mock_client.sessions.update.call_args
        assert call_args[1]["session_id"] == "session_123"
        assert "metadata" in call_args[1]["public_user_data"]
        assert call_args[1]["public_user_data"]["metadata"]["active_tenant_id"] == "tenant_456"

    @pytest.mark.asyncio
    async def test_update_active_tenant_in_session_fallback(self, clerk_service_with_client):
        """Test active tenant update with fallback to user metadata"""
        service, mock_client = clerk_service_with_client

        # Mock session metadata update failure
        mock_client.sessions.update.side_effect = Exception("Session update failed")

        # Mock getting current metadata
        mock_session = MagicMock()
        mock_session.public_user_data = MagicMock()
        mock_session.public_user_data.get.return_value = {}
        mock_client.sessions.get.return_value = mock_session

        # Mock user metadata update success
        mock_user = MagicMock()
        mock_user.public_metadata = {}
        mock_client.users.get.return_value = mock_user

        result = await service.update_active_tenant_in_session("user_123", "session_123", "tenant_456")

        assert result is True
        mock_client.users.update.assert_called_once()
        call_args = mock_client.users.update.call_args
        assert call_args[1]["user_id"] == "user_123"
        assert "active_tenant_id" in call_args[1]["public_metadata"]
        assert call_args[1]["public_metadata"]["active_tenant_id"] == "tenant_456"

    @pytest.mark.asyncio
    async def test_update_active_tenant_in_session_failure(self, clerk_service_with_client):
        """Test active tenant update complete failure"""
        service, mock_client = clerk_service_with_client

        # Mock all operations failing
        mock_client.sessions.update.side_effect = Exception("Session update failed")
        mock_client.users.update.side_effect = Exception("User update failed")

        result = await service.update_active_tenant_in_session("user_123", "session_123", "tenant_456")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_user_active_tenant_no_client(self, clerk_service):
        """Test getting active tenant when client is not configured"""
        clerk_service.clerk_client = None

        result = await clerk_service.get_user_active_tenant("user_123", "session_123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_active_tenant_from_session(self, clerk_service_with_client):
        """Test getting active tenant from session metadata"""
        service, mock_client = clerk_service_with_client

        # Mock session metadata with active tenant
        mock_session = MagicMock()
        mock_session.public_user_data = MagicMock()
        mock_session.public_user_data.get.return_value = {
            "active_tenant_id": "tenant_from_session"
        }
        mock_client.sessions.get.return_value = mock_session

        result = await service.get_user_active_tenant("user_123", "session_123")

        assert result == "tenant_from_session"
        mock_client.sessions.get.assert_called_once_with(session_id="session_123")

    @pytest.mark.asyncio
    async def test_get_user_active_tenant_fallback_to_user(self, clerk_service_with_client):
        """Test getting active tenant falling back to user metadata"""
        service, mock_client = clerk_service_with_client

        # Mock session metadata without active tenant
        mock_session = MagicMock()
        mock_session.public_user_data = MagicMock()
        mock_session.public_user_data.get.return_value = {}
        mock_client.sessions.get.return_value = mock_session

        # Mock user metadata with active tenant
        mock_user = MagicMock()
        mock_user.public_metadata = {"active_tenant_id": "tenant_from_user"}
        mock_client.users.get.return_value = mock_user

        result = await service.get_user_active_tenant("user_123", "session_123")

        assert result == "tenant_from_user"
        mock_client.users.get.assert_called_once_with(user_id="user_123")

    @pytest.mark.asyncio
    async def test_get_user_active_tenant_not_found(self, clerk_service_with_client):
        """Test getting active tenant when none exists"""
        service, mock_client = clerk_service_with_client

        # Mock both session and user metadata without active tenant
        mock_session = MagicMock()
        mock_session.public_user_data = MagicMock()
        mock_session.public_user_data.get.return_value = {}
        mock_client.sessions.get.return_value = mock_session

        mock_user = MagicMock()
        mock_user.public_metadata = {}
        mock_client.users.get.return_value = mock_user

        result = await service.get_user_active_tenant("user_123", "session_123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_active_tenant_failure(self, clerk_service_with_client):
        """Test getting active tenant with error"""
        service, mock_client = clerk_service_with_client

        mock_client.sessions.get.side_effect = Exception("Session access failed")
        mock_client.users.get.side_effect = Exception("User access failed")

        result = await service.get_user_active_tenant("user_123", "session_123")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_user_active_tenant_no_client(self, clerk_service):
        """Test updating user active tenant when client is not configured"""
        clerk_service.clerk_client = None

        result = await clerk_service.update_user_active_tenant("user_123", "tenant_456")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_user_active_tenant_success(self, clerk_service_with_client):
        """Test successful user active tenant update"""
        service, mock_client = clerk_service_with_client

        # Mock existing user metadata
        mock_user = MagicMock()
        mock_user.public_metadata = {"existing": "metadata"}
        mock_client.users.get.return_value = mock_user

        result = await service.update_user_active_tenant("user_123", "tenant_456")

        assert result is True
        mock_client.users.update.assert_called_once()
        call_args = mock_client.users.update.call_args
        assert call_args[1]["user_id"] == "user_123"
        assert "existing" in call_args[1]["public_metadata"]
        assert call_args[1]["public_metadata"]["active_tenant_id"] == "tenant_456"
        assert call_args[1]["public_metadata"]["existing"] == "metadata"  # Preserved existing

    @pytest.mark.asyncio
    async def test_update_user_active_tenant_no_existing_metadata(self, clerk_service_with_client):
        """Test updating user active tenant when no existing metadata"""
        service, mock_client = clerk_service_with_client

        # Mock user with no existing metadata
        mock_user = MagicMock()
        mock_user.public_metadata = None
        mock_client.users.get.return_value = mock_user

        result = await service.update_user_active_tenant("user_123", "tenant_456")

        assert result is True
        mock_client.users.update.assert_called_once()
        call_args = mock_client.users.update.call_args
        metadata = call_args[1]["public_metadata"]
        assert metadata["active_tenant_id"] == "tenant_456"

    @pytest.mark.asyncio
    async def test_update_user_active_tenant_failure(self, clerk_service_with_client):
        """Test user active tenant update failure"""
        service, mock_client = clerk_service_with_client

        mock_client.users.get.side_effect = Exception("User not found")

        result = await service.update_user_active_tenant("user_123", "tenant_456")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_user_from_jwt_success(self, clerk_service, valid_jwt_token):
        """Test extracting user info from JWT"""
        if not JWT_AVAILABLE:
            pytest.skip("PyJWT not available")

        result = await clerk_service.get_user_from_jwt(valid_jwt_token)

        assert result is not None
        assert result["sub"] == "user_test123"
        assert result["user_id"] == "user_test123"
        assert result["email"] == "test@example.com"
        assert result["tenant_id"] == "tenant-test-123"

    @pytest.mark.asyncio
    async def test_get_user_from_jwt_invalid_token(self, clerk_service):
        """Test extracting user info from invalid JWT"""
        result = await clerk_service.get_user_from_jwt("invalid.jwt.token")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_from_jwt_missing_fields(self, clerk_service):
        """Test extracting user info from JWT with missing fields"""
        if not JWT_AVAILABLE:
            pytest.skip("PyJWT not available")

        # Create token with minimal fields
        token = jwt.encode({"sub": "minimal_user"}, "test-secret", algorithm="HS256")

        result = await clerk_service.get_user_from_jwt(token)

        assert result is not None
        assert result["sub"] == "minimal_user"
        assert result["user_id"] == "minimal_user"
        assert result["email"] is None
        assert result["name"] is None
        assert result["session_id"] is None

    @pytest.mark.asyncio
    async def test_full_workflow_session_management(self, clerk_service_with_client):
        """Test complete session management workflow"""
        service, mock_client = clerk_service_with_client

        # Setup mocks
        mock_session = MagicMock()
        mock_session.id = "session_123"
        mock_session.user_id = "user_123"
        mock_session.status = "active"
        mock_client.sessions.verify_session_token.return_value = mock_session

        mock_session_metadata = MagicMock()
        mock_session_metadata.public_user_data = MagicMock()
        mock_session_metadata.public_user_data.get.return_value = {}
        mock_client.sessions.get.return_value = mock_session_metadata

        mock_user = MagicMock()
        mock_user.public_metadata = {}
        mock_client.users.get.return_value = mock_user

        # 1. Verify session token
        session_info = await service.verify_session_token("valid-token")
        assert session_info is not None
        assert session_info["user_id"] == "user_123"

        # 2. Get current active tenant (should be None initially)
        active_tenant = await service.get_user_active_tenant("user_123", "session_123")
        assert active_tenant is None

        # 3. Update active tenant in session
        update_success = await service.update_active_tenant_in_session("user_123", "session_123", "tenant_new")
        assert update_success is True

        # 4. Get updated active tenant
        # Configure the mock to return the updated tenant info
        updated_session_metadata = MagicMock()
        updated_session_metadata.public_user_data = MagicMock()
        updated_session_metadata.public_user_data.get.return_value = {"active_tenant_id": "tenant_new"}
        mock_client.sessions.get.return_value = updated_session_metadata

        active_tenant = await service.get_user_active_tenant("user_123", "session_123")
        assert active_tenant == "tenant_new"

        # Verify the sequence of calls
        assert mock_client.sessions.verify_session_token.called
        assert mock_client.sessions.get.called
        assert mock_client.sessions.update.called


class TestClerkServiceIntegration:
    """Integration tests for ClerkService"""

    @pytest.mark.asyncio
    async def test_service_without_backend_api(self):
        """Test service behavior when Clerk Backend API is not available"""
        with patch('couchdb_jwt_proxy.clerk_service.CLERK_API_AVAILABLE', False):
            service = ClerkService(secret_key="test", issuer_url="https://test.clerk.dev")

            # All operations should gracefully return None/False
            assert await service.verify_session_token("token") is None
            assert await service.get_user_session_metadata("user", "session") is None
            assert await service.update_active_tenant_in_session("user", "session", "tenant") is False
            assert await service.get_user_active_tenant("user", "session") is None
            assert await service.update_user_active_tenant("user", "tenant") is False
            assert service.is_configured() is False

    @pytest.mark.asyncio
    async def test_service_exception_handling(self, clerk_service_with_client):
        """Test service handles exceptions gracefully"""
        service, mock_client = clerk_service_with_client

        # Make all client methods raise exceptions
        mock_client.sessions.verify_session_token.side_effect = Exception("Session error")
        mock_client.sessions.get.side_effect = Exception("Get error")
        mock_client.sessions.update.side_effect = Exception("Update error")
        mock_client.users.get.side_effect = Exception("User error")
        mock_client.users.update.side_effect = Exception("User update error")

        # All operations should handle exceptions gracefully
        assert await service.verify_session_token("token") is None
        assert await service.get_user_session_metadata("user", "session") is None
        assert await service.update_active_tenant_in_session("user", "session", "tenant") is False
        assert await service.get_user_active_tenant("user", "session") is None
        assert await service.update_user_active_tenant("user", "tenant") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])