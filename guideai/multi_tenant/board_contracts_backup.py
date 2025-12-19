"""
Board Contracts - Pydantic models for Agile Board System

Implements polymorphic assignment (user OR agent) for stories and tasks.
Supports Kanban/Scrum workflows with sprints, epics, stories, and tasks.

Feature: 13.4.5 (Agent assignment to tasks) + 13.5.x (Agile Board System)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# Enums
# =============================================================================

class AssigneeType(str, Enum):
    """Type of assignee - user or agent (single assignee only)."""
    USER = "user"
    AGENT = "agent"


class WorkItemStatus(str, Enum):
    """Status for stories and tasks."""
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class EpicStatus(str, Enum):
    """Status for epics (higher-level milestones)."""
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkItemPriority(str, Enum):
    """Priority levels for work items."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskType(str, Enum):
    """Types of tasks."""
    FEATURE = "feature"
    BUG = "bug"
    CHORE = "chore"
    SPIKE = "spike"
    DOCUMENTATION = "documentation"


class SprintStatus(str, Enum):
    """Sprint lifecycle status."""
    PLANNING = "planning"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AssignmentAction(str, Enum):
    """Assignment history action types."""
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    REASSIGNED = "reassigned"


# =============================================================================
# Valid Status Transitions
# =============================================================================

VALID_WORK_ITEM_TRANSITIONS: dict[WorkItemStatus, list[WorkItemStatus]] = {
    WorkItemStatus.BACKLOG: [WorkItemStatus.TODO, WorkItemStatus.CANCELLED],
    WorkItemStatus.TODO: [WorkItemStatus.IN_PROGRESS, WorkItemStatus.BACKLOG, WorkItemStatus.CANCELLED],
    WorkItemStatus.IN_PROGRESS: [WorkItemStatus.IN_REVIEW, WorkItemStatus.TODO, WorkItemStatus.CANCELLED],
    WorkItemStatus.IN_REVIEW: [WorkItemStatus.DONE, WorkItemStatus.IN_PROGRESS, WorkItemStatus.CANCELLED],
    WorkItemStatus.DONE: [WorkItemStatus.TODO],  # Reopen
    WorkItemStatus.CANCELLED: [WorkItemStatus.BACKLOG],  # Restore
}

VALID_EPIC_TRANSITIONS: dict[EpicStatus, list[EpicStatus]] = {
    EpicStatus.DRAFT: [EpicStatus.ACTIVE, EpicStatus.CANCELLED],
    EpicStatus.ACTIVE: [EpicStatus.COMPLETED, EpicStatus.CANCELLED, EpicStatus.DRAFT],
    EpicStatus.COMPLETED: [EpicStatus.ACTIVE],  # Reopen
    EpicStatus.CANCELLED: [EpicStatus.DRAFT],  # Restore
}


def is_valid_work_item_transition(from_status: WorkItemStatus, to_status: WorkItemStatus) -> bool:
    """Check if a work item status transition is valid."""
    return to_status in VALID_WORK_ITEM_TRANSITIONS.get(from_status, [])


def is_valid_epic_transition(from_status: EpicStatus, to_status: EpicStatus) -> bool:
    """Check if an epic status transition is valid."""
    return to_status in VALID_EPIC_TRANSITIONS.get(from_status, [])


# =============================================================================
# Base Models
# =============================================================================

class BoardVisibility(str, Enum):
    """Board visibility settings (can override project visibility)."""
    INHERIT = "inherit"      # Inherit from parent project (default)
    PRIVATE = "private"      # Only board members can access
    INTERNAL = "internal"    # All org members can access
    PUBLIC = "public"        # Anyone (future)


class BoardSettings(BaseModel):
    """Board configuration settings."""
    default_column_id: str | None = None
    auto_archive_after_days: int | None = None
    show_story_points: bool = True
    show_due_dates: bool = True
    allow_subtasks: bool = True
    # Visibility inheritance: defaults to INHERIT (from project)
    visibility: BoardVisibility = BoardVisibility.INHERIT


