"""GuideAI core package providing service stubs used across parity surfaces."""

from .action_service import ActionService
from .action_contracts import Action, ActionCreateRequest, ReplayRequest, ReplayStatus, Actor
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
from .telemetry import TelemetryClient, TelemetryEvent, InMemoryTelemetrySink

__all__ = [
    "ActionService",
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
    "TelemetryClient",
    "TelemetryEvent",
    "InMemoryTelemetrySink",
]
