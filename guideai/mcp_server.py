#!/usr/bin/env python3
"""
GuideAI MCP Server

Model Context Protocol server providing stdio-based JSON-RPC interface for GuideAI tools.
Enables AI assistants (Claude Desktop, Cursor, Cline) to authenticate and interact with
GuideAI via standardized MCP protocol.

Supported Tools:
- auth.deviceLogin - OAuth 2.0 device authorization flow
- auth.authStatus - Check authentication status
- auth.refreshToken - Refresh expired access tokens
- auth.logout - Revoke tokens and clear storage
- [Future] behaviors.*, workflows.*, runs.*, etc.

Usage:
    # Run standalone:
    python -m guideai.mcp_server

    # Configure in Claude Desktop (~/Library/Application Support/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "guideai": {
          "command": "python",
          "args": ["-m", "guideai.mcp_server"]
        }
      }
    }

Protocol:
    - Input: JSON-RPC 2.0 requests via stdin
    - Output: JSON-RPC 2.0 responses via stdout
    - Logging: stderr (structured JSON logs)
"""

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

# MCP protocol types

from .action_service import ActionService
from .action_service_postgres import PostgresActionService
from .bci_service import BCIService
from .behavior_service import BehaviorService
from .workflow_service import WorkflowService
from .storage.postgres_pool import PostgresPool
from .utils.dsn import apply_host_overrides


@dataclass
class MCPRequest:
    """MCP JSON-RPC 2.0 request."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: str = ""
    params: Optional[Dict[str, Any]] = None


@dataclass
class MCPResponse:
    """MCP JSON-RPC 2.0 response."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


@dataclass
class MCPError:
    """MCP JSON-RPC error object."""
    code: int
    message: str
    data: Optional[Any] = None