class AcceptanceCriterion(BaseModel):
    """Single acceptance criterion for a story."""
    id: str
    description: str
    is_met: bool = False
    verified_by: str | None = None
    verified_at: datetime | None = None


class ChecklistItem(BaseModel):
    """Single checklist item for a task."""
    id: str
    description: str
    is_done: bool = False
    completed_by: str | None = None
    completed_at: datetime | None = None


# =============================================================================
# Board Models
# =============================================================================

class Board(BaseModel):
    """Kanban/Scrum board for project management."""
    board_id: str = Field(..., pattern=r"^brd-[a-f0-9]{12}$")
    project_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    settings: BoardSettings = Field(default_factory=BoardSettings)
    created_at: datetime
    updated_at: datetime
    created_by: str
    is_default: bool = False
    org_id: str | None = None


class BoardColumn(BaseModel):
    """Column in a board (maps to work item status)."""
    column_id: str = Field(..., pattern=r"^col-[a-f0-9]{12}$")
    board_id: str
    name: str = Field(..., min_length=1, max_length=100)
    position: int = Field(..., ge=0)
    status_mapping: WorkItemStatus
    wip_limit: int | None = Field(None, ge=1)
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CreateBoardRequest(BaseModel):
    """Request to create a new board."""
    project_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    settings: BoardSettings | None = None
    is_default: bool = False
    create_default_columns: bool = True  # Auto-create Backlog, To Do, In Progress, In Review, Done


class UpdateBoardRequest(BaseModel):
    """Request to update a board."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    settings: BoardSettings | None = None
    is_default: bool | None = None


class CreateColumnRequest(BaseModel):
    """Request to create a board column."""
    board_id: str
    name: str = Field(..., min_length=1, max_length=100)
    position: int = Field(0, ge=0)
    status_mapping: WorkItemStatus
    wip_limit: int | None = Field(None, ge=1)


class UpdateColumnRequest(BaseModel):
    """Request to update a board column."""
    name: str | None = Field(None, min_length=1, max_length=100)
    position: int | None = Field(None, ge=0)
    status_mapping: WorkItemStatus | None = None
    wip_limit: int | None = Field(None, ge=1)


# =============================================================================
# Epic Models
# =============================================================================

class Epic(BaseModel):
    """Epic - high-level milestone grouping stories."""
    epic_id: str = Field(..., pattern=r"^epic-[a-f0-9]{12}$")
    project_id: str
    board_id: str | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    status: EpicStatus = EpicStatus.DRAFT
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    color: str | None = Field(None, pattern=r"^#[a-fA-F0-9]{6}$")
    start_date: date | None = None
    target_date: date | None = None
    completed_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    created_by: str
    org_id: str | None = None

    # Computed fields (populated by service)
    story_count: int | None = None
    completed_story_count: int | None = None
    progress_percent: float | None = None


class CreateEpicRequest(BaseModel):
    """Request to create an epic."""
    project_id: str
    board_id: str | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    color: str | None = Field(None, pattern=r"^#[a-fA-F0-9]{6}$")
    start_date: date | None = None
    target_date: date | None = None
    labels: list[str] = Field(default_factory=list)


class UpdateEpicRequest(BaseModel):
    """Request to update an epic."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    status: EpicStatus | None = None
    priority: WorkItemPriority | None = None
    color: str | None = Field(None, pattern=r"^#[a-fA-F0-9]{6}$")
    start_date: date | None = None
    target_date: date | None = None
    labels: list[str] | None = None


# =============================================================================
# Story Models
# =============================================================================

class Assignee(BaseModel):
    """Polymorphic assignee reference."""
    assignee_id: str
    assignee_type: AssigneeType
    assigned_at: datetime | None = None
    assigned_by: str | None = None


