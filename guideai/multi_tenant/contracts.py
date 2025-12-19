"""Pydantic contracts for multi-tenant entities.

These contracts define the data models for:
- Organizations and memberships
- Projects and project memberships
- Agents (AI agents within organizations)
- Subscriptions and usage records

All contracts align with the PostgreSQL schema defined in migration 023.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Set
from pydantic import BaseModel, Field, field_validator, model_validator
import uuid


# =============================================================================
# Pagination Support
# =============================================================================

class PageInfo(BaseModel):
    """Pagination metadata in responses."""
    total: int = Field(..., description="Total number of items")
    limit: int = Field(..., description="Items per page")
    offset: int = Field(..., description="Current offset")
    has_more: bool = Field(..., description="Whether more items exist")


# =============================================================================
# Enums (matching PostgreSQL ENUMs from migration 023)
# =============================================================================

class OrgPlan(str, Enum):
    """Organization subscription plan tiers."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class OrgStatus(str, Enum):
    """Organization lifecycle status."""
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class MemberRole(str, Enum):
    """Organization-level member roles."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProjectRole(str, Enum):
    """Project-level member roles."""
    OWNER = "owner"
    MAINTAINER = "maintainer"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class ProjectVisibility(str, Enum):
    """Project visibility settings."""
    PRIVATE = "private"      # Only project members
    INTERNAL = "internal"    # All org members
    PUBLIC = "public"        # Anyone (future)


class AgentType(str, Enum):
    """Types of AI agents."""
    ORCHESTRATOR = "orchestrator"
    SPECIALIST = "specialist"
    CUSTOM = "custom"


class AgentStatus(str, Enum):
    """Agent lifecycle status.

    Status transitions:
        ACTIVE -> BUSY, IDLE, PAUSED, DISABLED, ARCHIVED
        BUSY -> ACTIVE, IDLE, PAUSED (cannot go directly to disabled/archived)
        IDLE -> ACTIVE, BUSY, PAUSED, DISABLED, ARCHIVED
        PAUSED -> ACTIVE, DISABLED, ARCHIVED
        DISABLED -> ACTIVE, ARCHIVED
        ARCHIVED -> (none - must use restore_agent to go to ACTIVE)

    Automatic transitions:
        - ACTIVE/IDLE -> BUSY when task is assigned
        - BUSY -> IDLE when task is completed
    """
    ACTIVE = "active"      # Ready and available for work
    BUSY = "busy"          # Currently executing a task
    IDLE = "idle"          # Available but not actively working
    PAUSED = "paused"      # Manually paused by user
    DISABLED = "disabled"  # Administratively disabled
    ARCHIVED = "archived"  # Soft-deleted


class SubscriptionStatus(str, Enum):
    """Stripe subscription status."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"


# =============================================================================
# Base Models
# =============================================================================

class TimestampMixin(BaseModel):
    """Mixin for created_at/updated_at timestamps."""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Organization Models
# =============================================================================

class Organization(TimestampMixin):
    """Organization entity representing a tenant."""

    id: str = Field(default_factory=lambda: f"org-{uuid.uuid4().hex[:12]}")
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    display_name: Optional[str] = None

    plan: OrgPlan = OrgPlan.FREE
    status: OrgStatus = OrgStatus.ACTIVE

    stripe_customer_id: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class CreateOrgRequest(BaseModel):
    """Request to create a new organization."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    display_name: Optional[str] = None
    plan: OrgPlan = OrgPlan.FREE
    settings: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Ensure slug is lowercase and URL-safe."""
        return v.lower().strip()


