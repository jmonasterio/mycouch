"""
API Routes for Tenant and Invitation Management

Provides endpoints for creating/managing workspaces and invitations.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional, Dict, Any, List
import logging
import httpx

from .auth_middleware import get_current_user

logger = logging.getLogger(__name__)


def create_tenant_router(couch_sitter_service, invite_service):
    """
    Create FastAPI router for tenant and invitation endpoints.

    Args:
        couch_sitter_service: CouchSitterService instance
        invite_service: InviteService instance

    Returns:
        APIRouter with all tenant/invitation endpoints
    """
    router = APIRouter(prefix="/api", tags=["tenants"])

    # ============ TENANT MANAGEMENT ============

    @router.post("/tenants")
    async def create_tenant(
        request_data: Dict[str, Any] = Body(...),
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        Create a new workspace tenant.

        Request:
            - name: Workspace name

        Returns:
            Created tenant document
        """
        try:
            name = request_data.get("name")
            if not name:
                raise HTTPException(status_code=400, detail="Tenant name is required")

            sub = current_user.get("sub")
            user_id = current_user.get("user_id")
            email = current_user.get("email")
            name_from_jwt = current_user.get("name")
            app_id = current_user.get("application_id", "roady")
            
            # CRITICAL: Ensure user exists before creating tenant
            # This creates the user document with correct ID format if it doesn't exist
            logger.info(f"Ensuring user exists for sub: {sub}")
            await couch_sitter_service.ensure_user_exists(
                sub=sub,
                email=email,
                name=name_from_jwt,
                requested_db_name=app_id
            )

            tenant = await couch_sitter_service.create_workspace_tenant(
                user_id=user_id,
                name=name,
                application_id=app_id
            )

            return {
                "tenantId": tenant.get("_id"),
                "_id": tenant.get("_id"),
                "type": tenant.get("type"),
                "name": tenant.get("name"),
                "applicationId": tenant.get("applicationId"),
                "userId": tenant.get("userId"),
                "userIds": tenant.get("userIds"),
                "createdAt": tenant.get("createdAt"),
                "metadata": tenant.get("metadata")
            }

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error creating tenant: {e}")
            raise HTTPException(status_code=500, detail="Failed to create tenant")

    @router.get("/my-tenants")
    async def list_user_tenants(
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        List all tenants the user has access to.

        Returns:
            List of tenants with user's role for each
        """
        try:
            user_id = current_user.get("user_id")
            tenant_id = current_user.get("tenant_id")
            sub = current_user.get("sub")

            # Get all tenants for user
            tenants_list, personal_tenant_id = await couch_sitter_service.get_user_tenants(sub)

            return {
                "tenants": tenants_list,
                "activeTenantId": tenant_id or personal_tenant_id
            }

        except Exception as e:
            logger.error(f"Error listing tenants: {e}")
            raise HTTPException(status_code=500, detail="Failed to list tenants")

    @router.put("/tenants/{tenant_id}")
    async def update_tenant(
        tenant_id: str,
        request_data: Dict[str, Any],
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        Update tenant (owner only).

        Request:
            - name: New tenant name

        Returns:
            Updated tenant
        """
        try:
            user_id = current_user.get("user_id")

            # Get tenant and check ownership
            tenant = await couch_sitter_service.get_tenant(tenant_id)
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant not found")

            if tenant.get("userId") != user_id:
                raise HTTPException(status_code=403, detail="Only owner can update tenant")

            # Update name
            if "name" in request_data:
                tenant["name"] = request_data["name"]

            from datetime import datetime, timezone
            tenant["updatedAt"] = datetime.now(timezone.utc).isoformat()

            response = await couch_sitter_service._make_request("PUT", tenant_id, json=tenant)
            updated = response.json()

            return {
                "_id": tenant.get("_id"),
                "name": tenant.get("name"),
                "updatedAt": tenant.get("updatedAt")
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating tenant: {e}")
            raise HTTPException(status_code=500, detail="Failed to update tenant")

    @router.delete("/tenants/{tenant_id}")
    async def delete_tenant(
        tenant_id: str,
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        Delete a tenant (owner only, cannot delete personal).

        Returns:
            204 No Content
        """
        try:
            user_id = current_user.get("user_id")

            # Get tenant
            tenant = await couch_sitter_service.get_tenant(tenant_id)
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant not found")

            # Check if personal
            if tenant.get("metadata", {}).get("autoCreated"):
                raise HTTPException(status_code=400, detail="Cannot delete personal tenant")

            # Check ownership
            if tenant.get("userId") != user_id:
                raise HTTPException(status_code=403, detail="Only owner can delete tenant")

            # Soft delete
            from datetime import datetime, timezone
            tenant["deletedAt"] = datetime.now(timezone.utc).isoformat()
            await couch_sitter_service._make_request("PUT", tenant_id, json=tenant)

            return {"status": "deleted"}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting tenant: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete tenant")

    # ============ INVITATION MANAGEMENT ============

    @router.post("/tenants/{tenant_id}/invitations")
    async def create_invitation(
        tenant_id: str,
        request_data: Dict[str, Any],
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        Create an invitation for a workspace tenant (owner/admin only).

        Request:
            - email: Email to invite
            - role: Role to assign (member, admin)

        Returns:
            Invitation with token and invite link
        """
        try:
            user_id = current_user.get("user_id")
            email = request_data.get("email", "")  # Email is optional
            role = request_data.get("role", "member")

            if role not in ["member", "admin", "editor", "viewer"]:
                raise HTTPException(status_code=400, detail="Invalid role")

            # Check tenant access and role
            logger.info(f"Looking up tenant: {tenant_id}")
            tenant = await couch_sitter_service.get_tenant(tenant_id)
            if not tenant:
                logger.error(f"Tenant not found: {tenant_id}")
                raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")

            # Cannot invite to personal tenants
            if tenant.get("metadata", {}).get("autoCreated"):
                raise HTTPException(status_code=400, detail="Cannot invite users to personal tenant")

            # Check if owner or admin
            user_role = await couch_sitter_service.get_user_role_for_tenant(user_id, tenant_id)

            if user_role not in ["owner", "admin"]:
                raise HTTPException(status_code=403, detail="Only owner/admin can create invitations")

            # Create invitation
            invitation = await invite_service.create_invitation(
                tenant_id=tenant_id,
                tenant_name=tenant.get("name"),
                email=email,
                role=role,
                created_by=user_id
            )

            return {
                "_id": invitation.get("_id"),
                "tenantId": invitation.get("tenantId"),
                "tenantName": invitation.get("tenantName"),
                "email": invitation.get("email"),
                "role": invitation.get("role"),
                "status": invitation.get("status"),
                "token": invitation.get("token"),
                "inviteLink": f"https://app.example.com/join?invite={invitation.get('token')}",
                "expiresAt": invitation.get("expiresAt"),
                "createdAt": invitation.get("createdAt")
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating invitation: {e}")
            raise HTTPException(status_code=500, detail="Failed to create invitation")

    @router.get("/tenants/{tenant_id}/invitations")
    async def list_invitations(
        tenant_id: str,
        status: Optional[str] = Query(None),
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        List invitations for a tenant (owner/admin only).

        Query:
            - status: Filter by pending/accepted/revoked

        Returns:
            List of invitations
        """
        try:
            user_id = current_user.get("user_id")

            # Check access
            tenant = await couch_sitter_service.get_tenant(tenant_id)
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant not found")

            user_role = await couch_sitter_service.get_user_role_for_tenant(user_id, tenant_id)

            if user_role not in ["owner", "admin"]:
                raise HTTPException(status_code=403, detail="Only owner/admin can list invitations")

            # Get invitations
            invitations = await invite_service.get_invitations_for_tenant(tenant_id, status)

            return [
                {
                    "_id": inv.get("_id"),
                    "email": inv.get("email"),
                    "role": inv.get("role"),
                    "status": inv.get("status"),
                    "createdAt": inv.get("createdAt"),
                    "expiresAt": inv.get("expiresAt")
                }
                for inv in invitations
            ]

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error listing invitations: {e}")
            raise HTTPException(status_code=500, detail="Failed to list invitations")

    @router.get("/invitations/preview")
    async def preview_invitation(token: str = Query(...)):
        """
        Preview an invitation (no auth required).

        Query:
            - token: Invitation token

        Returns:
            Invitation preview
        """
        try:
            invitation = await invite_service.validate_token(token)
            if not invitation:
                raise HTTPException(status_code=400, detail="Invalid or expired invitation")

            return {
                "tenantName": invitation.get("tenantName"),
                "role": invitation.get("role"),
                "isValid": True,
                "expiresAt": invitation.get("expiresAt")
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error previewing invitation: {e}")
            raise HTTPException(status_code=500, detail="Failed to preview invitation")

    @router.patch("/invitations/accept")
    async def accept_invitation(
        request_data: Dict[str, Any] = Body(...),
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        Accept an invitation and add user to tenant.

        Request:
            - inviteToken: Invitation token

        Returns:
            Success with tenant info

        Errors:
            - 404: Invalid or revoked token
            - 410: Expired token
            - 409: User already a member
        """
        try:
            invite_token = request_data.get("inviteToken")
            if not invite_token:
                raise HTTPException(status_code=400, detail="inviteToken is required")

            # Validate token
            invitation = await invite_service.validate_token(invite_token)
            if not invitation:
                # Check if expired to return correct status code
                # We need to find the invitation by token to check status
                # For now, return 404 for invalid/revoked
                raise HTTPException(status_code=404, detail="This invitation is no longer valid or has expired")

            user_id = current_user.get("user_id")
            tenant_id = invitation.get("tenantId")
            role = invitation.get("role", "editor")

            # Check if user is already a member
            existing_tenants = await couch_sitter_service.get_user_tenants(current_user.get("sub"))
            existing_tenant_ids = [t[0].get("_id") for t in existing_tenants[0]]
            
            if tenant_id in existing_tenant_ids:
                raise HTTPException(status_code=409, detail="You already belong to this band")

            # Add user to tenant
            await couch_sitter_service.add_user_to_tenant(tenant_id, user_id, role)

            # Mark invitation as accepted
            await invite_service.accept_invitation(invitation, user_id)

            # Get tenant for response
            tenant = await couch_sitter_service.get_tenant(tenant_id)

            logger.info(f"User {user_id} accepted invitation to tenant {tenant_id}")

            return {
                "success": True,
                "tenantId": tenant_id,
                "tenantName": tenant.get("name"),
                "role": role
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error accepting invitation: {e}")
            raise HTTPException(status_code=500, detail="Failed to accept invitation")

    @router.delete("/tenants/{tenant_id}/invitations/{invite_id}")
    async def revoke_invitation(
        tenant_id: str,
        invite_id: str,
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        Revoke a pending invitation (owner/admin only).

        Returns:
            204 No Content
        """
        try:
            user_id = current_user.get("user_id")

            # Check access
            user_role = await couch_sitter_service.get_user_role_for_tenant(user_id, tenant_id)

            if user_role not in ["owner", "admin"]:
                raise HTTPException(status_code=403, detail="Only owner/admin can revoke invitations")

            # Revoke invitation
            await invite_service.revoke_invitation(invite_id)

            return {"status": "revoked"}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error revoking invitation: {e}")
            raise HTTPException(status_code=500, detail="Failed to revoke invitation")

    @router.post("/tenants/{tenant_id}/invitations/{invite_id}/resend")
    async def resend_invitation(
        tenant_id: str,
        invite_id: str,
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        Resend an invitation (owner/admin only).

        Returns:
            Updated invitation with new token
        """
        try:
            user_id = current_user.get("user_id")

            # Check access
            user_role = await couch_sitter_service.get_user_role_for_tenant(user_id, tenant_id)

            if user_role not in ["owner", "admin"]:
                raise HTTPException(status_code=403, detail="Only owner/admin can resend invitations")

            # Get invitation
            invitation = await invite_service.get_invitation_by_id(invite_id)
            if not invitation:
                raise HTTPException(status_code=404, detail="Invitation not found")

            # Generate new token
            new_token = invite_service.generate_token()
            new_hash = invite_service.hash_token(new_token)

            from datetime import datetime, timezone, timedelta
            expiration_days = 7
            expires_at = (datetime.now(timezone.utc) + timedelta(days=expiration_days)).isoformat()

            invitation["token"] = new_token
            invitation["tokenHash"] = new_hash
            invitation["expiresAt"] = expires_at

            await couch_sitter_service._make_request("PUT", invite_id, json=invitation)

            return {
                "_id": invitation.get("_id"),
                "email": invitation.get("email"),
                "status": invitation.get("status"),
                "token": new_token,
                "inviteLink": f"https://app.example.com/join?invite={new_token}",
                "expiresAt": expires_at
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error resending invitation: {e}")
            raise HTTPException(status_code=500, detail="Failed to resend invitation")

    # ============ MEMBER MANAGEMENT ============

    @router.put("/tenants/{tenant_id}/members/{member_user_id}/role")
    async def change_member_role(
        tenant_id: str,
        member_user_id: str,
        request_data: Dict[str, Any],
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        Change a member's role (owner only).

        Request:
            - role: New role (admin, member)

        Returns:
            Updated mapping
        """
        try:
            user_id = current_user.get("user_id")
            new_role = request_data.get("role")

            if new_role not in ["admin", "member"]:
                raise HTTPException(status_code=400, detail="Invalid role")

            # Check ownership
            tenant = await couch_sitter_service.get_tenant(tenant_id)
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant not found")

            if tenant.get("userId") != user_id:
                raise HTTPException(status_code=403, detail="Only owner can change member roles")

            # Cannot change owner role
            if member_user_id == tenant.get("userId"):
                raise HTTPException(status_code=400, detail="Cannot change owner role")

            # Update user's tenants array with new role
            response = await couch_sitter_service._make_request("GET", member_user_id)
            user_doc = response.json()
            
            tenants = user_doc.get("tenants", [])
            tenant_entry = next((t for t in tenants if t.get("tenantId") == tenant_id), None)
            if not tenant_entry:
                raise HTTPException(status_code=404, detail="Member not found")

            tenant_entry["role"] = new_role
            from datetime import datetime, timezone
            tenant_entry["updatedAt"] = datetime.now(timezone.utc).isoformat()
            
            user_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
            await couch_sitter_service._make_request("PUT", member_user_id, json=user_doc)

            return {
                "userId": member_user_id,
                "role": new_role,
                "updatedAt": mapping.get("updatedAt")
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error changing member role: {e}")
            raise HTTPException(status_code=500, detail="Failed to change member role")

    @router.delete("/tenants/{tenant_id}/members/{member_user_id}")
    async def remove_member(
        tenant_id: str,
        member_user_id: str,
        current_user: Dict[str, Any] = Depends(get_current_user)
    ):
        """
        Remove a member from tenant (owner/admin only).

        Returns:
            Success with removed status
        """
        try:
            user_id = current_user.get("user_id")
            from datetime import datetime, timezone

            # Check access
            tenant = await couch_sitter_service.get_tenant(tenant_id)
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant not found")

            user_role = await couch_sitter_service.get_user_role_for_tenant(user_id, tenant_id)

            if user_role not in ["owner", "admin"]:
                raise HTTPException(status_code=403, detail="Only owner/admin can remove members")

            # Cannot remove owner
            if member_user_id == tenant.get("userId"):
                raise HTTPException(status_code=400, detail="Cannot remove owner from tenant")

            # 1. Remove from tenant's userIds
            tenant["userIds"] = [uid for uid in tenant.get("userIds", []) if uid != member_user_id]
            tenant["updatedAt"] = datetime.now(timezone.utc).isoformat()
            await couch_sitter_service._make_request("PUT", tenant_id, json=tenant)

            # 2. Remove tenant from user's tenants array
            try:
                response = await couch_sitter_service._make_request("GET", member_user_id)
                member_user_doc = response.json()
                
                member_user_doc["tenants"] = [
                    t for t in member_user_doc.get("tenants", [])
                    if t.get("tenantId") != tenant_id
                ]
                member_user_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
                await couch_sitter_service._make_request("PUT", member_user_id, json=member_user_doc)
                logger.info(f"Removed tenant {tenant_id} from user {member_user_id}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.warning(f"User {member_user_id} not found when removing from tenant")
                else:
                    logger.error(f"Failed to update user {member_user_id}: {e}")
                    raise

            logger.info(f"Removed member {member_user_id} from tenant {tenant_id}")
            return {"status": "removed"}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error removing member: {e}")
            raise HTTPException(status_code=500, detail="Failed to remove member")

    return router