class Story(BaseModel):
    """User story - work item that can be assigned to user or agent."""
    story_id: str = Field(..., pattern=r"^story-[a-f0-9]{12}$")
    project_id: str
    board_id: str | None = None
    epic_id: str | None = None
    column_id: str | None = None

    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    status: WorkItemStatus = WorkItemStatus.BACKLOG
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    story_points: int | None = Field(None, ge=0)
    position: int = 0

    # Single assignee (user OR agent)
    assignee_id: str | None = None
    assignee_type: AssigneeType | None = None
    assigned_at: datetime | None = None
    assigned_by: str | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None
    due_date: date | None = None

    labels: list[str] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    created_by: str
    org_id: str | None = None

    # Computed fields
    task_count: int | None = None
    completed_task_count: int | None = None

    @model_validator(mode="after")
    def validate_assignee(self) -> "Story":
        """Ensure assignee_id and assignee_type are both set or both null."""
        if (self.assignee_id is None) != (self.assignee_type is None):
            raise ValueError("assignee_id and assignee_type must both be set or both be null")
        return self


class CreateStoryRequest(BaseModel):
    """Request to create a story."""
    project_id: str
    board_id: str | None = None
    epic_id: str | None = None
    column_id: str | None = None
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    story_points: int | None = Field(None, ge=0)
    due_date: date | None = None
    labels: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)  # Simple strings, converted to AcceptanceCriterion


class UpdateStoryRequest(BaseModel):
    """Request to update a story."""
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    status: WorkItemStatus | None = None
    priority: WorkItemPriority | None = None
    story_points: int | None = Field(None, ge=0)
    column_id: str | None = None
    epic_id: str | None = None
    position: int | None = None
    due_date: date | None = None
    labels: list[str] | None = None
    acceptance_criteria: list[AcceptanceCriterion] | None = None


class MoveStoryRequest(BaseModel):
    """Request to move a story to a different column/position."""
    column_id: str
    position: int = 0


# =============================================================================
# Task Models
# =============================================================================

class Task(BaseModel):
    """Task - subtask of a story, can be assigned to user or agent."""
    task_id: str = Field(..., pattern=r"^task-[a-f0-9]{12}$")
    project_id: str
    story_id: str | None = None
    board_id: str | None = None
    column_id: str | None = None

    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    task_type: TaskType = TaskType.FEATURE
    status: WorkItemStatus = WorkItemStatus.TODO
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    estimated_hours: Decimal | None = Field(None, ge=0)
    actual_hours: Decimal | None = Field(None, ge=0)
    position: int = 0

    # Single assignee (user OR agent)
    assignee_id: str | None = None
    assignee_type: AssigneeType | None = None
    assigned_at: datetime | None = None
    assigned_by: str | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None
    due_date: date | None = None

    # Agent-specific fields
    behavior_id: str | None = None  # behavior_* reference
    run_id: str | None = None  # Execution run reference

    labels: list[str] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    created_by: str
    org_id: str | None = None

    @model_validator(mode="after")
    def validate_assignee(self) -> "Task":
        """Ensure assignee_id and assignee_type are both set or both null."""
        if (self.assignee_id is None) != (self.assignee_type is None):
            raise ValueError("assignee_id and assignee_type must both be set or both be null")
        return self


class CreateTaskRequest(BaseModel):
    """Request to create a task."""
    project_id: str
    story_id: str | None = None
    board_id: str | None = None
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    task_type: TaskType = TaskType.FEATURE
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    estimated_hours: Decimal | None = Field(None, ge=0)
    due_date: date | None = None
    labels: list[str] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)  # Simple strings, converted to ChecklistItem
    behavior_id: str | None = None


class UpdateTaskRequest(BaseModel):
    """Request to update a task."""
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    task_type: TaskType | None = None
    status: WorkItemStatus | None = None
    priority: WorkItemPriority | None = None
    estimated_hours: Decimal | None = Field(None, ge=0)
    actual_hours: Decimal | None = Field(None, ge=0)
    column_id: str | None = None
    story_id: str | None = None
    position: int | None = None
    due_date: date | None = None
    labels: list[str] | None = None
    checklist: list[ChecklistItem] | None = None
    behavior_id: str | None = None
    run_id: str | None = None


# =============================================================================
# Assignment Models
# =============================================================================

class AssignAgentRequest(BaseModel):
    """Request to assign an agent to a story or task."""
    assignable_id: str  # story_id or task_id
    assignable_type: Literal["story", "task"]
    agent_id: str  # Agent to assign
    reason: str | None = None


