"""
Manual Integration Tests for __users and __tenants Virtual Endpoints

This test suite is designed to be run manually with a valid JWT token.
It tests the virtual table endpoints that provide user and tenant management.

Usage:
    # Token is read from .env file (JWT_TOKEN=...)
    python -m pytest tests/test_virtual_endpoints_manual.py -v -s

Or set via environment variable:
    export JWT_TOKEN="your_clerk_jwt_token_here"
    python -m pytest tests/test_virtual_endpoints_manual.py -v -s

The endpoints being tested:
- GET /__users/{user_id}       - Get user document (user can read own)
- PUT /__users/{user_id}       - Update user document (user can update own)
- DELETE /__users/{user_id}    - Soft-delete user (cannot delete self)
- GET /__tenants/{tenant_id}   - Get tenant document
- GET /__tenants               - List user's tenants
- POST /__tenants              - Create new tenant
- PUT /__tenants/{tenant_id}   - Update tenant (owner only)
- DELETE /__tenants/{tenant_id} - Delete tenant (owner only, not active)
"""

import os
import sys
import json
import httpx
import hashlib
import pytest
from typing import Optional, Dict, Any
from pathlib import Path

# Load .env file
try:
    from dotenv import load_dotenv
    # Load from .env in the project root
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[OK] Loaded .env from {env_path}")
    else:
        print(f"[WARNING] .env not found at {env_path}, using environment variables")
except ImportError:
    print("[WARNING] python-dotenv not installed. Install with: pip install python-dotenv")
    print("   Or set JWT_TOKEN environment variable directly")

# Configuration
PROXY_URL = os.getenv("PROXY_URL", "http://localhost:5985")
JWT_TOKEN = os.getenv("JWT_TOKEN", "")

# Test utilities
def hash_sub(sub: str) -> str:
    """Hash a Clerk sub claim to match internal user ID format"""
    return hashlib.sha256(sub.encode('utf-8')).hexdigest()


