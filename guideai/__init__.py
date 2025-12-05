"""GuideAI core package providing service stubs used across parity surfaces."""

from .action_service import (
    ActionService,
    ActionServiceError,
    ActionNotFoundError,
    ReplayNotFoundError,
)
from .action_service_postgres import PostgresActionService
from .action_contracts import Action, ActionCreateRequest, ReplayRequest, ReplayStatus, Actor
from . import bci_contracts
from .bci_service import BCIService
from .agent_auth import (
    AgentAuthClient,
    DecisionReason,
    EnsureGrantRequest,
    EnsureGrantResponse,
    GrantDecision,
    GrantMetadata,
    ListGrantsRequest,
    Obligation,
    PolicyPreviewRequest,
    PolicyPreviewResponse,
    RevokeGrantRequest,
    RevokeGrantResponse,
)
from .run_service import RunService
from .run_service_postgres import PostgresRunService
from .telemetry import InMemoryTelemetrySink, TelemetryClient, TelemetryEvent
from .task_assignments import TaskAssignmentService

__all__ = [
    "ActionService",
    "ActionServiceError",
    "ActionNotFoundError",
    "ReplayNotFoundError",
    "PostgresActionService",
    "Action",
    "ActionCreateRequest",
    "ReplayRequest",
    "ReplayStatus",
    "Actor",
    "AgentAuthClient",
    "EnsureGrantRequest",
    "EnsureGrantResponse",
    "GrantMetadata",
    "GrantDecision",
    "DecisionReason",
    "Obligation",
    "RevokeGrantRequest",
    "RevokeGrantResponse",
    "ListGrantsRequest",
    "PolicyPreviewRequest",
    "PolicyPreviewResponse",
    "RunService",
    "PostgresRunService",
    "TelemetryClient",
    "TelemetryEvent",
    "InMemoryTelemetrySink",
    "TaskAssignmentService",
    "BCIService",
    "bci_contracts",
]