class AssignUserRequest(BaseModel):
    """Request to assign a user to a story or task."""
    assignable_id: str  # story_id or task_id
    assignable_type: Literal["story", "task"]
    user_id: str  # User to assign
    reason: str | None = None


class UnassignRequest(BaseModel):
    """Request to unassign current assignee."""
    assignable_id: str
    assignable_type: Literal["story", "task"]
    reason: str | None = None


class ReassignRequest(BaseModel):
    """Request to reassign to a different user/agent."""
    assignable_id: str
    assignable_type: Literal["story", "task"]
    new_assignee_id: str
    new_assignee_type: AssigneeType
    reason: str | None = None


class AssignmentHistory(BaseModel):
    """History record for assignment changes."""
    history_id: str = Field(..., pattern=r"^ahist-[a-f0-9]{12}$")
    assignable_id: str
    assignable_type: Literal["story", "task"]
    assignee_id: str | None = None
    assignee_type: AssigneeType | None = None
    action: AssignmentAction
    performed_by: str
    performed_at: datetime
    previous_assignee_id: str | None = None
    previous_assignee_type: AssigneeType | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    org_id: str | None = None


# =============================================================================
# Agent Suggestion Models (for board.suggest_agent MCP tool)
# =============================================================================

class AgentWorkload(BaseModel):
    """Agent workload metrics for capacity planning."""
    agent_id: str
    agent_name: str
    active_items: int = 0  # Stories + tasks in progress
    in_progress_count: int = 0
    completed_count: int = 0
    total_story_points: int = 0
    allowed_behaviors: list[str] = Field(default_factory=list)

    # Capacity metrics
    max_concurrent_items: int | None = None  # From agent config
    utilization_percent: float | None = None  # active_items / max_concurrent_items


class SuggestAgentRequest(BaseModel):
    """Request to suggest best agent for a story/task."""
    assignable_id: str
    assignable_type: Literal["story", "task"]
    required_behaviors: list[str] = Field(default_factory=list)  # Filter by allowed_behaviors
    max_suggestions: int = Field(3, ge=1, le=10)
    exclude_agent_ids: list[str] = Field(default_factory=list)


class AgentSuggestion(BaseModel):
    """Single agent suggestion with scoring."""
    agent_id: str
    agent_name: str
    score: float = Field(..., ge=0.0, le=1.0)  # 0-1 composite score
    behavior_match_score: float = Field(..., ge=0.0, le=1.0)
    workload_score: float = Field(..., ge=0.0, le=1.0)  # Lower workload = higher score
    current_workload: AgentWorkload
    matched_behaviors: list[str] = Field(default_factory=list)
    reason: str  # Human-readable explanation


class SuggestAgentResponse(BaseModel):
    """Response with agent suggestions."""
    suggestions: list[AgentSuggestion]
    assignable_id: str
    assignable_type: Literal["story", "task"]
    required_behaviors: list[str]
    total_eligible_agents: int


# =============================================================================
# Sprint Models
# =============================================================================

class Sprint(BaseModel):
    """Sprint for time-boxed work."""
    sprint_id: str = Field(..., pattern=r"^sprint-[a-f0-9]{12}$")
    project_id: str
    board_id: str
    name: str = Field(..., min_length=1, max_length=255)
    goal: str | None = None
    status: SprintStatus = SprintStatus.PLANNING
    start_date: date
    end_date: date
    velocity_planned: int | None = None
    velocity_completed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    created_by: str
    org_id: str | None = None

    # Computed
    story_ids: list[str] = Field(default_factory=list)
    story_count: int | None = None
    completed_story_count: int | None = None

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: date, info) -> date:
        """Ensure end_date is after start_date."""
        start = info.data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        return v


class CreateSprintRequest(BaseModel):
    """Request to create a sprint."""
    project_id: str
    board_id: str
    name: str = Field(..., min_length=1, max_length=255)
    goal: str | None = None
    start_date: date
    end_date: date
    velocity_planned: int | None = Field(None, ge=0)
    story_ids: list[str] = Field(default_factory=list)  # Stories to add to sprint