class UpdateOrgRequest(BaseModel):
    """Request to update an organization."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    display_name: Optional[str] = None
    plan: Optional[OrgPlan] = None
    status: Optional[OrgStatus] = None
    settings: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


# =============================================================================
# Membership Models
# =============================================================================

class OrgMembership(TimestampMixin):
    """Membership linking users to organizations."""

    id: str = Field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:12]}")
    org_id: str
    user_id: str
    role: MemberRole = MemberRole.MEMBER
    invited_by: Optional[str] = None
    invited_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CreateMembershipRequest(BaseModel):
    """Request to add a member to an organization."""

    user_id: str
    role: MemberRole = MemberRole.MEMBER


class UpdateMembershipRequest(BaseModel):
    """Request to update a membership."""

    role: MemberRole


# =============================================================================
# Project Models
# =============================================================================

class Project(TimestampMixin):
    """Project within an organization or owned by a user.

    Projects can be either:
    - Org-owned: org_id is set, owner_id is None
    - User-owned: owner_id is set, org_id is None (personal project)

    Exactly one of org_id or owner_id must be set (XOR constraint).
    """

    id: str = Field(default_factory=lambda: f"proj-{uuid.uuid4().hex[:12]}")
    org_id: Optional[str] = None  # Set for org-owned projects
    owner_id: Optional[str] = None  # Set for user-owned (personal) projects
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = None
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE
    settings: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ownership(self) -> "Project":
        """Ensure exactly one of org_id or owner_id is set."""
        if self.org_id and self.owner_id:
            raise ValueError("Cannot set both org_id and owner_id - project must be org-owned OR user-owned")
        if not self.org_id and not self.owner_id:
            raise ValueError("Must set either org_id or owner_id")
        return self

    class Config:
        from_attributes = True


class CreateProjectRequest(BaseModel):
    """Request to create a new project.

    For org-owned projects, the org_id is typically passed at the service level.
    For user-owned (personal) projects, set owner_id.
    """

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = None
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE
    settings: Dict[str, Any] = Field(default_factory=dict)
    owner_id: Optional[str] = None  # Set for personal projects (no org)


class UpdateProjectRequest(BaseModel):
    """Request to update a project."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    visibility: Optional[ProjectVisibility] = None
    settings: Optional[Dict[str, Any]] = None


# =============================================================================
# Project Membership Models
# =============================================================================

class ProjectMembership(TimestampMixin):
    """Membership linking users to projects."""

    id: str = Field(default_factory=lambda: f"pmem-{uuid.uuid4().hex[:12]}")
    project_id: str
    user_id: str
    role: ProjectRole = ProjectRole.CONTRIBUTOR

    class Config:
        from_attributes = True


class CreateProjectMembershipRequest(BaseModel):
    """Request to add a member to a project."""

    user_id: str
    role: ProjectRole = ProjectRole.CONTRIBUTOR


# =============================================================================
# Agent Models
# =============================================================================

class Agent(TimestampMixin):
    """AI agent within an organization or owned by a user.

    Agents can be either:
    - Org-owned: org_id is set, owner_id is None
    - User-owned: owner_id is set, org_id is None (personal agent)

    Exactly one of org_id or owner_id must be set (XOR constraint).
    """

    id: str = Field(default_factory=lambda: f"agent-{uuid.uuid4().hex[:12]}")
    org_id: Optional[str] = None  # Set for org-owned agents
    owner_id: Optional[str] = None  # Set for user-owned (personal) agents
    project_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=255)
    agent_type: AgentType = AgentType.SPECIALIST
    status: AgentStatus = AgentStatus.ACTIVE
    config: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ownership(self) -> "Agent":
        """Ensure exactly one of org_id or owner_id is set."""
        if self.org_id and self.owner_id:
            raise ValueError("Cannot set both org_id and owner_id - agent must be org-owned OR user-owned")
        if not self.org_id and not self.owner_id:
            raise ValueError("Must set either org_id or owner_id")
        return self

    class Config:
        from_attributes = True


class CreateAgentRequest(BaseModel):
    """Request to create a new agent.

    For org-owned agents, the org_id is typically passed at the service level.
    For user-owned (personal) agents, set owner_id.
    """

    name: str = Field(..., min_length=1, max_length=255)
    project_id: Optional[str] = None
    agent_type: AgentType = AgentType.SPECIALIST
    config: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)
    owner_id: Optional[str] = None  # Set for personal agents (no org)


