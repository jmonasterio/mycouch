"""
Virtual table handlers (sync-compatible).
Handles /__tenants and /__users endpoints.
"""
import logging
import hashlib
import uuid
from datetime import datetime
from typing import Dict, Any, Tuple, List, Optional

from .couch import couch_get, couch_put, couch_post

logger = logging.getLogger(__name__)


def hash_user_id(sub: str) -> str:
    """Hash a Clerk sub to get internal user ID format."""
    return hashlib.sha256(sub.encode('utf-8')).hexdigest()


# =============================================================================
# Tenant Handlers
# =============================================================================

def handle_create_tenant(user_id: str, data: Dict) -> Tuple[int, Dict]:
    """
    POST /__tenants - Create new tenant.

    Args:
        user_id: Clerk sub of requesting user
        data: Request body with name, applicationId, metadata

    Returns:
        (status_code, response_body)
    """
    tenant_id = str(uuid.uuid4())
    internal_id = f"tenant_{tenant_id}"
    now = datetime.utcnow().isoformat() + "Z"

    tenant_doc = {
        "_id": internal_id,
        "type": "tenant",
        "name": data.get("name", "Untitled Tenant"),
        "userId": user_id,
        "userIds": [user_id],
        "applicationId": data.get("applicationId", "roady"),
        "metadata": data.get("metadata", {}),
        "createdAt": now,
        "updatedAt": now
    }

    status, result = couch_put(f"/couch-sitter/{internal_id}", tenant_doc)
    if status in (200, 201):
        tenant_doc["_rev"] = result.get("rev")
        tenant_doc["_id"] = tenant_id  # Return virtual ID
        return 201, tenant_doc
    return status, result


def handle_list_tenants(user_id: str) -> Tuple[int, List]:
    """
    GET /__tenants - List tenants user is member of.

    Args:
        user_id: Clerk sub of requesting user

    Returns:
        (status_code, list_of_tenants)
    """
    query = {
        "selector": {
            "type": "tenant",
            "userIds": {"$elemMatch": {"$eq": user_id}},
            "deletedAt": {"$exists": False}
        },
        "limit": 100
    }

    status, result = couch_post("/couch-sitter/_find", query)
    if status != 200:
        return status, result

    docs = result.get("docs", [])
    # Filter soft-deleted and convert IDs
    filtered = []
    for doc in docs:
        if doc.get("deleted") or doc.get("deletedAt"):
            continue
        if doc.get("_id", "").startswith("tenant_"):
            doc["_id"] = doc["_id"][7:]  # Remove tenant_ prefix
        filtered.append(doc)

    return 200, filtered


def handle_get_tenant(tenant_id: str, user_id: str) -> Tuple[int, Dict]:
    """
    GET /__tenants/<id> - Get specific tenant.

    Args:
        tenant_id: Virtual tenant ID (without tenant_ prefix)
        user_id: Clerk sub of requesting user

    Returns:
        (status_code, tenant_doc)
    """
    internal_id = f"tenant_{tenant_id}"
    status, doc = couch_get(f"/couch-sitter/{internal_id}")

    if status != 200:
        return status, doc

    if doc.get("deleted") or doc.get("deletedAt"):
        return 404, {"error": "Tenant not found"}

    # Access control
    if user_id not in doc.get("userIds", []):
        return 403, {"error": "Not a member of this tenant"}

    doc["_id"] = tenant_id  # Return virtual ID
    return 200, doc


def handle_update_tenant(tenant_id: str, user_id: str, updates: Dict) -> Tuple[int, Dict]:
    """
    PUT /__tenants/<id> - Update tenant (owner only).

    Args:
        tenant_id: Virtual tenant ID
        user_id: Clerk sub of requesting user
        updates: Fields to update

    Returns:
        (status_code, updated_doc)
    """
    internal_id = f"tenant_{tenant_id}"
    status, current = couch_get(f"/couch-sitter/{internal_id}")

    if status != 200:
        return status, current

    # Only owner can update
    if current.get("userId") != user_id:
        return 403, {"error": "Only owner can update this tenant"}

    # Merge allowed fields only
    allowed = {"name", "metadata", "_rev"}
    now = datetime.utcnow().isoformat() + "Z"

    for key, value in updates.items():
        if key in allowed:
            current[key] = value

    current["updatedAt"] = now

    status, result = couch_put(f"/couch-sitter/{internal_id}", current)
    if status in (200, 201):
        current["_rev"] = result.get("rev")
        current["_id"] = tenant_id
        return 200, current
    return status, result


