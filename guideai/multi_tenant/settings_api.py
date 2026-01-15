"""FastAPI router for organization and project settings management.

Endpoints:
    # Organization Settings
    GET    /v1/orgs/{org_id}/settings              - Get complete org settings
    PATCH  /v1/orgs/{org_id}/settings              - Update org settings

    GET    /v1/orgs/{org_id}/settings/branding     - Get branding settings
    PATCH  /v1/orgs/{org_id}/settings/branding     - Update branding settings

    GET    /v1/orgs/{org_id}/settings/notifications - Get notification settings
    PATCH  /v1/orgs/{org_id}/settings/notifications - Update notification settings

    GET    /v1/orgs/{org_id}/settings/security     - Get security settings
    PATCH  /v1/orgs/{org_id}/settings/security     - Update security settings

    GET    /v1/orgs/{org_id}/settings/integrations - Get integration settings
    PATCH  /v1/orgs/{org_id}/settings/integrations - Update integration settings

    GET    /v1/orgs/{org_id}/settings/workflow     - Get workflow settings
    PATCH  /v1/orgs/{org_id}/settings/workflow     - Update workflow settings

    POST   /v1/orgs/{org_id}/settings/webhooks     - Add webhook
    DELETE /v1/orgs/{org_id}/settings/webhooks/{webhook_id} - Remove webhook

    PUT    /v1/orgs/{org_id}/settings/features/{feature} - Set feature flag

    # Project Settings
    GET    /v1/projects/{project_id}/settings      - Get complete project settings
    PATCH  /v1/projects/{project_id}/settings      - Update project settings

    GET    /v1/projects/{project_id}/settings/workflow - Get workflow settings
    PATCH  /v1/projects/{project_id}/settings/workflow - Update workflow settings

    PUT    /v1/projects/{project_id}/settings/repository - Set repository config
    PUT    /v1/projects/{project_id}/settings/features/{feature} - Set feature flag

Behavior: behavior_design_api_contract
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from .contracts import MemberRole, ProjectRole
from .settings import (
    SettingsService,
    OrgSettings,
    ProjectSettings,
    BrandingSettings,
    NotificationSettings,
    SecuritySettings,
    IntegrationSettings,
    WorkflowSettings,
    AgentSettings,
    UpdateBrandingRequest,
    UpdateNotificationRequest,
    UpdateSecurityRequest,
    UpdateWorkflowRequest,
)

if TYPE_CHECKING:
    from .organization_service import OrganizationService


# =============================================================================
# Request/Response Models
# =============================================================================

class OrgSettingsResponse(BaseModel):
    """Response for organization settings."""
    org_id: str
    branding: BrandingSettings
    notifications: NotificationSettings
    security: SecuritySettings
    integrations: IntegrationSettings
    workflow: WorkflowSettings
    agents: AgentSettings
    default_project_visibility: str
    default_member_role: str
    features: Dict[str, bool]
    custom: Dict[str, Any]


class ProjectSettingsResponse(BaseModel):
    """Response for project settings."""
    project_id: str
    inherit_org_settings: bool
    branding: Optional[BrandingSettings]
    workflow: WorkflowSettings
    agents: AgentSettings
    repository_url: Optional[str]
    default_branch: str
    protected_branches: List[str]
    local_project_path: Optional[str]
    environments: List[str]
    active_environment: str
    features: Dict[str, bool]
    custom: Dict[str, Any]


class UpdateOrgSettingsRequest(BaseModel):
    """Request to update complete org settings."""
    branding: Optional[UpdateBrandingRequest] = None
    notifications: Optional[UpdateNotificationRequest] = None
    security: Optional[UpdateSecurityRequest] = None
    workflow: Optional[UpdateWorkflowRequest] = None
    integrations: Optional[Dict[str, Any]] = None
    default_project_visibility: Optional[str] = Field(
        None, pattern=r"^(private|internal|public)$"
    )
    default_member_role: Optional[str] = Field(
        None, pattern=r"^(owner|admin|member|viewer)$"
    )
    features: Optional[Dict[str, bool]] = None
    custom: Optional[Dict[str, Any]] = None


class UpdateProjectSettingsRequest(BaseModel):
    """Request to update complete project settings."""
    inherit_org_settings: Optional[bool] = None
    branding: Optional[UpdateBrandingRequest] = None
    workflow: Optional[UpdateWorkflowRequest] = None
    repository_url: Optional[str] = Field(
        None,
        alias="github_repo_url",
        validation_alias="github_repo_url",
        description="GitHub repository URL",
    )
    default_branch: Optional[str] = Field(
        None,
        alias="github_default_branch",
        validation_alias="github_default_branch",
    )
    protected_branches: Optional[List[str]] = None
    local_project_path: Optional[str] = Field(None, description="Local filesystem path to project root")
    environments: Optional[List[str]] = None
    active_environment: Optional[str] = None
    features: Optional[Dict[str, bool]] = None
    custom: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class UpdateIntegrationsRequest(BaseModel):
    """Request to update integration settings."""
    github_enabled: Optional[bool] = None
    github_org: Optional[str] = None
    github_app_installation_id: Optional[str] = None

    gitlab_enabled: Optional[bool] = None
    gitlab_url: Optional[str] = None

    bitbucket_enabled: Optional[bool] = None
    bitbucket_workspace: Optional[str] = None

    jenkins_enabled: Optional[bool] = None
    jenkins_url: Optional[str] = None

    circleci_enabled: Optional[bool] = None
    github_actions_enabled: Optional[bool] = None

    slack_workspace_id: Optional[str] = None
    discord_enabled: Optional[bool] = None
    discord_webhook_url: Optional[str] = None

    datadog_enabled: Optional[bool] = None
    sentry_enabled: Optional[bool] = None


class AddWebhookRequest(BaseModel):
    """Request to add a webhook."""
    url: str = Field(..., description="Webhook endpoint URL")
    events: List[str] = Field(..., description="Events to subscribe to")
    secret: Optional[str] = Field(None, description="Optional webhook secret")


class AddWebhookResponse(BaseModel):
    """Response for adding a webhook."""
    id: str
    url: str
    events: List[str]
    enabled: bool


class SetFeatureFlagRequest(BaseModel):
    """Request to set a feature flag."""
    enabled: bool


class SetRepositoryRequest(BaseModel):
    """Request to set repository configuration."""
    repository_url: str = Field(..., description="Git repository URL")
    default_branch: str = Field("main", description="Default branch name")


# =============================================================================
# GitHub Integration Models
# =============================================================================

class GitHubRepoValidationRequest(BaseModel):
    """Request to validate a GitHub repository."""
    repository_url: str = Field(
        ...,
        description="GitHub repository URL (e.g., https://github.com/owner/repo)",
        pattern=r"^https?://github\.com/[\w.-]+/[\w.-]+/?$",
    )
    access_token: Optional[str] = Field(
        None,
        description="Optional personal access token. If not provided, uses OAuth token from user session.",
    )


class GitHubBranchInfo(BaseModel):
    """Information about a GitHub branch."""
    name: str
    sha: str
    protected: bool = False


class GitHubRepoValidationResponse(BaseModel):
    """Response from GitHub repository validation."""
    valid: bool = Field(..., description="Whether the repository is valid and accessible")
    owner: Optional[str] = Field(None, description="Repository owner/organization")
    repo: Optional[str] = Field(None, description="Repository name")
    default_branch: Optional[str] = Field(None, description="Default branch name")
    branches: List[GitHubBranchInfo] = Field(
        default_factory=list,
        description="Available branches (up to 30)",
    )
    visibility: Optional[str] = Field(None, description="Repository visibility (public/private)")
    description: Optional[str] = Field(None, description="Repository description")
    error: Optional[str] = Field(None, description="Error message if validation failed")


class GitHubBranchListResponse(BaseModel):
    """Response for listing GitHub branches."""
    branches: List[GitHubBranchInfo]
    total_count: Optional[int] = None
    page: int
    per_page: int


# =============================================================================
# Router Factory
# =============================================================================

def create_settings_routes(
    settings_service: SettingsService,
    get_user_id: Optional[callable] = None,
    tags: List[str] = None,
) -> APIRouter:
    """Create FastAPI router for settings management.

    Args:
        settings_service: SettingsService instance.
        get_user_id: Optional callable to extract user_id from request.
        tags: Optional tags for OpenAPI documentation.

    Returns:
        FastAPI APIRouter with all settings endpoints.
    """
    router = APIRouter(tags=tags or ["settings"])

    # Use the pool from settings_service for permission lookups
    _pool = settings_service.pool

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

    def _require_org_admin(request: Request, org_id: str) -> str:
        """Require admin role in organization.

        Returns:
            user_id if authorized.

        Raises:
            HTTPException: If not authorized.
        """
        user_id = _get_user_id(request)

        ctx = getattr(request.state, "org_context", None)
        if ctx and ctx.org_id == org_id:
            role_hierarchy = {
                MemberRole.VIEWER: 0,
                MemberRole.MEMBER: 1,
                MemberRole.ADMIN: 2,
                MemberRole.OWNER: 3,
            }
            if role_hierarchy.get(ctx.role, 0) >= role_hierarchy.get(MemberRole.ADMIN, 0):
                return user_id

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to modify settings",
        )

    def _require_org_viewer(request: Request, org_id: str) -> str:
        """Require at least viewer role in organization.

        Returns:
            user_id if authorized.
        """
        user_id = _get_user_id(request)

        ctx = getattr(request.state, "org_context", None)
        if ctx and ctx.org_id == org_id:
            return user_id

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access required",
        )

    def _get_user_project_role(user_id: str, project_id: str) -> Optional[ProjectRole]:
        """Look up user's role in a project from the database.

        Checks:
        1. Direct project membership in auth.project_memberships
        2. Project creator (created_by in auth.projects)

        Args:
            user_id: User ID to check
            project_id: Project ID to check

        Returns:
            ProjectRole or None if no access
        """
        if _pool is None:
            return None

        try:
            with _pool.connection() as conn:
                cursor = conn.cursor()

                # Check direct project membership
                cursor.execute(
                    """
                    SELECT role FROM auth.project_memberships
                    WHERE project_id = %s AND user_id = %s
                    """,
                    (project_id, user_id)
                )
                row = cursor.fetchone()
                if row:
                    role_str = row[0].lower()
                    role_map = {
                        "owner": ProjectRole.OWNER,
                        "maintainer": ProjectRole.MAINTAINER,
                        "contributor": ProjectRole.CONTRIBUTOR,
                        "viewer": ProjectRole.VIEWER,
                    }
                    return role_map.get(role_str)

                # Check if user is project creator (treat as owner)
                cursor.execute(
                    """
                    SELECT created_by FROM auth.projects
                    WHERE project_id = %s
                    """,
                    (project_id,)
                )
                row = cursor.fetchone()
                if row and row[0] == user_id:
                    return ProjectRole.OWNER

                return None
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Error checking project role: {e}")
            return None

    def _require_project_maintainer(request: Request, project_id: str) -> str:
        """Require maintainer role in project.

        Checks in order:
        1. Request state project_context (from middleware)
        2. Database lookup of project membership
        3. Project creator check

        Returns:
            user_id if authorized.
        """
        user_id = _get_user_id(request)

        role_hierarchy = {
            ProjectRole.VIEWER: 0,
            ProjectRole.CONTRIBUTOR: 1,
            ProjectRole.MAINTAINER: 2,
            ProjectRole.OWNER: 3,
        }

        # Check middleware-provided context first
        ctx = getattr(request.state, "project_context", None)
        if ctx and ctx.project_id == project_id:
            if role_hierarchy.get(ctx.role, 0) >= role_hierarchy.get(ProjectRole.MAINTAINER, 0):
                return user_id

        # Fall back to database lookup
        db_role = _get_user_project_role(user_id, project_id)
        if db_role and role_hierarchy.get(db_role, 0) >= role_hierarchy.get(ProjectRole.MAINTAINER, 0):
            return user_id

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Maintainer role required to modify project settings",
        )

    def _require_project_viewer(request: Request, project_id: str) -> str:
        """Require at least viewer role in project.

        Returns:
            user_id if authorized.
        """
        user_id = _get_user_id(request)

        # Check middleware-provided context first
        ctx = getattr(request.state, "project_context", None)
        if ctx and ctx.project_id == project_id:
            return user_id

        # Fall back to org context check for org-owned projects
        org_ctx = getattr(request.state, "org_context", None)
        if org_ctx:
            return user_id

        # Fall back to database lookup
        db_role = _get_user_project_role(user_id, project_id)
        if db_role is not None:
            return user_id

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project access required",
        )

    # =========================================================================
    # Organization Settings
    # =========================================================================

    @router.get(
        "/v1/orgs/{org_id}/settings",
        response_model=OrgSettingsResponse,
        summary="Get organization settings",
        description="Get complete settings for an organization. Requires viewer role.",
    )
    async def get_org_settings(
        request: Request,
        org_id: str,
    ) -> OrgSettingsResponse:
        """Get complete organization settings."""
        _require_org_viewer(request, org_id)

        try:
            settings = settings_service.get_org_settings(org_id)
            return OrgSettingsResponse(
                org_id=settings.org_id,
                branding=settings.branding,
                notifications=settings.notifications,
                security=settings.security,
                integrations=settings.integrations,
                workflow=settings.workflow,
                agents=settings.agents,
                default_project_visibility=settings.default_project_visibility,
                default_member_role=settings.default_member_role,
                features=settings.features,
                custom=settings.custom,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )

    @router.patch(
        "/v1/orgs/{org_id}/settings",
        response_model=OrgSettingsResponse,
        summary="Update organization settings",
        description="Update organization settings. Requires admin role.",
    )
    async def update_org_settings(
        request: Request,
        org_id: str,
        body: UpdateOrgSettingsRequest,
    ) -> OrgSettingsResponse:
        """Update complete organization settings."""
        user_id = _require_org_admin(request, org_id)

        try:
            current = settings_service.get_org_settings(org_id)

            # Apply partial updates
            if body.branding:
                update_data = body.branding.model_dump(exclude_none=True)
                current_branding = current.branding.model_dump()
                current_branding.update(update_data)
                current.branding = BrandingSettings(**current_branding)

            if body.notifications:
                update_data = body.notifications.model_dump(exclude_none=True)
                current_notifications = current.notifications.model_dump()
                current_notifications.update(update_data)
                current.notifications = NotificationSettings(**current_notifications)

            if body.security:
                update_data = body.security.model_dump(exclude_none=True)
                current_security = current.security.model_dump()
                current_security.update(update_data)
                current.security = SecuritySettings(**current_security)

            if body.workflow:
                update_data = body.workflow.model_dump(exclude_none=True)
                current_workflow = current.workflow.model_dump()
                current_workflow.update(update_data)
                current.workflow = WorkflowSettings(**current_workflow)

            if body.integrations:
                current_integrations = current.integrations.model_dump()
                current_integrations.update(body.integrations)
                current.integrations = IntegrationSettings(**current_integrations)

            if body.default_project_visibility is not None:
                current.default_project_visibility = body.default_project_visibility

            if body.default_member_role is not None:
                current.default_member_role = body.default_member_role

            if body.features is not None:
                current.features.update(body.features)

            if body.custom is not None:
                current.custom.update(body.custom)

            updated = settings_service.update_org_settings(org_id, current, user_id)

            return OrgSettingsResponse(
                org_id=updated.org_id,
                branding=updated.branding,
                notifications=updated.notifications,
                security=updated.security,
                integrations=updated.integrations,
                workflow=updated.workflow,
                agents=updated.agents,
                default_project_visibility=updated.default_project_visibility,
                default_member_role=updated.default_member_role,
                features=updated.features,
                custom=updated.custom,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )

    # =========================================================================
    # Organization Settings - Individual Sections
    # =========================================================================

    @router.get(
        "/v1/orgs/{org_id}/settings/branding",
        response_model=BrandingSettings,
        summary="Get branding settings",
    )
    async def get_org_branding(
        request: Request,
        org_id: str,
    ) -> BrandingSettings:
        """Get organization branding settings."""
        _require_org_viewer(request, org_id)

        try:
            settings = settings_service.get_org_settings(org_id)
            return settings.branding
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/orgs/{org_id}/settings/branding",
        response_model=BrandingSettings,
        summary="Update branding settings",
    )
    async def update_org_branding(
        request: Request,
        org_id: str,
        body: UpdateBrandingRequest,
    ) -> BrandingSettings:
        """Update organization branding settings."""
        user_id = _require_org_admin(request, org_id)

        try:
            return settings_service.update_org_branding(org_id, body, user_id)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.get(
        "/v1/orgs/{org_id}/settings/notifications",
        response_model=NotificationSettings,
        summary="Get notification settings",
    )
    async def get_org_notifications(
        request: Request,
        org_id: str,
    ) -> NotificationSettings:
        """Get organization notification settings."""
        _require_org_viewer(request, org_id)

        try:
            settings = settings_service.get_org_settings(org_id)
            return settings.notifications
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/orgs/{org_id}/settings/notifications",
        response_model=NotificationSettings,
        summary="Update notification settings",
    )
    async def update_org_notifications(
        request: Request,
        org_id: str,
        body: UpdateNotificationRequest,
    ) -> NotificationSettings:
        """Update organization notification settings."""
        user_id = _require_org_admin(request, org_id)

        try:
            return settings_service.update_org_notifications(org_id, body, user_id)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.get(
        "/v1/orgs/{org_id}/settings/security",
        response_model=SecuritySettings,
        summary="Get security settings",
    )
    async def get_org_security(
        request: Request,
        org_id: str,
    ) -> SecuritySettings:
        """Get organization security settings."""
        _require_org_viewer(request, org_id)

        try:
            settings = settings_service.get_org_settings(org_id)
            return settings.security
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/orgs/{org_id}/settings/security",
        response_model=SecuritySettings,
        summary="Update security settings",
    )
    async def update_org_security(
        request: Request,
        org_id: str,
        body: UpdateSecurityRequest,
    ) -> SecuritySettings:
        """Update organization security settings."""
        user_id = _require_org_admin(request, org_id)

        try:
            return settings_service.update_org_security(org_id, body, user_id)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.get(
        "/v1/orgs/{org_id}/settings/integrations",
        response_model=IntegrationSettings,
        summary="Get integration settings",
    )
    async def get_org_integrations(
        request: Request,
        org_id: str,
    ) -> IntegrationSettings:
        """Get organization integration settings."""
        _require_org_viewer(request, org_id)

        try:
            settings = settings_service.get_org_settings(org_id)
            return settings.integrations
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/orgs/{org_id}/settings/integrations",
        response_model=IntegrationSettings,
        summary="Update integration settings",
    )
    async def update_org_integrations(
        request: Request,
        org_id: str,
        body: UpdateIntegrationsRequest,
    ) -> IntegrationSettings:
        """Update organization integration settings."""
        user_id = _require_org_admin(request, org_id)

        try:
            integrations = body.model_dump(exclude_none=True)
            return settings_service.update_org_integrations(org_id, integrations, user_id)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.get(
        "/v1/orgs/{org_id}/settings/workflow",
        response_model=WorkflowSettings,
        summary="Get workflow settings",
    )
    async def get_org_workflow(
        request: Request,
        org_id: str,
    ) -> WorkflowSettings:
        """Get organization workflow settings."""
        _require_org_viewer(request, org_id)

        try:
            settings = settings_service.get_org_settings(org_id)
            return settings.workflow
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/orgs/{org_id}/settings/workflow",
        response_model=WorkflowSettings,
        summary="Update workflow settings",
    )
    async def update_org_workflow(
        request: Request,
        org_id: str,
        body: UpdateWorkflowRequest,
    ) -> WorkflowSettings:
        """Update organization workflow settings."""
        user_id = _require_org_admin(request, org_id)

        try:
            return settings_service.update_org_workflow(org_id, body, user_id)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # =========================================================================
    # Webhooks
    # =========================================================================

    @router.post(
        "/v1/orgs/{org_id}/settings/webhooks",
        response_model=AddWebhookResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Add webhook",
    )
    async def add_org_webhook(
        request: Request,
        org_id: str,
        body: AddWebhookRequest,
    ) -> AddWebhookResponse:
        """Add a webhook to organization."""
        user_id = _require_org_admin(request, org_id)

        try:
            webhook = settings_service.add_org_webhook(
                org_id=org_id,
                webhook_url=body.url,
                events=body.events,
                updated_by=user_id,
                secret=body.secret,
            )
            return AddWebhookResponse(
                id=webhook["id"],
                url=webhook["url"],
                events=webhook["events"],
                enabled=webhook["enabled"],
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.delete(
        "/v1/orgs/{org_id}/settings/webhooks/{webhook_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Remove webhook",
    )
    async def remove_org_webhook(
        request: Request,
        org_id: str,
        webhook_id: str,
    ) -> None:
        """Remove a webhook from organization."""
        user_id = _require_org_admin(request, org_id)

        removed = settings_service.remove_org_webhook(org_id, webhook_id, user_id)
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Webhook {webhook_id} not found",
            )

    # =========================================================================
    # Feature Flags
    # =========================================================================

    @router.put(
        "/v1/orgs/{org_id}/settings/features/{feature}",
        response_model=Dict[str, bool],
        summary="Set feature flag",
    )
    async def set_org_feature_flag(
        request: Request,
        org_id: str,
        feature: str,
        body: SetFeatureFlagRequest,
    ) -> Dict[str, bool]:
        """Set a feature flag for organization."""
        user_id = _require_org_admin(request, org_id)

        try:
            return settings_service.set_org_feature_flag(
                org_id=org_id,
                feature=feature,
                enabled=body.enabled,
                updated_by=user_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # =========================================================================
    # Project Settings
    # =========================================================================

    @router.get(
        "/v1/projects/{project_id}/settings",
        response_model=ProjectSettingsResponse,
        summary="Get project settings",
        description="Get complete settings for a project. If inherit_org_settings is true, includes org defaults.",
    )
    async def get_project_settings(
        request: Request,
        project_id: str,
    ) -> ProjectSettingsResponse:
        """Get complete project settings."""
        _require_project_viewer(request, project_id)

        try:
            settings = settings_service.get_project_settings(project_id)
            return ProjectSettingsResponse(
                project_id=settings.project_id,
                inherit_org_settings=settings.inherit_org_settings,
                branding=settings.branding,
                workflow=settings.workflow,
                agents=settings.agents,
                repository_url=settings.repository_url,
                default_branch=settings.default_branch,
                protected_branches=settings.protected_branches,
                local_project_path=settings.local_project_path,
                environments=settings.environments,
                active_environment=settings.active_environment,
                features=settings.features,
                custom=settings.custom,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )

    @router.patch(
        "/v1/projects/{project_id}/settings",
        response_model=ProjectSettingsResponse,
        summary="Update project settings",
        description="Update project settings. Requires maintainer role.",
    )
    async def update_project_settings(
        request: Request,
        project_id: str,
        body: UpdateProjectSettingsRequest,
    ) -> ProjectSettingsResponse:
        """Update complete project settings."""
        user_id = _require_project_maintainer(request, project_id)

        try:
            current = settings_service.get_project_settings(project_id)

            # Apply partial updates
            if body.inherit_org_settings is not None:
                current.inherit_org_settings = body.inherit_org_settings

            if body.branding:
                update_data = body.branding.model_dump(exclude_none=True)
                if current.branding:
                    current_branding = current.branding.model_dump()
                    current_branding.update(update_data)
                    current.branding = BrandingSettings(**current_branding)
                else:
                    current.branding = BrandingSettings(**update_data)

            if body.workflow:
                update_data = body.workflow.model_dump(exclude_none=True)
                current_workflow = current.workflow.model_dump()
                current_workflow.update(update_data)
                current.workflow = WorkflowSettings(**current_workflow)

            if body.repository_url is not None:
                current.repository_url = body.repository_url

            if body.default_branch is not None:
                current.default_branch = body.default_branch

            if body.protected_branches is not None:
                current.protected_branches = body.protected_branches

            if body.local_project_path is not None:
                current.local_project_path = body.local_project_path

            if body.environments is not None:
                current.environments = body.environments

            if body.active_environment is not None:
                current.active_environment = body.active_environment

            if body.features is not None:
                current.features.update(body.features)

            if body.custom is not None:
                current.custom.update(body.custom)

            updated = settings_service.update_project_settings(project_id, current, user_id)

            return ProjectSettingsResponse(
                project_id=updated.project_id,
                inherit_org_settings=updated.inherit_org_settings,
                branding=updated.branding,
                workflow=updated.workflow,
                agents=updated.agents,
                repository_url=updated.repository_url,
                default_branch=updated.default_branch,
                protected_branches=updated.protected_branches,
                local_project_path=updated.local_project_path,
                environments=updated.environments,
                active_environment=updated.active_environment,
                features=updated.features,
                custom=updated.custom,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )

    @router.get(
        "/v1/projects/{project_id}/settings/workflow",
        response_model=WorkflowSettings,
        summary="Get project workflow settings",
    )
    async def get_project_workflow(
        request: Request,
        project_id: str,
    ) -> WorkflowSettings:
        """Get project workflow settings."""
        _require_project_viewer(request, project_id)

        try:
            settings = settings_service.get_project_settings(project_id)
            return settings.workflow
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/projects/{project_id}/settings/workflow",
        response_model=WorkflowSettings,
        summary="Update project workflow settings",
    )
    async def update_project_workflow(
        request: Request,
        project_id: str,
        body: UpdateWorkflowRequest,
    ) -> WorkflowSettings:
        """Update project workflow settings."""
        user_id = _require_project_maintainer(request, project_id)

        try:
            return settings_service.update_project_workflow(project_id, body, user_id)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.put(
        "/v1/projects/{project_id}/settings/repository",
        response_model=ProjectSettingsResponse,
        summary="Set repository configuration",
    )
    async def set_project_repository(
        request: Request,
        project_id: str,
        body: SetRepositoryRequest,
    ) -> ProjectSettingsResponse:
        """Set project repository configuration."""
        user_id = _require_project_maintainer(request, project_id)

        try:
            settings = settings_service.set_project_repository(
                project_id=project_id,
                repository_url=body.repository_url,
                default_branch=body.default_branch,
                updated_by=user_id,
            )
            return ProjectSettingsResponse(
                project_id=settings.project_id,
                inherit_org_settings=settings.inherit_org_settings,
                branding=settings.branding,
                workflow=settings.workflow,
                agents=settings.agents,
                repository_url=settings.repository_url,
                default_branch=settings.default_branch,
                protected_branches=settings.protected_branches,
                local_project_path=settings.local_project_path,
                environments=settings.environments,
                active_environment=settings.active_environment,
                features=settings.features,
                custom=settings.custom,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.put(
        "/v1/projects/{project_id}/settings/features/{feature}",
        response_model=Dict[str, bool],
        summary="Set project feature flag",
    )
    async def set_project_feature_flag(
        request: Request,
        project_id: str,
        feature: str,
        body: SetFeatureFlagRequest,
    ) -> Dict[str, bool]:
        """Set a feature flag for project."""
        user_id = _require_project_maintainer(request, project_id)

        try:
            return settings_service.set_project_feature_flag(
                project_id=project_id,
                feature=feature,
                enabled=body.enabled,
                updated_by=user_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # =========================================================================
    # GitHub Integration Endpoints
    # =========================================================================

    @router.post(
        "/v1/projects/{project_id}/settings/repository/validate",
        response_model=GitHubRepoValidationResponse,
        summary="Validate GitHub repository",
    )
    async def validate_github_repository(
        request: Request,
        project_id: str,
        body: GitHubRepoValidationRequest,
    ) -> GitHubRepoValidationResponse:
        """Validate a GitHub repository and fetch its metadata.

        This endpoint validates that the repository exists and is accessible,
        then returns metadata including available branches and the default branch.

        Requires either:
        - User's GitHub OAuth token (if connected via federated auth)
        - A personal access token provided in the request

        Behavior: behavior_design_api_contract
        """
        _require_project_maintainer(request, project_id)

        try:
            result = await settings_service.validate_github_repository(
                repository_url=body.repository_url,
                access_token=body.access_token,
                request=request,
            )
            return GitHubRepoValidationResponse(
                valid=result["valid"],
                owner=result.get("owner"),
                repo=result.get("repo"),
                default_branch=result.get("default_branch"),
                branches=result.get("branches", []),
                visibility=result.get("visibility"),
                description=result.get("description"),
                error=result.get("error"),
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.get(
        "/v1/projects/{project_id}/settings/repository/branches",
        response_model=GitHubBranchListResponse,
        summary="List GitHub repository branches",
    )
    async def list_github_branches(
        request: Request,
        project_id: str,
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=30, ge=1, le=100),
    ) -> GitHubBranchListResponse:
        """List branches for the project's configured GitHub repository.

        Requires the project to have a repository_url configured.
        Uses pagination to handle repositories with many branches.

        Behavior: behavior_design_api_contract
        """
        _require_project_viewer(request, project_id)

        try:
            result = await settings_service.list_github_branches(
                project_id=project_id,
                page=page,
                per_page=per_page,
                request=request,
            )
            return GitHubBranchListResponse(
                branches=result["branches"],
                total_count=result.get("total_count"),
                page=page,
                per_page=per_page,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return router