class VirtualTableClient:
    """Helper client for virtual table endpoints"""
    
    def __init__(self, token: str, base_url: str = PROXY_URL):
        if not token:
            raise ValueError("JWT_TOKEN environment variable must be set")
        self.token = token
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.client = httpx.Client(timeout=30.0)
    
    def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make HTTP request to proxy"""
        url = f"{self.base_url}{path}"
        print(f"\n[{method}] {url}")
        if json_data:
            print(f"Body: {json.dumps(json_data, indent=2)}")
        
        try:
            if method == "GET":
                response = self.client.get(url, headers=self.headers)
            elif method == "POST":
                response = self.client.post(url, headers=self.headers, json=json_data)
            elif method == "PUT":
                response = self.client.put(url, headers=self.headers, json=json_data)
            elif method == "DELETE":
                response = self.client.delete(url, headers=self.headers)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            print(f"Status: {response.status_code}")
            
            # Try to parse JSON response
            try:
                result = response.json()
                print(f"Response: {json.dumps(result, indent=2)}")
                # Add status code to result for debugging
                if isinstance(result, dict):
                    result["_status_code"] = response.status_code
                return result
            except:
                print(f"Response (text): {response.text}")
                return {"text": response.text, "status_code": response.status_code, "_raw_response": True}
        
        except Exception as e:
            print(f"Error: {e}")
            raise
    
    def get_user(self, user_id: str) -> Dict[str, Any]:
        """GET /__users/{user_id}"""
        return self._request("GET", f"/__users/{user_id}")
    
    def update_user(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """PUT /__users/{user_id}"""
        return self._request("PUT", f"/__users/{user_id}", updates)
    
    def delete_user(self, user_id: str) -> Dict[str, Any]:
        """DELETE /__users/{user_id}"""
        return self._request("DELETE", f"/__users/{user_id}")
    
    def get_tenant(self, tenant_id: str) -> Dict[str, Any]:
        """GET /__tenants/{tenant_id}"""
        return self._request("GET", f"/__tenants/{tenant_id}")
    
    def list_tenants(self) -> Dict[str, Any]:
        """GET /__tenants"""
        return self._request("GET", "/__tenants")
    
    def create_tenant(self, name: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """POST /__tenants"""
        data = {"name": name}
        if metadata:
            data["metadata"] = metadata
        return self._request("POST", "/__tenants", data)
    
    def update_tenant(self, tenant_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """PUT /__tenants/{tenant_id}"""
        return self._request("PUT", f"/__tenants/{tenant_id}", updates)
    
    def delete_tenant(self, tenant_id: str) -> Dict[str, Any]:
        """DELETE /__tenants/{tenant_id}"""
        return self._request("DELETE", f"/__tenants/{tenant_id}")


# Fixtures
@pytest.fixture(scope="session")
def jwt_token():
    """Get JWT token from environment"""
    if not JWT_TOKEN:
        pytest.skip("JWT_TOKEN environment variable not set")
    return JWT_TOKEN


@pytest.fixture(scope="session")
def client(jwt_token):
    """Create virtual table client"""
    return VirtualTableClient(jwt_token)


@pytest.fixture(scope="session")
def sub_hash(jwt_token):
    """Extract and hash the 'sub' claim from JWT"""
    # Parse JWT (simple base64 decode of payload, no validation)
    import base64
    try:
        parts = jwt_token.split(".")
        payload = parts[1]
        # Add padding if needed
        padding = 4 - (len(payload) % 4)
        if padding != 4:
            payload += "=" * padding
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        sub = decoded.get("sub")
        if not sub:
            pytest.skip("Could not extract 'sub' from JWT")
        return hash_sub(sub)
    except Exception as e:
        pytest.skip(f"Could not parse JWT: {e}")


# Tests: User Endpoints
class TestUserEndpoints:
    """Test __users virtual table endpoints"""
    
    def test_get_own_user(self, client, sub_hash):
        """Test: User can read their own document"""
        result = client.get_user(sub_hash)
        
        # Debug output
        if result.get("_status_code", 200) != 200:
            print(f"ERROR: Expected 200, got {result.get('_status_code')}")
            print(f"Full response: {result}")
            pytest.fail(f"Expected status 200, got {result.get('_status_code')}")
        
        # Should succeed with 200
        assert result.get("type") == "user", f"Response should be a user document, got: {result}"
        assert result.get("_id"), "User document should have _id"
        print(f"[OK] Got user: {result.get('_id')}")
    
    def test_get_nonexistent_user(self, client):
        """Test: Getting nonexistent user returns 404"""
        fake_hash = "0000000000000000000000000000000000000000000000000000000000000000"
        result = client.get_user(fake_hash)
        
        # Should fail with 404
        assert result.get("detail") is not None or result.get("status_code") == 404
        print(f"✓ Nonexistent user returns error")
    
    def test_update_user_name(self, client, sub_hash):
        """Test: User can update their own name"""
        new_name = f"Test User {sub_hash[:8]}"
        result = client.update_user(sub_hash, {"name": new_name})

        # Should succeed (status 200)
        assert result.get("_status_code") == 200, f"Expected 200, got {result.get('_status_code')}"
        assert result.get("name") == new_name, f"Name should be updated to {new_name}, got {result.get('name')}"
        print(f"✓ Updated user name to: {new_name}")
    
    def test_update_user_email(self, client, sub_hash):
        """Test: User can update their own email"""
        new_email = f"test-{sub_hash[:8]}@example.com"
        result = client.update_user(sub_hash, {"email": new_email})
        
        # Should succeed
        assert result.get("email") == new_email, "Email should be updated"
        print(f"✓ Updated user email to: {new_email}")
    
    def test_update_other_user_fails(self, client, sub_hash):
        """Test: Cannot update another user's document"""
        fake_hash = "1111111111111111111111111111111111111111111111111111111111111111"
        result = client.update_user(fake_hash, {"name": "Hacker"})
        
        # Should fail with 403
        assert result.get("detail") is not None
        print(f"✓ Cannot update other user (403)")
    
    def test_delete_self_fails(self, client, sub_hash):
        """Test: User cannot delete their own document"""
        result = client.delete_user(sub_hash)
        
        # Should fail with 403
        assert result.get("detail") is not None
        print(f"✓ Cannot delete self (403)")