class UpdateAgentRequest(BaseModel):
    """Request to update an agent."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[AgentStatus] = None
    config: Optional[Dict[str, Any]] = None
    capabilities: Optional[List[str]] = None


# =============================================================================
# Subscription Models
# =============================================================================

class Subscription(TimestampMixin):
    """Stripe subscription for an organization or user.

    Subscriptions can be either:
    - Org-level: org_id is set, user_id is None
    - User-level: user_id is set, org_id is None

    Billing priority: When a user works in an org context, the org subscription
    takes precedence. User subscriptions are used for personal projects.
    """

    id: str = Field(default_factory=lambda: f"sub-{uuid.uuid4().hex[:12]}")
    org_id: Optional[str] = None  # Set for org-level subscription
    user_id: Optional[str] = None  # Set for user-level subscription
    stripe_subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    plan: OrgPlan = OrgPlan.FREE
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_subscription_owner(self) -> "Subscription":
        """Ensure exactly one of org_id or user_id is set."""
        if self.org_id and self.user_id:
            raise ValueError("Cannot set both org_id and user_id - subscription must be org-level OR user-level")
        if not self.org_id and not self.user_id:
            raise ValueError("Must set either org_id or user_id for subscription")
        return self

    class Config:
        from_attributes = True


# =============================================================================
# Usage Models
# =============================================================================

class UsageRecord(BaseModel):
    """Usage tracking for metered billing.

    Usage can be attributed to either:
    - Org-level: org_id is set (usage within org context)
    - User-level: user_id is set, org_id is None (personal project usage)

    When user works in org context, usage goes to org subscription.
    """

    id: str = Field(default_factory=lambda: f"usage-{uuid.uuid4().hex[:12]}")
    org_id: Optional[str] = None  # Set for org-level usage
    user_id: Optional[str] = None  # Set for personal project usage
    metric_name: str
    quantity: int = 0
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_usage_owner(self) -> "UsageRecord":
        """Ensure at least one of org_id or user_id is set."""
        # Note: For usage, we allow both to be set (user working in org context)
        # but at least one must be present
        if not self.org_id and not self.user_id:
            raise ValueError("Must set either org_id or user_id for usage record")
        return self

    class Config:
        from_attributes = True


class RecordUsageRequest(BaseModel):
    """Request to record usage."""

    metric_name: str
    quantity: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Response Models
# =============================================================================

class OrgWithMembers(Organization):
    """Organization with membership info."""

    members: List[OrgMembership] = Field(default_factory=list)
    member_count: int = 0


class OrgWithRole(Organization):
    """Organization with user's role (for list_user_organizations)."""

    role: MemberRole
    member_count: int = 0


class ProjectWithMembers(Project):
    """Project with membership info."""

    members: List[ProjectMembership] = Field(default_factory=list)
    member_count: int = 0


class UserOrganizations(BaseModel):
    """List of organizations a user belongs to."""

    user_id: str
    organizations: List[OrgWithMembers] = Field(default_factory=list)


class OrgContext(BaseModel):
    """Current organization context for a request."""

    org_id: str
    user_id: str
    role: MemberRole
    plan: OrgPlan
    settings: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Project Collaborator Models (for sharing personal projects without orgs)
# =============================================================================

class ProjectCollaborator(TimestampMixin):
    """Collaborator on a user-owned project (personal project sharing).

    This enables users to share personal projects without creating an org.
    The project owner invites collaborators directly.
    """

    id: str = Field(default_factory=lambda: f"collab-{uuid.uuid4().hex[:12]}")
    project_id: str  # Must be a user-owned project (owner_id set)
    user_id: str  # The collaborator being invited
    role: ProjectRole = ProjectRole.CONTRIBUTOR
    invited_by: str  # user_id who sent the invite
    invited_at: datetime = Field(default_factory=datetime.utcnow)
    accepted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AddCollaboratorRequest(BaseModel):
    """Request to add a collaborator to a personal project."""

    user_id: str  # Collaborator to invite
    role: ProjectRole = ProjectRole.CONTRIBUTOR


class UpdateCollaboratorRequest(BaseModel):
    """Request to update a collaborator's role."""

    role: ProjectRole


