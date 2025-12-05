"""GuideAI Amprealize integration.

This module provides a thin wrapper around the standalone amprealize package,
wiring it to guideai services (ActionService, ComplianceService, MetricsService).

For standalone usage without guideai, use the amprealize package directly:
    pip install amprealize
    from amprealize import AmprealizeService, PlanRequest

NOTE: The standalone amprealize package is REQUIRED. Install with:
    pip install -e ./packages/amprealize
"""

# Re-export models from standalone package
from amprealize import (
    # Request/Response models
    PlanRequest,
    PlanResponse,
    EnvironmentEstimates,
    ApplyRequest,
    ApplyResponse,
    StatusResponse,
    HealthCheck,
    TelemetryData,
    DestroyRequest,
    DestroyResponse,
    # Infrastructure models
    Blueprint,
    ServiceSpec,
    EnvironmentDefinition,
    RuntimeConfig,
    InfrastructureConfig,
    AuditEntry,
    StatusEvent,
    # Hooks
    AmprealizeHooks,
    # Blueprint utilities
    get_blueprint_path,
    list_blueprints,
    # Bandwidth enforcement
)
from amprealize.service import BandwidthEnforcer

# Import the guideai-integrated service wrapper
from .service import GuideAIAmprealizeService as AmprealizeService
from .service import RedisNotAvailableError

__all__ = [
    # Request/Response models
    "PlanRequest",
    "PlanResponse",
    "EnvironmentEstimates",
    "ApplyRequest",
    "ApplyResponse",
    "StatusResponse",
    "HealthCheck",
    "TelemetryData",
    "DestroyRequest",
    "DestroyResponse",
    # Infrastructure models
    "Blueprint",
    "ServiceSpec",
    "EnvironmentDefinition",
    "RuntimeConfig",
    "InfrastructureConfig",
    "AuditEntry",
    "StatusEvent",
    # Hooks
    "AmprealizeHooks",
    # Service (guideai-integrated wrapper)
    "AmprealizeService",
    # Errors
    "RedisNotAvailableError",
    # Blueprint utilities
    "get_blueprint_path",
    "list_blueprints",
    # Bandwidth enforcement
    "BandwidthEnforcer",
]
