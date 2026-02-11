"""Amprealize - Infrastructure-as-Code orchestration with blueprint-driven container management.

Amprealize provides a Terraform-like workflow (plan → apply → destroy) for containerized
development environments, with built-in compliance gates, resource estimation, and
lifecycle management.

Basic usage:
    from amprealize import AmprealizeService, PlanRequest, ApplyRequest
    from amprealize.executors import PodmanExecutor

    executor = PodmanExecutor()
    service = AmprealizeService(executor=executor)

    plan = service.plan(PlanRequest(
        blueprint_id="postgres-dev",
        environment="development"
    ))
    result = service.apply(ApplyRequest(plan_id=plan.plan_id))

With hooks for external integration:
    from amprealize import AmprealizeService, AmprealizeHooks

    hooks = AmprealizeHooks(
        on_action=my_action_handler,
        on_compliance_step=my_compliance_handler,
        on_metric=my_metrics_handler,
    )
    service = AmprealizeService(executor=executor, hooks=hooks)
"""

from amprealize.models import (
    # Request/Response models
    PlanRequest,
    PlanResponse,
    ApplyRequest,
    ApplyResponse,
    StatusResponse,
    DestroyRequest,
    DestroyResponse,
    # Infrastructure models
    Blueprint,
    ServiceSpec,
    EnvironmentDefinition,
    RuntimeConfig,
    InfrastructureConfig,
    # Supporting models
    EnvironmentEstimates,
    HealthCheck,
    TelemetryData,
    AuditEntry,
    StatusEvent,
    # Validation models
    EnvironmentManifest,
    StrictEnvironmentDefinition,
    StrictRuntimeConfig,
    StrictInfrastructureConfig,
)
from amprealize.hooks import AmprealizeHooks
from amprealize.service import AmprealizeService

# Orchestrator for workspace management
from amprealize.orchestrator import (
    AmpOrchestrator,
    WorkspaceConfig,
    WorkspaceInfo,
    OrchestratorHooks,
    OrchestratorError,
    WorkspaceNotFoundError,
    QuotaExceededError,
    ProvisionError,
    get_orchestrator,
)

# Quota service for plan-based limits
from amprealize.quota import (
    QuotaService,
    QuotaLimits,
    PLAN_LIMITS,
    get_isolation_scope,
    parse_scope,
    get_quota_service,
    reset_quota_service,
    EnvironmentPlanResolver,
    DatabasePlanResolver,
)

__version__ = "0.1.0"
__all__ = [
    # Core service
    "AmprealizeService",
    "AmprealizeHooks",
    # Orchestrator
    "AmpOrchestrator",
    "WorkspaceConfig",
    "WorkspaceInfo",
    "OrchestratorHooks",
    "OrchestratorError",
    "WorkspaceNotFoundError",
    "QuotaExceededError",
    "ProvisionError",
    "get_orchestrator",
    # Quota service
    "QuotaService",
    "QuotaLimits",
    "PLAN_LIMITS",
    "get_isolation_scope",
    "parse_scope",
    "get_quota_service",
    "reset_quota_service",
    "EnvironmentPlanResolver",
    "DatabasePlanResolver",
    # Request/Response models
    "PlanRequest",
    "PlanResponse",
    "ApplyRequest",
    "ApplyResponse",
    "StatusResponse",
    "DestroyRequest",
    "DestroyResponse",
    # Infrastructure models
    "Blueprint",
    "ServiceSpec",
    "EnvironmentDefinition",
    "RuntimeConfig",
    "InfrastructureConfig",
    # Supporting models
    "EnvironmentEstimates",
    "HealthCheck",
    "TelemetryData",
    "AuditEntry",
    "StatusEvent",
    # Validation models
    "EnvironmentManifest",
    "StrictEnvironmentDefinition",
    "StrictRuntimeConfig",
    "StrictInfrastructureConfig",
    # Blueprints utilities
    "get_blueprint_path",
    "list_blueprints",
]

# Blueprint utilities
from amprealize.blueprints import get_blueprint_path, list_blueprints