# =============================================================================
# Billing Context Models
# =============================================================================

class BillingContext(BaseModel):
    """Resolved billing context for a user/project.

    Determines which subscription to bill based on:
    1. If working in org context (org_id set) → use org subscription
    2. If working on personal project → use user subscription

    Org subscription takes precedence when working in org context.
    """

    subscription_id: str
    subscription_type: str  # 'org' or 'user'
    org_id: Optional[str] = None
    user_id: str
    plan: OrgPlan
    status: SubscriptionStatus
    token_budget: int = 100000
    tokens_used: int = 0
    is_within_budget: bool = True


class ResolveBillingRequest(BaseModel):
    """Request to resolve billing context for a user."""

    user_id: str
    org_id: Optional[str] = None  # If set, org subscription takes precedence
    project_id: Optional[str] = None  # Used to determine ownership if org_id not set


# =============================================================================
# User Subscription Request Models
# =============================================================================

class CreateUserSubscriptionRequest(BaseModel):
    """Request to create a user-level subscription."""

    plan: OrgPlan = OrgPlan.FREE
    stripe_payment_method_id: Optional[str] = None


class UserWithSubscription(BaseModel):
    """User with their personal subscription info."""

    user_id: str
    subscription: Optional[Subscription] = None
    has_active_subscription: bool = False
    plan: OrgPlan = OrgPlan.FREE


# =============================================================================
# Invitation Models
# =============================================================================

