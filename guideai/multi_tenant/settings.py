"""Settings service — enterprise feature.

Full implementation available in guideai-enterprise package.
Install: pip install guideai-enterprise

Settings Pydantic models (OrgSettings, ProjectSettings, BrandingSettings, etc.)
and SettingsService are enterprise-only features.
"""

try:
    from guideai_enterprise.multi_tenant.settings import (
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
except ImportError:
    SettingsService = None
    OrgSettings = None
    ProjectSettings = None
    BrandingSettings = None
    NotificationSettings = None
    SecuritySettings = None
    IntegrationSettings = None
    WorkflowSettings = None
    AgentSettings = None
    UpdateBrandingRequest = None
    UpdateNotificationRequest = None
    UpdateSecurityRequest = None
    UpdateWorkflowRequest = None

__all__ = [
    "SettingsService",
    "OrgSettings",
    "ProjectSettings",
    "BrandingSettings",
    "NotificationSettings",
    "SecuritySettings",
    "IntegrationSettings",
    "WorkflowSettings",
    "AgentSettings",
    "UpdateBrandingRequest",
    "UpdateNotificationRequest",
    "UpdateSecurityRequest",
    "UpdateWorkflowRequest",
]