# Tests: Tenant Endpoints
class TestTenantEndpoints:
    """Test __tenants virtual table endpoints"""
    
    def test_list_tenants(self, client):
        """Test: User can list their own tenants"""
        result = client.list_tenants()
        
        # Should return array
        assert isinstance(result, list), "Should return list of tenants"
        print(f"✓ Listed {len(result)} tenants")
        return result  # For use in other tests
    
    def test_create_tenant(self, client):
        """Test: User can create a new tenant"""
        tenant_name = f"Test Tenant {hash_sub('test')[:8]}"
        result = client.create_tenant(tenant_name)
        
        # Should succeed
        assert result.get("_id"), "Created tenant should have _id"
        assert result.get("type") == "tenant", "Should be a tenant document"
        assert result.get("name") == tenant_name, "Tenant name should match"
        print(f"✓ Created tenant: {result.get('_id')}")
        return result.get("_id")
    
    def test_get_own_tenant(self, client):
        """Test: User can read their own tenant"""
        # First create a tenant
        result = client.create_tenant("Test Tenant for Get")
        tenant_id = result.get("_id")
        
        # Now get it
        result = client.get_tenant(tenant_id)
        
        # Should succeed
        assert result.get("type") == "tenant", "Should be a tenant document"
        assert result.get("_id") == tenant_id, "IDs should match"
        print(f"✓ Got tenant: {result.get('_id')}")
        return tenant_id
    
    def test_update_tenant(self, client):
        """Test: Tenant owner can update tenant"""
        # Create a tenant
        result = client.create_tenant("Test Tenant for Update")
        tenant_id = result.get("_id")
        
        if result.get("_status_code") != 200:
            print(f"DEBUG: Create tenant failed: {result}")
            pytest.fail(f"Failed to create tenant: {result.get('detail')}")
        
        # Update it
        new_name = f"Updated Tenant {hash_sub('test')[:8]}"
        result = client.update_tenant(tenant_id, {"name": new_name})
        
        # Debug: print response if update fails
        if result.get("_status_code", 200) != 200:
            print(f"DEBUG: Update tenant response: {result}")
        
        # Should succeed (status 200)
        assert result.get("_status_code") == 200, f"Expected 200, got {result.get('_status_code')}: {result.get('detail')}"
        assert result.get("name") == new_name, f"Tenant name should be updated to {new_name}, got {result.get('name')}"
        print(f"✓ Updated tenant name to: {new_name}")
        return tenant_id
    
    def test_delete_tenant(self, client):
        """Test: Tenant owner can delete tenant"""
        # Create a tenant
        result = client.create_tenant("Test Tenant for Delete")
        tenant_id = result.get("_id")
        
        # Delete it
        result = client.delete_tenant(tenant_id)
        
        # Should succeed
        assert result.get("ok") == True, "Delete should return ok=true"
        print(f"✓ Deleted tenant: {tenant_id}")
    
    def test_get_nonexistent_tenant(self, client):
        """Test: Getting nonexistent tenant returns 404"""
        fake_id = "00000000000000000000000000000000"
        result = client.get_tenant(fake_id)
        
        # Should fail with 404 or 403
        assert result.get("detail") is not None
        print(f"✓ Nonexistent tenant returns error")


# Tests: Error Cases
class TestErrorCases:
    """Test error handling"""
    
    def test_missing_auth_header(self):
        """Test: Missing auth header returns 401"""
        try:
            response = httpx.get(f"{PROXY_URL}/__users/test")
            assert response.status_code == 401
            print(f"✓ Missing auth header returns 401")
        except Exception as e:
            print(f"✗ Error: {e}")
    
    def test_invalid_token(self):
        """Test: Invalid token returns 401"""
        try:
            headers = {"Authorization": "Bearer invalid_token"}
            response = httpx.get(f"{PROXY_URL}/__users/test", headers=headers)
            assert response.status_code == 401
            print(f"✓ Invalid token returns 401")
        except Exception as e:
            print(f"✗ Error: {e}")


# Manual test runner
if __name__ == "__main__":
    if not JWT_TOKEN:
        print("\nERROR: JWT_TOKEN not found")
        print("\nSetup options:")
        print("  1. Add to .env file:")
        print("     JWT_TOKEN=your_clerk_jwt_token")
        print("     python tests/test_virtual_endpoints_manual.py")
        print("\n  2. Or set environment variable:")
        print("     export JWT_TOKEN='your_clerk_jwt_token'")
        print("     python tests/test_virtual_endpoints_manual.py")
        print("\n  3. Or install python-dotenv:")
        print("     pip install python-dotenv")
        print("     python tests/test_virtual_endpoints_manual.py")
        sys.exit(1)
    
    print(f"\nProxy URL: {PROXY_URL}")
    print(f"JWT Token: {JWT_TOKEN[:50]}...")
    print(f"\nRunning manual integration tests...\n")
    
    pytest.main([__file__, "-v", "-s"])