class UpdateSprintRequest(BaseModel):
    """Request to update a sprint."""
    name: str | None = Field(None, min_length=1, max_length=255)
    goal: str | None = None
    status: SprintStatus | None = None
    start_date: date | None = None
    end_date: date | None = None
    velocity_planned: int | None = Field(None, ge=0)
    velocity_completed: int | None = Field(None, ge=0)


# =============================================================================
# List/Filter Models
# =============================================================================

class ListBoardsRequest(BaseModel):
    """Request to list boards."""
    project_id: str | None = None
    include_columns: bool = False
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class ListEpicsRequest(BaseModel):
    """Request to list epics."""
    project_id: str | None = None
    board_id: str | None = None
    status: list[EpicStatus] | None = None
    include_progress: bool = False
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class ListStoriesRequest(BaseModel):
    """Request to list stories."""
    project_id: str | None = None
    board_id: str | None = None
    epic_id: str | None = None
    column_id: str | None = None
    sprint_id: str | None = None
    status: list[WorkItemStatus] | None = None
    assignee_id: str | None = None
    assignee_type: AssigneeType | None = None
    unassigned_only: bool = False
    include_tasks: bool = False
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class ListTasksRequest(BaseModel):
    """Request to list tasks."""
    project_id: str | None = None
    story_id: str | None = None
    board_id: str | None = None
    status: list[WorkItemStatus] | None = None
    task_type: list[TaskType] | None = None
    assignee_id: str | None = None
    assignee_type: AssigneeType | None = None
    unassigned_only: bool = False
    behavior_id: str | None = None
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


# =============================================================================
# Response Models
# =============================================================================

class BoardWithColumns(Board):
    """Board with columns included."""
    columns: list[BoardColumn] = Field(default_factory=list)


class StoryWithTasks(Story):
    """Story with tasks included."""
    tasks: list[Task] = Field(default_factory=list)


class ListBoardsResponse(BaseModel):
    """Response for list boards."""
    boards: list[Board | BoardWithColumns]
    total: int
    limit: int
    offset: int


class ListEpicsResponse(BaseModel):
    """Response for list epics."""
    epics: list[Epic]
    total: int
    limit: int
    offset: int


class ListStoriesResponse(BaseModel):
    """Response for list stories."""
    stories: list[Story | StoryWithTasks]
    total: int
    limit: int
    offset: int


class ListTasksResponse(BaseModel):
    """Response for list tasks."""
    tasks: list[Task]
    total: int
    limit: int
    offset: int


# =============================================================================
# Delete Request/Response Models
# =============================================================================

class DeleteEpicRequest(BaseModel):
    """Request to delete an epic."""
    hard_delete: bool = False  # If True, permanently delete; else soft-delete (status→cancelled)
    reason: str | None = None


class DeleteStoryRequest(BaseModel):
    """Request to delete a story."""
    hard_delete: bool = False  # If True, permanently delete; else soft-delete (status→cancelled)
    reason: str | None = None


class DeleteTaskRequest(BaseModel):
    """Request to delete a task."""
    hard_delete: bool = False  # If True, permanently delete; else soft-delete (status→cancelled)
    reason: str | None = None


class DeleteResult(BaseModel):
    """Result of a delete operation."""
    id: str
    entity_type: Literal["epic", "story", "task"]
    deleted: bool
    hard_deleted: bool
    deleted_at: datetime
    deleted_by: str
    reason: str | None = None


# =============================================================================
# Attachment Models (URL placeholders - actual storage deferred)
# =============================================================================

class Attachment(BaseModel):
    """Attachment reference - URL placeholder for future file storage."""
    id: str = Field(..., pattern=r"^att-[a-f0-9]{12}$")
    filename: str = Field(..., min_length=1, max_length=255)
    url: str  # Placeholder URL - actual storage deferred
    content_type: str | None = None
    size_bytes: int | None = Field(None, ge=0)
    uploaded_by: str
    uploaded_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddAttachmentRequest(BaseModel):
    """Request to add an attachment to a story or task."""
    entity_id: str  # story_id or task_id
    entity_type: Literal["story", "task"]
    filename: str = Field(..., min_length=1, max_length=255)
    url: str  # Placeholder URL
    content_type: str | None = None
    size_bytes: int | None = Field(None, ge=0)


