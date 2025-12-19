"""FastAPI router for multi-tenant organization management.

Endpoints:
    POST   /v1/orgs                    - Create organization
    GET    /v1/orgs                    - List user's organizations
    GET    /v1/orgs/{org_id}           - Get organization details
    PATCH  /v1/orgs/{org_id}           - Update organization
    DELETE /v1/orgs/{org_id}           - Delete organization (soft)

    GET    /v1/orgs/{org_id}/members   - List members
    POST   /v1/orgs/{org_id}/members   - Add member
    PATCH  /v1/orgs/{org_id}/members/{user_id} - Update member role
    DELETE /v1/orgs/{org_id}/members/{user_id} - Remove member

    GET    /v1/orgs/{org_id}/projects  - List projects
    POST   /v1/orgs/{org_id}/projects  - Create project
    GET    /v1/orgs/{org_id}/projects/{project_id} - Get project
    PATCH  /v1/orgs/{org_id}/projects/{project_id} - Update project
    DELETE /v1/orgs/{org_id}/projects/{project_id} - Delete project (soft)

    GET    /v1/orgs/{org_id}/agents    - List agents
    POST   /v1/orgs/{org_id}/agents    - Create agent
    GET    /v1/orgs/{org_id}/agents/{agent_id} - Get agent
    PATCH  /v1/orgs/{org_id}/agents/{agent_id} - Update agent config
    DELETE /v1/orgs/{org_id}/agents/{agent_id} - Delete agent (soft)
    PUT    /v1/orgs/{org_id}/agents/{agent_id}/status - Update agent status
    POST   /v1/orgs/{org_id}/agents/{agent_id}/pause - Pause agent
    POST   /v1/orgs/{org_id}/agents/{agent_id}/activate - Activate agent
    POST   /v1/orgs/{org_id}/agents/{agent_id}/disable - Disable agent
    GET    /v1/orgs/{org_id}/agents/{agent_id}/status/history - Status history

    GET    /v1/orgs/{org_id}/invitations - List invitations
    POST   /v1/orgs/{org_id}/invitations - Create and send invitation
    GET    /v1/orgs/{org_id}/invitations/{invitation_id} - Get invitation
    DELETE /v1/orgs/{org_id}/invitations/{invitation_id} - Revoke invitation
    POST   /v1/orgs/{org_id}/invitations/{invitation_id}/resend - Resend invitation

    POST   /v1/orgs/{org_id}/usage     - Record usage
    GET    /v1/orgs/{org_id}/usage     - Get usage summary
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from pydantic import BaseModel, Field

from .context import TenantContext, get_current_org_id
from .organization_service import OrganizationService
from .invitation_service import InvitationService
from .contracts import (
    Organization,
    CreateOrgRequest,
    UpdateOrgRequest,
    OrgMembership,
    CreateMembershipRequest,
    UpdateMembershipRequest,
    Project,
    CreateProjectRequest,
    UpdateProjectRequest,
    Agent,
    CreateAgentRequest,
    UpdateAgentRequest,
    OrgWithMembers,
    OrgContext,
    MemberRole,
    RecordUsageRequest,
    # Agent status tracking
    AgentStatus,
    AgentStatusChangeRequest,
    AgentStatusEvent,
    AgentStatusHistory,
    # Invitations
    Invitation,
    CreateInvitationRequest,
    InvitationListResponse,
    InvitationStatus,
    # Pagination
    PageInfo,
)


# =============================================================================
# Response Models
# =============================================================================

class OrgListResponse(BaseModel):
    """Response for listing organizations."""
    organizations: List[OrgWithMembers]
    total: int
    page_info: Optional[PageInfo] = None


class MemberListResponse(BaseModel):
    """Response for listing members."""
    members: List[OrgMembership]
    total: int
    page_info: Optional[PageInfo] = None


class ProjectListResponse(BaseModel):
    """Response for listing projects."""
    projects: List[Project]
    total: int
    page_info: Optional[PageInfo] = None


class AgentListResponse(BaseModel):
    """Response for listing agents."""
    agents: List[Agent]
    total: int
    page_info: Optional[PageInfo] = None


class AgentStatusChangeResponse(BaseModel):
    """Response for agent status change operations."""
    success: bool
    agent_id: str
    from_status: str
    to_status: str
    event_id: str
    message: str


class UsageSummaryResponse(BaseModel):
    """Response for usage summary."""
    org_id: str
    metric_name: str
    total: int
    start_date: datetime
    end_date: datetime


class ContextResponse(BaseModel):
    """Response for current org context."""
    context: Optional[OrgContext]


# =============================================================================
# Router Factory
# =============================================================================

def create_org_routes(
    org_service: OrganizationService,
    invitation_service: Optional[InvitationService] = None,
    get_user_id: Optional[callable] = None,
    tags: List[str] = None,
) -> APIRouter:
    """Create FastAPI router for organization management.

    Args:
        org_service: OrganizationService instance.
        invitation_service: Optional InvitationService instance for invitation endpoints.
        get_user_id: Optional callable to extract user_id from request.
                     If None, falls back to request.state.user_id.
        tags: Optional tags for OpenAPI documentation.

    Returns:
        FastAPI APIRouter with all org endpoints.
    """
    router = APIRouter(prefix="/v1/orgs", tags=tags or ["organizations"])

    def _get_user_id(request: Request) -> str:
        """Extract user_id from request state or raise 401."""
        if get_user_id:
            return get_user_id(request)

        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        return user_id

    async def _require_permission(
        request: Request,
        org_id: str,
        permission_name: str,
        fallback_role: MemberRole = MemberRole.VIEWER,
    ) -> OrgContext:
        """Require a specific permission in an organization.

        Uses AsyncPermissionService if available, otherwise falls back to role check.

        Args:
            request: FastAPI request.
            org_id: Organization ID.
            permission_name: OrgPermission name (e.g., "VIEW_MEMBERS").
            fallback_role: Role to require if permission service unavailable.

        Returns:
            OrgContext if authorized.

        Raises:
            HTTPException: If not authorized.
        """
        user_id = _get_user_id(request)

        # Try AsyncPermissionService first
        perm_service = getattr(request.app.state, "async_permission_service", None)
        if perm_service:
            from guideai.multi_tenant.permissions import OrgPermission, NotAMember, PermissionDenied
            try:
                permission = OrgPermission[permission_name]
                ctx = await perm_service.require_org_permission(user_id, org_id, permission)
                return OrgContext(
                    org_id=org_id,
                    user_id=user_id,
                    role=ctx.role,
                )
            except NotAMember:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization not found or access denied",
                )
            except PermissionDenied as e:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(e),
                )
            except KeyError:
                # Unknown permission, fall through to role check
                pass

        # Fallback to role-based check
        return _require_member(request, org_id, fallback_role)

    def _require_member(
        request: Request,
        org_id: str,
        min_role: MemberRole = MemberRole.VIEWER,
    ) -> OrgContext:
        """Verify user is a member of the org with minimum role.

        Args:
            request: FastAPI request.
            org_id: Organization ID.
            min_role: Minimum required role.

        Returns:
            OrgContext if authorized.

        Raises:
            HTTPException: If not authorized.
        """
        # This would be async in production; simplified for sync compatibility
        user_id = _get_user_id(request)

        # Role hierarchy for comparison
        role_hierarchy = {
            MemberRole.VIEWER: 0,
            MemberRole.MEMBER: 1,
            MemberRole.ADMIN: 2,
            MemberRole.OWNER: 3,
        }

        # Check membership via request state (set by TenantMiddleware)
        ctx = getattr(request.state, "org_context", None)
        if ctx and ctx.org_id == org_id:
            if role_hierarchy.get(ctx.role, 0) >= role_hierarchy.get(min_role, 0):
                return ctx

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires {min_role.value} role or higher in organization",
        )

    # =========================================================================
    # Organization CRUD
    # =========================================================================

    @router.post("", response_model=Organization, status_code=status.HTTP_201_CREATED)
    async def create_organization(
        request: Request,
        body: CreateOrgRequest,
    ) -> Organization:
        """Create a new organization.

        The authenticated user becomes the owner.
        """
        user_id = _get_user_id(request)

        try:
            return org_service.create_organization(body, owner_id=user_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    @router.get("", response_model=OrgListResponse)
    async def list_organizations(
        request: Request,
        include_deleted: bool = Query(False, description="Include deleted organizations"),
        limit: int = Query(100, ge=1, le=1000, description="Maximum items to return"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
    ) -> OrgListResponse:
        """List all organizations the authenticated user belongs to.

        Supports pagination via limit/offset for large organization lists.
        """
        user_id = _get_user_id(request)

        orgs = org_service.list_user_organizations(
            user_id=user_id,
            include_deleted=include_deleted,
        )

        total = len(orgs)
        paginated = orgs[offset:offset + limit]

        return OrgListResponse(
            organizations=paginated,
            total=total,
            page_info=PageInfo(
                total=total,
                limit=limit,
                offset=offset,
                has_more=offset + limit < total,
            ),
        )

    @router.get("/context", response_model=ContextResponse)
    async def get_current_context(request: Request) -> ContextResponse:
        """Get the current organization context for the request.

        Returns the org context set by TenantMiddleware, if any.
        """
        ctx = getattr(request.state, "org_context", None)
        return ContextResponse(context=ctx)

    @router.get("/{org_id}", response_model=Organization)
    async def get_organization(
        request: Request,
        org_id: str,
    ) -> Organization:
        """Get organization details.

        Requires viewer role or higher.
        """
        _require_member(request, org_id, MemberRole.VIEWER)

        org = org_service.get_organization(org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} not found",
            )
        return org

    @router.patch("/{org_id}", response_model=Organization)
    async def update_organization(
        request: Request,
        org_id: str,
        body: UpdateOrgRequest,
    ) -> Organization:
        """Update organization details.

        Requires admin role or higher.
        """
        _require_member(request, org_id, MemberRole.ADMIN)

        org = org_service.update_organization(org_id, body)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} not found",
            )
        return org

    @router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_organization(
        request: Request,
        org_id: str,
    ) -> None:
        """Soft-delete an organization.

        Requires owner role.
        """
        _require_member(request, org_id, MemberRole.OWNER)

        deleted = org_service.delete_organization(org_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} not found",
            )

    # =========================================================================
    # Membership Management
    # =========================================================================

    @router.get("/{org_id}/members", response_model=MemberListResponse)
    async def list_members(
        request: Request,
        org_id: str,
        limit: int = Query(100, ge=1, le=1000, description="Maximum items to return"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
    ) -> MemberListResponse:
        """List all members of an organization.

        Requires viewer role or higher. Supports pagination via limit/offset.
        """
        _require_member(request, org_id, MemberRole.VIEWER)

        members = org_service.list_members(org_id)
        total = len(members)
        paginated = members[offset:offset + limit]

        return MemberListResponse(
            members=paginated,
            total=total,
            page_info=PageInfo(
                total=total,
                limit=limit,
                offset=offset,
                has_more=offset + limit < total,
            ),
        )

    @router.post("/{org_id}/members", response_model=OrgMembership, status_code=status.HTTP_201_CREATED)
    async def add_member(
        request: Request,
        org_id: str,
        body: CreateMembershipRequest,
    ) -> OrgMembership:
        """Add a member to an organization.

        Requires admin role or higher.
        """
        ctx = _require_member(request, org_id, MemberRole.ADMIN)

        try:
            return org_service.add_member(
                org_id=org_id,
                request=body,
                invited_by=ctx.user_id,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    @router.patch("/{org_id}/members/{user_id}", response_model=OrgMembership)
    async def update_member(
        request: Request,
        org_id: str,
        user_id: str,
        body: UpdateMembershipRequest,
    ) -> OrgMembership:
        """Update a member's role.

        Requires admin role or higher.
        Only owners can promote to owner role.
        """
        ctx = _require_member(request, org_id, MemberRole.ADMIN)

        # Only owners can promote to owner
        if body.role == MemberRole.OWNER and ctx.role != MemberRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owners can promote members to owner role",
            )

        membership = org_service.update_member_role(org_id, user_id, body)
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Member {user_id} not found in organization",
            )
        return membership

    @router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_member(
        request: Request,
        org_id: str,
        user_id: str,
    ) -> None:
        """Remove a member from an organization.

        Requires admin role or higher.
        Cannot remove the last owner.
        """
        _require_member(request, org_id, MemberRole.ADMIN)

        try:
            removed = org_service.remove_member(org_id, user_id)
            if not removed:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Member {user_id} not found in organization",
                )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # =========================================================================
    # Project Management
    # =========================================================================

    @router.get("/{org_id}/projects", response_model=ProjectListResponse)
    async def list_projects(
        request: Request,
        org_id: str,
        limit: int = Query(100, ge=1, le=1000, description="Maximum items to return"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
    ) -> ProjectListResponse:
        """List all projects in an organization.

        Requires member role or higher. Supports pagination via limit/offset.
        """
        _require_member(request, org_id, MemberRole.MEMBER)

        projects = org_service.list_projects(org_id)
        total = len(projects)
        paginated = projects[offset:offset + limit]

        return ProjectListResponse(
            projects=paginated,
            total=total,
            page_info=PageInfo(
                total=total,
                limit=limit,
                offset=offset,
                has_more=offset + limit < total,
            ),
        )

    @router.post("/{org_id}/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
    async def create_project(
        request: Request,
        org_id: str,
        body: CreateProjectRequest,
    ) -> Project:
        """Create a new project in an organization.

        Requires member role or higher. Creator becomes project owner.
        """
        ctx = _require_member(request, org_id, MemberRole.MEMBER)

        try:
            return org_service.create_project(
                org_id=org_id,
                request=body,
                owner_id=ctx.user_id,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    @router.get("/{org_id}/projects/{project_id}", response_model=Project)
    async def get_project(
        request: Request,
        org_id: str,
        project_id: str,
    ) -> Project:
        """Get a project by ID.

        Requires member role or higher.
        """
        _require_member(request, org_id, MemberRole.MEMBER)

        project = org_service.get_project(project_id, org_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return project

    @router.patch("/{org_id}/projects/{project_id}", response_model=Project)
    async def update_project(
        request: Request,
        org_id: str,
        project_id: str,
        body: UpdateProjectRequest,
    ) -> Project:
        """Update a project.

        Requires admin role or higher.
        """
        _require_member(request, org_id, MemberRole.ADMIN)

        try:
            project = org_service.update_project(
                project_id=project_id,
                request=body,
                org_id=org_id,
            )
            if not project:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Project {project_id} not found",
                )
            return project
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    @router.delete("/{org_id}/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_project(
        request: Request,
        org_id: str,
        project_id: str,
    ) -> None:
        """Delete (archive) a project.

        Requires admin role or higher. This is a soft-delete operation.
        Agents assigned to the project are unassigned but not deleted.
        """
        _require_member(request, org_id, MemberRole.ADMIN)

        deleted = org_service.delete_project(project_id, org_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )

    # =========================================================================
    # Agent Management
    # =========================================================================

    @router.get("/{org_id}/agents", response_model=AgentListResponse)
    async def list_agents(
        request: Request,
        org_id: str,
        project_id: Optional[str] = Query(None, description="Filter by project ID"),
        limit: int = Query(100, ge=1, le=1000, description="Maximum items to return"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
    ) -> AgentListResponse:
        """List all agents in an organization.

        Requires member role or higher. Supports pagination via limit/offset.
        """
        _require_member(request, org_id, MemberRole.MEMBER)

        agents = org_service.list_agents(org_id, project_id=project_id)
        total = len(agents)
        paginated = agents[offset:offset + limit]

        return AgentListResponse(
            agents=paginated,
            total=total,
            page_info=PageInfo(
                total=total,
                limit=limit,
                offset=offset,
                has_more=offset + limit < total,
            ),
        )

    @router.post("/{org_id}/agents", response_model=Agent, status_code=status.HTTP_201_CREATED)
    async def create_agent(
        request: Request,
        org_id: str,
        body: CreateAgentRequest,
    ) -> Agent:
        """Create a new agent in an organization.

        Requires admin role or higher.
        """
        _require_member(request, org_id, MemberRole.ADMIN)

        return org_service.create_agent(org_id=org_id, request=body)

    # =========================================================================
    # Agent Status Management
    # =========================================================================

    @router.get("/{org_id}/agents/{agent_id}", response_model=Agent)
    async def get_agent(
        request: Request,
        org_id: str,
        agent_id: str,
    ) -> Agent:
        """Get an agent by ID.

        Requires member role or higher.
        """
        _require_member(request, org_id, MemberRole.MEMBER)

        agent = org_service.get_agent(agent_id=agent_id, org_id=org_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found"
            )
        return agent

    @router.patch("/{org_id}/agents/{agent_id}", response_model=Agent)
    async def update_agent(
        request: Request,
        org_id: str,
        agent_id: str,
        body: UpdateAgentRequest,
    ) -> Agent:
        """Update an agent's configuration.

        Can update name, config, capabilities. Use the status endpoint
        for status changes.

        Requires admin role or higher.
        """
        _require_member(request, org_id, MemberRole.ADMIN)

        try:
            agent = org_service.update_agent(
                agent_id=agent_id,
                request=body,
                org_id=org_id,
            )
            if not agent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent {agent_id} not found",
                )
            return agent
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    @router.delete("/{org_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_agent(
        request: Request,
        org_id: str,
        agent_id: str,
    ) -> None:
        """Delete (archive) an agent.

        This is a soft-delete operation that sets the agent status to 'archived'.

        Requires admin role or higher.
        """
        _require_member(request, org_id, MemberRole.ADMIN)

        deleted = org_service.delete_agent(agent_id, org_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found",
            )

    @router.put(
        "/{org_id}/agents/{agent_id}/status",
        response_model=AgentStatusChangeResponse,
    )
    async def update_agent_status(
        request: Request,
        org_id: str,
        agent_id: str,
        body: AgentStatusChangeRequest,
    ) -> AgentStatusChangeResponse:
        """Update an agent's status.

        Validates the transition and records it in the audit trail.
        Requires admin role or higher.

        Valid transitions:
        - ACTIVE → BUSY, PAUSED, DISABLED, ARCHIVED
        - BUSY → IDLE, ACTIVE, PAUSED
        - IDLE → BUSY, ACTIVE, PAUSED, DISABLED
        - PAUSED → ACTIVE, IDLE, DISABLED, ARCHIVED
        - DISABLED → ACTIVE, IDLE, ARCHIVED
        - ARCHIVED → (none - terminal state)
        """
        user_id = _require_member(request, org_id, MemberRole.ADMIN)

        try:
            event = org_service.update_agent_status(
                agent_id=agent_id,
                org_id=org_id,
                new_status=body.status,
                triggered_by=user_id,
                trigger=body.trigger,
                reason=body.reason,
                task_id=body.task_id,
                metadata=body.metadata,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found"
            )

        return AgentStatusChangeResponse(
            success=True,
            agent_id=agent_id,
            from_status=event.from_status.value,
            to_status=event.to_status.value,
            event_id=event.id,
            message=f"Agent status changed from {event.from_status.value} to {event.to_status.value}",
        )

    @router.post(
        "/{org_id}/agents/{agent_id}/pause",
        response_model=AgentStatusChangeResponse,
    )
    async def pause_agent(
        request: Request,
        org_id: str,
        agent_id: str,
        reason: Optional[str] = Query(None, description="Reason for pausing"),
    ) -> AgentStatusChangeResponse:
        """Pause an agent.

        Convenience endpoint for pausing an agent without specifying
        full status change details. Requires admin role or higher.
        """
        user_id = _require_member(request, org_id, MemberRole.ADMIN)

        try:
            event = org_service.pause_agent(
                agent_id=agent_id,
                org_id=org_id,
                triggered_by=user_id,
                reason=reason,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found"
            )

        return AgentStatusChangeResponse(
            success=True,
            agent_id=agent_id,
            from_status=event.from_status.value,
            to_status=event.to_status.value,
            event_id=event.id,
            message="Agent paused",
        )

    @router.post(
        "/{org_id}/agents/{agent_id}/activate",
        response_model=AgentStatusChangeResponse,
    )
    async def activate_agent(
        request: Request,
        org_id: str,
        agent_id: str,
        reason: Optional[str] = Query(None, description="Reason for activating"),
    ) -> AgentStatusChangeResponse:
        """Activate an agent.

        Convenience endpoint for activating an agent without specifying
        full status change details. Requires admin role or higher.
        """
        user_id = _require_member(request, org_id, MemberRole.ADMIN)

        try:
            event = org_service.activate_agent(
                agent_id=agent_id,
                org_id=org_id,
                triggered_by=user_id,
                reason=reason,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found"
            )

        return AgentStatusChangeResponse(
            success=True,
            agent_id=agent_id,
            from_status=event.from_status.value,
            to_status=event.to_status.value,
            event_id=event.id,
            message="Agent activated",
        )

    @router.post(
        "/{org_id}/agents/{agent_id}/disable",
        response_model=AgentStatusChangeResponse,
    )
    async def disable_agent(
        request: Request,
        org_id: str,
        agent_id: str,
        reason: Optional[str] = Query(None, description="Reason for disabling"),
    ) -> AgentStatusChangeResponse:
        """Disable an agent.

        Convenience endpoint for disabling an agent without specifying
        full status change details. Requires admin role or higher.
        """
        user_id = _require_member(request, org_id, MemberRole.ADMIN)

        try:
            event = await org_service.disable_agent(
                agent_id=agent_id,
                org_id=org_id,
                triggered_by=user_id,
                reason=reason,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found"
            )

        return AgentStatusChangeResponse(
            success=True,
            agent_id=agent_id,
            from_status=event.from_status.value,
            to_status=event.to_status.value,
            event_id=event.id,
            message="Agent disabled",
        )

    @router.get(
        "/{org_id}/agents/{agent_id}/status/history",
        response_model=AgentStatusHistory,
    )
    async def get_agent_status_history(
        request: Request,
        org_id: str,
        agent_id: str,
        limit: int = Query(50, ge=1, le=100, description="Maximum events to return"),
        offset: int = Query(0, ge=0, description="Events to skip"),
    ) -> AgentStatusHistory:
        """Get agent status change history.

        Returns a paginated list of status change events for the agent,
        ordered by most recent first. Requires member role or higher.
        """
        _require_member(request, org_id, MemberRole.MEMBER)

        history = await org_service.get_agent_status_history(
            agent_id=agent_id,
            org_id=org_id,
            limit=limit,
            offset=offset,
        )

        if not history:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found"
            )

        return history

    # =========================================================================
    # Usage Tracking
    # =========================================================================

    @router.post("/{org_id}/usage", status_code=status.HTTP_201_CREATED)
    async def record_usage(
        request: Request,
        org_id: str,
        body: RecordUsageRequest,
    ) -> Dict[str, str]:
        """Record usage for metered billing.

        Requires member role or higher.
        """
        _require_member(request, org_id, MemberRole.MEMBER)

        record = await org_service.record_usage(org_id=org_id, request=body)
        return {"id": record.id, "status": "recorded"}

    @router.get("/{org_id}/usage", response_model=UsageSummaryResponse)
    async def get_usage_summary(
        request: Request,
        org_id: str,
        metric_name: str = Query(..., description="Name of the metric"),
        start_date: datetime = Query(..., description="Start of period"),
        end_date: Optional[datetime] = Query(None, description="End of period (defaults to now)"),
    ) -> UsageSummaryResponse:
        """Get usage summary for a metric.

        Requires viewer role or higher.
        """
        _require_member(request, org_id, MemberRole.VIEWER)

        end = end_date or datetime.utcnow()
        total = await org_service.get_usage_summary(
            org_id=org_id,
            metric_name=metric_name,
            start_date=start_date,
            end_date=end,
        )

        return UsageSummaryResponse(
            org_id=org_id,
            metric_name=metric_name,
            total=total,
            start_date=start_date,
            end_date=end,
        )

    # =========================================================================
    # Invitation Management
    # =========================================================================

    if invitation_service is not None:

        @router.get("/{org_id}/invitations", response_model=InvitationListResponse)
        async def list_invitations(
            request: Request,
            org_id: str,
            status_filter: Optional[InvitationStatus] = Query(
                None, alias="status", description="Filter by invitation status"
            ),
            limit: int = Query(50, ge=1, le=100, description="Max results"),
            offset: int = Query(0, ge=0, description="Pagination offset"),
        ) -> InvitationListResponse:
            """List invitations for an organization.

            Requires admin role or higher.
            """
            _require_member(request, org_id, MemberRole.ADMIN)

            return invitation_service.list_org_invitations(
                org_id=org_id,
                status=status_filter,
                limit=limit,
                offset=offset,
            )

        @router.post(
            "/{org_id}/invitations",
            response_model=Invitation,
            status_code=status.HTTP_201_CREATED,
        )
        async def create_invitation(
            request: Request,
            org_id: str,
            body: CreateInvitationRequest,
        ) -> Invitation:
            """Create and send an invitation to join the organization.

            Requires admin role or higher.
            """
            ctx = _require_member(request, org_id, MemberRole.ADMIN)

            try:
                return invitation_service.create_invitation(
                    org_id=org_id,
                    request=body,
                    invited_by=ctx.user_id,
                    send=True,
                )
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )

        @router.get("/{org_id}/invitations/{invitation_id}", response_model=Invitation)
        async def get_invitation(
            request: Request,
            org_id: str,
            invitation_id: str,
        ) -> Invitation:
            """Get an invitation by ID.

            Requires admin role or higher.
            """
            _require_member(request, org_id, MemberRole.ADMIN)

            invitation = invitation_service.get_invitation(invitation_id)
            if not invitation or invitation.org_id != org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Invitation {invitation_id} not found",
                )
            return invitation

        @router.delete(
            "/{org_id}/invitations/{invitation_id}",
            status_code=status.HTTP_204_NO_CONTENT,
        )
        async def revoke_invitation(
            request: Request,
            org_id: str,
            invitation_id: str,
        ) -> None:
            """Revoke a pending invitation.

            Requires admin role or higher. Only pending invitations can be revoked.
            """
            ctx = _require_member(request, org_id, MemberRole.ADMIN)

            try:
                invitation_service.revoke_invitation(
                    invitation_id=invitation_id,
                    revoked_by=ctx.user_id,
                )
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )

        @router.post(
            "/{org_id}/invitations/{invitation_id}/resend",
            response_model=Invitation,
        )
        async def resend_invitation(
            request: Request,
            org_id: str,
            invitation_id: str,
        ) -> Invitation:
            """Resend a pending invitation.

            Requires admin role or higher.
            """
            _require_member(request, org_id, MemberRole.ADMIN)

            try:
                return invitation_service.resend_invitation(invitation_id)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )

    return router