def handle_delete_tenant(tenant_id: str, user_id: str, active_tenant_id: Optional[str] = None) -> Tuple[int, Dict]:
    """
    DELETE /__tenants/<id> - Soft-delete tenant (owner only).

    Args:
        tenant_id: Virtual tenant ID
        user_id: Clerk sub of requesting user
        active_tenant_id: User's current active tenant (cannot delete active)

    Returns:
        (status_code, result)
    """
    internal_id = f"tenant_{tenant_id}"
    status, current = couch_get(f"/couch-sitter/{internal_id}")

    if status != 200:
        return status, current

    # Only owner can delete
    if current.get("userId") != user_id:
        return 403, {"error": "Only owner can delete this tenant"}

    # Cannot delete active tenant
    if active_tenant_id in (internal_id, tenant_id):
        return 403, {"error": "Cannot delete active tenant. Switch to another tenant first."}

    # Soft-delete
    now = datetime.utcnow().isoformat() + "Z"
    current["deletedAt"] = now
    current["updatedAt"] = now

    status, result = couch_put(f"/couch-sitter/{internal_id}", current)
    if status in (200, 201):
        return 200, {"ok": True, "_id": tenant_id, "_rev": result.get("rev")}
    return status, result


# =============================================================================
# User Handlers
# =============================================================================

def handle_get_user(user_hash: str, requesting_user_id: str) -> Tuple[int, Dict]:
    """
    GET /__users/<id> - Get user document.

    Args:
        user_hash: Hashed user ID from URL
        requesting_user_id: Clerk sub of requesting user

    Returns:
        (status_code, user_doc)
    """
    # Access control: can only read own doc
    if hash_user_id(requesting_user_id) != user_hash:
        return 403, {"error": "Cannot read other users' documents"}

    internal_id = f"user_{user_hash}"
    status, doc = couch_get(f"/couch-sitter/{internal_id}")

    if status != 200:
        return status, doc

    if doc.get("deleted"):
        return 404, {"error": "User not found"}

    return 200, doc


def handle_update_user(
    user_hash: str,
    requesting_user_id: str,
    updates: Dict
) -> Tuple[int, Dict]:
    """
    PUT /__users/<id> - Update or create user document (upsert).

    Args:
        user_hash: Hashed user ID from URL
        requesting_user_id: Clerk sub of requesting user
        updates: Fields to update

    Returns:
        (status_code, updated_doc)
    """
    # Access control
    if hash_user_id(requesting_user_id) != user_hash:
        return 403, {"error": "Cannot update other users' documents"}

    internal_id = f"user_{user_hash}"
    status, current = couch_get(f"/couch-sitter/{internal_id}")

    now = datetime.utcnow().isoformat() + "Z"

    if status == 404:
        # User doesn't exist - create new user doc
        current = {
            "_id": internal_id,
            "type": "user",
            "sub": requesting_user_id,
            "createdAt": now,
        }
        logger.info(f"Creating new user document: {internal_id}")
    elif status != 200:
        return status, current

    # Merge updates (only allowed fields)
    allowed = {"name", "email", "active_tenant_id", "_rev"}
    for key, value in updates.items():
        if key in allowed or key.startswith("_"):
            current[key] = value

    current["updatedAt"] = now

    return couch_put(f"/couch-sitter/{internal_id}", current)


def handle_delete_user(user_hash: str, requesting_user_id: str) -> Tuple[int, Dict]:
    """
    DELETE /__users/<id> - Soft-delete user (cannot delete self).

    Args:
        user_hash: Hashed user ID from URL
        requesting_user_id: Clerk sub of requesting user

    Returns:
        (status_code, result)
    """
    # Cannot delete self
    if hash_user_id(requesting_user_id) == user_hash:
        return 403, {"error": "Users cannot delete themselves"}

    internal_id = f"user_{user_hash}"
    status, current = couch_get(f"/couch-sitter/{internal_id}")

    if status != 200:
        return status, current

    # Soft-delete
    now = datetime.utcnow().isoformat() + "Z"
    current["deleted"] = True
    current["updatedAt"] = now

    status, result = couch_put(f"/couch-sitter/{internal_id}", current)
    if status in (200, 201):
        return 200, {"ok": True, "_id": user_hash, "_rev": result.get("rev")}
    return status, result