class RemoveAttachmentRequest(BaseModel):
    """Request to remove an attachment."""
    entity_id: str
    entity_type: Literal["story", "task"]
    attachment_id: str


# =============================================================================
# Acceptance Criteria Operations
# =============================================================================

class AddAcceptanceCriterionRequest(BaseModel):
    """Request to add an acceptance criterion to a story."""
    story_id: str
    description: str = Field(..., min_length=1, max_length=1000)


class UpdateAcceptanceCriterionRequest(BaseModel):
    """Request to update an acceptance criterion."""
    story_id: str
    criterion_id: str
    description: str | None = Field(None, min_length=1, max_length=1000)
    is_met: bool | None = None


class ToggleCriterionCompleteRequest(BaseModel):
    """Request to toggle an acceptance criterion completion status."""
    story_id: str
    criterion_id: str


class DeleteAcceptanceCriterionRequest(BaseModel):
    """Request to delete an acceptance criterion."""
    story_id: str
    criterion_id: str


# =============================================================================
# Checklist Operations
# =============================================================================

class AddChecklistItemRequest(BaseModel):
    """Request to add a checklist item to a task."""
    task_id: str
    description: str = Field(..., min_length=1, max_length=500)


class ToggleChecklistItemRequest(BaseModel):
    """Request to toggle a checklist item completion status."""
    task_id: str
    item_id: str


class DeleteChecklistItemRequest(BaseModel):
    """Request to delete a checklist item."""
    task_id: str
    item_id: str


# =============================================================================
# Board Event Models (for webhooks/event emission)
# =============================================================================

class BoardEventType(str, Enum):
    """Types of board events for webhooks."""
    # Epic events
    EPIC_CREATED = "epic.created"
    EPIC_UPDATED = "epic.updated"
    EPIC_DELETED = "epic.deleted"
    EPIC_STATUS_CHANGED = "epic.status_changed"

    # Story events
    STORY_CREATED = "story.created"
    STORY_UPDATED = "story.updated"
    STORY_DELETED = "story.deleted"
    STORY_STATUS_CHANGED = "story.status_changed"
    STORY_MOVED = "story.moved"
    STORY_ASSIGNED = "story.assigned"
    STORY_UNASSIGNED = "story.unassigned"
    STORY_REASSIGNED = "story.reassigned"

    # Task events
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_DELETED = "task.deleted"
    TASK_STATUS_CHANGED = "task.status_changed"
    TASK_ASSIGNED = "task.assigned"
    TASK_UNASSIGNED = "task.unassigned"
    TASK_REASSIGNED = "task.reassigned"

    # Acceptance criteria events
    CRITERION_ADDED = "criterion.added"
    CRITERION_MET = "criterion.met"
    CRITERION_UNMET = "criterion.unmet"

    # Checklist events
    CHECKLIST_ITEM_ADDED = "checklist_item.added"
    CHECKLIST_ITEM_COMPLETED = "checklist_item.completed"
    CHECKLIST_ITEM_UNCOMPLETED = "checklist_item.uncompleted"


class BoardEvent(BaseModel):
    """Event emitted for board changes (for webhooks/notifications)."""
    event_id: str = Field(..., pattern=r"^bevt-[a-f0-9]{12}$")
    event_type: BoardEventType
    entity_id: str  # epic_id, story_id, or task_id
    entity_type: Literal["epic", "story", "task", "criterion", "checklist_item"]
    project_id: str
    org_id: str | None = None
    actor_id: str
    actor_type: Literal["user", "agent", "system"]
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Assignment History Query
# =============================================================================

class ListAssignmentHistoryRequest(BaseModel):
    """Request to list assignment history for an entity."""
    assignable_id: str
    assignable_type: Literal["story", "task"]
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class ListAssignmentHistoryResponse(BaseModel):
    """Response for assignment history query."""
    history: list[AssignmentHistory]
    total: int
    limit: int
    offset: int