class MCPServiceRegistry:
    """Lazy initializer for MCP service singletons using PostgreSQL DSNs."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger("guideai.mcp_server.services")
        self._behavior_service: Optional[BehaviorService] = None
        self._bci_service: Optional[BCIService] = None
        self._workflow_service: Optional[WorkflowService] = None
        self._action_service: Optional[Union[PostgresActionService, ActionService]] = None
        self._trace_analysis_service: Optional[Any] = None
        self._run_service: Optional[Any] = None
        self._metrics_service: Optional[Any] = None
        self._analytics_service: Optional[Any] = None
        self._agent_orchestrator_service: Optional[Any] = None
        self._compliance_service: Optional[Any] = None
        self._audit_log_service: Optional[Any] = None
        self._agent_auth_service: Optional[Any] = None
        self._task_assignment_service: Optional[Any] = None
        self._raze_service: Optional[Any] = None
        self._amprealize_service: Optional[Any] = None

        # Epic 7 Advanced Features services
        self._fine_tuning_service: Optional[Any] = None
        self._agent_review_service: Optional[Any] = None
        self._multi_tenant_service: Optional[Any] = None
        self._advanced_retrieval_service: Optional[Any] = None
        self._collaboration_service: Optional[Any] = None
        self._api_rate_limiting_service: Optional[Any] = None
        self._reflection_service: Optional[Any] = None

        # Multi-tenant services for orgs/projects/boards
        self._organization_service: Optional[Any] = None
        self._board_service: Optional[Any] = None
        self._agent_registry_service: Optional[Any] = None

        # Work item execution
        self._work_item_execution_service: Optional[Any] = None

        # File and GitHub services
        self._github_service: Optional[Any] = None

        # Config services
        self._credential_store: Optional[Any] = None

        # Shared connection pools for PostgreSQL services
        # Note: Services create their own PostgresPool instances, but PostgresPool
        # internally caches engines by DSN, so multiple services with the same DSN
        # will share the same underlying connection pool (via _POOL_CACHE).
        self._pools: Dict[str, PostgresPool] = {}

    def _get_pool(self, dsn: str, service_name: str) -> PostgresPool:
        """
        Get or create a PostgresPool for the given DSN and service.

        This method is primarily for pre-warming pools or getting pool metrics.
        Services create their own PostgresPool instances, but the internal
        _POOL_CACHE ensures they share the same SQLAlchemy engine.
        """
        if dsn not in self._pools:
            self._pools[dsn] = PostgresPool(dsn=dsn, service_name=service_name)
            self._logger.info(f"Created PostgresPool for {service_name}")
        return self._pools[dsn]

    def prewarm_pools(self) -> None:
        """Pre-warm connection pools for all configured PostgreSQL services.

        Validates database connectivity and provides clear error diagnostics
        including DSN comparison when connections fail.
        """
        dsn_map = {
            "GUIDEAI_BEHAVIOR_PG_DSN": "behavior",
            "GUIDEAI_WORKFLOW_PG_DSN": "workflow",
            "GUIDEAI_ACTION_PG_DSN": "action",
            "GUIDEAI_RUN_PG_DSN": "run",
            "GUIDEAI_METRICS_PG_DSN": "metrics",
            "GUIDEAI_COMPLIANCE_PG_DSN": "compliance",
            "GUIDEAI_REFLECTION_PG_DSN": "reflection",
            "GUIDEAI_COLLABORATION_PG_DSN": "collaboration",
        }

        failed_services: list[tuple[str, str, str]] = []  # (service, env_var, error)

        for env_var, service_name in dsn_map.items():
            raw_dsn = os.environ.get(env_var)
            dsn = apply_host_overrides(raw_dsn, service_name.upper())
            if dsn:
                try:
                    pool = self._get_pool(dsn, service_name)
                    # Test connection
                    with pool.connection() as conn:
                        cur = conn.cursor()
                        try:
                            cur.execute("SELECT 1")
                        finally:
                            cur.close()
                    self._logger.info(f"Pre-warmed {service_name} pool successfully")
                except Exception as e:
                    # Extract connection details for diagnostic (hide password)
                    dsn_diagnostic = self._sanitize_dsn_for_logging(dsn)
                    error_msg = str(e)
                    failed_services.append((service_name, env_var, error_msg))
                    self._logger.error(
                        f"❌ Database connection failed for {service_name}:\n"
                        f"   Environment variable: {env_var}\n"
                        f"   DSN (sanitized): {dsn_diagnostic}\n"
                        f"   Error: {error_msg}\n"
                        f"   💡 Check that .env matches your database configuration "
                        f"(port, credentials, database name)"
                    )

        # Log summary if any failures occurred
        if failed_services:
            service_names = ", ".join(s[0] for s in failed_services)
            self._logger.warning(
                f"⚠️  {len(failed_services)} database connection(s) failed: {service_names}\n"
                f"   Some MCP tools may not work. Check your .env configuration."
            )

    def _sanitize_dsn_for_logging(self, dsn: str) -> str:
        """Remove password from DSN for safe logging."""
        import re
        # Match patterns like :password@ or password=xxx
        sanitized = re.sub(r':([^:@/]+)@', r':***@', dsn)
        sanitized = re.sub(r'password=[^&\s]+', 'password=***', sanitized)
        return sanitized

    def amprealize_service(self) -> Any:
        if not self._amprealize_service:
            from .amprealize import AmprealizeService
            # It needs action_service, compliance_service, and metrics_service
            self._amprealize_service = AmprealizeService(
                action_service=self.action_service(),
                compliance_service=self.compliance_service(),
                metrics_service=self.metrics_service()
            )
        return self._amprealize_service

    def behavior_service(self) -> BehaviorService:
        if self._behavior_service is None:
            service = BehaviorService()
            dsn_repr = getattr(service, "_dsn", "<hidden>")
            self._logger.info(
                "Initialized BehaviorService for MCP with PostgreSQL backend (dsn=%s)",
                dsn_repr,
            )
            self._behavior_service = service
        return self._behavior_service

    def bci_service(self) -> BCIService:
        """Get or create BCIService singleton for MCP."""
        if self._bci_service is None:
            service = BCIService()
            self._logger.info("Initialized BCIService for MCP")
            self._bci_service = service
        return self._bci_service

    def workflow_service(self) -> WorkflowService:
        if self._workflow_service is None:
            service = WorkflowService(
                dsn=None,
                behavior_service=self.behavior_service(),
            )
            dsn_repr = getattr(service, "dsn", "<hidden>")
            self._logger.info(
                "Initialized WorkflowService for MCP with PostgreSQL backend (dsn=%s)",
                dsn_repr,
            )
            self._workflow_service = service
        return self._workflow_service

    def action_service(self) -> Union[PostgresActionService, ActionService]:
        if self._action_service is None:
            dsn = apply_host_overrides(os.environ.get("GUIDEAI_ACTION_PG_DSN"), "ACTION")
            if dsn:
                from .telemetry import TelemetryClient

                service: Union[PostgresActionService, ActionService] = PostgresActionService(
                    dsn=dsn, telemetry=TelemetryClient.noop()
                )
                self._logger.info(
                    "Initialized PostgresActionService for MCP with PostgreSQL backend"
                )
            else:
                # Fallback to in-memory for development
                service = ActionService()
                self._logger.warning(
                    "Using in-memory ActionService (GUIDEAI_ACTION_PG_DSN not set)"
                )
            self._action_service = service
        return self._action_service

    def trace_analysis_service(self) -> Any:
        """Get or create TraceAnalysisService singleton for MCP."""
        if self._trace_analysis_service is None:
            from .trace_analysis_service import TraceAnalysisService

            dsn = apply_host_overrides(os.environ.get("GUIDEAI_TRACE_ANALYSIS_PG_DSN"), "TRACE_ANALYSIS")
            if dsn:
                try:
                    from .trace_analysis_service_postgres import PostgresTraceAnalysisService
                    storage = PostgresTraceAnalysisService(dsn=dsn)
                    service = TraceAnalysisService(storage=storage)
                    self._logger.info(
                        "Initialized TraceAnalysisService for MCP with PostgreSQL backend"
                    )
                except ImportError:
                    service = TraceAnalysisService()
                    self._logger.warning(
                        "Using in-memory TraceAnalysisService (PostgreSQL backend unavailable)"
                    )
            else:
                service = TraceAnalysisService()
                self._logger.info(
                    "Initialized TraceAnalysisService for MCP (in-memory mode)"
                )
            self._trace_analysis_service = service
        return self._trace_analysis_service

    def run_service(self) -> Any:
        """Get or create RunService singleton for MCP."""
        if self._run_service is None:
            dsn = apply_host_overrides(os.environ.get("GUIDEAI_RUN_PG_DSN"), "RUN")
            if dsn:
                try:
                    from .run_service_postgres import PostgresRunService
                    from .telemetry import TelemetryClient

                    service = PostgresRunService(dsn=dsn, telemetry=TelemetryClient.noop())
                    self._logger.info(
                        "Initialized PostgresRunService for MCP with PostgreSQL backend"
                    )
                except ImportError:
                    from .run_service import RunService

                    service = RunService()
                    self._logger.warning(
                        "Using in-memory RunService (PostgreSQL backend unavailable)"
                    )
            else:
                from .run_service import RunService

                service = RunService()
                self._logger.info(
                    "Initialized RunService for MCP (in-memory mode, GUIDEAI_RUN_PG_DSN not set)"
                )
            self._run_service = service
        return self._run_service

    def metrics_service(self) -> Any:
        """Get or create MetricsService singleton for MCP."""
        if self._metrics_service is None:
            dsn = apply_host_overrides(os.environ.get("GUIDEAI_METRICS_PG_DSN"), "METRICS")
            if dsn:
                try:
                    from .metrics_service_postgres import PostgresMetricsService

                    service = PostgresMetricsService(dsn=dsn)
                    self._logger.info(
                        "Initialized PostgresMetricsService for MCP with PostgreSQL backend"
                    )
                except ImportError:
                    from .metrics_service import MetricsService

                    service = MetricsService()
                    self._logger.warning(
                        "Using in-memory MetricsService (PostgreSQL backend unavailable)"
                    )
            else:
                from .metrics_service import MetricsService

                service = MetricsService()
                self._logger.info(
                    "Initialized MetricsService for MCP (in-memory mode, GUIDEAI_METRICS_PG_DSN not set)"
                )
            self._metrics_service = service
        return self._metrics_service

    def analytics_service(self) -> Any:
        """Get or create AnalyticsWarehouse singleton for MCP."""
        if self._analytics_service is None:
            from .analytics.warehouse import AnalyticsWarehouse

            # Check for custom DuckDB path from environment
            db_path = os.environ.get("GUIDEAI_ANALYTICS_DUCKDB_PATH")
            service = AnalyticsWarehouse(db_path=db_path) if db_path else AnalyticsWarehouse()
            self._logger.info(
                "Initialized AnalyticsWarehouse for MCP (db_path=%s)",
                db_path or "<default: data/telemetry.duckdb>",
            )
            self._analytics_service = service
        return self._analytics_service

    def agent_orchestrator_service(self) -> Any:
        """Get or create AgentOrchestratorService singleton for MCP."""
        if self._agent_orchestrator_service is None:
            from .agent_orchestrator_service import AgentOrchestratorService

            service = AgentOrchestratorService()
            self._logger.info("Initialized AgentOrchestratorService for MCP (in-memory mode)")
            self._agent_orchestrator_service = service
        return self._agent_orchestrator_service

    def compliance_service(self) -> Any:
        """Get or create ComplianceService singleton for MCP."""
        if self._compliance_service is None:
            from .compliance_service import ComplianceService

            # ComplianceService uses PostgreSQL; resolves DSN from GUIDEAI_COMPLIANCE_PG_DSN env var
            service = ComplianceService(dsn=None)
            self._logger.info("Initialized ComplianceService for MCP (PostgreSQL backend)")
            self._compliance_service = service
        return self._compliance_service

    def audit_log_service(self) -> Any:
        """Get or create AuditLogService singleton for MCP."""
        if self._audit_log_service is None:
            from .services.audit_log_service import AuditLogService

            # AuditLogService uses PostgreSQL hot tier; resolves DSN from GUIDEAI_AUDIT_PG_DSN env var
            # Also uses S3 for warm tier (WORM storage) and OpenSearch for indexing
            dsn = apply_host_overrides(os.environ.get("GUIDEAI_AUDIT_PG_DSN"), "AUDIT")
            service = AuditLogService(dsn=dsn)
            if dsn:
                self._logger.info(
                    "Initialized AuditLogService for MCP (PostgreSQL + S3 + OpenSearch)"
                )
            else:
                self._logger.info(
                    "Initialized AuditLogService for MCP (in-memory mode, GUIDEAI_AUDIT_PG_DSN not set)"
                )
            self._audit_log_service = service
        return self._audit_log_service

    def agent_auth_service(self) -> Any:
        """Get or create AgentAuthService singleton for MCP."""
        if self._agent_auth_service is None:
            from .services.agent_auth_service import AgentAuthService
            from .telemetry import TelemetryClient

            # AgentAuthService uses PostgreSQL; prefer GUIDEAI_AGENTAUTH_PG_DSN env override when set
            dsn = os.environ.get("GUIDEAI_AGENTAUTH_PG_DSN")
            service = AgentAuthService(dsn=dsn, telemetry=TelemetryClient.noop())
            if dsn:
                self._logger.info(
                    "Initialized AgentAuthService for MCP (PostgreSQL backend, custom DSN override)"
                )
            else:
                self._logger.info("Initialized AgentAuthService for MCP (PostgreSQL backend)")
            self._agent_auth_service = service
        return self._agent_auth_service

    def task_assignment_service(self) -> Any:
        """Get or create TaskService singleton for MCP (replaces stub)."""
        if self._task_assignment_service is None:
            from .services.task_service import TaskService

            # TaskService uses PostgreSQL telemetry database
            # Priority order: GUIDEAI_TASK_PG_DSN -> GUIDEAI_TELEMETRY_PG_DSN -> legacy default
            dsn_source = "GUIDEAI_TASK_PG_DSN"
            dsn = os.environ.get("GUIDEAI_TASK_PG_DSN")

            if not dsn:
                dsn = os.environ.get("GUIDEAI_TELEMETRY_PG_DSN")
                dsn_source = "GUIDEAI_TELEMETRY_PG_DSN"

            if not dsn:
                dsn = "postgresql://guideai:guideai_dev@localhost:5432/guideai"
                dsn_source = "default_guideai_db"
                self._logger.warning(
                    "TaskService falling back to default guideai DSN; set "
                    "GUIDEAI_TASK_PG_DSN for custom configuration"
                )

            service = TaskService(dsn=dsn)
            self._logger.info(
                "Initialized TaskService for MCP (PostgreSQL backend, dsn_source=%s)",
                dsn_source,
            )
            self._task_assignment_service = service
        return self._task_assignment_service

    def fine_tuning_service(self) -> Any:
        """Get or create MidnighterService singleton for MCP."""
        if self._fine_tuning_service is None:
            from .midnighter import create_midnighter_service

            # Pass the shared BehaviorService so midnighter can retrieve behaviors
            service = create_midnighter_service(
                behavior_service=self.behavior_service(),
            )
            self._logger.info("Initialized MidnighterService for MCP (with shared BehaviorService)")
            self._fine_tuning_service = service
        return self._fine_tuning_service

    def agent_review_service(self) -> Any:
        """Get or create AgentReviewService singleton for MCP."""
        if self._agent_review_service is None:
            from .agent_review_service import AgentReviewService

            service = AgentReviewService()
            self._logger.info("Initialized AgentReviewService for MCP (in-memory mode)")
            self._agent_review_service = service
        return self._agent_review_service

    def multi_tenant_service(self) -> Any:
        """Get or create MultiTenantService singleton for MCP."""
        if self._multi_tenant_service is None:
            from .multi_tenant_service import MultiTenantService

            service = MultiTenantService()
            self._logger.info("Initialized MultiTenantService for MCP (in-memory mode)")
            self._multi_tenant_service = service
        return self._multi_tenant_service

    def advanced_retrieval_service(self) -> Any:
        """Get or create AdvancedRetrievalService singleton for MCP."""
        if self._advanced_retrieval_service is None:
            from .advanced_retrieval_service import AdvancedRetrievalService

            service = AdvancedRetrievalService()
            self._logger.info("Initialized AdvancedRetrievalService for MCP (in-memory mode)")
            self._advanced_retrieval_service = service
        return self._advanced_retrieval_service

    def collaboration_service(self) -> Any:
        """Get or create CollaborationService singleton for MCP.

        Uses PostgreSQL backend when GUIDEAI_COLLABORATION_PG_DSN is set,
        otherwise falls back to in-memory implementation.
        """
        if self._collaboration_service is None:
            dsn = apply_host_overrides(os.environ.get("GUIDEAI_COLLABORATION_PG_DSN"), "COLLABORATION")
            if dsn:
                from .collaboration_service_postgres import PostgresCollaborationService
                from .telemetry import TelemetryClient

                service = PostgresCollaborationService(dsn=dsn, telemetry=TelemetryClient.noop())
                self._logger.info("Initialized PostgresCollaborationService for MCP (PostgreSQL backend)")
            else:
                from .collaboration_service import CollaborationService
                service = CollaborationService()
                self._logger.info("Initialized CollaborationService for MCP (in-memory mode)")
            self._collaboration_service = service
        return self._collaboration_service

    def reflection_service(self) -> Any:
        """Get or create ReflectionService singleton for MCP.

        Uses PostgreSQL backend when GUIDEAI_REFLECTION_PG_DSN is set,
        otherwise falls back to in-memory implementation.
        """
        if self._reflection_service is None:
            dsn = apply_host_overrides(os.environ.get("GUIDEAI_REFLECTION_PG_DSN"), "REFLECTION")
            if dsn:
                from .reflection_service_postgres import PostgresReflectionService
                from .telemetry import TelemetryClient

                service = PostgresReflectionService(
                    dsn=dsn,
                    behavior_service=self.behavior_service(),
                    bci_service=self.bci_service(),
                    telemetry=TelemetryClient.noop(),
                )
                self._logger.info("Initialized PostgresReflectionService for MCP (PostgreSQL backend)")
            else:
                from .reflection_service import ReflectionService
                service = ReflectionService(
                    behavior_service=self.behavior_service(),
                    bci_service=self.bci_service(),
                )
                self._logger.info("Initialized ReflectionService for MCP (in-memory mode)")
            self._reflection_service = service
        return self._reflection_service

    def api_rate_limiting_service(self) -> Any:
        """Get or create APIRateLimitingService singleton for MCP."""
        if self._api_rate_limiting_service is None:
            from .api_rate_limiting_service import APIRateLimitingService

            service = APIRateLimitingService()
            self._logger.info("Initialized APIRateLimitingService for MCP (in-memory mode)")
            self._api_rate_limiting_service = service
        return self._api_rate_limiting_service

    def raze_service(self) -> Any:
        """Get or create RazeService singleton for MCP structured logging."""
        if self._raze_service is None:
            try:
                from raze import RazeService
                from raze.sinks import InMemorySink

                # Check for TimescaleDB configuration
                raze_dsn = os.environ.get("RAZE_TIMESCALEDB_DSN") or os.environ.get("GUIDEAI_RAZE_DSN")
                if raze_dsn:
                    try:
                        from raze.sinks import TimescaleDBSink
                        sink = TimescaleDBSink(dsn=raze_dsn)
                        self._logger.info("Initialized RazeService for MCP (TimescaleDB backend)")
                    except Exception as e:
                        self._logger.warning(f"TimescaleDB unavailable, using in-memory sink: {e}")
                        sink = InMemorySink()
                else:
                    sink = InMemorySink()
                    self._logger.info("Initialized RazeService for MCP (in-memory mode)")

                self._raze_service = RazeService(
                    sink=sink,
                    service_name="guideai-mcp",
                    batch_size=1000,
                    linger_ms=100,
                )
            except ImportError:
                self._logger.warning("Raze package not installed, raze tools unavailable")
                self._raze_service = None
        return self._raze_service

    def organization_service(self) -> Any:
        """Get or create OrganizationService singleton for MCP."""
        if self._organization_service is None:
            from .multi_tenant.organization_service import OrganizationService

            dsn = apply_host_overrides(
                os.environ.get("GUIDEAI_ORG_PG_DSN") or os.environ.get("GUIDEAI_MULTI_TENANT_PG_DSN") or os.environ.get("GUIDEAI_PG_DSN"),
                "ORG"
            )
            if dsn:
                service = OrganizationService(dsn=dsn)
                self._logger.info("Initialized OrganizationService for MCP (PostgreSQL backend)")
            else:
                # Fallback DSN for local development - include auth schema in search_path
                service = OrganizationService(dsn="postgresql://guideai:guideai_dev@localhost:5432/guideai?options=-csearch_path%3Dauth")
                self._logger.warning("Using default OrganizationService DSN (GUIDEAI_ORG_PG_DSN not set)")
            self._organization_service = service
        return self._organization_service

    def board_service(self) -> Any:
        """Get or create BoardService singleton for MCP."""
        if self._board_service is None:
            from .services.board_service import BoardService

            dsn = apply_host_overrides(
                os.environ.get("GUIDEAI_BOARD_PG_DSN") or os.environ.get("GUIDEAI_PG_DSN"),
                "BOARD"
            )
            if dsn:
                service = BoardService(dsn=dsn)
                self._logger.info("Initialized BoardService for MCP (PostgreSQL backend)")
            else:
                # Fallback DSN for local development
                service = BoardService(dsn="postgresql://guideai:guideai_dev@localhost:5432/guideai")
                self._logger.warning("Using default BoardService DSN (GUIDEAI_BOARD_PG_DSN not set)")
            self._board_service = service
        return self._board_service

    def agent_registry_service(self) -> Any:
        """Get or create AgentRegistryService singleton for MCP.

        Used by agentRegistry.* tools for bootstrap, publish, search operations.
        """
        if self._agent_registry_service is None:
            from .agent_registry_service import AgentRegistryService
            from .telemetry import TelemetryClient

            dsn = apply_host_overrides(
                os.environ.get("GUIDEAI_AGENT_REGISTRY_PG_DSN") or os.environ.get("GUIDEAI_PG_DSN"),
                "AGENT_REGISTRY"
            )
            if dsn:
                service = AgentRegistryService(dsn=dsn, telemetry=TelemetryClient.noop())
                self._logger.info("Initialized AgentRegistryService for MCP (PostgreSQL backend)")
            else:
                # Fallback DSN for local development
                service = AgentRegistryService(
                    dsn="postgresql://guideai:guideai_dev@localhost:5432/guideai",
                    telemetry=TelemetryClient.noop(),
                )
                self._logger.warning("Using default AgentRegistryService DSN (GUIDEAI_AGENT_REGISTRY_PG_DSN not set)")
            self._agent_registry_service = service
        return self._agent_registry_service

    def github_service(self) -> Any:
        """Get or create GitHubService singleton for MCP.

        Used by github.* tools for PR and commit operations.
        Uses GITHUB_TOKEN or GH_TOKEN environment variable for authentication.
        """
        if self._github_service is None:
            from .services.github_service import GitHubService

            service = GitHubService()
            self._logger.info("Initialized GitHubService for MCP")
            self._github_service = service
        return self._github_service

    def credential_store(self) -> Any:
        """Get or create CredentialStore singleton for MCP.

        Used by config.* tools for model availability queries.
        Manages LLM provider credentials at platform/org/project scope.
        """
        if self._credential_store is None:
            from .work_item_execution_service import CredentialStore
            from .auth.llm_credential_repository import LLMCredentialRepository

            # CredentialStore needs LLMCredentialRepository for BYOK credentials
            # Get DSN from environment for database access
            dsn = apply_host_overrides(
                os.environ.get("GUIDEAI_PG_DSN"),
                "CREDENTIAL_STORE"
            )
            if not dsn:
                dsn = "postgresql://guideai:guideai_dev@localhost:5432/guideai"

            from .storage.postgres_pool import PostgresPool
            pool = PostgresPool(dsn)
            credential_repo = LLMCredentialRepository(pool=pool)

            # CredentialStore loads platform credentials from environment
            # and can resolve org/project BYOK credentials from database
            store = CredentialStore(pool=pool, credential_repository=credential_repo)
            self._logger.info("Initialized CredentialStore for MCP with LLMCredentialRepository")
            self._credential_store = store
        return self._credential_store

    def work_item_execution_service(self) -> Any:
        """Get or create WorkItemExecutionService singleton for MCP.

        Orchestrates GuideAI Execution Protocol (GEP) for work item execution
        through 8 phases: PLANNING → CLARIFYING → ARCHITECTING → EXECUTING →
        TESTING → FIXING → VERIFYING → COMPLETING.

        Uses wire_execution_service to connect AgentExecutionLoop + AgentLLMClient
        for real agent execution.
        """
        if self._work_item_execution_service is None:
            from .execution_wiring import wire_execution_service

            # WorkItemExecutionService needs PostgreSQL for execution state
            dsn = apply_host_overrides(
                os.environ.get("GUIDEAI_EXECUTION_PG_DSN") or os.environ.get("GUIDEAI_PG_DSN"),
                "EXECUTION"
            )
            if not dsn:
                # Fallback DSN for local development
                dsn = "postgresql://guideai:guideai_dev@localhost:5432/guideai"
                self._logger.warning("Using default WorkItemExecutionService DSN (GUIDEAI_EXECUTION_PG_DSN not set)")

            # Use wire_execution_service to create fully-wired service
            # This connects AgentExecutionLoop + AgentLLMClient for real execution
            service = wire_execution_service(
                dsn=dsn,
                run_service=self.run_service(),
                telemetry=self.telemetry_client(),
            )
            self._logger.info("Initialized WorkItemExecutionService for MCP with AgentExecutionLoop wired")
            self._work_item_execution_service = service
        return self._work_item_execution_service


class MCPServer:
    """
    GuideAI MCP server implementing JSON-RPC 2.0 over stdio.

    Handles tool discovery, capability negotiation, and tool execution
    for device flow authentication and future GuideAI capabilities.
    """

    # JSON-RPC error codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    RATE_LIMITED = -32000  # Custom code for rate limiting

    def __init__(self) -> None:
        """Initialize MCP server with tool handlers."""
        self._setup_logging()
        self._logger = logging.getLogger("guideai.mcp_server")
        self._services = MCPServiceRegistry(logger=self._logger)

        # Stdio framing mode detection.
        # Some MCP clients (including VS Code/Copilot) use LSP-style Content-Length framing.
        # Keep backward compatibility with line-delimited JSON used by older/manual clients.
        self._stdio_framing: Literal["unknown", "newline", "content-length"] = "unknown"

        # Initialize rate limiter for abuse prevention (MCP_SERVER_DESIGN.md §9)
        from .mcp_rate_limiter import MCPRateLimiter
        self._rate_limiter = MCPRateLimiter()
        self._client_id: Optional[str] = None  # Set during initialize

        # Connection stability (Epic 6 - MCP Server Stability)
        self._shutdown_requested = False
        self._pending_requests: Dict[str, asyncio.Task[Any]] = {}
        self._last_activity = time.time()
        self._idle_timeout_seconds = float(os.environ.get("MCP_IDLE_TIMEOUT", "3600"))  # 1 hour default
        self._idle_check_task: Optional[asyncio.Task[Any]] = None
        self._graceful_shutdown_timeout = float(os.environ.get("MCP_SHUTDOWN_TIMEOUT", "30"))  # 30s default

        # Pre-warm connection pools for faster first requests
        self._logger.info("Pre-warming PostgreSQL connection pools...")
        self._services.prewarm_pools()

        # Import device flow handler
        try:
            from .mcp_device_flow import MCPDeviceFlowHandler, MCPDeviceFlowService

            # Initialize service with AgentAuthService integration
            device_flow_service = MCPDeviceFlowService(
                agent_auth_service=self._services.agent_auth_service(),
            )
            self._device_flow_handler = MCPDeviceFlowHandler(service=device_flow_service)
        except ImportError as e:
            self._logger.error(f"Failed to import device flow handler: {e}")
            self._device_flow_handler = None

        # Import task handler
        try:
            from .mcp_task_handler import MCPTaskHandler

            # Initialize handler with TaskService integration
            self._task_handler = MCPTaskHandler(task_service=self._services.task_assignment_service())
        except ImportError as e:
            self._logger.error(f"Failed to import task handler: {e}")
            self._task_handler = None

        # Initialize Amprealize adapter
        try:
            from .adapters import MCPAmprealizeAdapter

            self._amprealize_adapter = MCPAmprealizeAdapter(
                service=self._services.amprealize_service()
            )
        except Exception as e:
            self._logger.error(f"Failed to initialize Amprealize adapter: {e}")
            self._amprealize_adapter = None

        # Tool registry
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._load_tool_manifests()

        # Performance metrics
        self._metrics = {
            "requests_total": 0,
            "requests_by_method": {},
            "tool_calls_total": 0,
            "tool_calls_by_name": {},
            "tool_latency_seconds": {},
            "errors_total": 0,
            "batch_requests_total": 0,
        }

        self._logger.info(f"GuideAI MCP Server initialized with {len(self._tools)} tools")

    def _setup_logging(self) -> None:
        """Configure structured logging to stderr."""
        logging.basicConfig(
            level=logging.INFO,
            format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            stream=sys.stderr,
        )

    def _write_stdout_message(self, message: str) -> None:
        """Write a JSON-RPC message to stdout using the active framing mode."""
        if self._stdio_framing == "content-length":
            body = message.encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            sys.stdout.buffer.write(header)
            sys.stdout.buffer.write(body)
            sys.stdout.buffer.flush()
        else:
            # Default to newline-delimited framing.
            sys.stdout.write(message + "\n")
            sys.stdout.flush()

    def _read_stdin_message_blocking(self) -> Optional[str]:
        """Read a single JSON-RPC message from stdin.

        Supports either:
        - newline-delimited JSON (one JSON object per line), or
        - LSP-style Content-Length framing.

        Returns:
            The raw JSON string payload, or None on EOF.
        """
        buf = sys.stdin.buffer

        while True:
            first_line = buf.readline()
            if first_line == b"":
                return None

            # Ignore empty lines (common in content-length framing between messages).
            if first_line in (b"\r\n", b"\n") or first_line.strip() == b"":
                if self._stdio_framing == "newline":
                    continue
                # In unknown/content-length mode, treat blank lines as separators.
                continue

            # Detect framing if unknown.
            if self._stdio_framing == "unknown":
                stripped = first_line.lstrip()
                if stripped.lower().startswith(b"content-length:"):
                    self._stdio_framing = "content-length"
                elif stripped.startswith(b"{") or stripped.startswith(b"["):
                    self._stdio_framing = "newline"
                    return first_line.decode("utf-8", errors="replace").strip()
                else:
                    # Unknown/noise line. Keep scanning.
                    continue

            if self._stdio_framing == "newline":
                return first_line.decode("utf-8", errors="replace").strip()

            # Content-Length framing.
            headers: Dict[str, str] = {}
            header_line = first_line

            while True:
                if header_line in (b"\r\n", b"\n", b""):
                    break
                try:
                    decoded = header_line.decode("utf-8", errors="replace")
                    key, value = decoded.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
                except ValueError:
                    # Malformed header; ignore.
                    pass

                header_line = buf.readline()
                if header_line == b"":
                    return None

            content_length_value = headers.get("content-length")
            if not content_length_value:
                self._logger.warning("Missing Content-Length header; falling back to newline framing")
                self._stdio_framing = "newline"
                continue

            try:
                content_length = int(content_length_value)
            except ValueError:
                self._logger.warning("Invalid Content-Length header; falling back to newline framing")
                self._stdio_framing = "newline"
                continue

            body = buf.read(content_length)
            if body == b"":
                return None

            return body.decode("utf-8", errors="replace")

    def _normalize_tool_name(self, name: str) -> str:
        """Normalize tool name to be VS Code MCP compliant.

        VS Code currently validates tool names against: [a-z0-9_-]
        """
        normalized = name.replace(".", "_").replace("/", "_")
        normalized = normalized.lower()
        normalized = re.sub(r"[^a-z0-9_-]", "_", normalized)
        return normalized

    def _load_tool_manifests(self) -> None:
        """Load MCP tool manifests from mcp/tools/ directory."""
        # Find mcp/tools directory relative to this file
        mcp_tools_dir = Path(__file__).parent.parent / "mcp" / "tools"

        if not mcp_tools_dir.exists():
            self._logger.warning(f"MCP tools directory not found: {mcp_tools_dir}")
            return

        # Load all .json tool manifests
        for manifest_path in mcp_tools_dir.glob("*.json"):
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)

                original_name = manifest.get("name")
                if not original_name:
                    self._logger.warning(f"Tool manifest missing 'name': {manifest_path}")
                    continue

                # Normalize tool name for MCP compliance (VS Code only allows [a-z0-9_-])
                tool_name = self._normalize_tool_name(original_name)
                manifest["name"] = tool_name  # Update manifest with normalized name
                manifest["_original_name"] = original_name  # Keep original for handler lookup

                if tool_name in self._tools:
                    existing_original = self._tools[tool_name].get("_original_name")
                    if existing_original != original_name:
                        self._logger.error(
                            "Tool name collision after normalization: "
                            f"{original_name} -> {tool_name} conflicts with {existing_original}"
                        )
                        continue

                self._tools[tool_name] = manifest
                self._logger.info(f"Loaded tool: {tool_name}")

            except Exception as e:
                self._logger.error(f"Failed to load tool manifest {manifest_path}: {e}")

    async def handle_request(self, request_line: str) -> Optional[str]:
        """
        Handle a single JSON-RPC request or batch request.

        Args:
            request_line: JSON-RPC request as string (single or array)

        Returns:
            JSON-RPC response as string, or None for notifications
        """
        try:
            request_data = json.loads(request_line)
        except json.JSONDecodeError as e:
            return self._error_response(
                None,
                self.PARSE_ERROR,
                f"Parse error: {e}",
            )

        # Handle batch requests (array of requests)
        if isinstance(request_data, list):
            return await self._handle_batch_request(request_data)

        # Handle single request
        return await self._handle_single_request(request_data)

    async def _handle_batch_request(self, requests: List[Dict[str, Any]]) -> str:
        """
        Handle a batch of JSON-RPC requests in parallel.

        Args:
            requests: List of JSON-RPC request objects

        Returns:
            JSON array of responses
        """
        self._logger.info(f"Handling batch request with {len(requests)} items")

        # Process all requests in parallel
        tasks = [self._handle_single_request(req) for req in requests]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error responses
        results = []
        for i, response in enumerate(responses):
            if isinstance(response, Exception):
                request_id = requests[i].get("id")
                error_response = self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Batch item {i} failed: {str(response)}",
                )
                results.append(json.loads(error_response))
            elif response and isinstance(response, str):  # Skip None (notifications)
                results.append(json.loads(response))

        return json.dumps(results)

    async def _handle_single_request(self, request_data: Dict[str, Any]) -> Optional[str]:
        """
        Handle a single JSON-RPC request.

        Args:
            request_data: Parsed JSON-RPC request object

        Returns:
            JSON-RPC response as string, or None for notifications
        """
        request_id = request_data.get("id")
        method = request_data.get("method")
        params = request_data.get("params", {})

        # JSON-RPC 2.0: Notifications have no "id" field and expect no response
        # Per spec, notifications MUST NOT receive a response (not even an error)
        if request_id is None:
            self._logger.debug(f"Received notification: {method} (no response expected)")
            return None

        self._logger.info(f"Received request: method={method}, id={request_id}")

        # Handle MCP protocol methods
        if method == "initialize":
            return self._handle_initialize(request_id, params)
        elif method == "tools/list":
            return self._handle_tools_list(request_id)
        elif method == "tools/call":
            return await self._handle_tools_call(request_id, params)
        elif method == "ping":
            return self._success_response(request_id, {"status": "ok"})
        elif method == "health":
            return self._success_response(request_id, self.get_health_status())
        elif method == "metrics":
            return self._success_response(request_id, self.get_metrics_summary())
        else:
            return self._error_response(
                request_id,
                self.METHOD_NOT_FOUND,
                f"Method not found: {method}",
            )

    def _handle_initialize(self, request_id: Optional[str], params: Dict[str, Any]) -> str:
        """Handle MCP initialize request."""
        client_info = params.get("clientInfo", {})
        self._logger.info(f"Client connected: {client_info}")

        # Capture client ID for rate limiting
        # Use client name + version as unique identifier, fallback to session
        client_name = client_info.get("name", "unknown")
        client_version = client_info.get("version", "0.0.0")
        self._client_id = f"{client_name}:{client_version}:{id(self)}"
        self._logger.info(f"Rate limiter client ID: {self._client_id}")

        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "guideai",
                "version": "0.1.0",
            },
            "capabilities": {
                "tools": {
                    "listChanged": False,  # Tool list is static for now
                },
                "experimental": {
                    "batchRequests": True,  # Support batch requests
                    "rateLimiting": True,  # Rate limiting enabled
                },
            },
        }

        return self._success_response(request_id, result)

    def _handle_tools_list(self, request_id: Optional[str]) -> str:
        """Handle MCP tools/list request."""
        tools_list = []

        for tool_name, manifest in self._tools.items():
            tools_list.append({
                "name": tool_name,
                "description": manifest.get("description", ""),
                "inputSchema": manifest.get("inputSchema", {}),
            })

        result = {"tools": tools_list}
        return self._success_response(request_id, result)

    async def _handle_tools_call(self, request_id: Optional[str], params: Dict[str, Any]) -> str:
        """Handle MCP tools/call request with rate limiting and latency tracking."""
        from .mcp_rate_limiter import RateLimitDecision

        tool_name = params.get("name")
        tool_params = params.get("arguments", {})

        if not tool_name:
            return self._error_response(
                request_id,
                self.INVALID_PARAMS,
                "Missing required parameter: name",
            )

        # Apply rate limiting (MCP_SERVER_DESIGN.md §9)
        client_id = self._client_id or f"anonymous:{id(self)}"
        rate_result = self._rate_limiter.check(client_id, tool_name)

        if rate_result.decision == RateLimitDecision.DENY:
            self._logger.warning(
                f"Rate limit blocked: client={client_id}, tool={tool_name}, "
                f"rule={rate_result.rule_name}, retry_after={rate_result.retry_after_seconds}"
            )
            return self._error_response(
                request_id,
                self.RATE_LIMITED,
                rate_result.message,
                data={
                    "retry_after_seconds": rate_result.retry_after_seconds,
                    "remaining_tokens": rate_result.remaining_tokens,
                    "rule": rate_result.rule_name,
                },
            )
        elif rate_result.decision == RateLimitDecision.WARN:
            self._logger.info(
                f"Rate limit warning: client={client_id}, tool={tool_name}, "
                f"remaining={rate_result.remaining_tokens:.2f}"
            )

        # Start timing
        start_time = time.time()

        self._logger.info(f"Calling tool: {tool_name} with params: {tool_params}")

        # Increment counters
        self._metrics["tool_calls_total"] += 1
        self._metrics["tool_calls_by_name"][tool_name] = self._metrics["tool_calls_by_name"].get(tool_name, 0) + 1

        try:
            result_str = await self._dispatch_tool_call(request_id, tool_name, tool_params)

            # Record latency
            duration = time.time() - start_time
            if tool_name not in self._metrics["tool_latency_seconds"]:
                self._metrics["tool_latency_seconds"][tool_name] = []
            self._metrics["tool_latency_seconds"][tool_name].append(duration)

            self._logger.info(f"Tool {tool_name} completed in {duration:.3f}s")
            return result_str

        except Exception as e:
            self._metrics["errors_total"] += 1
            duration = time.time() - start_time
            self._logger.error(f"Tool {tool_name} failed after {duration:.3f}s: {e}", exc_info=True)
            raise

    def _denormalize_tool_name(self, normalized_name: str) -> str:
        """Convert underscore-normalized tool name back to dot notation for handler dispatch.

        This reverses the normalization done in _normalize_tool_name.
        Tool names follow the pattern: namespace_action or namespace_subnamespace_action
        We need to restore the first underscore to a dot for namespace.action format.
        """
        # First check if we have the original name stored in the tool manifest
        if normalized_name in self._tools:
            tool_def = self._tools[normalized_name]
            if "_original_name" in tool_def:
                return tool_def["_original_name"]

        # Fallback: Convert first underscore to dot (handles namespace_action pattern)
        # This is a heuristic for tools not in manifest
        parts = normalized_name.split("_", 1)
        if len(parts) == 2:
            return f"{parts[0]}.{parts[1]}"
        return normalized_name

    async def _dispatch_tool_call(self, request_id: Optional[str], tool_name: str, tool_params: Dict[str, Any]) -> str:
        """Dispatch tool call to appropriate handler."""
        # Convert from normalized name (underscores) back to internal format (dots)
        internal_tool_name = self._denormalize_tool_name(tool_name)
        self._logger.debug(f"Tool dispatch: normalized={tool_name} -> internal={internal_tool_name}")

        # Route device flow tools
        if internal_tool_name.startswith("auth."):
            if not self._device_flow_handler:
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    "Device flow handler not available",
                )

            result = await self._device_flow_handler.handle_tool_call(internal_tool_name, tool_params)

            # Wrap result in MCP content format
            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # Route task management tools
        if internal_tool_name.startswith("tasks."):
            if not self._task_handler:
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    "Task handler not available",
                )

            # Dispatch to appropriate handler method
            if internal_tool_name == "tasks.listAssignments":
                result = await self._task_handler.handle_list_assignments(tool_params)
            elif internal_tool_name == "tasks.create":
                result = await self._task_handler.handle_create_task(tool_params)
            elif internal_tool_name == "tasks.updateStatus":
                result = await self._task_handler.handle_update_status(tool_params)
            elif internal_tool_name == "tasks.getStats":
                result = await self._task_handler.handle_get_stats(tool_params)
            else:
                return self._error_response(
                    request_id,
                    self.METHOD_NOT_FOUND,
                    f"Unknown task tool: {internal_tool_name}",
                )

            # Wrap result in MCP content format
            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # Route Amprealize tools
        if internal_tool_name.startswith("amprealize."):
            if not self._amprealize_adapter:
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    "Amprealize adapter not available",
                )

            try:
                if internal_tool_name == "amprealize.plan":
                    result = self._amprealize_adapter.plan(
                        blueprint_id=tool_params["blueprint_id"],
                        environment=tool_params.get("environment", "development"),
                        checklist_id=tool_params.get("checklist_id"),
                        lifetime=tool_params.get("lifetime", "90m"),
                        compliance_tier=tool_params.get("compliance_tier", "dev"),
                        behaviors=tool_params.get("behaviors"),
                        variables=tool_params.get("variables"),
                    )
                elif internal_tool_name == "amprealize.apply":
                    result = self._amprealize_adapter.apply(
                        plan_id=tool_params.get("plan_id"),
                        manifest_file=tool_params.get("manifest_file"),
                        watch=tool_params.get("watch", False),
                        resume=tool_params.get("resume", False),
                    )
                elif internal_tool_name == "amprealize.status":
                    result = self._amprealize_adapter.status(
                        run_id=tool_params["run_id"]
                    )
                elif internal_tool_name == "amprealize.destroy":
                    result = self._amprealize_adapter.destroy(
                        run_id=tool_params["run_id"],
                        cascade=tool_params.get("cascade", True),
                        reason=tool_params.get("reason", "MANUAL"),
                    )
                elif internal_tool_name == "amprealize.listBlueprints":
                    result = self._amprealize_adapter.list_blueprints(
                        source=tool_params.get("source", "all"),
                    )
                elif internal_tool_name == "amprealize.listEnvironments":
                    result = self._amprealize_adapter.list_environments(
                        phase=tool_params.get("phase", "all"),
                    )
                elif internal_tool_name == "amprealize.configure":
                    result = self._amprealize_adapter.configure(
                        config_dir=tool_params.get("config_dir"),
                        include_blueprints=tool_params.get("include_blueprints", False),
                        blueprints=tool_params.get("blueprints"),
                        force=tool_params.get("force", False),
                    )
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown Amprealize tool: {internal_tool_name}",
                    )
            except KeyError as e:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Missing required parameter: {e}",
                )

            # Wrap result in MCP content format
            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # Route pattern analysis tools
        if internal_tool_name.startswith("patterns."):
            try:
                from .adapters import MCPTraceAnalysisServiceAdapter

                adapter = MCPTraceAnalysisServiceAdapter(self._services.trace_analysis_service())

                if internal_tool_name == "patterns.detectPatterns":
                    # Send progress notification for long-running operation
                    self._send_notification(
                        "tool/progress",
                        {
                            "request_id": request_id,
                            "tool": internal_tool_name,
                            "status": "starting",
                            "message": "Analyzing trace for recurring patterns...",
                        }
                    )

                    result = adapter.detectPatterns(tool_params)

                    # Send completion notification
                    self._send_notification(
                        "tool/progress",
                        {
                            "request_id": request_id,
                            "tool": internal_tool_name,
                            "status": "complete",
                            "message": f"Detected {len(result.get('patterns', []))} patterns",
                        }
                    )
                elif internal_tool_name == "patterns.scoreReusability":
                    result = adapter.scoreReusability(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown patterns tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Pattern tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Pattern tool execution failed: {str(e)}",
                )

        # Route action service tools
        if internal_tool_name.startswith("actions."):
            try:
                from .adapters import MCPActionServiceAdapter

                adapter = MCPActionServiceAdapter(self._services.action_service())

                if internal_tool_name == "actions.create":
                    result = adapter.create(tool_params)
                elif internal_tool_name == "actions.list":
                    result = adapter.list()
                elif internal_tool_name == "actions.get":
                    action_id = tool_params.get("action_id")
                    if not action_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: action_id",
                        )
                    result = adapter.get(action_id)
                elif internal_tool_name == "actions.replay":
                    result = adapter.replay(tool_params)
                elif internal_tool_name == "actions.replayStatus":
                    replay_id = tool_params.get("replay_id")
                    if not replay_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: replay_id",
                        )
                    result = adapter.get_replay_status(replay_id)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown actions tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Action tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Action tool execution failed: {str(e)}",
                )

        # Route behavior service tools
        if internal_tool_name.startswith("behaviors."):
            try:
                from .adapters import MCPBehaviorServiceAdapter

                adapter = MCPBehaviorServiceAdapter(self._services.behavior_service())

                if internal_tool_name == "behaviors.create":
                    result = adapter.create(tool_params)
                elif internal_tool_name == "behaviors.list":
                    result = adapter.list(tool_params)
                elif internal_tool_name == "behaviors.search":
                    query = tool_params.get("query")
                    if not query:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: query",
                        )
                    result = adapter.search(tool_params)
                elif internal_tool_name == "behaviors.get":
                    behavior_id = tool_params.get("behavior_id")
                    if not behavior_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: behavior_id",
                        )
                    result = adapter.get(tool_params)
                elif internal_tool_name == "behaviors.update":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    if not behavior_id or not version:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version",
                        )
                    result = adapter.update(tool_params)
                elif internal_tool_name == "behaviors.submit":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    if not behavior_id or not version:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version",
                        )
                    result = adapter.submit(tool_params)
                elif internal_tool_name == "behaviors.approve":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    effective_from = tool_params.get("effective_from")
                    if not behavior_id or not version or not effective_from:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version, effective_from",
                        )
                    result = adapter.approve(tool_params)
                elif internal_tool_name == "behaviors.deprecate":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    effective_to = tool_params.get("effective_to")
                    if not behavior_id or not version or not effective_to:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version, effective_to",
                        )
                    result = adapter.deprecate(tool_params)
                elif internal_tool_name == "behaviors.deleteDraft":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    if not behavior_id or not version:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version",
                        )
                    adapter.delete_draft(tool_params)
                    result = {"success": True, "message": f"Draft {behavior_id} v{version} deleted"}
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown behaviors tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Behavior tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Behavior tool execution failed: {str(e)}",
                )

        # ComplianceService tool routing
        if internal_tool_name.startswith("compliance/"):
            from guideai.compliance_service import RecordStepRequest, Actor

            try:
                compliance_service = self._services.compliance_service()
                actor = Actor(id="test-strategist", role="STRATEGIST", surface="mcp")

                if internal_tool_name == "compliance/create-checklist":
                    result = compliance_service.create_checklist(
                        title=tool_params["title"],
                        description=tool_params.get("description", ""),
                        template_id=tool_params.get("template_id"),
                        milestone=tool_params.get("milestone"),
                        compliance_category=tool_params.get("compliance_category", []),
                        actor=actor,
                    )
                    result_dict = {
                        "checklist_id": result.checklist_id,
                        "title": result.title,
                        "description": result.description,
                        "template_id": result.template_id,
                        "milestone": result.milestone,
                        "compliance_category": result.compliance_category,
                        "steps": [],
                        "created_at": result.created_at,
                        "completed_at": result.completed_at,
                        "coverage_score": result.coverage_score,
                    }

                elif internal_tool_name == "compliance/list-checklists":
                    checklists = compliance_service.list_checklists(
                        milestone=tool_params.get("milestone"),
                        compliance_category=tool_params.get("compliance_category"),
                        status_filter=tool_params.get("status_filter"),
                    )
                    result_dict = {
                        "checklists": [
                            {
                                "checklist_id": c.checklist_id,
                                "title": c.title,
                                "description": c.description,
                                "template_id": c.template_id,
                                "milestone": c.milestone,
                                "compliance_category": c.compliance_category,
                                "steps": [
                                    {
                                        "step_id": s.step_id,
                                        "checklist_id": s.checklist_id,
                                        "title": s.title,
                                        "status": s.status,
                                        "actor": {"id": s.actor.id, "role": s.actor.role, "surface": s.actor.surface},
                                        "evidence": s.evidence,
                                        "behaviors_cited": s.behaviors_cited,
                                        "related_run_id": s.related_run_id,
                                        "audit_log_event_id": s.audit_log_event_id,
                                        "validation_result": s.validation_result,
                                        "timestamp": s.timestamp,
                                    }
                                    for s in c.steps
                                ],
                                "created_at": c.created_at,
                                "completed_at": c.completed_at,
                                "coverage_score": c.coverage_score,
                            }
                            for c in checklists
                        ]
                    }

                elif internal_tool_name == "compliance/get-checklist":
                    checklist = compliance_service.get_checklist(
                        checklist_id=tool_params["checklist_id"]
                    )
                    result_dict = {
                        "checklist_id": checklist.checklist_id,
                        "title": checklist.title,
                        "description": checklist.description,
                        "template_id": checklist.template_id,
                        "milestone": checklist.milestone,
                        "compliance_category": checklist.compliance_category,
                        "steps": [
                            {
                                "step_id": s.step_id,
                                "checklist_id": s.checklist_id,
                                "title": s.title,
                                "status": s.status,
                                "actor": {"id": s.actor.id, "role": s.actor.role, "surface": s.actor.surface},
                                "evidence": s.evidence,
                                "behaviors_cited": s.behaviors_cited,
                                "related_run_id": s.related_run_id,
                                "audit_log_event_id": s.audit_log_event_id,
                                "validation_result": s.validation_result,
                                "timestamp": s.timestamp,
                            }
                            for s in checklist.steps
                        ],
                        "created_at": checklist.created_at,
                        "completed_at": checklist.completed_at,
                        "coverage_score": checklist.coverage_score,
                    }

                elif internal_tool_name == "compliance/record-step":
                    record_req = RecordStepRequest(
                        checklist_id=tool_params["checklist_id"],
                        title=tool_params["title"],
                        status=tool_params["status"],
                        evidence=tool_params.get("evidence"),
                        behaviors_cited=tool_params.get("behaviors_cited", []),
                        related_run_id=tool_params.get("related_run_id"),
                    )
                    step = compliance_service.record_step(record_req, actor)
                    result_dict = {
                        "step_id": step.step_id,
                        "checklist_id": step.checklist_id,
                        "title": step.title,
                        "status": step.status,
                        "actor": {"id": step.actor.id, "role": step.actor.role, "surface": step.actor.surface},
                        "evidence": step.evidence,
                        "behaviors_cited": step.behaviors_cited,
                        "related_run_id": step.related_run_id,
                        "audit_log_event_id": step.audit_log_event_id,
                        "validation_result": step.validation_result,
                        "timestamp": step.timestamp,
                    }

                elif internal_tool_name == "compliance/validate-compliance":
                    validation = compliance_service.validate_checklist(
                        checklist_id=tool_params["checklist_id"],
                        actor=actor,
                    )
                    result_dict = {
                        "checklist_id": validation.checklist_id,
                        "valid": validation.valid,
                        "coverage_score": validation.coverage_score,
                        "missing_steps": validation.missing_steps,
                        "failed_steps": validation.failed_steps,
                        "warnings": validation.warnings,
                    }

                elif internal_tool_name == "compliance/validate-by-action":
                    validation = compliance_service.validate_by_action_id(
                        action_id=tool_params["action_id"],
                        actor=actor,
                    )
                    result_dict = {
                        "checklist_id": validation.checklist_id,
                        "valid": validation.valid,
                        "coverage_score": validation.coverage_score,
                        "missing_steps": validation.missing_steps,
                        "failed_steps": validation.failed_steps,
                        "warnings": validation.warnings,
                    }

                elif internal_tool_name == "compliance/create-policy":
                    policy = compliance_service.create_policy(
                        name=tool_params["name"],
                        description=tool_params.get("description", ""),
                        policy_type=tool_params["policy_type"],
                        enforcement_level=tool_params["enforcement_level"],
                        actor=actor,
                        org_id=tool_params.get("org_id"),
                        project_id=tool_params.get("project_id"),
                        version=tool_params.get("version", "1.0.0"),
                        rules=tool_params.get("rules"),
                        required_behaviors=tool_params.get("required_behaviors"),
                        compliance_categories=tool_params.get("compliance_categories"),
                        metadata=tool_params.get("metadata"),
                    )
                    result_dict = policy.to_dict()

                elif internal_tool_name == "compliance/get-policy":
                    policy = compliance_service.get_policy(tool_params["policy_id"])
                    result_dict = policy.to_dict()

                elif internal_tool_name == "compliance/list-policies":
                    policies = compliance_service.list_policies(
                        org_id=tool_params.get("org_id"),
                        project_id=tool_params.get("project_id"),
                        policy_type=tool_params.get("policy_type"),
                        enforcement_level=tool_params.get("enforcement_level"),
                        is_active=tool_params.get("is_active"),
                        include_global=tool_params.get("include_global", True),
                    )
                    result_dict = {"policies": [p.to_dict() for p in policies]}

                elif internal_tool_name == "compliance/audit-trail":
                    report = compliance_service.get_audit_trail(
                        run_id=tool_params.get("run_id"),
                        checklist_id=tool_params.get("checklist_id"),
                        action_id=tool_params.get("action_id"),
                        start_date=tool_params.get("start_date"),
                        end_date=tool_params.get("end_date"),
                    )
                    result_dict = report.to_dict()

                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown compliance tool: {internal_tool_name}",
                    )

                # Wrap result in MCP format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result_dict, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Compliance tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Compliance tool execution failed: {str(e)}",
                )

        # Route run service tools
        if internal_tool_name.startswith("runs."):
            try:
                from .adapters import MCPRunServiceAdapter

                adapter = MCPRunServiceAdapter(self._services.run_service())

                if internal_tool_name == "runs.create":
                    result = adapter.create(tool_params)
                elif internal_tool_name == "runs.list":
                    result = {"runs": adapter.list(tool_params)}
                elif internal_tool_name == "runs.get":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.get(run_id)
                elif internal_tool_name == "runs.updateProgress":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.update(run_id, tool_params)
                elif internal_tool_name == "runs.complete":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.complete(run_id, tool_params)
                elif internal_tool_name == "runs.cancel":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.cancel(run_id, tool_params)
                elif internal_tool_name == "runs.updateStatus":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    if "status" not in tool_params:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: status",
                        )
                    result = adapter.update_status(run_id, tool_params)
                elif internal_tool_name == "runs.fetchLogs":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    # Get RazeService for log queries
                    raze_service = self._get_raze_service()
                    import asyncio
                    # Run async method
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(
                                asyncio.run,
                                adapter.fetch_logs(run_id, tool_params, raze_service)
                            )
                            result = future.result()
                    else:
                        result = loop.run_until_complete(
                            adapter.fetch_logs(run_id, tool_params, raze_service)
                        )
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown runs tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Run tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Run tool execution failed: {str(e)}",
                )

        # Workflow tools: workflow.template.*, workflow.run.*
        if internal_tool_name.startswith("workflow."):
            try:
                from .adapters import MCPWorkflowServiceAdapter

                adapter = MCPWorkflowServiceAdapter(self._services.workflow_service())

                if internal_tool_name == "workflow.template.create":
                    result = adapter.create_template(tool_params)
                elif internal_tool_name == "workflow.template.list":
                    result = {"templates": adapter.list_templates(tool_params)}
                elif internal_tool_name == "workflow.template.get":
                    template_id = tool_params.get("template_id")
                    if not template_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: template_id",
                        )
                    result = adapter.get_template(template_id)
                    if result is None:
                        return self._error_response(
                            request_id,
                            self.INTERNAL_ERROR,
                            f"Template not found: {template_id}",
                        )
                elif internal_tool_name == "workflow.run.start":
                    result = adapter.run_workflow(tool_params)
                elif internal_tool_name == "workflow.run.status":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.get_run(run_id)
                    if result is None:
                        return self._error_response(
                            request_id,
                            self.INTERNAL_ERROR,
                            f"Workflow run not found: {run_id}",
                        )
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown workflow tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Workflow tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Workflow tool execution failed: {str(e)}",
                )

        # BCI tools: bci.*
        if internal_tool_name.startswith("bci."):
            try:
                from .mcp.handlers import bci_handlers

                service = self._services.bci_service()

                if internal_tool_name == "bci.retrieve":
                    result = bci_handlers.bci_retrieve(tool_params)
                elif internal_tool_name == "bci.retrieveHybrid":
                    result = bci_handlers.bci_retrieve_hybrid(tool_params)
                elif internal_tool_name == "bci.composePrompt":
                    result = bci_handlers.bci_compose_prompt(tool_params)
                elif internal_tool_name == "bci.composeBatchPrompts":
                    result = bci_handlers.bci_compose_prompts_batch(tool_params)
                elif internal_tool_name == "bci.parseCitations":
                    result = bci_handlers.bci_parse_citations(tool_params)
                elif internal_tool_name == "bci.validateCitations":
                    result = bci_handlers.bci_validate_citations(tool_params)
                elif internal_tool_name == "bci.computeTokenSavings":
                    result = bci_handlers.bci_compute_token_savings(tool_params)
                elif internal_tool_name == "bci.segmentTrace":
                    result = bci_handlers.bci_segment_trace(tool_params)
                elif internal_tool_name == "bci.detectPatterns":
                    result = bci_handlers.bci_detect_patterns(tool_params)
                elif internal_tool_name == "bci.scoreReusability":
                    result = bci_handlers.bci_score_reusability(tool_params)
                elif internal_tool_name == "bci.rebuildIndex":
                    result = bci_handlers.bci_rebuild_index(tool_params)
                elif internal_tool_name == "bci.generate":
                    result = bci_handlers.bci_generate(tool_params)
                elif internal_tool_name == "bci.improve":
                    result = bci_handlers.bci_improve(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown BCI tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"BCI tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"BCI tool execution failed: {str(e)}",
                )

        # Handle metrics.* tools
        if internal_tool_name.startswith("metrics."):
            try:
                from .adapters import MCPMetricsServiceAdapter

                service = self._services.metrics_service()
                adapter = MCPMetricsServiceAdapter(service=service)

                if internal_tool_name == "metrics.getSummary":
                    result = adapter.get_summary(tool_params or {})
                elif internal_tool_name == "metrics.export":
                    result = adapter.export(tool_params or {})
                elif internal_tool_name == "metrics.subscribe":
                    result = adapter.subscribe(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown metrics tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Metrics tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Metrics tool execution failed: {str(e)}",
                )

        # Handle analytics.* tools
        if internal_tool_name.startswith("analytics."):
            try:
                from .adapters import MCPAnalyticsServiceAdapter

                service = self._services.analytics_service()
                adapter = MCPAnalyticsServiceAdapter(service=service)

                if internal_tool_name == "analytics.kpiSummary":
                    result = adapter.kpi_summary(tool_params or {})
                elif internal_tool_name == "analytics.behaviorUsage":
                    result = adapter.behavior_usage(tool_params or {})
                elif internal_tool_name == "analytics.tokenSavings":
                    result = adapter.token_savings(tool_params or {})
                elif internal_tool_name == "analytics.complianceCoverage":
                    result = adapter.compliance_coverage(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown analytics tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Analytics tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Analytics tool execution failed: {str(e)}",
                )

        # Handle audit.* tools (compliance-grade audit log access)
        if internal_tool_name.startswith("audit."):
            try:
                from .adapters import MCPAuditServiceAdapter

                service = self._services.audit_log_service()
                adapter = MCPAuditServiceAdapter(service=service)

                if internal_tool_name == "audit.query":
                    result = await adapter.query(tool_params or {})
                elif internal_tool_name == "audit.archive":
                    result = await adapter.archive(tool_params or {})
                elif internal_tool_name == "audit.verify":
                    result = await adapter.verify(tool_params or {})
                elif internal_tool_name == "audit.status":
                    result = await adapter.status(tool_params or {})
                elif internal_tool_name == "audit.listArchives":
                    result = adapter.list_archives(tool_params or {})
                elif internal_tool_name == "audit.getRetention":
                    result = adapter.get_retention(tool_params or {})
                elif internal_tool_name == "audit.verifyArchive":
                    result = adapter.verify_archive(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown audit tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Audit tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Audit tool execution failed: {str(e)}",
                )

        # Handle agents.* tools
        if internal_tool_name.startswith("agents."):
            try:
                from .adapters import MCPAgentOrchestratorAdapter

                service = self._services.agent_orchestrator_service()
                adapter = MCPAgentOrchestratorAdapter(service=service)

                if internal_tool_name == "agents.assign":
                    result = adapter.assign(tool_params or {})
                elif internal_tool_name == "agents.switch":
                    result = adapter.switch(tool_params or {})
                elif internal_tool_name == "agents.status":
                    result = adapter.status(tool_params or {})
                    if result is None:
                        return self._error_response(
                            request_id,
                            self.INTERNAL_ERROR,
                            "Agent assignment not found",
                        )
                elif internal_tool_name == "agents.delegate":
                    result = adapter.delegate(tool_params or {})
                elif internal_tool_name == "agents.consult":
                    result = adapter.consult(tool_params or {})
                elif internal_tool_name == "agents.handoff":
                    result = adapter.handoff(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown agents tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except KeyError as e:
                self._logger.error(f"Agent orchestration validation failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Invalid parameters: {str(e)}",
                )
            except Exception as e:
                self._logger.error(f"Agent orchestration tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Agent orchestration tool execution failed: {str(e)}",
                )

        # Handle escalation.* tools (Section 11.4 - Human Escalation)
        if internal_tool_name.startswith("escalation."):
            try:
                from .adapters import MCPEscalationAdapter

                service = self._services.agent_orchestrator_service()
                adapter = MCPEscalationAdapter(service)

                if internal_tool_name == "escalation.requestHelp":
                    result = adapter.request_help(tool_params or {})
                elif internal_tool_name == "escalation.requestApproval":
                    result = adapter.request_approval(tool_params or {})
                elif internal_tool_name == "escalation.notifyBlocked":
                    result = adapter.notify_blocked(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown escalation tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except KeyError as e:
                self._logger.error(f"Escalation validation failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Invalid parameters: {str(e)}",
                )
            except ValueError as e:
                self._logger.error(f"Escalation validation failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Validation error: {str(e)}",
                )
            except Exception as e:
                self._logger.error(f"Escalation tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Escalation tool execution failed: {str(e)}",
                )

        # Handle agentRegistry.* tools (agent CRUD operations)
        if internal_tool_name.startswith("agentRegistry."):
            try:
                from .mcp.handlers.agent_registry_handlers import AGENT_REGISTRY_HANDLERS

                handler = AGENT_REGISTRY_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown agentRegistry tool: {internal_tool_name}",
                    )

                # All agentRegistry.* tools use AgentRegistryService
                service = self._services.agent_registry_service()

                # Call the async handler
                result = await handler(service=service, params=tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"agentRegistry tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"agentRegistry tool execution failed: {str(e)}",
                )

        # Handle reflection.* tools
        if internal_tool_name.startswith("reflection."):
            try:
                from .adapters import MCPReflectionServiceAdapter

                # Use registry's reflection_service (PostgreSQL or in-memory)
                service = self._services.reflection_service()
                adapter = MCPReflectionServiceAdapter(service=service)

                if internal_tool_name == "reflection.extract":
                    result = adapter.extract(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown reflection tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Reflection tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Reflection tool execution failed: {str(e)}",
                )

        # Handle security.* tools
        if internal_tool_name.startswith("security."):
            try:
                if internal_tool_name == "security.scanSecrets":
                    # Integrate with existing gitleaks scanner
                    repo_path = tool_params.get("repo_path", ".")
                    result = subprocess.run(
                        ["./scripts/scan_secrets.sh"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )

                    scan_result = {
                        "repo_path": repo_path,
                        "exit_code": result.returncode,
                        "clean": result.returncode == 0,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "message": "No secrets detected" if result.returncode == 0 else "Secrets detected or scan failed",
                    }
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown security tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(scan_result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except subprocess.TimeoutExpired:
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    "Secret scanning timed out after 60 seconds",
                )
            except Exception as e:
                self._logger.error(f"Security tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Security tool execution failed: {str(e)}",
                )

        # Handle tasks.* tools
        if internal_tool_name.startswith("tasks."):
            try:
                from .adapters import MCPTaskAssignmentAdapter

                service = self._services.task_assignment_service()
                adapter = MCPTaskAssignmentAdapter(service=service)

                if internal_tool_name == "tasks.listAssignments":
                    result = adapter.list_assignments(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown tasks tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Tasks tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Tasks tool execution failed: {str(e)}",
                )

        # Handle auth.* tools
        if internal_tool_name.startswith("auth."):
            try:
                from .adapters import MCPAgentAuthServiceAdapter

                service = self._services.agent_auth_service()
                adapter = MCPAgentAuthServiceAdapter(client=service)

                if internal_tool_name == "auth.ensureGrant":
                    result = adapter.ensure_grant(tool_params)
                elif internal_tool_name == "auth.listGrants":
                    result = adapter.list_grants(tool_params)
                elif internal_tool_name == "auth.policy.preview":
                    result = adapter.policy_preview(tool_params)
                elif internal_tool_name == "auth.revoke":
                    result = adapter.revoke(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown auth tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Auth tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Auth tool execution failed: {str(e)}",
                )

        # Handle fine-tuning.* tools (using midnighter package)
        if internal_tool_name.startswith("fine-tuning."):
            try:
                from .adapters import MCPFineTuningServiceAdapter

                service = self._services.fine_tuning_service()
                adapter = MCPFineTuningServiceAdapter(service=service)

                if internal_tool_name == "fine-tuning.create-corpus":
                    result = adapter.create_corpus(tool_params)
                elif internal_tool_name == "fine-tuning.generate-corpus":
                    result = adapter.generate_corpus(tool_params)
                elif internal_tool_name == "fine-tuning.start-job":
                    result = adapter.start_job(tool_params)
                elif internal_tool_name == "fine-tuning.status":
                    result = adapter.get_status(tool_params)
                elif internal_tool_name == "fine-tuning.list":
                    result = adapter.list_jobs(tool_params)
                elif internal_tool_name == "fine-tuning.list-corpora":
                    result = adapter.list_corpora(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown fine-tuning tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Fine-tuning tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Fine-tuning tool execution failed: {str(e)}",
                )

        # Handle reviews.* tools
        if internal_tool_name.startswith("reviews."):
            try:
                from .adapters import MCPAgentReviewServiceAdapter

                service = self._services.agent_review_service()
                adapter = MCPAgentReviewServiceAdapter(service=service)

                if internal_tool_name == "reviews.create":
                    result = adapter.create_review(tool_params)
                elif internal_tool_name == "reviews.status":
                    result = adapter.get_review_status(tool_params)
                elif internal_tool_name == "reviews.list":
                    result = adapter.list_reviews(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown reviews tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Reviews tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Reviews tool execution failed: {str(e)}",
                )

        # Handle tenants.* tools
        if internal_tool_name.startswith("tenants."):
            try:
                from .adapters import MCPMultiTenantServiceAdapter

                service = self._services.multi_tenant_service()
                adapter = MCPMultiTenantServiceAdapter(service=service)

                if internal_tool_name == "tenants.create":
                    result = adapter.create_tenant(tool_params)
                elif internal_tool_name == "tenants.status":
                    result = adapter.get_tenant_status(tool_params)
                elif internal_tool_name == "tenants.list":
                    result = adapter.list_tenants(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown tenants tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Tenants tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Tenants tool execution failed: {str(e)}",
                )

        # Handle retrieval.* tools
        if internal_tool_name.startswith("retrieval."):
            try:
                from .adapters import MCPAdvancedRetrievalServiceAdapter

                service = self._services.advanced_retrieval_service()
                adapter = MCPAdvancedRetrievalServiceAdapter(service=service)

                if internal_tool_name == "retrieval.advanced-search":
                    result = adapter.advanced_search(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown retrieval tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Retrieval tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Retrieval tool execution failed: {str(e)}",
                )

        # Handle collaboration.* tools
        if internal_tool_name.startswith("collaboration."):
            try:
                from .adapters import MCPCollaborationServiceAdapter

                service = self._services.collaboration_service()
                adapter = MCPCollaborationServiceAdapter(service=service)

                if internal_tool_name == "collaboration.workspace.create":
                    result = adapter.create_workspace(tool_params)
                elif internal_tool_name == "collaboration.workspace.status":
                    result = adapter.get_workspace_status(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown collaboration tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Collaboration tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Collaboration tool execution failed: {str(e)}",
                )

        # Handle mcp-rate-limits.* tools (MCP server rate limiting)
        if internal_tool_name.startswith("mcp-rate-limits."):
            try:
                if internal_tool_name == "mcp-rate-limits.status":
                    client_id = tool_params.get("client_id") or self._client_id or f"anonymous:{id(self)}"
                    status = self._rate_limiter.get_client_status(client_id)
                    if status is None:
                        result = {"error": f"No rate limit state for client: {client_id}"}
                    else:
                        result = status
                elif internal_tool_name == "mcp-rate-limits.metrics":
                    result = self._rate_limiter.get_metrics()
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown mcp-rate-limits tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"MCP rate limits tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"MCP rate limits tool execution failed: {str(e)}",
                )

        # Handle rate-limits.* tools (API rate limiting)
        if internal_tool_name.startswith("rate-limits."):
            try:
                from .adapters import MCPAPIRateLimitingServiceAdapter

                service = self._services.api_rate_limiting_service()
                adapter = MCPAPIRateLimitingServiceAdapter(service=service)

                if internal_tool_name == "rate-limits.configure":
                    result = adapter.configure_rate_limits(tool_params)
                elif internal_tool_name == "rate-limits.status":
                    result = adapter.get_rate_limit_status(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown rate-limits tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Rate limits tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Rate limits tool execution failed: {str(e)}",
                )

        # Handle raze.* tools for structured logging
        if internal_tool_name.startswith("raze."):
            try:
                service = self._services.raze_service()
                if service is None:
                    return self._error_response(
                        request_id,
                        self.INTERNAL_ERROR,
                        "Raze service not available (package not installed)",
                    )

                if internal_tool_name == "raze.emit":
                    # Emit a single log entry
                    result = service.emit(
                        level=tool_params.get("level", "info"),
                        message=tool_params["message"],
                        context=tool_params.get("context", {}),
                        run_id=tool_params.get("run_id"),
                        behavior_id=tool_params.get("behavior_id"),
                        tags=tool_params.get("tags", []),
                    )
                elif internal_tool_name == "raze.emit-batch":
                    # Emit multiple log entries
                    entries = tool_params.get("entries", [])
                    result = service.emit_batch(entries)
                elif internal_tool_name == "raze.query":
                    # Query logs with filters
                    result = service.query(
                        start_time=tool_params.get("start_time"),
                        end_time=tool_params.get("end_time"),
                        levels=tool_params.get("levels"),
                        run_id=tool_params.get("run_id"),
                        behavior_id=tool_params.get("behavior_id"),
                        tags=tool_params.get("tags"),
                        limit=tool_params.get("limit", 100),
                        offset=tool_params.get("offset", 0),
                    )
                elif internal_tool_name == "raze.aggregate":
                    # Get aggregated statistics
                    result = service.aggregate(
                        start_time=tool_params.get("start_time"),
                        end_time=tool_params.get("end_time"),
                        group_by=tool_params.get("group_by", ["level"]),
                        run_id=tool_params.get("run_id"),
                    )
                elif internal_tool_name == "raze.flush":
                    # Flush pending logs to sink
                    result = service.flush()
                elif internal_tool_name == "raze.status":
                    # Get service status
                    result = service.status()
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown raze tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Raze tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Raze tool execution failed: {str(e)}",
                )

        # Handle telemetry.* tools for telemetry querying and dashboards
        if internal_tool_name.startswith("telemetry."):
            try:
                if internal_tool_name == "telemetry.query":
                    # Query telemetry events using RazeService
                    service = self._services.raze_service()
                    if service is None:
                        return self._error_response(
                            request_id,
                            self.INTERNAL_ERROR,
                            "Telemetry service not available (Raze package not installed)",
                        )

                    # Parse date parameters with relative date support
                    from datetime import datetime, timezone, timedelta
                    import re

                    def _parse_relative_datetime(date_str: str) -> datetime:
                        if not date_str:
                            return datetime.now(timezone.utc)
                        # Try relative format (e.g., "7d", "24h", "30m")
                        match = re.match(r"^(\d+)([dhms])$", date_str.lower())
                        if match:
                            value = int(match.group(1))
                            unit = match.group(2)
                            delta_map = {"d": timedelta(days=value), "h": timedelta(hours=value),
                                         "m": timedelta(minutes=value), "s": timedelta(seconds=value)}
                            return datetime.now(timezone.utc) - delta_map[unit]
                        # Try ISO format
                        if len(date_str) == 10:
                            return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
                        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))

                    start_time = tool_params.get("start_time") or "7d"
                    end_time = tool_params.get("end_time")

                    query_params = {
                        "start_time": _parse_relative_datetime(start_time).isoformat() if start_time else None,
                        "end_time": _parse_relative_datetime(end_time).isoformat() if end_time else None,
                        "limit": tool_params.get("limit", 100),
                        "offset": tool_params.get("offset", 0),
                    }

                    # Add optional filters
                    if tool_params.get("event_type"):
                        query_params["event_type"] = tool_params["event_type"]
                    if tool_params.get("run_id"):
                        query_params["run_id"] = tool_params["run_id"]
                    if tool_params.get("action_id"):
                        query_params["action_id"] = tool_params["action_id"]
                    if tool_params.get("session_id"):
                        query_params["session_id"] = tool_params["session_id"]
                    if tool_params.get("actor_surface"):
                        query_params["actor_surface"] = tool_params["actor_surface"].replace("-", "_").lower()
                    if tool_params.get("level"):
                        query_params["level"] = tool_params["level"].upper()
                    if tool_params.get("search"):
                        query_params["search"] = tool_params["search"]

                    query_result = service.query(**query_params)
                    logs = query_result.logs if hasattr(query_result, 'logs') else query_result

                    result = {
                        "events": [log.to_dict() if hasattr(log, 'to_dict') else log for log in (logs or [])],
                        "total": len(logs) if logs else 0,
                        "limit": query_params["limit"],
                        "offset": query_params["offset"],
                    }

                elif internal_tool_name == "telemetry.dashboard":
                    # Dashboard using AnalyticsWarehouse
                    from datetime import datetime, timezone, timedelta
                    warehouse = self._services.analytics_service()

                    start_date = tool_params.get("start_date") or (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
                    end_date = tool_params.get("end_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    run_id = tool_params.get("run_id")

                    if run_id:
                        # Drill-down to specific run
                        token_data = warehouse.get_token_savings(run_id=run_id, limit=1)
                        cost_data = warehouse.get_cost_per_run(run_id=run_id)
                        record = token_data[0] if token_data else {}

                        result = {
                            "period": {"start": start_date, "end": end_date},
                            "run_detail": {
                                "run_id": run_id,
                                "token_accounting": {
                                    "baseline_tokens": record.get("baseline_tokens", 0),
                                    "actual_tokens": record.get("actual_tokens", 0),
                                    "tokens_saved": record.get("tokens_saved", 0),
                                    "savings_rate_pct": record.get("savings_rate_pct", 0),
                                },
                                "cost_breakdown": cost_data or [],
                            },
                        }
                    else:
                        # Summary dashboard
                        include_kpi = tool_params.get("include_kpi", True)
                        include_token_savings = tool_params.get("include_token_savings", True)
                        include_daily_costs = tool_params.get("include_daily_costs", True)
                        token_savings_limit = tool_params.get("token_savings_limit", 10)

                        result = {"period": {"start": start_date, "end": end_date}}

                        if include_kpi:
                            kpi_records = warehouse.get_kpi_summary(start_date=start_date, end_date=end_date)
                            latest = kpi_records[-1] if kpi_records else {}
                            result["kpi_summary"] = {
                                "behavior_reuse_rate_pct": latest.get("reuse_rate_pct", 0),
                                "token_savings_rate_pct": latest.get("avg_savings_rate_pct", 0),
                                "task_completion_rate_pct": latest.get("completion_rate_pct", 0),
                                "compliance_coverage_pct": latest.get("avg_coverage_rate_pct", 0),
                            }

                        if include_token_savings:
                            result["token_savings"] = warehouse.get_token_savings(
                                start_date=start_date, end_date=end_date, limit=token_savings_limit
                            )

                        if include_daily_costs:
                            result["daily_costs"] = warehouse.get_daily_cost_summary(
                                start_date=start_date, end_date=end_date
                            )

                        # Calculate totals
                        total_saved = sum(r.get("tokens_saved", 0) for r in result.get("token_savings", []))
                        total_cost = sum(r.get("total_cost_usd", 0) for r in result.get("daily_costs", []))
                        total_runs = sum(r.get("total_runs", 0) for r in result.get("daily_costs", []))
                        result["totals"] = {
                            "total_tokens_saved": total_saved,
                            "total_cost_usd": total_cost,
                            "total_runs": total_runs,
                        }

                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown telemetry tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, default=str),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Telemetry tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Telemetry tool execution failed: {str(e)}",
                )

        # Handle orgs.* tools (organization management)
        if internal_tool_name.startswith("orgs."):
            try:
                from .mcp.handlers.org_handlers import ORG_HANDLERS

                handler = ORG_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown orgs tool: {internal_tool_name}",
                    )

                # Get the organization service
                org_service = self._services.organization_service()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, org_service, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Orgs tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Orgs tool execution failed: {str(e)}",
                )

        # Handle projects.* tools (project management)
        if internal_tool_name.startswith("projects."):
            try:
                from .mcp.handlers.project_handlers import PROJECT_HANDLERS

                handler = PROJECT_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown projects tool: {internal_tool_name}",
                    )

                # Get services - OrganizationService handles both orgs and projects
                org_service = self._services.organization_service()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, org_service, org_service, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Projects tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Projects tool execution failed: {str(e)}",
                )

        # Handle boards.* tools (board management)
        if internal_tool_name.startswith("boards."):
            try:
                from .mcp.handlers.board_handlers import BOARD_HANDLERS

                handler = BOARD_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown boards tool: {internal_tool_name}",
                    )

                # Get the board service
                board_service = self._services.board_service()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, board_service, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Boards tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Boards tool execution failed: {str(e)}",
                )

        # Handle workItems.* tools (work item management and execution)
        if internal_tool_name.startswith("workItems."):
            # Execution tools (workItems.execute, executionStatus, etc.)
            execution_tools = {
                "workItems.execute",
                "workItems.executionStatus",
                "workItems.cancelExecution",
                "workItems.provideClarification",
                "workItems.listExecutions",
            }

            if internal_tool_name in execution_tools:
                try:
                    from .mcp.handlers.work_item_execution_handlers import (
                        create_work_item_execution_handlers,
                    )

                    # Get the work item execution service
                    work_item_execution_service = self._services.work_item_execution_service()

                    # Create handlers
                    handlers = create_work_item_execution_handlers(work_item_execution_service)
                    handler = handlers.get(internal_tool_name)

                    if not handler:
                        return self._error_response(
                            request_id,
                            self.METHOD_NOT_FOUND,
                            f"Unknown work item execution tool: {internal_tool_name}",
                        )

                    # Call the async handler
                    result = await handler(tool_params)

                    # Wrap result in MCP content format
                    mcp_result = {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2),
                            }
                        ]
                    }

                    return self._success_response(request_id, mcp_result)

                except Exception as e:
                    self._logger.error(f"Work item execution tool failed: {e}", exc_info=True)
                    return self._error_response(
                        request_id,
                        self.INTERNAL_ERROR,
                        f"Work item execution tool failed: {str(e)}",
                    )

            # Board management tools (workItems.create, update, delete, etc.)
            try:
                from .mcp.handlers.board_handlers import WORK_ITEM_HANDLERS

                handler = WORK_ITEM_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown workItems tool: {internal_tool_name}",
                    )

                # Get the board service (work items are managed by BoardService)
                board_service = self._services.board_service()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, board_service, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"WorkItems tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"WorkItems tool execution failed: {str(e)}",
                )

        # Handle files.* tools (file operations)
        if internal_tool_name.startswith("files."):
            try:
                from .mcp.handlers.file_handlers import FILE_HANDLERS

                handler = FILE_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown files tool: {internal_tool_name}",
                    )

                # File handlers don't need a service - they operate on the filesystem
                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, None, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Files tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Files tool execution failed: {str(e)}",
                )

        # Handle github.* tools (GitHub PR and commit operations)
        if internal_tool_name.startswith("github."):
            try:
                from .mcp.handlers.github_handlers import GITHUB_HANDLERS

                handler = GITHUB_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown github tool: {internal_tool_name}",
                    )

                # Get the GitHub service
                github_service = self._services.github_service()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, github_service, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"GitHub tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"GitHub tool execution failed: {str(e)}",
                )

        # Handle config.* tools (configuration and model availability)
        if internal_tool_name.startswith("config."):
            try:
                from .mcp.handlers.config_handlers import CONFIG_HANDLERS

                handler = CONFIG_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown config tool: {internal_tool_name}",
                    )

                # Get the credential store for model availability queries
                credential_store = self._services.credential_store()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, credential_store, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except KeyError as exc:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Missing required field: {exc}",
                )
            except ValueError as exc:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    str(exc),
                )
            except Exception as e:
                self._logger.error(f"Config tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Config tool execution failed: {str(e)}",
                )

        # Unknown tool prefix
        return self._error_response(
            request_id,
            self.METHOD_NOT_FOUND,
            f"Unknown tool: {internal_tool_name}",
        )

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get metrics summary for monitoring."""
        import statistics

        latency_summary = {}
        for tool_name, latencies in self._metrics["tool_latency_seconds"].items():
            if latencies:
                latency_summary[tool_name] = {
                    "count": len(latencies),
                    "mean": statistics.mean(latencies),
                    "median": statistics.median(latencies),
                    "min": min(latencies),
                    "max": max(latencies),
                    "p95": statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies),
                }

        return {
            "requests_total": self._metrics["requests_total"],
            "requests_by_method": dict(self._metrics["requests_by_method"]),
            "tool_calls_total": self._metrics["tool_calls_total"],
            "tool_calls_by_name": dict(self._metrics["tool_calls_by_name"]),
            "tool_latency_summary": latency_summary,
            "errors_total": self._metrics["errors_total"],
            "batch_requests_total": self._metrics["batch_requests_total"],
            "rate_limiting": self._rate_limiter.get_metrics(),
        }

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status for MCP server (Epic 6 - Health Check Endpoints).

        Returns health status including:
        - Overall status: "healthy", "degraded", or "unhealthy"
        - PostgreSQL connection pool stats per service
        - Tool manifest availability
        - Service registry status
        - Memory and uptime metrics

        Used by Dockerfile HEALTHCHECK and container orchestration.
        """
        import psutil

        health_checks: Dict[str, Dict[str, Any]] = {}
        overall_status = "healthy"
        degraded_services: List[str] = []
        failed_services: List[str] = []

        # Check PostgreSQL pools
        pool_checks: Dict[str, Any] = {}
        for dsn, pool in self._services._pools.items():
            try:
                stats = pool.get_pool_stats()
                service_name = stats.get("service", "unknown")
                pool_status = "healthy"

                # Check if pool is exhausted (available = 0 and connections checked out)
                if stats.get("available", 0) == 0 and stats.get("checked_out", 0) > 0:
                    pool_status = "degraded"
                    degraded_services.append(f"pool:{service_name}")

                pool_checks[service_name] = {
                    "status": pool_status,
                    "checked_out": stats.get("checked_out", 0),
                    "available": stats.get("available", 0),
                    "pool_size": stats.get("pool_size", 0),
                    "overflow": stats.get("overflow", 0),
                }
            except Exception as e:
                service_name = dsn[:20] + "..." if len(dsn) > 20 else dsn
                pool_checks[service_name] = {
                    "status": "unhealthy",
                    "error": str(e),
                }
                failed_services.append(f"pool:{service_name}")

        health_checks["postgres_pools"] = pool_checks

        # Check service registry status
        services_status: Dict[str, str] = {}
        for service_name, attr_name in [
            ("behavior", "_behavior_service"),
            ("bci", "_bci_service"),
            ("workflow", "_workflow_service"),
            ("action", "_action_service"),
            ("run", "_run_service"),
            ("compliance", "_compliance_service"),
            ("agent_auth", "_agent_auth_service"),
            ("metrics", "_metrics_service"),
        ]:
            # Check if service has been initialized (lazy loading)
            service = getattr(self._services, attr_name, None)
            if service is not None:
                services_status[service_name] = "initialized"
            else:
                services_status[service_name] = "not_loaded"  # Lazy - will initialize on first use

        health_checks["services"] = services_status

        # Check tool manifests
        tools_status = {
            "loaded_count": len(self._tools),
            "status": "healthy" if len(self._tools) > 0 else "degraded",
            "tools": list(self._tools.keys())[:10],  # First 10 tools
            "total_tools": len(self._tools),
        }
        if len(self._tools) == 0:
            degraded_services.append("tools")

        health_checks["tools"] = tools_status

        # Memory and process metrics
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            health_checks["process"] = {
                "memory_rss_mb": round(memory_info.rss / 1024 / 1024, 2),
                "memory_vms_mb": round(memory_info.vms / 1024 / 1024, 2),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "num_threads": process.num_threads(),
                "open_files": len(process.open_files()),
                "uptime_seconds": round(time.time() - process.create_time(), 2),
            }
        except Exception as e:
            health_checks["process"] = {"status": "unavailable", "error": str(e)}

        # Connection stability metrics
        health_checks["connection"] = {
            "idle_seconds": round(time.time() - self._last_activity, 2),
            "idle_timeout_seconds": self._idle_timeout_seconds,
            "shutdown_requested": self._shutdown_requested,
            "pending_requests": len(self._pending_requests),
        }

        # Determine overall status
        if failed_services:
            overall_status = "unhealthy"
        elif degraded_services:
            overall_status = "degraded"

        return {
            "status": overall_status,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "version": "0.1.0",
            "environment": os.environ.get("GUIDEAI_ENV", os.environ.get("ENVIRONMENT", "development")),
            "transport": os.environ.get("MCP_TRANSPORT", "stdio"),
            "checks": health_checks,
            "degraded_services": degraded_services,
            "failed_services": failed_services,
        }

    def _success_response(self, request_id: Optional[str], result: Any) -> str:
        """Build JSON-RPC success response."""
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        return json.dumps(response)

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """
        Send a JSON-RPC notification (no response expected).

        Notifications are JSON-RPC messages without an 'id' field.
        They're useful for progress updates during long-running operations.
        """
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_stdout_message(json.dumps(notification))
        self._logger.debug(f"Sent notification: {method}")

    def _error_response(self, request_id: Optional[str], code: int, message: str, data: Any = None) -> str:
        """Build JSON-RPC error response."""
        error = {
            "code": code,
            "message": message,
        }
        if data is not None:
            error["data"] = data

        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error,
        }
        return json.dumps(response)

    async def run(self) -> None:
        """Run MCP server main loop (stdio)."""
        self._logger.info("GuideAI MCP Server starting...")
        self._logger.info(f"Loaded {len(self._tools)} tools: {', '.join(self._tools.keys())}")
        self._logger.info(f"Idle timeout: {self._idle_timeout_seconds}s, Shutdown timeout: {self._graceful_shutdown_timeout}s")

        # Setup signal handlers for graceful shutdown (Epic 6 - Connection Stability)
        loop = asyncio.get_event_loop()

        def signal_handler(signum: int) -> None:
            sig_name = signal.Signals(signum).name
            self._logger.info(f"Received {sig_name}, initiating graceful shutdown...")
            self._shutdown_requested = True

        # Register signal handlers (Unix only)
        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

        # Start idle connection cleanup task
        self._idle_check_task = asyncio.create_task(self._idle_connection_monitor())

        try:
            # Read requests from stdin, write responses to stdout
            while not self._shutdown_requested:
                # Read one line (JSON-RPC request) with timeout for shutdown check
                try:
                    request_line = await asyncio.wait_for(
                        loop.run_in_executor(None, self._read_stdin_message_blocking),
                        timeout=1.0  # Check shutdown flag every second
                    )
                except asyncio.TimeoutError:
                    continue  # Check shutdown flag and continue

                if not request_line:
                    self._logger.info("Stdin closed, shutting down")
                    break

                request_line = request_line.strip()
                if not request_line:
                    continue

                # Update last activity for idle tracking
                self._last_activity = time.time()

                # Handle request
                response = await self.handle_request(request_line)

                if response:
                    self._write_stdout_message(response)

        except KeyboardInterrupt:
            self._logger.info("Received keyboard interrupt")
            self._shutdown_requested = True
        except Exception as e:
            self._logger.error(f"Server error: {e}", exc_info=True)
            self._shutdown_requested = True
        finally:
            await self._graceful_shutdown()

    async def _idle_connection_monitor(self) -> None:
        """Monitor for idle connections and cleanup resources (Epic 6 - Connection Stability)."""
        self._logger.info(f"Starting idle connection monitor (timeout: {self._idle_timeout_seconds}s)")

        while not self._shutdown_requested:
            try:
                await asyncio.sleep(60)  # Check every minute

                idle_duration = time.time() - self._last_activity
                if idle_duration >= self._idle_timeout_seconds:
                    self._logger.warning(
                        f"Connection idle for {idle_duration:.0f}s (threshold: {self._idle_timeout_seconds}s), "
                        "initiating idle cleanup..."
                    )
                    # Perform idle cleanup
                    await self._cleanup_idle_resources()
                    # Reset activity timer after cleanup
                    self._last_activity = time.time()
                elif idle_duration > self._idle_timeout_seconds * 0.8:
                    # Warn when approaching idle timeout
                    self._logger.info(
                        f"Connection approaching idle timeout: {idle_duration:.0f}s / {self._idle_timeout_seconds}s"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error in idle monitor: {e}", exc_info=True)

    async def _cleanup_idle_resources(self) -> None:
        """Clean up resources when connection is idle (Epic 6 - Connection Stability)."""
        self._logger.info("Performing idle resource cleanup...")

        try:
            # Release service caches to free memory
            self._services._behavior_service = None
            self._services._bci_service = None
            self._services._workflow_service = None
            self._services._trace_analysis_service = None
            self._services._run_service = None
            self._services._metrics_service = None
            self._services._analytics_service = None

            # Note: We keep action_service and agent_auth_service as they hold auth state
            # They'll be re-initialized lazily on next request

            self._logger.info("Idle cleanup completed - services will be re-initialized on next request")
        except Exception as e:
            self._logger.error(f"Error during idle cleanup: {e}", exc_info=True)

    async def _graceful_shutdown(self) -> None:
        """Gracefully shutdown server, draining pending requests (Epic 6 - Connection Stability)."""
        self._logger.info("Starting graceful shutdown...")

        # Cancel idle monitor
        if self._idle_check_task and not self._idle_check_task.done():
            self._idle_check_task.cancel()
            try:
                await self._idle_check_task
            except asyncio.CancelledError:
                pass

        # Wait for pending requests to complete with timeout
        if self._pending_requests:
            self._logger.info(f"Waiting for {len(self._pending_requests)} pending requests to complete...")
            pending_tasks = list(self._pending_requests.values())

            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_tasks, return_exceptions=True),
                    timeout=self._graceful_shutdown_timeout
                )
                self._logger.info("All pending requests completed")
            except asyncio.TimeoutError:
                self._logger.warning(
                    f"Shutdown timeout ({self._graceful_shutdown_timeout}s) reached, "
                    f"cancelling {len(pending_tasks)} remaining requests"
                )
                for task in pending_tasks:
                    task.cancel()

        # Cleanup services
        self._logger.info("Cleaning up services...")
        try:
            # Close database pools
            if self._services._pools:
                for dsn, pool in self._services._pools.items():
                    try:
                        pool.close()
                        self._logger.info(f"Closed pool for DSN: {dsn[:50]}...")
                    except Exception as e:
                        self._logger.error(f"Error closing pool: {e}")
                self._services._pools.clear()
        except Exception as e:
            self._logger.error(f"Error closing database pools: {e}")

        self._logger.info("Graceful shutdown completed")


async def main() -> None:
    """Main entry point for MCP server."""
    server = MCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
