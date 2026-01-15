"""Organization and Project Settings Service.

This module provides structured settings management for organizations
and projects, including branding, integrations, workflow config, and defaults.

Behavior: behavior_externalize_configuration

Usage:
    from guideai.multi_tenant.settings import (
        SettingsService,
        OrgSettings,
        ProjectSettings,
        BrandingSettings,
        IntegrationSettings,
    )

    settings_service = SettingsService(pool=pool)

    # Update org branding
    settings_service.update_org_branding(
        org_id="org-123",
        branding=BrandingSettings(
            logo_url="https://example.com/logo.png",
            primary_color="#2563eb",
        ),
        updated_by="user-456",
    )

    # Get full settings
    settings = settings_service.get_org_settings(org_id="org-123")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, HttpUrl, field_validator

if TYPE_CHECKING:
    from guideai.storage.postgres_pool import PostgresPool

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class ExecutionMode(str, Enum):
    """Execution mode for work item processing.

    Determines where file changes are written during agent execution:
    - LOCAL: Changes written directly to local filesystem (requires IDE/CLI)
    - GITHUB_PR: Changes committed to a branch and opened as PR
    - LOCAL_AND_PR: Both local changes and PR creation
    """
    LOCAL = "local"
    GITHUB_PR = "github_pr"
    LOCAL_AND_PR = "local_and_pr"


# Surfaces that support local file operations
LOCAL_CAPABLE_SURFACES = frozenset({"cli", "vscode", "mcp", "codespaces", "gitpod"})

# Surfaces that do NOT support local file operations
REMOTE_ONLY_SURFACES = frozenset({"web", "api"})


# =============================================================================
# Settings Contracts
# =============================================================================

class BrandingSettings(BaseModel):
    """Organization or project branding configuration."""

    # Visual identity
    logo_url: Optional[str] = Field(None, description="URL to organization logo")
    logo_dark_url: Optional[str] = Field(None, description="Logo for dark mode")
    favicon_url: Optional[str] = Field(None, description="Favicon URL")

    # Colors
    primary_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="Primary brand color (hex)")
    secondary_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="Secondary brand color")
    accent_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="Accent color")

    # Text
    display_name: Optional[str] = Field(None, max_length=100, description="Display name override")
    tagline: Optional[str] = Field(None, max_length=255, description="Organization tagline")

    # Custom domain
    custom_domain: Optional[str] = Field(None, description="Custom domain (e.g., app.acme.com)")

    class Config:
        extra = "allow"  # Allow additional fields for future extensibility


class NotificationSettings(BaseModel):
    """Notification preferences."""

    # Email notifications
    email_enabled: bool = True
    email_digest_frequency: str = Field("daily", pattern=r"^(realtime|hourly|daily|weekly|none)$")

    # Slack notifications
    slack_enabled: bool = False
    slack_webhook_url: Optional[str] = None
    slack_channel: Optional[str] = None

    # In-app notifications
    in_app_enabled: bool = True
    browser_push_enabled: bool = False

    # Notification types
    notify_on_run_complete: bool = True
    notify_on_run_failure: bool = True
    notify_on_compliance_violation: bool = True
    notify_on_member_invite: bool = True
    notify_on_billing_events: bool = True

    class Config:
        extra = "allow"


class SecuritySettings(BaseModel):
    """Security and access control settings."""

    # Authentication
    require_mfa: bool = False
    allowed_auth_methods: List[str] = Field(default_factory=lambda: ["password", "oauth"])
    session_timeout_hours: int = Field(24, ge=1, le=720)

    # SSO (Enterprise)
    sso_enabled: bool = False
    sso_provider: Optional[str] = None  # "okta", "azure_ad", "google", "saml"
    sso_config: Dict[str, Any] = Field(default_factory=dict)

    # IP restrictions
    ip_allowlist_enabled: bool = False
    ip_allowlist: List[str] = Field(default_factory=list)

    # API access
    api_key_enabled: bool = True
    api_key_expiration_days: Optional[int] = Field(None, ge=1, le=365)

    # Audit
    audit_log_retention_days: int = Field(90, ge=30, le=365)

    class Config:
        extra = "allow"


class IntegrationSettings(BaseModel):
    """Third-party integration settings."""

    # Git integrations
    github_enabled: bool = False
    github_org: Optional[str] = None
    github_app_installation_id: Optional[str] = None

    gitlab_enabled: bool = False
    gitlab_url: Optional[str] = None

    bitbucket_enabled: bool = False
    bitbucket_workspace: Optional[str] = None

    # CI/CD integrations
    jenkins_enabled: bool = False
    jenkins_url: Optional[str] = None

    circleci_enabled: bool = False
    github_actions_enabled: bool = False

    # Communication integrations
    slack_workspace_id: Optional[str] = None
    slack_bot_token_ref: Optional[str] = None  # Reference to secrets manager

    discord_enabled: bool = False
    discord_webhook_url: Optional[str] = None

    # Observability integrations
    datadog_enabled: bool = False
    datadog_api_key_ref: Optional[str] = None

    sentry_enabled: bool = False
    sentry_dsn_ref: Optional[str] = None

    # Custom webhooks
    webhooks: List["WebhookSettings"] = Field(default_factory=list)

    class Config:
        extra = "allow"


class WebhookSettings(BaseModel):
    """Custom webhook configuration."""

    url: str = Field(..., description="Webhook URL")
    events: List[str] = Field(default_factory=list, description="Event types to deliver")
    enabled: bool = Field(True, description="Whether webhook is enabled")

    class Config:
        extra = "allow"


class WorkflowSettings(BaseModel):
    """Workflow and automation settings."""

    # Default behaviors
    default_behaviors: List[str] = Field(default_factory=list, description="Behavior IDs to apply by default")
    required_behaviors: List[str] = Field(default_factory=list, description="Behaviors that must be applied")

    # Compliance
    auto_compliance_check: bool = True
    require_compliance_approval: bool = False
    compliance_policies: List[str] = Field(default_factory=list, description="Policy IDs to enforce")

    # Run settings
    default_agent_type: str = "specialist"
    max_concurrent_runs: int = Field(10, ge=1, le=100)
    run_timeout_minutes: int = Field(60, ge=1, le=1440)

    # Review settings
    require_human_review: bool = False
    auto_merge_enabled: bool = False

    # Token limits
    default_token_budget: int = Field(10000, ge=100, le=1000000)
    max_token_budget_per_run: int = Field(100000, ge=1000, le=10000000)

    class Config:
        extra = "allow"


class AgentSettings(BaseModel):
    """Agent configuration settings."""

    # Default model
    default_model: str = "claude-sonnet-4-20250514"
    allowed_models: List[str] = Field(
        default_factory=lambda: [
            "claude-sonnet-4-20250514",
            "gpt-4",
            "gpt-4o",
        ]
    )

    # Agent behavior
    auto_assign_enabled: bool = True
    prefer_specialized_agents: bool = True

    # Context settings
    max_context_files: int = Field(50, ge=1, le=500)
    include_workspace_context: bool = True

    # Safety
    require_confirmation_for_writes: bool = False
    sandbox_mode: bool = False

    class Config:
        extra = "allow"


class OrgSettings(BaseModel):
    """Complete organization settings."""

    org_id: str

    # Settings sections
    branding: BrandingSettings = Field(default_factory=BrandingSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    integrations: IntegrationSettings = Field(default_factory=IntegrationSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)

    # Organization defaults
    default_project_visibility: str = "private"
    default_member_role: str = "member"

    # Feature flags
    features: Dict[str, bool] = Field(default_factory=dict)

    # Custom settings (for extensibility)
    custom: Dict[str, Any] = Field(default_factory=dict)

    # Metadata
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None

    class Config:
        extra = "allow"

    @classmethod
    def from_jsonb(cls, org_id: str, data: Dict[str, Any]) -> "OrgSettings":
        """Create OrgSettings from JSONB data stored in database."""
        return cls(org_id=org_id, **data)

    def to_jsonb(self) -> Dict[str, Any]:
        """Convert to dictionary for JSONB storage."""
        data = self.model_dump(exclude={"org_id"})
        # Convert datetime to ISO string
        if "updated_at" in data:
            data["updated_at"] = data["updated_at"].isoformat()
        return data


class ProjectSettings(BaseModel):
    """Complete project settings."""

    project_id: str

    # Inherit from org or override
    inherit_org_settings: bool = True

    # Project-specific branding
    branding: Optional[BrandingSettings] = None

    # Project workflow
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)

    # Agent settings
    agents: AgentSettings = Field(default_factory=AgentSettings)

    # Repository settings
    repository_url: Optional[str] = Field(None, description="GitHub repository URL (e.g., https://github.com/owner/repo)")
    default_branch: str = "main"
    protected_branches: List[str] = Field(default_factory=lambda: ["main", "master"])

    # Local project path (for IDE/CLI integration)
    local_project_path: Optional[str] = Field(None, description="Local filesystem path to project root")

    # Execution mode - determines where file changes are written
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.GITHUB_PR,
        description="Where file changes are written during execution. 'local' requires IDE/CLI, 'github_pr' works from any surface."
    )

    # Environment settings
    environments: List[str] = Field(default_factory=lambda: ["development", "staging", "production"])
    active_environment: str = "development"

    # Feature flags (project-level overrides)
    features: Dict[str, bool] = Field(default_factory=dict)

    # Custom settings
    custom: Dict[str, Any] = Field(default_factory=dict)

    # Metadata
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None

    class Config:
        extra = "allow"

    @classmethod
    def from_jsonb(cls, project_id: str, data: Dict[str, Any]) -> "ProjectSettings":
        """Create ProjectSettings from JSONB data stored in database."""
        return cls(project_id=project_id, **data)

    def to_jsonb(self) -> Dict[str, Any]:
        """Convert to dictionary for JSONB storage."""
        data = self.model_dump(exclude={"project_id"})
        if "updated_at" in data:
            data["updated_at"] = data["updated_at"].isoformat()
        return data


# =============================================================================
# Update Request Models
# =============================================================================

class UpdateBrandingRequest(BaseModel):
    """Request to update branding settings."""
    logo_url: Optional[str] = None
    logo_dark_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    display_name: Optional[str] = Field(None, max_length=100)
    tagline: Optional[str] = Field(None, max_length=255)
    custom_domain: Optional[str] = None


class UpdateNotificationRequest(BaseModel):
    """Request to update notification settings."""
    email_enabled: Optional[bool] = None
    email_digest_frequency: Optional[str] = None
    slack_enabled: Optional[bool] = None
    slack_webhook_url: Optional[str] = None
    slack_channel: Optional[str] = None
    in_app_enabled: Optional[bool] = None
    notify_on_run_complete: Optional[bool] = None
    notify_on_run_failure: Optional[bool] = None
    notify_on_compliance_violation: Optional[bool] = None


class UpdateSecurityRequest(BaseModel):
    """Request to update security settings."""
    require_mfa: Optional[bool] = None
    session_timeout_hours: Optional[int] = Field(None, ge=1, le=720)
    sso_enabled: Optional[bool] = None
    sso_provider: Optional[str] = None
    ip_allowlist_enabled: Optional[bool] = None
    ip_allowlist: Optional[List[str]] = None
    api_key_enabled: Optional[bool] = None
    audit_log_retention_days: Optional[int] = Field(None, ge=30, le=365)


class UpdateWorkflowRequest(BaseModel):
    """Request to update workflow settings."""
    default_behaviors: Optional[List[str]] = None
    required_behaviors: Optional[List[str]] = None
    auto_compliance_check: Optional[bool] = None
    require_compliance_approval: Optional[bool] = None
    max_concurrent_runs: Optional[int] = Field(None, ge=1, le=100)
    run_timeout_minutes: Optional[int] = Field(None, ge=1, le=1440)
    default_token_budget: Optional[int] = Field(None, ge=100, le=1000000)


# =============================================================================
# Settings Service
# =============================================================================

class SettingsService:
    """Service for managing organization and project settings.

    Settings are stored in the existing JSONB columns on organizations
    and projects tables, with this service providing structured access.

    Attributes:
        pool: PostgresPool instance for database operations.
    """

    def __init__(
        self,
        pool: Optional["PostgresPool"] = None,
        dsn: Optional[str] = None,
    ):
        """Initialize the settings service.

        Args:
            pool: PostgresPool instance for database operations.
            dsn: PostgreSQL connection string (creates pool automatically).

        Raises:
            ValueError: If neither pool nor dsn is provided.
        """
        if pool is not None:
            self.pool = pool
        elif dsn is not None:
            from guideai.storage.postgres_pool import PostgresPool
            self.pool = PostgresPool(dsn=dsn)
        else:
            raise ValueError("Either pool or dsn must be provided")

    # =========================================================================
    # Organization Settings
    # =========================================================================

    def get_org_settings(self, org_id: str) -> OrgSettings:
        """Get complete organization settings.

        Args:
            org_id: Organization ID.

        Returns:
            OrgSettings with all configuration.

        Raises:
            ValueError: If organization not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT settings FROM organizations WHERE id = %s",
                (org_id,)
            )
            row = cursor.fetchone()

            if not row:
                raise ValueError(f"Organization {org_id} not found")

            settings_data = row[0] or {}
            return OrgSettings.from_jsonb(org_id, settings_data)

    def update_org_settings(
        self,
        org_id: str,
        settings: OrgSettings,
        updated_by: str,
    ) -> OrgSettings:
        """Update complete organization settings.

        Args:
            org_id: Organization ID.
            settings: Complete settings to save.
            updated_by: User ID making the update.

        Returns:
            Updated OrgSettings.
        """
        settings.updated_at = datetime.utcnow()
        settings.updated_by = updated_by

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE organizations
                SET settings = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING settings
                """,
                (json.dumps(settings.to_jsonb()), org_id)
            )
            conn.commit()

            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Organization {org_id} not found")

            return OrgSettings.from_jsonb(org_id, row[0])

    def update_org_branding(
        self,
        org_id: str,
        branding: UpdateBrandingRequest,
        updated_by: str,
    ) -> BrandingSettings:
        """Update organization branding settings.

        Args:
            org_id: Organization ID.
            branding: Branding updates (only non-None fields are updated).
            updated_by: User ID making the update.

        Returns:
            Updated BrandingSettings.
        """
        current = self.get_org_settings(org_id)

        # Merge updates into current branding
        update_data = branding.model_dump(exclude_none=True)
        current_branding = current.branding.model_dump()
        current_branding.update(update_data)
        current.branding = BrandingSettings(**current_branding)

        updated = self.update_org_settings(org_id, current, updated_by)
        return updated.branding

    def update_org_notifications(
        self,
        org_id: str,
        notifications: UpdateNotificationRequest,
        updated_by: str,
    ) -> NotificationSettings:
        """Update organization notification settings.

        Args:
            org_id: Organization ID.
            notifications: Notification updates.
            updated_by: User ID making the update.

        Returns:
            Updated NotificationSettings.
        """
        current = self.get_org_settings(org_id)

        update_data = notifications.model_dump(exclude_none=True)
        current_notifications = current.notifications.model_dump()
        current_notifications.update(update_data)
        current.notifications = NotificationSettings(**current_notifications)

        updated = self.update_org_settings(org_id, current, updated_by)
        return updated.notifications

    def update_org_security(
        self,
        org_id: str,
        security: UpdateSecurityRequest,
        updated_by: str,
    ) -> SecuritySettings:
        """Update organization security settings.

        Args:
            org_id: Organization ID.
            security: Security updates.
            updated_by: User ID making the update.

        Returns:
            Updated SecuritySettings.
        """
        current = self.get_org_settings(org_id)

        update_data = security.model_dump(exclude_none=True)
        current_security = current.security.model_dump()
        current_security.update(update_data)
        current.security = SecuritySettings(**current_security)

        updated = self.update_org_settings(org_id, current, updated_by)
        return updated.security

    def update_org_workflow(
        self,
        org_id: str,
        workflow: UpdateWorkflowRequest,
        updated_by: str,
    ) -> WorkflowSettings:
        """Update organization workflow settings.

        Args:
            org_id: Organization ID.
            workflow: Workflow updates.
            updated_by: User ID making the update.

        Returns:
            Updated WorkflowSettings.
        """
        current = self.get_org_settings(org_id)

        update_data = workflow.model_dump(exclude_none=True)
        current_workflow = current.workflow.model_dump()
        current_workflow.update(update_data)
        current.workflow = WorkflowSettings(**current_workflow)

        updated = self.update_org_settings(org_id, current, updated_by)
        return updated.workflow

    def update_org_integrations(
        self,
        org_id: str,
        integrations: Dict[str, Any],
        updated_by: str,
    ) -> IntegrationSettings:
        """Update organization integration settings.

        Args:
            org_id: Organization ID.
            integrations: Integration updates as dict.
            updated_by: User ID making the update.

        Returns:
            Updated IntegrationSettings.
        """
        current = self.get_org_settings(org_id)

        current_integrations = current.integrations.model_dump()
        current_integrations.update(integrations)
        current.integrations = IntegrationSettings(**current_integrations)

        updated = self.update_org_settings(org_id, current, updated_by)
        return updated.integrations

    def set_org_feature_flag(
        self,
        org_id: str,
        feature: str,
        enabled: bool,
        updated_by: str,
    ) -> Dict[str, bool]:
        """Set a feature flag for an organization.

        Args:
            org_id: Organization ID.
            feature: Feature flag name.
            enabled: Whether feature is enabled.
            updated_by: User ID making the update.

        Returns:
            Updated feature flags dict.
        """
        current = self.get_org_settings(org_id)
        current.features[feature] = enabled

        updated = self.update_org_settings(org_id, current, updated_by)
        return updated.features

    # =========================================================================
    # Project Settings
    # =========================================================================

    def get_project_settings(self, project_id: str) -> ProjectSettings:
        """Get complete project settings.

        If inherit_org_settings is True, org settings are used as base.

        Args:
            project_id: Project ID.

        Returns:
            ProjectSettings with all configuration.

        Raises:
            ValueError: If project not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT settings, org_id FROM projects WHERE project_id = %s",
                (project_id,)
            )
            row = cursor.fetchone()

            if not row:
                raise ValueError(f"Project {project_id} not found")

            settings_data = row[0] or {}
            project_settings = ProjectSettings.from_jsonb(project_id, settings_data)

            # If inheriting and project has org, merge with org settings
            org_id = row[1]
            if project_settings.inherit_org_settings and org_id:
                org_settings = self.get_org_settings(org_id)
                project_settings = self._merge_with_org_settings(
                    project_settings, org_settings
                )

            return project_settings

    def _merge_with_org_settings(
        self,
        project: ProjectSettings,
        org: OrgSettings,
    ) -> ProjectSettings:
        """Merge project settings with org defaults.

        Project-specific settings override org defaults.

        Args:
            project: Project settings.
            org: Organization settings.

        Returns:
            Merged ProjectSettings.
        """
        # Use org workflow as base, overlay project-specific
        if project.workflow:
            org_workflow = org.workflow.model_dump()
            project_workflow = project.workflow.model_dump()
            # Only overlay non-default values
            for key, value in project_workflow.items():
                if value is not None:
                    org_workflow[key] = value
            project.workflow = WorkflowSettings(**org_workflow)
        else:
            project.workflow = org.workflow

        # Similar for agent settings
        if project.agents:
            org_agents = org.agents.model_dump()
            project_agents = project.agents.model_dump()
            for key, value in project_agents.items():
                if value is not None:
                    org_agents[key] = value
            project.agents = AgentSettings(**org_agents)
        else:
            project.agents = org.agents

        return project

    def update_project_settings(
        self,
        project_id: str,
        settings: ProjectSettings,
        updated_by: str,
    ) -> ProjectSettings:
        """Update complete project settings.

        Args:
            project_id: Project ID.
            settings: Complete settings to save.
            updated_by: User ID making the update.

        Returns:
            Updated ProjectSettings.
        """
        settings.updated_at = datetime.utcnow()
        settings.updated_by = updated_by

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE projects
                SET settings = %s, updated_at = NOW()
                WHERE project_id = %s
                RETURNING settings
                """,
                (json.dumps(settings.to_jsonb()), project_id)
            )
            conn.commit()

            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Project {project_id} not found")

            return ProjectSettings.from_jsonb(project_id, row[0])

    def update_project_workflow(
        self,
        project_id: str,
        workflow: UpdateWorkflowRequest,
        updated_by: str,
    ) -> WorkflowSettings:
        """Update project workflow settings.

        Args:
            project_id: Project ID.
            workflow: Workflow updates.
            updated_by: User ID making the update.

        Returns:
            Updated WorkflowSettings.
        """
        current = self.get_project_settings(project_id)

        update_data = workflow.model_dump(exclude_none=True)
        current_workflow = current.workflow.model_dump()
        current_workflow.update(update_data)
        current.workflow = WorkflowSettings(**current_workflow)

        # Mark as not inheriting if specific overrides are made
        if update_data:
            current.inherit_org_settings = False

        updated = self.update_project_settings(project_id, current, updated_by)
        return updated.workflow

    def set_project_feature_flag(
        self,
        project_id: str,
        feature: str,
        enabled: bool,
        updated_by: str,
    ) -> Dict[str, bool]:
        """Set a feature flag for a project.

        Args:
            project_id: Project ID.
            feature: Feature flag name.
            enabled: Whether feature is enabled.
            updated_by: User ID making the update.

        Returns:
            Updated feature flags dict.
        """
        current = self.get_project_settings(project_id)
        current.features[feature] = enabled

        updated = self.update_project_settings(project_id, current, updated_by)
        return updated.features

    def set_project_repository(
        self,
        project_id: str,
        repository_url: str,
        default_branch: str = "main",
        updated_by: str = "",
    ) -> ProjectSettings:
        """Set project repository configuration.

        Args:
            project_id: Project ID.
            repository_url: Git repository URL.
            default_branch: Default branch name.
            updated_by: User ID making the update.

        Returns:
            Updated ProjectSettings.
        """
        current = self.get_project_settings(project_id)
        current.repository_url = repository_url
        current.default_branch = default_branch

        return self.update_project_settings(project_id, current, updated_by)

    # =========================================================================
    # Webhook Management
    # =========================================================================

    def add_org_webhook(
        self,
        org_id: str,
        webhook_url: str,
        events: List[str],
        updated_by: str,
        secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a webhook to organization.

        Args:
            org_id: Organization ID.
            webhook_url: Webhook endpoint URL.
            events: List of events to subscribe to.
            updated_by: User ID making the update.
            secret: Optional webhook secret for signature verification.

        Returns:
            Created webhook configuration.
        """
        import uuid

        webhook = {
            "id": f"wh-{uuid.uuid4().hex[:12]}",
            "url": webhook_url,
            "events": events,
            "secret_ref": secret,  # Store reference, not actual secret
            "enabled": True,
            "created_at": datetime.utcnow().isoformat(),
        }

        current = self.get_org_settings(org_id)
        current.integrations.webhooks.append(webhook)

        self.update_org_settings(org_id, current, updated_by)
        return webhook

    def remove_org_webhook(
        self,
        org_id: str,
        webhook_id: str,
        updated_by: str,
    ) -> bool:
        """Remove a webhook from organization.

        Args:
            org_id: Organization ID.
            webhook_id: Webhook ID to remove.
            updated_by: User ID making the update.

        Returns:
            True if webhook was found and removed.
        """
        current = self.get_org_settings(org_id)

        initial_count = len(current.integrations.webhooks)
        current.integrations.webhooks = [
            wh for wh in current.integrations.webhooks
            if wh.get("id") != webhook_id
        ]

        if len(current.integrations.webhooks) < initial_count:
            self.update_org_settings(org_id, current, updated_by)
            return True

        return False

    # =========================================================================
    # GitHub Integration
    # =========================================================================

    async def validate_github_repository(
        self,
        repository_url: str,
        access_token: Optional[str] = None,
        request: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Validate a GitHub repository and fetch metadata.

        Args:
            repository_url: GitHub repository URL.
            access_token: Optional personal access token.
            request: FastAPI request for fetching OAuth token from session.

        Returns:
            Dict with validation result and repository metadata.

        Behavior: behavior_design_api_contract
        """
        import re
        import httpx

        # Parse repository URL
        match = re.match(
            r"https?://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/?",
            repository_url,
        )
        if not match:
            return {
                "valid": False,
                "error": "Invalid GitHub repository URL format",
            }

        owner = match.group("owner")
        repo = match.group("repo").rstrip(".git")

        # Get access token
        token = access_token
        if not token and request:
            # Try to get OAuth token from user session
            token = await self._get_github_token_from_session(request)

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient() as client:
                # Fetch repository info
                repo_response = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers=headers,
                    timeout=10.0,
                )

                if repo_response.status_code == 404:
                    return {
                        "valid": False,
                        "owner": owner,
                        "repo": repo,
                        "error": "Repository not found or not accessible",
                    }
                elif repo_response.status_code == 401:
                    return {
                        "valid": False,
                        "owner": owner,
                        "repo": repo,
                        "error": "Authentication required to access this repository",
                    }
                elif repo_response.status_code != 200:
                    return {
                        "valid": False,
                        "owner": owner,
                        "repo": repo,
                        "error": f"GitHub API error: {repo_response.status_code}",
                    }

                repo_data = repo_response.json()

                # Fetch branches (limit to 30 for validation)
                branches_response = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/branches",
                    headers=headers,
                    params={"per_page": 30},
                    timeout=10.0,
                )

                branches = []
                if branches_response.status_code == 200:
                    for branch in branches_response.json():
                        branches.append({
                            "name": branch["name"],
                            "sha": branch["commit"]["sha"],
                            "protected": branch.get("protected", False),
                        })

                return {
                    "valid": True,
                    "owner": owner,
                    "repo": repo,
                    "default_branch": repo_data.get("default_branch", "main"),
                    "branches": branches,
                    "visibility": "private" if repo_data.get("private") else "public",
                    "description": repo_data.get("description"),
                }

        except httpx.TimeoutException:
            return {
                "valid": False,
                "owner": owner,
                "repo": repo,
                "error": "GitHub API request timed out",
            }
        except Exception as e:
            return {
                "valid": False,
                "owner": owner,
                "repo": repo,
                "error": f"Failed to validate repository: {str(e)}",
            }

    async def list_github_branches(
        self,
        project_id: str,
        page: int = 1,
        per_page: int = 30,
        request: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """List branches for a project's configured GitHub repository.

        Args:
            project_id: Project ID.
            page: Page number (1-indexed).
            per_page: Results per page (max 100).
            request: FastAPI request for fetching OAuth token.

        Returns:
            Dict with branches list and pagination info.

        Raises:
            ValueError: If project has no repository configured.
        """
        import re
        import httpx

        # Get project settings
        settings = self.get_project_settings(project_id)
        if not settings.repository_url:
            raise ValueError("Project has no repository configured")

        # Parse repository URL
        match = re.match(
            r"https?://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/?",
            settings.repository_url,
        )
        if not match:
            raise ValueError("Invalid GitHub repository URL in project settings")

        owner = match.group("owner")
        repo = match.group("repo").rstrip(".git")

        # Get access token
        token = await self._get_github_token_from_session(request) if request else None

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/branches",
                    headers=headers,
                    params={"page": page, "per_page": per_page},
                    timeout=10.0,
                )

                if response.status_code != 200:
                    raise ValueError(f"GitHub API error: {response.status_code}")

                branches = []
                for branch in response.json():
                    branches.append({
                        "name": branch["name"],
                        "sha": branch["commit"]["sha"],
                        "protected": branch.get("protected", False),
                    })

                # Try to get total count from Link header
                total_count = None
                link_header = response.headers.get("Link", "")
                if 'rel="last"' in link_header:
                    import re as regex
                    last_match = regex.search(r'page=(\d+)[^>]*>; rel="last"', link_header)
                    if last_match:
                        last_page = int(last_match.group(1))
                        total_count = last_page * per_page

                return {
                    "branches": branches,
                    "total_count": total_count,
                }

        except httpx.TimeoutException:
            raise ValueError("GitHub API request timed out")
        except Exception as e:
            raise ValueError(f"Failed to fetch branches: {str(e)}")

    async def _get_github_token_from_session(
        self,
        request: Any,
    ) -> Optional[str]:
        """Get GitHub OAuth token from user session.

        Args:
            request: FastAPI request with user context.

        Returns:
            GitHub access token if available, None otherwise.
        """
        # Check for user_id in request state
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return None

        try:
            # Look up GitHub federated identity for user
            with self.pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT access_token
                    FROM federated_identities
                    WHERE user_id = %s
                      AND provider = 'github'
                      AND access_token IS NOT NULL
                    LIMIT 1
                    """,
                    (user_id,)
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
        except Exception:
            pass

        return None