class InvitationStatus(str, Enum):
    """Invitation lifecycle status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class InvitationChannel(str, Enum):
    """Channel through which invitation was sent."""
    EMAIL = "email"
    SLACK = "slack"
    SMS = "sms"
    LINK = "link"  # Copy-link for manual sharing


class Invitation(TimestampMixin):
    """Organization invitation entity."""

    id: str = Field(default_factory=lambda: f"inv-{uuid.uuid4().hex[:12]}")
    org_id: str
    email: str = Field(..., description="Email address of invitee")
    role: MemberRole = MemberRole.MEMBER
    status: InvitationStatus = InvitationStatus.PENDING
    token: str = Field(default_factory=lambda: uuid.uuid4().hex)
    channel: InvitationChannel = InvitationChannel.EMAIL

    invited_by: str  # User ID who sent invitation
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    accepted_by: Optional[str] = None  # User ID who accepted

    message: Optional[str] = None  # Optional personal message
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class CreateInvitationRequest(BaseModel):
    """Request to create an invitation."""

    email: str = Field(..., description="Email address of invitee")
    role: MemberRole = MemberRole.MEMBER
    channel: InvitationChannel = InvitationChannel.EMAIL
    message: Optional[str] = Field(None, max_length=500, description="Personal message to include")
    expires_in_days: int = Field(default=7, ge=1, le=30, description="Days until expiration")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InvitationEvent(BaseModel):
    """Event tracking invitation lifecycle changes."""

    id: str = Field(default_factory=lambda: f"iev-{uuid.uuid4().hex[:12]}")
    invitation_id: str
    event_type: str  # 'created', 'sent', 'viewed', 'accepted', 'expired', 'revoked'
    actor_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class InvitationWithOrg(BaseModel):
    """Invitation with organization details for display."""

    invitation: Invitation
    org_name: str
    org_slug: str
    inviter_name: Optional[str] = None


class AcceptInvitationRequest(BaseModel):
    """Request to accept an invitation."""

    token: str = Field(..., description="Invitation token from link")
    user_id: str = Field(..., description="User ID accepting the invitation")


class InvitationListResponse(BaseModel):
    """Response for listing invitations."""

    invitations: List[Invitation]
    total: int
    pending_count: int
    page_info: Optional[PageInfo] = None


# =============================================================================
# Agent Status Tracking Models
# =============================================================================


class AgentStatusTransitionTrigger(str, Enum):
    """What triggered an agent status change.

    Used for auditing and to differentiate automatic transitions
    from manual administrative actions.
    """

    MANUAL = "manual"           # Admin/user explicitly changed status
    TASK_START = "task_start"   # Agent started working on a task (IDLE→BUSY)
    TASK_COMPLETE = "task_complete"  # Agent finished a task (BUSY→IDLE)
    TASK_ERROR = "task_error"   # Task failed (BUSY→IDLE)
    SCHEDULED = "scheduled"     # Scheduled maintenance or policy
    API = "api"                 # External API call
    TIMEOUT = "timeout"         # Idle timeout reached
    SYSTEM = "system"           # System-initiated (startup, shutdown)


class AgentStatusChangeRequest(BaseModel):
    """Request to change an agent's status.

    Includes validation for allowed transitions and required fields
    based on target status.
    """

    status: AgentStatus = Field(..., description="Target status")
    reason: Optional[str] = Field(None, max_length=500, description="Reason for status change")
    trigger: AgentStatusTransitionTrigger = Field(
        default=AgentStatusTransitionTrigger.MANUAL,
        description="What triggered this change"
    )
    task_id: Optional[str] = Field(None, description="Associated task ID (for BUSY transitions)")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_task_requirement(self) -> "AgentStatusChangeRequest":
        """Validate that task_id is provided when trigger is task-related."""
        task_triggers = {
            AgentStatusTransitionTrigger.TASK_START,
            AgentStatusTransitionTrigger.TASK_COMPLETE,
            AgentStatusTransitionTrigger.TASK_ERROR,
        }
        if self.trigger in task_triggers and not self.task_id:
            raise ValueError(f"task_id is required when trigger is {self.trigger.value}")
        return self


class AgentStatusEvent(BaseModel):
    """Event tracking agent status changes.

    This event is emitted whenever an agent's status changes, providing
    a complete audit trail for compliance and enabling real-time notifications
    via SSE/WebSocket hooks.
    """

    id: str = Field(default_factory=lambda: f"ase-{uuid.uuid4().hex[:12]}")
    agent_id: str
    org_id: str
    from_status: AgentStatus
    to_status: AgentStatus
    reason: Optional[str] = None
    trigger: AgentStatusTransitionTrigger
    triggered_by: str = Field(..., description="User ID who triggered the change")
    task_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Hook data for SSE/WebSocket integration
    notification_channel: Optional[str] = Field(
        None,
        description="Channel name for real-time notifications (e.g., 'agent:{agent_id}:status')"
    )


class AgentStatusHistory(BaseModel):
    """Response containing agent status change history."""

    agent_id: str
    events: List[AgentStatusEvent]
    total: int
    current_status: AgentStatus


# Valid status transitions matrix
VALID_AGENT_STATUS_TRANSITIONS: Dict[AgentStatus, Set[AgentStatus]] = {
    AgentStatus.ACTIVE: {AgentStatus.BUSY, AgentStatus.PAUSED, AgentStatus.DISABLED, AgentStatus.ARCHIVED},
    AgentStatus.BUSY: {AgentStatus.IDLE, AgentStatus.ACTIVE, AgentStatus.PAUSED},
    AgentStatus.IDLE: {AgentStatus.BUSY, AgentStatus.ACTIVE, AgentStatus.PAUSED, AgentStatus.DISABLED},
    AgentStatus.PAUSED: {AgentStatus.ACTIVE, AgentStatus.IDLE, AgentStatus.DISABLED, AgentStatus.ARCHIVED},
    AgentStatus.DISABLED: {AgentStatus.ACTIVE, AgentStatus.IDLE, AgentStatus.ARCHIVED},
    AgentStatus.ARCHIVED: set(),  # Terminal state - no transitions out
}


def is_valid_status_transition(from_status: AgentStatus, to_status: AgentStatus) -> bool:
    """Check if a status transition is valid.

    Args:
        from_status: Current agent status
        to_status: Desired target status

    Returns:
        True if transition is allowed, False otherwise
    """
    if from_status == to_status:
        return False  # No-op transitions not allowed
    return to_status in VALID_AGENT_STATUS_TRANSITIONS.get(from_status, set())
