"""FastAPI application exposing GuideAI service stubs over HTTP."""

from __future__ import annotations

# Load environment variables from .env files before anything else
from pathlib import Path as _Path
from dotenv import load_dotenv as _load_dotenv

_project_root = _Path(__file__).parent.parent
for _env_file in [".env", ".env.github-oauth", ".env.google-oauth"]:
    _env_path = _project_root / _env_file
    if _env_path.exists():
        _load_dotenv(_env_path)

import asyncio
import base64
import html
import json
import logging
import os
import secrets
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from fastapi import FastAPI, HTTPException, Query, Response, status, Request, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from .action_service import (
    ActionNotFoundError,
    ActionService,
    ActionServiceError,
    ReplayNotFoundError,
)
from .action_contracts import Actor
from .action_service_postgres import PostgresActionService
from .adapters import (
    RestActionServiceAdapter,
    RestAgentAuthServiceAdapter,
    RestAgentRegistryAdapter,
    RestAmprealizeAdapter,
    RestBehaviorServiceAdapter,
    RestBCIAdapter,
    RestComplianceServiceAdapter,
    RestMetricsServiceAdapter,
    RestReflectionAdapter,
    RestRunServiceAdapter,
    RestTaskAssignmentAdapter,
    RestAssignmentAdapter,
    RestWorkflowServiceAdapter,
)
from .amprealize import (
    PlanRequest,
    PlanResponse,
    ApplyRequest,
    ApplyResponse,
    StatusResponse,
    DestroyRequest,
    DestroyResponse,
    AmprealizeService,
)
from .behavior_service import (
    BehaviorNotFoundError,
    BehaviorService,
    BehaviorServiceError,
)

# Agent Registry imports (lazy to avoid circular imports at startup)
try:
    from .agent_registry_service import (
        AgentRegistryService,
        AgentNotFoundError,
        AgentVersionNotFoundError,
        AgentRegistryError,
    )
    AGENT_REGISTRY_AVAILABLE = True
except ImportError:
    AGENT_REGISTRY_AVAILABLE = False
    AgentRegistryService = None  # type: ignore[assignment, misc]
    AgentNotFoundError = Exception  # type: ignore[assignment, misc]
    AgentVersionNotFoundError = Exception  # type: ignore[assignment, misc]
    AgentRegistryError = Exception  # type: ignore[assignment, misc]
from .compliance_service import (
    ChecklistNotFoundError,
    ComplianceService,
    ComplianceServiceError,
)
from .agent_auth import AgentAuthClient
from .auth.providers import InvalidCredentialsError, OAuthError
from .auth.providers.internal import InternalAuthProvider
from .auth.providers.github import GitHubOAuthProvider
from .auth.providers.google import GoogleOAuthProvider
from .device_flow import (
    DeviceAuthorizationStatus,
    DeviceAuthorizationSession,
    DeviceFlowManager,
    DeviceCodeNotFoundError,
    UserCodeNotFoundError,
    DeviceCodeExpiredError,
    DeviceFlowError,
    RefreshTokenNotFoundError,
    RefreshTokenExpiredError,
)
from .task_assignments import TaskAssignmentService
from .telemetry import TelemetryClient, create_sink_from_env
from .workflow_service import WorkflowService, WorkflowStatus
from .analytics.telemetry_kpi_projector import TelemetryKPIProjector, TelemetryProjection
from .analytics.warehouse import AnalyticsWarehouse
from .behavior_retriever import BehaviorRetriever
from .bci_service import BCIService
from .metrics_service import MetricsService
from .metrics_service_postgres import PostgresMetricsService
from .reflection_service import ReflectionService
from .reflection_service_postgres import PostgresReflectionService
from .collaboration_contracts import (
    CollaborationRole,
    CreateDocumentRequest,
    CreateWorkspaceRequest,
    EditOperationType,
    RealTimeEditRequest,
)
from .collaboration_service import CollaborationService, VersionConflictError
from .collaboration_service_postgres import PostgresCollaborationService
from .projects_api import InMemoryProjectStore, create_project_routes
from .run_service import RunService, RunNotFoundError
from .run_service_postgres import PostgresRunService
from .utils.dsn import resolve_optional_postgres_dsn
from .services.board_service import BoardService
from .services.assignment_service import AssignmentService
from .services.board_api_v2 import create_board_routes

# Raze structured logging (optional dependency)
try:
    from raze import RazeService, RazeLogger
    from raze.sinks import InMemorySink
    from raze.integrations.fastapi import create_log_routes, RazeMiddleware
    RAZE_AVAILABLE = True
except ImportError:
    RAZE_AVAILABLE = False
    RazeService = None  # type: ignore[assignment, misc]
    RazeLogger = None  # type: ignore[assignment, misc]

# Multi-tenant organization management (optional - requires PostgreSQL)
try:
    from .multi_tenant.organization_service import OrganizationService
    from .multi_tenant.invitation_service import InvitationService
    from .multi_tenant.api import create_org_routes
    MULTI_TENANT_AVAILABLE = True
except ImportError:
    MULTI_TENANT_AVAILABLE = False
    OrganizationService = None  # type: ignore[assignment, misc]
    InvitationService = None  # type: ignore[assignment, misc]
    create_org_routes = None  # type: ignore[assignment, misc]

# Billing service (optional - requires billing package)
try:
    from billing import BillingService, MockBillingProvider
    try:
        from billing.providers.stripe import StripeBillingProvider
        STRIPE_AVAILABLE = True
    except ImportError:
        STRIPE_AVAILABLE = False
        StripeBillingProvider = None  # type: ignore[assignment, misc]
    from .billing.api import create_billing_router
    BILLING_AVAILABLE = True
except ImportError:
    BILLING_AVAILABLE = False
    BillingService = None  # type: ignore[assignment, misc]
    MockBillingProvider = None  # type: ignore[assignment, misc]
    StripeBillingProvider = None  # type: ignore[assignment, misc]
    create_billing_router = None  # type: ignore[assignment, misc]
    STRIPE_AVAILABLE = False


class _UnavailableWarehouse:
    """Fallback analytics warehouse that raises a helpful error when invoked."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def _unavailable(self, *_: Any, **__: Any) -> List[Dict[str, Any]]:
        raise RuntimeError(self._reason)

    get_kpi_summary = _unavailable
    get_behavior_usage = _unavailable
    get_token_savings = _unavailable
    get_compliance_coverage = _unavailable


class _ServiceContainer:
    """Lazily constructed service instances shared by API routes."""

    def __init__(
        self,
        *,
        behavior_db_path: Optional[Path] = None,
        workflow_db_path: Optional[Path] = None,
    ) -> None:
        logger = logging.getLogger(__name__)
        telemetry = TelemetryClient(
            sink=create_sink_from_env(),
            default_actor={
                "id": "guideai-api",
                "role": "SYSTEM",
                "surface": "api",
            },
        )

        # ActionService now uses PostgreSQL DSN from environment or default
        action_dsn = resolve_optional_postgres_dsn(
            service="ACTION",
            explicit_dsn=None,
            env_var="GUIDEAI_ACTION_PG_DSN",
        )
        if action_dsn:
            self.action_service = PostgresActionService(dsn=action_dsn, telemetry=telemetry)
        else:
            # Fallback to in-memory for testing
            self.action_service = ActionService(telemetry=telemetry)
        self.action_adapter = RestActionServiceAdapter(self.action_service)

        # ComplianceService uses PostgreSQL (required); resolves DSN from GUIDEAI_COMPLIANCE_PG_DSN env var
        self.compliance_service = ComplianceService(dsn=None, telemetry=telemetry)
        self.compliance_adapter = RestComplianceServiceAdapter(self.compliance_service)

        # BehaviorService now uses PostgreSQL DSN from environment or default
        # behavior_db_path parameter is deprecated (was SQLite path)
        self.behavior_service = BehaviorService(
            dsn=None,  # Uses GUIDEAI_BEHAVIOR_PG_DSN environment variable
            telemetry=telemetry,
        )
        self.behavior_adapter = RestBehaviorServiceAdapter(self.behavior_service)

        # AgentRegistryService uses PostgreSQL DSN from environment
        self.agent_registry_service = None
        self.agent_registry_adapter = None
        if AGENT_REGISTRY_AVAILABLE:
            agent_dsn = resolve_optional_postgres_dsn(
                service="AGENT_REGISTRY",
                explicit_dsn=None,
                env_var="GUIDEAI_AGENT_REGISTRY_PG_DSN",
            )
            if agent_dsn:
                self.agent_registry_service = AgentRegistryService(
                    dsn=agent_dsn,
                    telemetry=telemetry,
                )
                self.agent_registry_adapter = RestAgentRegistryAdapter(self.agent_registry_service)
            else:
                logger.warning("AgentRegistryService skipped: No DSN configured")

        self.behavior_retriever = BehaviorRetriever(
            behavior_service=self.behavior_service,
            telemetry=telemetry,
            eager_load_model=False,  # Disable eager model loading to avoid OOM in staging
        )
        setattr(self.behavior_service, "_behavior_retriever", self.behavior_retriever)

        self.bci_service = BCIService(
            behavior_service=self.behavior_service,
            telemetry=telemetry,
            behavior_retriever=self.behavior_retriever,
        )
        self.bci_adapter = RestBCIAdapter(self.bci_service)

        # ReflectionService uses PostgreSQL DSN from environment or fallback to in-memory
        reflection_dsn = resolve_optional_postgres_dsn(
            service="REFLECTION",
            explicit_dsn=None,
            env_var="GUIDEAI_REFLECTION_PG_DSN",
        )
        if reflection_dsn:
            self.reflection_service = PostgresReflectionService(
                dsn=reflection_dsn,
                behavior_service=self.behavior_service,
                bci_service=self.bci_service,
                telemetry=telemetry,
            )
        else:
            self.reflection_service = ReflectionService(
                behavior_service=self.behavior_service,
                bci_service=self.bci_service,
                telemetry=telemetry,
            )
        self.reflection_adapter = RestReflectionAdapter(self.reflection_service)

        # WorkflowService now uses PostgreSQL DSN from environment or default
        # workflow_db_path parameter is deprecated (was SQLite path)
        self.workflow_service = WorkflowService(
            dsn=None,  # Uses GUIDEAI_WORKFLOW_PG_DSN environment variable
            behavior_service=self.behavior_service,
        )
        self.workflow_adapter = RestWorkflowServiceAdapter(self.workflow_service)

        # MetricsService uses PostgreSQL DSN from environment or fallback to in-memory cache
        metrics_dsn = resolve_optional_postgres_dsn(
            service="METRICS",
            explicit_dsn=None,
            env_var="GUIDEAI_METRICS_PG_DSN",
        )
        if metrics_dsn:
            self.metrics_service = PostgresMetricsService(dsn=metrics_dsn)
        else:
            self.metrics_service = MetricsService()
        self.metrics_adapter = RestMetricsServiceAdapter(self.metrics_service)

        self.amprealize_service = AmprealizeService(
            action_service=cast(ActionService, self.action_service),
            compliance_service=self.compliance_service,
            metrics_service=self.metrics_service,
        )
        self.amprealize_adapter = RestAmprealizeAdapter(self.amprealize_service)

        # Initialize AgentAuth client and adapter
        self.agent_auth_client = AgentAuthClient(telemetry=telemetry)
        self.agent_auth_adapter = RestAgentAuthServiceAdapter(self.agent_auth_client)

        # Initialize internal auth provider for username/password authentication.
        # This is optional; device-flow prototype auth can run without it.
        internal_provider: Optional[InternalAuthProvider]
        try:
            internal_provider = InternalAuthProvider(dsn=None)
        except Exception as exc:
            internal_provider = None
            logger.warning("InternalAuthProvider unavailable; continuing without internal auth: %s", exc)
        self.device_flow_manager = DeviceFlowManager(
            telemetry=telemetry,
            provider=internal_provider,
        )

        # Initialize OAuth providers for social login (GitHub, Google)
        # These are optional; if credentials are not set, the provider will be None
        self.github_provider: Optional[GitHubOAuthProvider] = None
        self.google_provider: Optional[GoogleOAuthProvider] = None

        github_client_id = os.getenv("GITHUB_CLIENT_ID") or os.getenv("OAUTH_CLIENT_ID")
        github_client_secret = os.getenv("GITHUB_CLIENT_SECRET") or os.getenv("OAUTH_CLIENT_SECRET")
        if github_client_id and github_client_secret:
            self.github_provider = GitHubOAuthProvider(
                client_id=github_client_id,
                client_secret=github_client_secret,
            )
            logger.info("GitHub OAuth provider initialized for social login")
        else:
            logger.info("GitHub OAuth provider not configured (missing GITHUB_CLIENT_ID/SECRET)")

        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        if google_client_id and google_client_secret:
            self.google_provider = GoogleOAuthProvider(
                client_id=google_client_id,
                client_secret=google_client_secret,
            )
            logger.info("Google OAuth provider initialized for social login")
        else:
            logger.info("Google OAuth provider not configured (missing GOOGLE_CLIENT_ID/SECRET)")

        # RunService uses PostgreSQL DSN from environment or fallback to SQLite
        run_dsn = resolve_optional_postgres_dsn(
            service="RUN",
            explicit_dsn=None,
            env_var="GUIDEAI_RUN_PG_DSN",
        )
        if run_dsn:
            self.run_service = PostgresRunService(dsn=run_dsn, telemetry=telemetry)
        else:
            self.run_service = RunService(telemetry=telemetry)
        self.run_adapter = RestRunServiceAdapter(self.run_service)

        # CollaborationService uses PostgreSQL DSN from environment or falls back to in-memory.
        collaboration_dsn = resolve_optional_postgres_dsn(
            service="COLLABORATION",
            explicit_dsn=None,
            env_var="GUIDEAI_COLLABORATION_PG_DSN",
        )
        if collaboration_dsn:
            self.collaboration_service = PostgresCollaborationService(dsn=collaboration_dsn, telemetry=telemetry)
        else:
            self.collaboration_service = CollaborationService(telemetry=telemetry)

        self.task_assignment_service = TaskAssignmentService()
        self.task_adapter = RestTaskAssignmentAdapter(self.task_assignment_service)

        # Projects are available without PostgreSQL (in-memory fallback).
        self.project_store = InMemoryProjectStore()

        # Board/Assignment services for agent suggestions
        self.board_service = BoardService(pool=None, telemetry=telemetry)
        self.assignment_service = AssignmentService(
            dsn=None,
            telemetry=telemetry,
            board_service=self.board_service,
        )
        self.assignment_adapter = RestAssignmentAdapter(self.assignment_service)

        # Multi-tenant organization services (requires PostgreSQL)
        self.org_service: Optional[Any] = None
        self.invitation_service: Optional[Any] = None
        if MULTI_TENANT_AVAILABLE:
            org_dsn = resolve_optional_postgres_dsn(
                service="ORG",
                explicit_dsn=os.getenv("GUIDEAI_ORG_PG_DSN") or os.getenv("GUIDEAI_AUTH_PG_DSN"),
                env_var="GUIDEAI_ORG_PG_DSN",
            )
            if org_dsn:
                self.org_service = OrganizationService(
                    dsn=org_dsn,
                    board_service=self.board_service,
                )
                self.invitation_service = InvitationService(
                    dsn=org_dsn,
                    base_url=os.getenv("GUIDEAI_BASE_URL", "https://guideai.dev"),
                )

        # Billing service (uses Stripe if credentials provided, otherwise mock)
        self.billing_service: Optional[Any] = None
        if BILLING_AVAILABLE:
            stripe_api_key = os.getenv("GUIDEAI_STRIPE_API_KEY")
            stripe_webhook_secret = os.getenv("GUIDEAI_STRIPE_WEBHOOK_SECRET")
            if STRIPE_AVAILABLE and stripe_api_key:
                provider = StripeBillingProvider(
                    api_key=stripe_api_key,
                    webhook_secret=stripe_webhook_secret,
                )
                logger.info("BillingService initialized with Stripe provider")
            else:
                provider = MockBillingProvider()
                logger.info("BillingService initialized with Mock provider (no Stripe credentials)")
            self.billing_service = BillingService(provider=provider)

        # Analytics: supports DuckDB (GUIDEAI_ANALYTICS_WAREHOUSE_PATH) or
        # Postgres/TimescaleDB (GUIDEAI_ANALYTICS_PG_DSN or GUIDEAI_TELEMETRY_PG_DSN)
        warehouse_path = os.getenv("GUIDEAI_ANALYTICS_WAREHOUSE_PATH")
        analytics_dsn = resolve_optional_postgres_dsn(
            service="ANALYTICS",
            explicit_dsn=os.getenv("GUIDEAI_ANALYTICS_PG_DSN") or os.getenv("GUIDEAI_TELEMETRY_PG_DSN"),
            env_var="GUIDEAI_ANALYTICS_PG_DSN",
        )
        if warehouse_path:
            self.analytics_warehouse = AnalyticsWarehouse(db_path=Path(warehouse_path))
        elif analytics_dsn:
            self.analytics_warehouse = AnalyticsWarehouse(dsn=analytics_dsn)
        else:
            self.analytics_warehouse = _UnavailableWarehouse("Analytics warehouse not configured")

        self.telemetry_projector = TelemetryKPIProjector()

        # Raze structured logging service (optional)
        self.raze_service: Optional[Any] = None
        if RAZE_AVAILABLE:
            raze_dsn = os.getenv("RAZE_TIMESCALEDB_DSN") or os.getenv("GUIDEAI_RAZE_DSN")
            if raze_dsn:
                try:
                    from raze.sinks import TimescaleDBSink
                    raze_sink = TimescaleDBSink(dsn=raze_dsn)
                except Exception:
                    # Fallback to in-memory if TimescaleDB unavailable
                    raze_sink = InMemorySink()
            else:
                # Use in-memory sink for development/testing
                raze_sink = InMemorySink()

            self.raze_service = RazeService(
                sink=raze_sink,
                batch_size=1000,
                linger_ms=100,
            )


def _normalize_user_code(user_code: str) -> str:
    """Normalise user code input (case-insensitive, remove separators)."""

    alphanumeric = "".join(ch for ch in user_code if ch.isalnum())
    if not alphanumeric:
        raise ValueError("user_code must contain letters or numbers")
    upper = alphanumeric.upper()
    if len(upper) >= 8:
        midpoint = len(upper) // 2
        return f"{upper[:midpoint]}-{upper[midpoint:]}"
    return upper


def _render_device_activation_page(
    *,
    user_code: str = "",
    session: Optional[DeviceAuthorizationSession] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> HTMLResponse:
    safe_code = html.escape(user_code or "")

    banners: List[str] = []
    if error:
        banners.append(f'<div class="alert alert-error">{html.escape(error)}</div>')
    if message:
        banners.append(f'<div class="alert alert-success">{html.escape(message)}</div>')
    alerts_html = "\n".join(banners)

    details_html = ""
    if session is not None:
        status_class = session.status.value.lower()
        scopes_display = ", ".join(session.scopes) or "-"
        metadata_html = "\n".join(
            f"<li><strong>{html.escape(str(key))}</strong> {html.escape(str(value))}</li>"
            for key, value in sorted(session.metadata.items())
        ) or "<li>No additional metadata</li>"

        tokens_html = ""
        if session.tokens is not None:
            access_expires = session.tokens.access_token_expires_at.isoformat()
            refresh_expires = session.tokens.refresh_token_expires_at.isoformat()
            tokens_html = textwrap.dedent(
                f"""
                <div class=\"token-card\">
                    <h3>Issued Tokens</h3>
                    <dl>
                        <div>
                            <dt>Access token expires</dt>
                            <dd>{html.escape(access_expires)} ({session.tokens.access_expires_in()}s)</dd>
                        </div>
                        <div>
                            <dt>Refresh token expires</dt>
                            <dd>{html.escape(refresh_expires)} ({session.tokens.refresh_expires_in()}s)</dd>
                        </div>
                    </dl>
                </div>
                """
            ).strip()

        actions_html = ""
        if session.status is DeviceAuthorizationStatus.PENDING:
            actions_html = textwrap.dedent(
                f"""
                <div class=\"action-grid\">
                    <form method=\"post\" class=\"card\">
                        <h3>Approve access</h3>
                        <input type=\"hidden\" name=\"action\" value=\"approve\" />
                        <input type=\"hidden\" name=\"user_code\" value=\"{html.escape(session.user_code)}\" />
                        <label for=\"approve-name\">Approver name</label>
                        <input id=\"approve-name\" name=\"approver\" value=\"web-reviewer\" required />
                        <label for=\"approve-roles\">Roles (comma-separated)</label>
                        <input id=\"approve-roles\" name=\"roles\" value=\"STRATEGIST\" />
                        <label class=\"checkbox\">
                            <input type=\"checkbox\" name=\"mfa_verified\" value=\"true\" /> MFA verified
                        </label>
                        <button type=\"submit\" class=\"btn primary\">Approve</button>
                    </form>
                    <form method=\"post\" class=\"card\">
                        <h3>Deny request</h3>
                        <input type=\"hidden\" name=\"action\" value=\"deny\" />
                        <input type=\"hidden\" name=\"user_code\" value=\"{html.escape(session.user_code)}\" />
                        <label for=\"deny-name\">Responder</label>
                        <input id=\"deny-name\" name=\"approver\" value=\"web-reviewer\" required />
                        <label for=\"deny-reason\">Reason</label>
                        <input id=\"deny-reason\" name=\"reason\" placeholder=\"Optional reason\" />
                        <button type=\"submit\" class=\"btn danger\">Deny</button>
                    </form>
                </div>
                """
            ).strip()

        details_html = textwrap.dedent(
            f"""
            <section class=\"card\">
                <h2>Consent request</h2>
                <div class=\"status-row\">
                    <span class=\"status-badge status-{status_class}\">{html.escape(session.status.value.title())}</span>
                    <span class=\"status-meta\">Expires in {session.expires_in()}s</span>
                </div>
                <dl class=\"details\">
                    <div><dt>User code</dt><dd>{html.escape(session.user_code)}</dd></div>
                    <div><dt>Client ID</dt><dd>{html.escape(session.client_id)}</dd></div>
                    <div><dt>Surface</dt><dd>{html.escape(session.surface)}</dd></div>
                    <div><dt>Scopes</dt><dd>{html.escape(scopes_display)}</dd></div>
                    <div><dt>Created</dt><dd>{html.escape(session.created_at.isoformat())}</dd></div>
                    <div><dt>Expires</dt><dd>{html.escape(session.expires_at.isoformat())}</dd></div>
                </dl>
                <div class=\"metadata\">
                    <h3>Metadata</h3>
                    <ul>{metadata_html}</ul>
                </div>
                {tokens_html}
            </section>
            {actions_html}
            """
        ).strip()

    page = textwrap.dedent(
        f"""
        <!DOCTYPE html>
        <html lang=\"en\">
        <head>
            <meta charset=\"utf-8\" />
            <title>GuideAI Device Activation</title>
            <style>
                :root {{
                    font-family: 'Inter', system-ui, sans-serif;
                    color: #0f172a;
                    background: #f8fafc;
                }}
                body {{
                    margin: 0;
                    padding: 0 16px 32px;
                    display: flex;
                    justify-content: center;
                }}
                main {{
                    max-width: 720px;
                    width: 100%;
                }}
                h1 {{
                    font-size: 1.75rem;
                    margin-top: 32px;
                    margin-bottom: 8px;
                }}
                p.subtitle {{
                    margin-top: 0;
                    color: #475569;
                }}
                .card {{
                    background: #ffffff;
                    border-radius: 16px;
                    padding: 24px;
                    margin-top: 24px;
                }}
                label {{
                    display: block;
                    font-weight: 600;
                    margin-bottom: 6px;
                }}
                input[type=\"text\"], input:not([type]) {{
                    width: 100%;
                    padding: 12px;
                    border-radius: 10px;
                    border: 1px solid #cbd5f5;
                    margin-bottom: 16px;
                    font-size: 1rem;
                }}
                button {{
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    padding: 12px 20px;
                    border-radius: 999px;
                    border: none;
                    font-weight: 600;
                    cursor: pointer;
                    transition: transform 0.15s ease;
                }}
                button:hover {{
                    transform: translateY(-1px);
                }}
                .btn.primary {{
                    background: #2563eb;
                    color: #fff;
                }}
                .btn.danger {{
                    background: #dc2626;
                    color: #fff;
                }}
                .alert {{
                    margin-top: 20px;
                    padding: 14px 18px;
                    border-radius: 12px;
                    font-weight: 600;
                }}
                .alert-error {{
                    background: rgba(239, 68, 68, 0.12);
                    color: #b91c1c;
                }}
                .alert-success {{
                    background: rgba(16, 185, 129, 0.12);
                    color: #047857;
                }}
                .status-row {{
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    margin-bottom: 16px;
                }}
                .status-badge {{
                    padding: 6px 14px;
                    border-radius: 999px;
                    font-size: 0.875rem;
                    font-weight: 600;
                }}
                .status-pending {{ background: #fef3c7; color: #92400e; }}
                .status-approved {{ background: #dcfce7; color: #166534; }}
                .status-denied {{ background: #fee2e2; color: #991b1b; }}
                .status-expired {{ background: #e2e8f0; color: #475569; }}
                dl.details {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 12px;
                }}
                dl.details div {{
                    background: #f8fafc;
                    border-radius: 12px;
                    padding: 12px;
                }}
                dl.details dt {{
                    font-size: 0.75rem;
                    text-transform: uppercase;
                    color: #64748b;
                    margin-bottom: 4px;
                }}
                dl.details dd {{
                    margin: 0;
                    font-weight: 600;
                }}
                .metadata ul {{
                    margin: 0;
                    padding-left: 18px;
                }}
                .token-card {{
                    margin-top: 18px;
                    background: #f0f9ff;
                    border-radius: 12px;
                    padding: 16px;
                }}
                .token-card h3 {{
                    margin-top: 0;
                }}
                .action-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                    gap: 16px;
                    margin-top: 16px;
                }}
                .checkbox {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-weight: 500;
                    margin-bottom: 16px;
                }}
                footer {{
                    margin-top: 32px;
                    text-align: center;
                    color: #94a3b8;
                }}
            </style>
        </head>
        <body>
            <main>
                <h1>GuideAI Device Activation</h1>
                <p class=\"subtitle\">Enter the code shown on your CLI or IDE to approve access.</p>
                {alerts_html}
                <section class=\"card\">
                    <h2>Lookup consent request</h2>
                    <form method=\"post\">
                        <input type=\"hidden\" name=\"action\" value=\"lookup\" />
                        <label for=\"lookup-user-code\">User code</label>
                        <input id=\"lookup-user-code\" name=\"user_code\" value=\"{safe_code}\" placeholder=\"ABCD-EFGH\" required />
                        <button type=\"submit\" class=\"btn primary\">Lookup code</button>
                    </form>
                </section>
                {details_html}
                <footer>Device flow prototype · GuideAI</footer>
            </main>
        </body>
        </html>
        """
    ).strip()

    return HTMLResponse(content=page)


def create_app(
    *,
    behavior_db_path: Optional[Path] = None,
    workflow_db_path: Optional[Path] = None,
    enable_auth_middleware: Optional[bool] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        behavior_db_path: Deprecated. Path for SQLite behavior DB.
        workflow_db_path: Deprecated. Path for SQLite workflow DB.
        enable_auth_middleware: Enable JWT auth middleware. Defaults to env var GUIDEAI_AUTH_ENABLED.
    """

    # Ensure a single in-process JWT secret is available for any JWT validation/issuance.
    # For multi-worker deployments, set GUIDEAI_JWT_SECRET explicitly in the environment.
    #
    # Optional dev convenience: set GUIDEAI_JWT_SECRET_FILE to persist a generated secret
    # across server restarts (avoids device-flow sessions being invalidated on reload).
    if not os.getenv("GUIDEAI_JWT_SECRET"):
        secret_file = os.getenv("GUIDEAI_JWT_SECRET_FILE")
        if secret_file:
            try:
                secret_path = Path(secret_file).expanduser()
                if secret_path.exists():
                    existing = secret_path.read_text(encoding="utf-8").strip()
                    if existing:
                        os.environ["GUIDEAI_JWT_SECRET"] = existing
                else:
                    secret_path.parent.mkdir(parents=True, exist_ok=True)
                    generated = secrets.token_urlsafe(32)
                    secret_path.write_text(generated, encoding="utf-8")
                    os.environ["GUIDEAI_JWT_SECRET"] = generated
            except Exception:
                # Fall back to in-memory secret if the file is not usable.
                os.environ["GUIDEAI_JWT_SECRET"] = secrets.token_urlsafe(32)
        else:
            os.environ["GUIDEAI_JWT_SECRET"] = secrets.token_urlsafe(32)

    app = FastAPI(title="GuideAI API", version="0.1.0")

    # ------------------------------------------------------------------
    # CORS Configuration
    # ------------------------------------------------------------------
    def _parse_cors_origins(raw: str | None) -> list[str]:
        if not raw:
            return []
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    # Allow requests from local development servers (safe dev default).
    #
    # If GUIDEAI_CORS_ORIGINS is set, it is used as the explicit allowlist.
    # Additionally, we allow an opt-in localhost regex (enabled by default) to
    # prevent common dev breakages when the Vite port changes.
    cors_origins = _parse_cors_origins(os.getenv("GUIDEAI_CORS_ORIGINS"))
    cors_origin_regex = os.getenv("GUIDEAI_CORS_ORIGIN_REGEX")
    allow_localhost_regex = os.getenv("GUIDEAI_CORS_ALLOW_LOCALHOST", "true").lower() in ("true", "1", "yes")
    if allow_localhost_regex and not cors_origin_regex:
        cors_origin_regex = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"

    # Default allowed origins for CORS header injection on error responses
    default_cors_origins = ["http://localhost:5173", "http://localhost:3000"]

    # ------------------------------------------------------------------
    # Exception Handler with CORS headers
    # ------------------------------------------------------------------
    # FastAPI/Starlette's default exception handler returns responses that bypass
    # the CORSMiddleware. We add a custom handler to ensure CORS headers are present
    # on error responses (especially 500s) so the browser can read the error.
    @app.exception_handler(Exception)
    async def cors_exception_handler(request: Request, exc: Exception):
        """Catch-all exception handler that ensures CORS headers on errors."""
        from starlette.responses import JSONResponse
        import traceback
        import re

        origin = request.headers.get("origin", "")

        # Determine if origin is allowed
        allowed = False
        if origin:
            if origin in default_cors_origins or origin in cors_origins:
                allowed = True
            elif cors_origin_regex:
                allowed = bool(re.match(cors_origin_regex, origin))

        # Build CORS headers if origin is allowed
        cors_headers = {}
        if allowed:
            cors_headers = {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
            }

        # Log the exception for debugging
        import logging
        logging.getLogger(__name__).exception(
            f"Unhandled exception in {request.method} {request.url.path}",
            exc_info=exc,
        )

        # Return JSON error response with CORS headers
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "type": type(exc).__name__,
            },
            headers=cors_headers,
        )

    container = _ServiceContainer(
        behavior_db_path=behavior_db_path,
        workflow_db_path=workflow_db_path,
    )

    # ------------------------------------------------------------------
    # Auth Middleware & Permission Service
    # ------------------------------------------------------------------
    # Check if auth should be enabled (env var or explicit parameter)
    auth_enabled = enable_auth_middleware
    if auth_enabled is None:
        auth_enabled = os.getenv("GUIDEAI_AUTH_ENABLED", "").lower() in ("true", "1", "yes")

    if auth_enabled:
        from guideai.auth.middleware import AuthMiddleware, AuthConfig
        from guideai.multi_tenant.permissions import AsyncPermissionService

        auth_config = AuthConfig(
            skip_paths={
                "/health", "/health/", "/metrics", "/docs", "/openapi.json", "/redoc",
                "/api/v1/device/authorize",  # Device flow doesn't need auth
                "/api/v1/device/token",  # Token endpoint
                "/api/v1/activate",  # Activation page
            }
        )
        app.add_middleware(AuthMiddleware, config=auth_config)

        # Initialize async permission service if DSN is available
        auth_dsn = resolve_optional_postgres_dsn(
            service="AUTH",
            explicit_dsn=None,
            env_var="GUIDEAI_AUTH_PG_DSN",
        )
        if auth_dsn:
            try:
                app.state.async_permission_service = AsyncPermissionService(dsn=auth_dsn)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to initialize AsyncPermissionService: {exc}. "
                    "Permission checks will not be available."
                )
                app.state.async_permission_service = None
        else:
            app.state.async_permission_service = None

    def _validated_uuid(value: str, resource_name: str) -> str:
        try:
            uuid.UUID(value)
            return value
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{resource_name} not found",
            ) from exc

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    @app.post("/api/v1/actions", status_code=status.HTTP_201_CREATED)
    def create_action(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.action_adapter.create_action(payload)
        except ActionServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/actions")
    def list_actions() -> List[Dict[str, Any]]:
        return container.action_adapter.list_actions()

    @app.get("/api/v1/actions/{action_id}")
    def get_action(action_id: str) -> Dict[str, Any]:
        try:
            return container.action_adapter.get_action(action_id)
        except ActionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/api/v1/actions:replay", status_code=status.HTTP_202_ACCEPTED)
    def replay_actions(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.action_adapter.replay_actions(payload)
        except ActionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ActionServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/actions/replays/{replay_id}")
    def get_replay_status(replay_id: str) -> Dict[str, Any]:
        try:
            return container.action_adapter.get_replay_status(replay_id)
        except (ActionNotFoundError, ReplayNotFoundError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Behaviors
    # ------------------------------------------------------------------
    @app.get("/api/v1/behaviors")
    def list_behaviors(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        tags: Optional[List[str]] = Query(default=None),
        role_focus: Optional[str] = Query(default=None),
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if status_filter:
            payload["status"] = status_filter
        if tags:
            payload["tags"] = list(tags)
        if role_focus:
            payload["role_focus"] = role_focus
        return container.behavior_adapter.list_behaviors(payload)

    @app.post("/api/v1/behaviors", status_code=status.HTTP_201_CREATED)
    def create_behavior(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.create_draft(payload)
        except (BehaviorServiceError, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/behaviors:search")
    def search_behaviors(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            return container.behavior_adapter.search_behaviors(payload)
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/behaviors/{behavior_id}")
    def get_behavior(behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.get_behavior(behavior_id, version)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.patch("/api/v1/behaviors/{behavior_id}/versions/{version}")
    def update_behavior(behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.update_draft(behavior_id, version, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/behaviors/{behavior_id}/versions/{version}:submit")
    def submit_behavior(behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.submit_for_review(behavior_id, version, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/behaviors/{behavior_id}:approve")
    def approve_behavior(behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.approve(behavior_id, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/behaviors/{behavior_id}:deprecate")
    def deprecate_behavior(behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.deprecate(behavior_id, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.delete("/api/v1/behaviors/{behavior_id}/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_behavior_draft(behavior_id: str, version: str, payload: Dict[str, Any]) -> Response:
        try:
            container.behavior_adapter.delete_draft(behavior_id, version, payload)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Behavior Effectiveness & Admin
    # ------------------------------------------------------------------
    @app.get("/api/v1/admin/behaviors/effectiveness")
    def get_behavior_effectiveness(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        sort_by: Optional[str] = Query(default="usage_count", description="Sort by: usage_count, avg_accuracy, token_reduction"),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> Dict[str, Any]:
        """Get behavior effectiveness metrics for admin dashboard."""
        try:
            return container.behavior_adapter.get_effectiveness_metrics(
                status_filter=status_filter,
                sort_by=sort_by,
                limit=limit,
            )
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/admin/behaviors/{behavior_id}/feedback", status_code=status.HTTP_201_CREATED)
    def submit_behavior_feedback(behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Submit curator feedback for a behavior."""
        try:
            required = ["relevance_score", "actor_id"]
            missing = [f for f in required if f not in payload]
            if missing:
                raise ValueError(f"Missing required fields: {missing}")

            return container.behavior_adapter.record_feedback(
                behavior_id=behavior_id,
                relevance_score=payload["relevance_score"],
                helpfulness_score=payload.get("helpfulness_score"),
                token_reduction_observed=payload.get("token_reduction_observed"),
                comment=payload.get("comment"),
                actor_id=payload["actor_id"],
                context=payload.get("context", {}),
            )
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (BehaviorServiceError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/admin/behaviors/{behavior_id}/feedback")
    def get_behavior_feedback(
        behavior_id: str,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> List[Dict[str, Any]]:
        """Get feedback entries for a specific behavior."""
        try:
            return container.behavior_adapter.get_feedback(behavior_id=behavior_id, limit=limit)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get("/api/v1/admin/behaviors/benchmark")
    def get_behavior_benchmark_results(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> Dict[str, Any]:
        """Get latest benchmark results for behavior retrieval performance."""
        try:
            return container.behavior_adapter.get_benchmark_results(limit=limit)
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/admin/behaviors/benchmark:run", status_code=status.HTTP_202_ACCEPTED)
    def trigger_behavior_benchmark(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger a new benchmark run (async)."""
        try:
            return container.behavior_adapter.trigger_benchmark(
                corpus_path=payload.get("corpus_path"),
                sample_size=payload.get("sample_size", 100),
                actor_id=payload.get("actor_id", "system"),
            )
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Agent Registry
    # ------------------------------------------------------------------
    @app.get("/api/v1/agents")
    def list_agents(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        visibility: Optional[str] = Query(default=None),
        role_alignment: Optional[str] = Query(default=None),
        builtin: Optional[bool] = Query(default=None),
        owner_id: Optional[str] = Query(default=None),
        tags: Optional[List[str]] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> Dict[str, Any]:
        """List agents with optional filters."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        payload: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status_filter:
            payload["status"] = status_filter
        if visibility:
            payload["visibility"] = visibility
        if role_alignment:
            payload["role_alignment"] = role_alignment
        if builtin is not None:
            payload["builtin"] = builtin
        if owner_id:
            payload["owner_id"] = owner_id
        if tags:
            payload["tags"] = list(tags)
        try:
            agents = container.agent_registry_adapter.list_agents(payload)
            return {"agents": agents, "total": len(agents), "limit": limit, "offset": offset}
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents", status_code=status.HTTP_201_CREATED)
    def create_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new agent."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.create_agent(payload)
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents:search")
    def search_agents(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Search agents using full-text search and filters."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.search_agents(payload)
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/agents/{agent_id}")
    def get_agent(
        agent_id: str,
        version: Optional[int] = Query(default=None),
        include_history: bool = Query(default=False),
    ) -> Dict[str, Any]:
        """Get a specific agent by ID."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.get_agent(
                agent_id, version=version, include_history=include_history
            )
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.patch("/api/v1/agents/{agent_id}")
    def update_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing agent (creates new version if published)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.update_agent(agent_id, payload)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.delete("/api/v1/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_agent(agent_id: str) -> None:
        """Delete an agent (only drafts can be deleted)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            container.agent_registry_adapter.delete_agent(agent_id)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents/{agent_id}/versions", status_code=status.HTTP_201_CREATED)
    def create_agent_version(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new version of an agent."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.create_new_version(agent_id, payload)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents/{agent_id}:publish")
    def publish_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Publish an agent (change status from DRAFT to PUBLISHED)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.publish_agent(agent_id, payload)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents/{agent_id}:deprecate")
    def deprecate_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Deprecate an agent (change status to DEPRECATED)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.deprecate_agent(agent_id, payload)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/admin/agents:bootstrap", status_code=status.HTTP_202_ACCEPTED)
    def bootstrap_agents(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Bootstrap builtin agents from playbook files (admin only)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.bootstrap_from_playbooks(payload)
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------
    @app.post("/api/v1/workflows/templates", status_code=status.HTTP_201_CREATED)
    def create_workflow_template(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.workflow_adapter.create_template(payload)
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/workflows/templates")
    def list_workflow_templates(
        role_focus: Optional[str] = Query(default=None),
        tags: Optional[List[str]] = Query(default=None),
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if role_focus:
            payload["role_focus"] = role_focus
        if tags:
            payload["tags"] = list(tags)
        return container.workflow_adapter.list_templates(payload)

    @app.get("/api/v1/workflows/templates/{template_id}")
    def get_workflow_template(template_id: str) -> Dict[str, Any]:
        template = container.workflow_adapter.get_template(template_id)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow template not found")
        return template

    @app.post("/api/v1/workflows/runs", status_code=status.HTTP_201_CREATED)
    def start_workflow_run(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.workflow_adapter.run_workflow(payload)
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/workflows/runs/{run_id}")
    def get_workflow_run(run_id: str) -> Dict[str, Any]:
        run = container.workflow_adapter.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")
        return run

    @app.patch("/api/v1/workflows/runs/{run_id}")
    def update_workflow_run(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            status_value = payload.get("status")
            if status_value is not None:
                WorkflowStatus(status_value)  # Validate value early
            return container.workflow_adapter.update_run_status(run_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Amprealize
    # ------------------------------------------------------------------
    @app.post("/api/v1/amprealize/plan", status_code=status.HTTP_202_ACCEPTED)
    def amprealize_plan(
        payload: PlanRequest,
        actor_id: str = Query(..., description="ID of the actor requesting the plan"),
        actor_role: str = Query(..., description="Role of the actor"),
    ) -> PlanResponse:
        """Create an execution plan for a given goal."""
        actor = Actor(id=actor_id, role=actor_role, surface="api")
        return container.amprealize_adapter.plan(payload, actor=actor)

    @app.post("/api/v1/amprealize/apply", status_code=status.HTTP_202_ACCEPTED)
    def amprealize_apply(
        payload: ApplyRequest,
        actor_id: str = Query(..., description="ID of the actor applying the plan"),
        actor_role: str = Query(..., description="Role of the actor"),
    ) -> ApplyResponse:
        """Apply a previously created plan."""
        actor = Actor(id=actor_id, role=actor_role, surface="api")
        return container.amprealize_adapter.apply(payload, actor=actor)

    @app.get("/api/v1/amprealize/status/{run_id}")
    def amprealize_status(run_id: str) -> StatusResponse:
        """Get the status of a plan or apply operation."""
        return container.amprealize_adapter.status(run_id)

    @app.post("/api/v1/amprealize/destroy", status_code=status.HTTP_202_ACCEPTED)
    def amprealize_destroy(
        payload: DestroyRequest,
        actor_id: str = Query(..., description="ID of the actor requesting destruction"),
        actor_role: str = Query(..., description="Role of the actor"),
    ) -> DestroyResponse:
        """Destroy resources associated with a deployment."""
        actor = Actor(id=actor_id, role=actor_role, surface="api")
        return container.amprealize_adapter.destroy(payload, actor=actor)

    # ------------------------------------------------------------------
    # Collaboration
    # ------------------------------------------------------------------
    @app.post("/api/v1/collaboration/workspaces", status_code=status.HTTP_201_CREATED)
    def create_collaboration_workspace(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            request = CreateWorkspaceRequest(
                name=str(payload.get("name") or ""),
                description=str(payload.get("description") or ""),
                owner_id=str(payload.get("owner_id") or ""),
                settings=payload.get("settings"),
                tags=payload.get("tags"),
                is_shared=bool(payload.get("is_shared", False)),
            )
            workspace = container.collaboration_service.create_workspace(request)
            return workspace.to_dict()
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/collaboration/workspaces/{workspace_id}")
    def get_collaboration_workspace(workspace_id: str) -> Dict[str, Any]:
        workspace = container.collaboration_service.get_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        return workspace.to_dict()

    @app.get("/api/v1/collaboration/workspaces/{workspace_id}/documents")
    def list_collaboration_documents(workspace_id: str) -> List[Dict[str, Any]]:
        documents = container.collaboration_service.get_workspace_documents(workspace_id)
        return [doc.to_dict() for doc in documents]

    @app.post("/api/v1/collaboration/documents", status_code=status.HTTP_201_CREATED)
    def create_collaboration_document(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            request = CreateDocumentRequest(
                workspace_id=str(payload.get("workspace_id") or ""),
                title=str(payload.get("title") or ""),
                content=str(payload.get("content") or ""),
                document_type=str(payload.get("document_type") or "markdown"),
                created_by=str(payload.get("created_by") or ""),
                metadata=payload.get("metadata"),
            )
            document = container.collaboration_service.create_document(request)
            return document.to_dict()
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/collaboration/documents/{document_id}")
    def get_collaboration_document(document_id: str) -> Dict[str, Any]:
        document = container.collaboration_service.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return document.to_dict()

    @app.get("/api/v1/collaboration/documents/{document_id}/operations")
    def get_collaboration_document_operations(
        document_id: str,
        limit: int = Query(default=100),
    ) -> List[Dict[str, Any]]:
        operations = container.collaboration_service.get_document_operations(document_id, limit=limit)
        return [op.to_dict() for op in operations]

    class _CollaborationHub:
        def __init__(self) -> None:
            self._connections: Dict[str, List[WebSocket]] = {}
            self._doc_locks: Dict[str, asyncio.Lock] = {}

        def _lock_for(self, document_id: str) -> asyncio.Lock:
            if document_id not in self._doc_locks:
                self._doc_locks[document_id] = asyncio.Lock()
            return self._doc_locks[document_id]

        async def connect(self, document_id: str, websocket: WebSocket) -> None:
            await websocket.accept()
            self._connections.setdefault(document_id, []).append(websocket)

        async def disconnect(self, document_id: str, websocket: WebSocket) -> None:
            conns = self._connections.get(document_id)
            if not conns:
                return
            try:
                conns.remove(websocket)
            except ValueError:
                return
            if not conns:
                self._connections.pop(document_id, None)
                self._doc_locks.pop(document_id, None)

        async def broadcast(self, document_id: str, message: Dict[str, Any]) -> None:
            conns = list(self._connections.get(document_id, []))
            for conn in conns:
                try:
                    await conn.send_json(message)
                except Exception:
                    # Best-effort cleanup; actual disconnect handled by receiver loop.
                    pass

    if not hasattr(app.state, "collaboration_hub"):
        app.state.collaboration_hub = _CollaborationHub()

    @app.websocket("/api/v1/collaboration/ws/{document_id}")
    async def collaboration_ws(websocket: WebSocket, document_id: str) -> None:
        hub: _CollaborationHub = app.state.collaboration_hub

        user_id = websocket.query_params.get("user_id") or ""
        session_id = websocket.query_params.get("session_id")

        document = container.collaboration_service.get_document(document_id)
        if document is None:
            await websocket.accept()
            await websocket.send_json(
                {"type": "error", "code": "NOT_FOUND", "message": "Document not found"}
            )
            await websocket.close(code=1008)
            return

        await hub.connect(document_id, websocket)
        try:
            await websocket.send_json({"type": "snapshot", "document": document.to_dict()})

            while True:
                message = await websocket.receive_json()
                msg_type = message.get("type")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue

                if msg_type != "edit":
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "BAD_REQUEST",
                            "message": "Unsupported message type",
                        }
                    )
                    continue

                op = message.get("operation") or {}
                try:
                    op_type = EditOperationType(str(op.get("operation_type")))
                    base_version = int(op.get("version"))
                    position = int(op.get("position"))
                    content = str(op.get("content") or "")

                    request = RealTimeEditRequest(
                        document_id=document_id,
                        user_id=str(op.get("user_id") or user_id),
                        operation_type=op_type,
                        position=position,
                        content=content,
                        version=base_version,
                        session_id=str(op.get("session_id") or session_id) if (op.get("session_id") or session_id) else None,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    await websocket.send_json(
                        {"type": "error", "code": "BAD_REQUEST", "message": str(exc)}
                    )
                    continue

                async with hub._lock_for(document_id):
                    try:
                        operation = container.collaboration_service.apply_real_time_edit(request)
                        updated = container.collaboration_service.get_document(document_id)
                        await hub.broadcast(
                            document_id,
                            {
                                "type": "operation",
                                "operation": operation.to_dict(),
                                "document": updated.to_dict() if updated else None,
                            },
                        )
                    except VersionConflictError as exc:
                        current = container.collaboration_service.get_document(document_id)
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "VERSION_CONFLICT",
                                "message": str(exc),
                                "expected_version": exc.expected_version,
                                "got_version": exc.got_version,
                                "document": current.to_dict() if current else None,
                            }
                        )
                    except Exception as exc:  # pylint: disable=broad-except
                        await websocket.send_json(
                            {"type": "error", "code": "APPLY_FAILED", "message": str(exc)}
                        )
        except WebSocketDisconnect:
            await hub.disconnect(document_id, websocket)
        except Exception:
            await hub.disconnect(document_id, websocket)
            raise

    # ------------------------------------------------------------------
    # BCI
    # ------------------------------------------------------------------
    @app.post("/api/v1/bci:retrieve")
    def bci_retrieve(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.retrieve(payload)

    @app.post("/api/v1/bci/retrieve")
    def bci_retrieve_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.retrieve(payload)

    @app.post("/api/v1/bci:retrieveHybrid")
    def bci_retrieve_hybrid(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.retrieve_hybrid(payload)

    @app.post("/api/v1/bci:rebuildIndex")
    def bci_rebuild_index() -> Dict[str, Any]:
        return container.bci_adapter.rebuild_index()

    @app.post("/api/v1/bci/rebuild-index")
    def bci_rebuild_index_rest() -> Dict[str, Any]:
        return container.bci_adapter.rebuild_index()

    @app.post("/api/v1/bci:composePrompt")
    def bci_compose_prompt(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compose_prompt(payload)

    @app.post("/api/v1/bci/compose-prompt")
    def bci_compose_prompt_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compose_prompt(payload)

    @app.post("/api/v1/bci:composeBatchPrompts")
    def bci_compose_batch_prompts(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compose_batch_prompts(payload)

    @app.post("/api/v1/bci:parseCitations")
    def bci_parse_citations(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.parse_citations(payload)

    @app.post("/api/v1/bci:validateCitations")
    def bci_validate_citations(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.validate_citations(payload)

    @app.post("/api/v1/bci/validate-citations")
    def bci_validate_citations_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.validate_citations(payload)

    @app.post("/api/v1/bci:computeTokenSavings")
    def bci_compute_token_savings(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compute_token_savings(payload)

    @app.post("/api/v1/bci:segmentTrace")
    def bci_segment_trace(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.segment_trace(payload)

    @app.post("/api/v1/bci:detectPatterns")
    def bci_detect_patterns(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.detect_patterns(payload)

    @app.post("/api/v1/bci:scoreReusability")
    def bci_score_reusability(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.score_reusability(payload)

    @app.post("/api/v1/bci:generate")
    def bci_generate(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.generate(payload)

    @app.post("/api/v1/bci/generate")
    def bci_generate_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.generate(payload)

    @app.post("/api/v1/bci:improve")
    def bci_improve(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.improve(payload)

    @app.post("/api/v1/bci/improve")
    def bci_improve_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.improve(payload)

    # ------------------------------------------------------------------
    # Reflection
    # ------------------------------------------------------------------
    @app.post("/api/v1/reflection:extract")
    def reflection_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.reflection_adapter.extract(payload)

    @app.post("/api/v1/reflection/extract")
    def reflection_extract_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.reflection_adapter.extract(payload)

    @app.post("/api/v1/reflection/candidates/approve")
    def reflection_approve_candidate(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Approve an extracted behavior candidate and add to handbook.

        payload: {
            slug: str,              # Candidate slug (e.g., "behavior_validate_inputs")
            status: str,            # "approved" or "auto_approved"
            reviewer_notes?: str,   # Optional notes from reviewer
        }
        """
        return container.reflection_adapter.approve_candidate(payload)

    @app.post("/api/v1/reflection/candidates/reject")
    def reflection_reject_candidate(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Reject an extracted behavior candidate.

        payload: {
            slug: str,        # Candidate slug to reject
            reason?: str,     # Optional rejection reason
        }
        """
        return container.reflection_adapter.reject_candidate(payload)

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    @app.post("/api/v1/runs", status_code=status.HTTP_201_CREATED)
    def create_run(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.run_adapter.create_run(payload)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/runs")
    def list_runs(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        workflow_id: Optional[str] = Query(default=None),
        template_id: Optional[str] = Query(default=None),
        limit: int = Query(default=50),
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if status_filter:
            payload["status"] = status_filter
        if workflow_id:
            payload["workflow_id"] = workflow_id
        if template_id:
            payload["template_id"] = template_id
        payload["limit"] = limit
        return container.run_adapter.list_runs(payload)

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> Dict[str, Any]:
        run_id = _validated_uuid(run_id, "Run")
        try:
            return container.run_adapter.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/progress")
    def update_run_progress(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_id = _validated_uuid(run_id, "Run")
        try:
            return container.run_adapter.update_run(run_id, payload)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/complete")
    def complete_run(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_id = _validated_uuid(run_id, "Run")
        try:
            return container.run_adapter.complete_run(run_id, payload)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel_run(run_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        run_id = _validated_uuid(run_id, "Run")
        try:
            return container.run_adapter.cancel_run(run_id, payload or {})
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.delete("/api/v1/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_run(run_id: str) -> None:
        run_id = _validated_uuid(run_id, "Run")
        try:
            container.run_adapter.delete_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Compliance
    # ------------------------------------------------------------------
    @app.post("/api/v1/compliance/checklists", status_code=status.HTTP_201_CREATED)
    def create_checklist(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.compliance_adapter.create_checklist(payload)
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/compliance/checklists")
    def list_checklists(
        milestone: Optional[str] = Query(default=None),
        compliance_category: Optional[List[str]] = Query(default=None),
        status_filter: Optional[str] = Query(default=None),
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if milestone:
            payload["milestone"] = milestone
        if compliance_category:
            payload["compliance_category"] = list(compliance_category)
        if status_filter:
            payload["status_filter"] = status_filter
        return container.compliance_adapter.list_checklists(payload)

    @app.get("/api/v1/compliance/checklists/{checklist_id}")
    def get_checklist(checklist_id: str) -> Dict[str, Any]:
        checklist_id = _validated_uuid(checklist_id, "Checklist")
        try:
            return container.compliance_adapter.get_checklist(checklist_id)
        except ChecklistNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/api/v1/compliance/checklists/{checklist_id}/steps", status_code=status.HTTP_201_CREATED)
    def record_step(checklist_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        checklist_id = _validated_uuid(checklist_id, "Checklist")
        payload = dict(payload)
        payload["checklist_id"] = checklist_id
        try:
            return container.compliance_adapter.record_step(payload)
        except ChecklistNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/compliance/checklists/{checklist_id}:validate")
    def validate_checklist(checklist_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        checklist_id = _validated_uuid(checklist_id, "Checklist")
        payload = dict(payload)
        payload["checklist_id"] = checklist_id
        try:
            return container.compliance_adapter.validate_checklist(payload)
        except ChecklistNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/compliance/actions/{action_id}:validate")
    def validate_by_action_id(action_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate compliance for all checklists related to an action."""
        payload = dict(payload)
        payload["action_id"] = action_id
        try:
            return container.compliance_adapter.validate_by_action_id(payload)
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/compliance/policies", status_code=status.HTTP_201_CREATED)
    def create_policy(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new compliance policy."""
        try:
            return container.compliance_adapter.create_policy(payload)
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/compliance/policies")
    def list_policies(
        org_id: Optional[str] = Query(default=None),
        project_id: Optional[str] = Query(default=None),
        policy_type: Optional[str] = Query(default=None),
        enforcement_level: Optional[str] = Query(default=None),
        is_active: Optional[bool] = Query(default=None),
        include_global: bool = Query(default=True),
    ) -> List[Dict[str, Any]]:
        """List compliance policies with optional filters."""
        payload: Dict[str, Any] = {"include_global": include_global}
        if org_id:
            payload["org_id"] = org_id
        if project_id:
            payload["project_id"] = project_id
        if policy_type:
            payload["policy_type"] = policy_type
        if enforcement_level:
            payload["enforcement_level"] = enforcement_level
        if is_active is not None:
            payload["is_active"] = is_active
        return container.compliance_adapter.list_policies(payload)

    @app.get("/api/v1/compliance/policies/{policy_id}")
    def get_policy(policy_id: str) -> Dict[str, Any]:
        """Retrieve a single policy by ID."""
        from .compliance_service import PolicyNotFoundError
        policy_id = _validated_uuid(policy_id, "Policy")
        try:
            return container.compliance_adapter.get_policy(policy_id)
        except PolicyNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get("/api/v1/compliance/audit")
    def get_audit_trail(
        run_id: Optional[str] = Query(default=None),
        checklist_id: Optional[str] = Query(default=None),
        action_id: Optional[str] = Query(default=None),
        start_date: Optional[str] = Query(default=None),
        end_date: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        """Generate an audit trail report."""
        payload: Dict[str, Any] = {}
        if run_id:
            payload["run_id"] = run_id
        if checklist_id:
            payload["checklist_id"] = checklist_id
        if action_id:
            payload["action_id"] = action_id
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        return container.compliance_adapter.get_audit_trail(payload)

    # ------------------------------------------------------------------
    # Task assignments
    # ------------------------------------------------------------------
    @app.post("/api/v1/tasks:listAssignments")
    def list_task_assignments(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            return container.task_adapter.list_assignments(payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/v1/assignments:suggestAgent")
    def suggest_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.assignment_adapter.suggest_agent(payload)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - unexpected failures
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    @app.post("/api/v1/analytics:projectKPI")
    def project_kpi(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Project KPI metrics from telemetry events (in-memory)."""
        events = payload.get("events", [])
        include_facts = payload.get("include_facts", True)
        projection: TelemetryProjection = container.telemetry_projector.project(events)
        response: Dict[str, Any] = {
            "summary": projection.summary,
        }
        if include_facts:
            response.update(
                {
                    "fact_behavior_usage": projection.fact_behavior_usage,
                    "fact_token_savings": projection.fact_token_savings,
                    "fact_execution_status": projection.fact_execution_status,
                    "fact_compliance_steps": projection.fact_compliance_steps,
                }
            )
        return response

    @app.get("/api/v1/analytics/kpi-summary")
    def get_kpi_summary(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
    ) -> Dict[str, Any]:
        """Query KPI summary from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_kpi_summary(
                start_date=start_date,
                end_date=end_date,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/behavior-usage")
    def get_behavior_usage(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        limit: int = Query(100, description="Maximum number of records", ge=1, le=1000),
    ) -> Dict[str, Any]:
        """Query behavior usage facts from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_behavior_usage(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/token-savings")
    def get_token_savings(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        limit: int = Query(100, description="Maximum number of records", ge=1, le=1000),
    ) -> Dict[str, Any]:
        """Query token savings facts from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_token_savings(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/compliance-coverage")
    def get_compliance_coverage(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        limit: int = Query(100, description="Maximum number of records", ge=1, le=1000),
    ) -> Dict[str, Any]:
        """Query compliance coverage facts from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_compliance_coverage(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Cost Optimization Analytics (PRD 8.17)
    # ------------------------------------------------------------------
    @app.get("/api/v1/analytics/cost-by-service")
    def get_cost_by_service(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        service_name: Optional[str] = Query(None, description="Filter by service name"),
    ) -> Dict[str, Any]:
        """Query cost breakdown by service from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_cost_by_service(
                start_date=start_date,
                end_date=end_date,
                service_name=service_name,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/cost-per-run")
    def get_cost_per_run(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        template_id: Optional[str] = Query(None, description="Filter by template ID"),
        limit: int = Query(100, description="Maximum number of records", ge=1, le=1000),
    ) -> Dict[str, Any]:
        """Query cost breakdown per run from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_cost_per_run(
                start_date=start_date,
                end_date=end_date,
                template_id=template_id,
                limit=limit,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/roi-summary")
    def get_roi_summary() -> Dict[str, Any]:
        """Query ROI analysis summary from DuckDB warehouse."""
        try:
            record = container.analytics_warehouse.get_roi_summary()
            settings = get_settings()
            return {
                "roi": record,
                "budget_threshold_usd": settings.cost.daily_budget_usd,
                "budget_status": "over" if (record or {}).get("total_cost_usd", 0) > settings.cost.daily_budget_usd else "ok",
            }
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/daily-costs")
    def get_daily_costs(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        limit: int = Query(30, description="Maximum number of days", ge=1, le=365),
    ) -> Dict[str, Any]:
        """Query daily cost summary for budget tracking from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_daily_cost_summary(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            settings = get_settings()
            budget = settings.cost.daily_budget_usd
            # Add budget status to each record
            for record in records:
                record["over_budget"] = record.get("daily_cost_usd", 0) > budget
            return {
                "records": records,
                "count": len(records),
                "budget_threshold_usd": budget,
            }
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/top-expensive")
    def get_top_expensive(
        limit: int = Query(10, description="Number of workflows to return", ge=1, le=100),
    ) -> Dict[str, Any]:
        """Query top expensive workflows from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_top_expensive_workflows(limit=limit)
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Metrics (Real-Time Aggregation with Caching)
    # ------------------------------------------------------------------
    @app.get("/api/v1/metrics/summary")
    def get_metrics_summary(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        use_cache: bool = Query(True, description="Use cached data if available"),
    ) -> Dict[str, Any]:
        """Get real-time metrics summary with PRD KPI targets."""
        try:
            payload: Dict[str, Any] = {"use_cache": use_cache}
            if start_date:
                payload["start_date"] = start_date
            if end_date:
                payload["end_date"] = end_date
            return container.metrics_adapter.get_summary(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Metrics query failed: {exc}",
            ) from exc

    @app.post("/api/v1/metrics/export")
    def export_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Export metrics data to specified format."""
        try:
            return container.metrics_adapter.export_metrics(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Export failed: {exc}",
            ) from exc

    @app.post("/api/v1/metrics/subscriptions")
    def create_metrics_subscription(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new metrics subscription for real-time streaming."""
        try:
            return container.metrics_adapter.create_subscription(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Subscription creation failed: {exc}",
            ) from exc

    @app.delete("/api/v1/metrics/subscriptions/{subscription_id}")
    def cancel_metrics_subscription(subscription_id: str) -> Dict[str, Any]:
        """Cancel an active metrics subscription."""
        try:
            return container.metrics_adapter.cancel_subscription(subscription_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    # ------------------------------------------------------------------
    # AgentAuth
    # ------------------------------------------------------------------
    @app.post("/api/v1/auth/device", status_code=status.HTTP_201_CREATED)
    @app.post("/api/v1/auth/device/authorize", status_code=status.HTTP_201_CREATED)
    def start_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Initiate device authorization for CLI or partner surfaces."""

        try:
            session = container.device_flow_manager.start_authorization(
                client_id=payload["client_id"],
                scopes=payload["scopes"],
                surface=payload.get("surface", "CLI"),
                metadata=payload.get("metadata"),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc.args[0]}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return {
            "device_code": session.device_code,
            "user_code": session.user_code,
            "verification_uri": session.verification_uri,
            "verification_uri_complete": session.verification_uri_complete,
            "expires_in": session.expires_in(),
            "interval": session.poll_interval,
            "status": session.status.value,
        }

    @app.post("/api/v1/auth/device/lookup")
    def lookup_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Look up a device authorization request by user code."""

        raw_code = payload.get("user_code")
        if not raw_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_code is required",
            )
        try:
            normalized = _normalize_user_code(raw_code)
            session = container.device_flow_manager.describe_user_code(normalized)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except UserCodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        return {
            "status": session.status.value,
            "client_id": session.client_id,
            "scopes": session.scopes,
            "surface": session.surface,
            "user_code": session.user_code,
            "verification_uri": session.verification_uri,
            "expires_in": session.expires_in(),
            "created_at": session.created_at.isoformat(),
        }

    @app.post("/api/v1/auth/device/approve")
    def approve_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Approve a device authorization request."""

        raw_code = payload.get("user_code")
        approver = payload.get("approver")
        if not raw_code or not approver:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_code and approver are required",
            )
        roles = payload.get("roles") or []
        mfa_verified = bool(payload.get("mfa_verified", False))
        surface = payload.get("surface", "WEB")
        try:
            normalized = _normalize_user_code(raw_code)
            session = container.device_flow_manager.approve_user_code(
                normalized,
                approver,
                approver_surface=surface,
                roles=roles,
                mfa_verified=mfa_verified,
            )
        except (ValueError, DeviceCodeExpiredError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except UserCodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except DeviceFlowError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        return {
            "status": session.status.value,
            "client_id": session.client_id,
            "scopes": session.scopes,
            "approved_at": session.approved_at.isoformat() if session.approved_at else None,
        }

    @app.post("/api/v1/auth/device/deny")
    def deny_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Deny a device authorization request."""

        raw_code = payload.get("user_code")
        approver = payload.get("approver")
        if not raw_code or not approver:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_code and approver are required",
            )
        reason = payload.get("reason")
        surface = payload.get("surface", "WEB")
        try:
            normalized = _normalize_user_code(raw_code)
            session = container.device_flow_manager.deny_user_code(
                normalized,
                approver,
                approver_surface=surface,
                reason=reason,
            )
        except (ValueError, DeviceCodeExpiredError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except UserCodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except DeviceFlowError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        return {
            "status": session.status.value,
            "client_id": session.client_id,
            "scopes": session.scopes,
            "denied_reason": session.denied_reason,
        }

    @app.post("/api/v1/auth/device/token")
    def poll_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Poll a device authorization for tokens."""

        device_code = payload.get("device_code")
        if not device_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="device_code is required",
            )
        try:
            result = container.device_flow_manager.poll_device_code(device_code)
        except DeviceCodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        # Per RFC 8628, pending authorization should return 400 with authorization_pending error
        if result.status is DeviceAuthorizationStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "authorization_pending",
                    "error_description": "The authorization request is still pending.",
                    "interval": result.retry_after or 5,
                },
            )

        if result.status is DeviceAuthorizationStatus.DENIED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "access_denied",
                    "error_description": result.denied_reason or "The user denied the authorization request.",
                },
            )

        if result.status is DeviceAuthorizationStatus.EXPIRED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "expired_token",
                    "error_description": "The device code has expired.",
                },
            )

        # Only APPROVED status gets here
        assert result.tokens is not None
        tokens = result.tokens
        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "expires_in": tokens.access_expires_in(),
            "refresh_expires_in": tokens.refresh_expires_in(),
            "scope": " ".join(result.scopes),
        }

    @app.post("/api/v1/auth/device/refresh")
    def refresh_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh an access token using a stored refresh token."""

        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="refresh_token is required",
            )
        try:
            session = container.device_flow_manager.refresh_access_token(refresh_token)
        except RefreshTokenNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (RefreshTokenExpiredError, DeviceCodeExpiredError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except DeviceFlowError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        tokens = session.tokens
        assert tokens is not None, "refreshed session must include tokens"

        return {
            "status": session.status.value,
            "client_id": session.client_id,
            "scopes": session.scopes,
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "access_token_expires_at": tokens.access_token_expires_at.isoformat(),
            "refresh_token_expires_at": tokens.refresh_token_expires_at.isoformat(),
            "access_expires_in": tokens.access_expires_in(),
            "refresh_expires_in": tokens.refresh_expires_in(),
        }

    @app.post("/api/v1/auth/token/refresh")
    def refresh_token_alias(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Alias for refreshing access tokens (web-console compatibility).

        The web console API client expects `/v1/auth/token/refresh` to return an OAuth-like
        response shape with `expires_in`. Internally this is backed by the device-flow
        refresh token store.
        """

        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="refresh_token is required",
            )

        try:
            session = container.device_flow_manager.refresh_access_token(refresh_token)
        except RefreshTokenNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (RefreshTokenExpiredError, DeviceCodeExpiredError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except DeviceFlowError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        tokens = session.tokens
        assert tokens is not None, "refreshed session must include tokens"

        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_in": tokens.access_expires_in(),
            "token_type": tokens.token_type,
        }

    @app.get("/api/v1/auth/me")
    def get_current_user(request: Request) -> Dict[str, Any]:
        """Get current user info from the access token."""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
            )

        access_token = auth_header[7:]  # Remove "Bearer " prefix

        # Look up user info from the access token
        user_info = container.device_flow_manager.get_user_info_from_access_token(access_token)
        if user_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
            )

        return {
            "sub": user_info.get("sub", ""),
            "name": user_info.get("name", "User"),
            "email": user_info.get("email"),
            "picture": None,
            "roles": ["STUDENT"],  # Default role for device flow auth
            "scopes": user_info.get("scopes", []),
        }

    def _require_user_id(request: Request) -> str:
        """Extract authenticated user_id from bearer token."""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
            )

        access_token = auth_header[7:]
        user_info = container.device_flow_manager.get_user_info_from_access_token(access_token)
        if user_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
            )

        user_id = user_info.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token subject",
            )
        return str(user_id)

    # ------------------------------------------------------------------
    # Additional Device Flow REST API Endpoints (Integration Test Support)
    # ------------------------------------------------------------------
    @app.post("/api/v1/auth/device/login", status_code=status.HTTP_201_CREATED)
    def device_login_alias(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Alias for /v1/auth/device to support integration test expectations.
        Initiates device authorization flow with client_id and scopes.
        """
        return start_device_flow(payload)

    @app.get("/api/v1/auth/status")
    def get_auth_status(client_id: str = Query("guideai-staging-client")) -> Dict[str, Any]:
        """
        Check authentication status for a client_id.
        Reads tokens from FileTokenStore and returns validity, expiry, scopes.
        """
        try:
            from .auth_tokens import FileTokenStore

            store = FileTokenStore()
            bundle = store.load()

            if bundle is None or bundle.client_id != client_id:
                return {
                    "is_authenticated": False,
                    "access_token_valid": False,
                    "refresh_token_valid": False,
                    "client_id": client_id,
                    "needs_login": True,
                }

            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            access_token_valid = bundle.expires_at > now
            refresh_token_valid = bundle.refresh_expires_at > now

            return {
                "is_authenticated": access_token_valid or refresh_token_valid,
                "access_token_valid": access_token_valid,
                "refresh_token_valid": refresh_token_valid,
                "client_id": bundle.client_id,
                "scopes": bundle.scopes,
                "expires_in": int((bundle.expires_at - now).total_seconds()),
                "expires_at": bundle.expires_at.isoformat(),
                "refresh_expires_in": int((bundle.refresh_expires_at - now).total_seconds()),
                "refresh_expires_at": bundle.refresh_expires_at.isoformat(),
                "needs_refresh": not access_token_valid and refresh_token_valid,
                "needs_login": not access_token_valid and not refresh_token_valid,
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read auth status: {exc}",
            ) from exc

    @app.post("/api/v1/auth/refresh")
    def token_refresh_alias(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Alias for /v1/auth/device/refresh to support integration test expectations.
        Refreshes access token using stored refresh token.
        """
        return refresh_device_flow(payload)

    @app.post("/api/v1/auth/logout")
    def logout_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Revoke tokens and clear local storage for a client_id.
        Clears FileTokenStore for the specified client.
        """
        client_id = payload.get("client_id", "guideai-staging-client")

        try:
            from .auth_tokens import FileTokenStore

            store = FileTokenStore()
            bundle = store.load()

            tokens_cleared = False
            if bundle and bundle.client_id == client_id:
                store.clear()
                tokens_cleared = True

            status_value = "logged_out" if tokens_cleared else "no_tokens"

            return {
                "status": status_value,
                "tokens_cleared": tokens_cleared,
                "client_id": client_id,
                "access_token_revoked": False,  # Remote revocation not implemented
                "refresh_token_revoked": False,
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to logout: {exc}",
            ) from exc

    # -------------------------------------------------------------------------
    # Internal Authentication Endpoints
    # -------------------------------------------------------------------------

    @app.get("/api/v1/auth/providers")
    def list_auth_providers() -> Dict[str, Any]:
        """
        List available authentication providers.

        Returns information about configured OAuth providers and internal password auth.
        """
        providers = []

        # GitHub OAuth (always available via device flow)
        providers.append({
            "name": "github",
            "type": "oauth",
            "device_flow": True,
            "enabled": True,
            "description": "GitHub OAuth (device flow)",
        })

        # Google OAuth (if configured)
        if container.google_provider is not None:
            providers.append({
                "name": "google",
                "type": "oauth",
                "device_flow": False,
                "enabled": True,
                "description": "Google OAuth",
            })

        # Internal password auth
        providers.append({
            "name": "internal",
            "type": "password",
            "device_flow": False,
            "enabled": True,
            "description": "Internal username/password authentication",
        })

        return {"providers": providers}

    @app.post("/api/v1/auth/internal/register", status_code=status.HTTP_201_CREATED)
    async def internal_register(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new internal auth user and return authentication tokens.

        Request body:
            username (str): Username (min 3 characters)
            password (str): Password (min 8 characters)
            email (str, optional): Email address

        Returns:
            Authentication tokens and user info
        """
        username = payload.get("username")
        password = payload.get("password")
        email = payload.get("email")

        # Validation
        if not username or len(username) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username must be at least 3 characters",
            )
        if not password or len(password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters",
            )

        try:
            tokens = await container.device_flow_manager.register_internal_user(
                username=username,
                password=password,
                email=email,
                surface="API",
                metadata={"endpoint": "/api/v1/auth/internal/register"},
            )

            # Calculate expiry times
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)

            return {
                "status": "registered",
                "username": username,
                "provider": "internal",
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "expires_in": int((tokens.access_token_expires_at - now).total_seconds()),
                "expires_at": tokens.access_token_expires_at.isoformat(),
                "refresh_expires_in": int((tokens.refresh_token_expires_at - now).total_seconds()),
                "refresh_expires_at": tokens.refresh_token_expires_at.isoformat(),
            }

        except (DeviceFlowError, OAuthError) as exc:
            # Check for duplicate user errors
            error_msg = str(exc).lower()
            if "duplicate" in error_msg or "exists" in error_msg or "already registered" in error_msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Username '{username}' already exists",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Registration failed: {exc}",
            ) from exc

    @app.post("/api/v1/auth/internal/login")
    async def internal_login(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Authenticate with username/password and return tokens.

        Request body:
            username (str): Username
            password (str): Password

        Returns:
            Authentication tokens and user info
        """
        username = payload.get("username")
        password = payload.get("password")

        if not username or not password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username and password required",
            )

        try:
            tokens = await container.device_flow_manager.start_authorization_internal(
                username=username,
                password=password,
                surface="API",
                metadata={"endpoint": "/api/v1/auth/internal/login"},
            )

            # Calculate expiry times
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)

            return {
                "status": "authenticated",
                "username": username,
                "provider": "internal",
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "expires_in": int((tokens.access_token_expires_at - now).total_seconds()),
                "expires_at": tokens.access_token_expires_at.isoformat(),
                "refresh_expires_in": int((tokens.refresh_token_expires_at - now).total_seconds()),
                "refresh_expires_at": tokens.refresh_token_expires_at.isoformat(),
            }

        except InvalidCredentialsError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            ) from exc
        except DeviceFlowError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Authentication failed: {exc}",
            ) from exc

    @app.post("/api/v1/auth/email/send-verification")
    async def send_email_verification(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send an email verification link to the user's email address.

        Request body:
            email (str): Email address to verify
            user_id (str, optional): User ID if known, otherwise lookup by email

        Returns:
            Status message
        """
        email = payload.get("email")
        user_id = payload.get("user_id")

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email address required",
            )

        try:
            # Get user service from internal auth provider
            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            # Look up user by email if user_id not provided
            if not user_id:
                user = user_service.get_user_by_email(email)
                if not user:
                    # Don't reveal if email exists - return success anyway for security
                    return {"status": "sent", "message": "If the email exists, a verification link has been sent"}
                user_id = user.id
            else:
                user = user_service.get_user_by_id(user_id)
                if not user or user.email != email:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="User not found or email mismatch",
                    )

            # Check if already verified
            if user.email_verified:
                return {"status": "already_verified", "message": "Email is already verified"}

            # Create verification token
            token = user_service.create_email_verification_token(user_id, email)

            # TODO: Send email with verification link
            # For now, return the token for testing (in production, this would send an email)
            # verification_url = f"{settings.APP_URL}/verify-email?token={token}"
            # await send_email(email, "Verify your email", f"Click here: {verification_url}")

            return {
                "status": "sent",
                "message": "Verification email sent",
                # Include token in dev/test mode only (remove in production)
                "token": token,  # TODO: Remove in production
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send verification email: {exc}",
            ) from exc

    @app.post("/api/v1/auth/email/verify")
    async def verify_email(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify an email address using a verification token.

        Request body:
            token (str): Verification token from email

        Returns:
            Status and user info
        """
        token = payload.get("token")

        if not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification token required",
            )

        try:
            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            result = user_service.verify_email_token(token)

            if not result:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired verification token",
                )

            return {
                "status": "verified",
                "message": "Email verified successfully",
                "user_id": result["user_id"],
                "email": result["email"],
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Email verification failed: {exc}",
            ) from exc

    @app.get("/api/v1/auth/email/status")
    async def email_verification_status(
        user_id: str = Query(..., description="User ID to check"),
    ) -> Dict[str, Any]:
        """
        Check email verification status for a user.

        Query params:
            user_id: User ID

        Returns:
            Email verification status
        """
        try:
            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            user = user_service.get_user_by_id(user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )

            return {
                "user_id": user_id,
                "email": user.email,
                "email_verified": user.email_verified,
                "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get verification status: {exc}",
            ) from exc

    # =========================================================================
    # OAUTH SOCIAL LOGIN ENDPOINTS (Web-based Authorization Code Flow)
    # =========================================================================

    @app.get("/api/v1/auth/oauth/{provider}/authorize")
    async def oauth_authorize(
        provider: str,
        redirect_uri: str = Query(..., description="Client callback URL"),
        state: Optional[str] = Query(None, description="CSRF state parameter"),
    ) -> RedirectResponse:
        """
        Redirect to OAuth provider authorization page.

        Supports GitHub and Google OAuth for web-based social login.
        After user authorizes, they are redirected to redirect_uri with code.

        Args:
            provider: OAuth provider (github or google)
            redirect_uri: Where to redirect after authorization
            state: Optional CSRF protection state

        Returns:
            Redirect to OAuth provider authorization URL
        """
        try:
            if provider == "github":
                oauth_provider = container.github_provider
            elif provider == "google":
                oauth_provider = container.google_provider
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported OAuth provider: {provider}. Supported: github, google",
                )

            if oauth_provider is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"OAuth provider '{provider}' is not configured",
                )

            logger.info("Generating auth URL for provider=%s, redirect_uri=%s, state=%s", provider, redirect_uri, state)
            logger.info("Provider instance: %s", oauth_provider)

            auth_url = oauth_provider.get_authorization_url(
                redirect_uri=redirect_uri,
                state=state,
            )

            return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)

        except NotImplementedError:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"OAuth provider '{provider}' does not support authorization code flow",
            )
        except Exception as exc:
            logger.error("Error in oauth_authorize: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate authorization URL: {exc}",
            ) from exc

    @app.post("/api/v1/auth/oauth/callback")
    async def oauth_callback(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exchange OAuth authorization code for access token.

        Called by web client after user authorizes with OAuth provider.
        Creates a GuideAI session and returns GuideAI tokens that work with
        the standard device flow refresh endpoints.

        Request body:
            code (str): Authorization code from OAuth callback
            state (str, optional): CSRF state to verify
            redirect_uri (str): Same redirect_uri used in authorize request

        Returns:
            access_token, token_type, expires_in, refresh_token, user info
        """
        code = payload.get("code")
        state = payload.get("state")
        redirect_uri = payload.get("redirect_uri")

        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authorization code required",
            )
        if not redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="redirect_uri required",
            )

        def _parse_oauth_state_provider(raw_state: Optional[str]) -> Optional[str]:
            if not raw_state:
                return None
            if raw_state in ("github", "google"):
                return raw_state
            try:
                padded = raw_state + "=" * (-len(raw_state) % 4)
                decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
                data = json.loads(decoded)
                provider_hint = data.get("provider")
                if provider_hint in ("github", "google"):
                    return provider_hint
            except Exception:
                return None
            return None

        provider_hint = _parse_oauth_state_provider(state)
        provider = None
        token_response = None
        user_info = None
        last_error: Optional[str] = None

        providers_to_try = [provider_hint] if provider_hint else ["github", "google"]
        for try_provider in providers_to_try:
            try:
                if try_provider == "github":
                    oauth_provider = container.github_provider
                else:
                    oauth_provider = container.google_provider

                if oauth_provider is None:
                    last_error = f"OAuth provider '{try_provider}' is not configured."
                    continue

                token_response = await oauth_provider.exchange_code(code, redirect_uri)
                user_info = await oauth_provider.validate_token(token_response.access_token)
                provider = try_provider
                break

            except OAuthError as exc:
                last_error = f"{try_provider} OAuth error: {exc}"
                logger.warning(f"OAuth error for {try_provider}: {exc}")
                continue
            except Exception as exc:
                last_error = f"{try_provider} OAuth exchange failed: {exc}"
                logger.error(f"OAuth exchange failed for {try_provider}: {exc}", exc_info=True)
                continue

        if not token_response or not user_info:
            logger.error(f"OAuth callback failed. Last error: {last_error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=last_error or "Failed to exchange authorization code. Code may be invalid or expired.",
            )

        # Create a GuideAI session from OAuth credentials
        # This bridges OAuth tokens to device flow tokens, enabling standard refresh
        guideai_tokens = container.device_flow_manager.create_session_from_oauth(
            provider=provider,
            user_id=user_info.user_id,
            email=user_info.email,
            name=user_info.display_name or user_info.username,
            picture=getattr(user_info, "picture", None),
            provider_access_token=token_response.access_token,
            provider_refresh_token=token_response.refresh_token,
            scopes=token_response.scope.split() if token_response.scope else None,
        )

        # Return GuideAI tokens (not raw provider tokens) so they work with
        # standard device flow refresh endpoints (/api/v1/auth/device/refresh)
        return {
            "access_token": guideai_tokens.access_token,
            "token_type": "Bearer",
            "expires_in": int(guideai_tokens.access_expires_in()),
            "refresh_token": guideai_tokens.refresh_token,
            "scope": token_response.scope,
            "user": {
                "id": user_info.user_id,
                "email": user_info.email,
                "display_name": user_info.display_name or user_info.username,
                "provider": provider,
            },
        }

    # =========================================================================
    # MFA (Multi-Factor Authentication) ENDPOINTS
    # =========================================================================

    @app.post("/api/v1/auth/mfa/setup")
    async def mfa_setup(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start MFA setup by generating a TOTP secret and QR code.

        Request body:
            user_id (str): User ID
            device_name (str, optional): Friendly name for the device

        Returns:
            QR code and secret for authenticator app setup
        """
        user_id = payload.get("user_id")
        device_name = payload.get("device_name", "Authenticator App")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID required",
            )

        try:
            from guideai.auth.mfa_service import MfaService
            import os

            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            # Get user
            user = user_service.get_user_by_id(user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )

            # Get or create MFA encryption key
            mfa_key = os.environ.get("MFA_ENCRYPTION_KEY")
            if not mfa_key:
                # Generate a key for development (should be set in production)
                mfa_key = MfaService.generate_encryption_key()
                os.environ["MFA_ENCRYPTION_KEY"] = mfa_key

            mfa_service = MfaService(mfa_key)

            # Generate new secret
            secret = mfa_service.generate_secret()
            encrypted_secret = mfa_service.encrypt_secret(secret)

            # Create MFA device record (unverified)
            device_id = user_service.create_mfa_device(
                user_id=user_id,
                secret_encrypted=encrypted_secret,
                device_type="totp",
                device_name=device_name,
            )

            # Generate QR code
            qr_code_base64 = mfa_service.generate_qr_code_base64(
                secret=secret,
                username=user.email or user.username,
                issuer="GuideAI",
            )

            # Generate backup codes
            backup_codes = mfa_service.generate_backup_codes()
            encrypted_backup_codes = mfa_service.encrypt_backup_codes(backup_codes)

            return {
                "status": "pending_verification",
                "device_id": device_id,
                "device_name": device_name,
                "secret": secret,  # Show once for manual entry
                "qr_code": f"data:image/png;base64,{qr_code_base64}",
                "backup_codes": backup_codes,  # Show once, store encrypted
                "provisioning_uri": mfa_service.get_provisioning_uri(
                    secret, user.email or user.username, "GuideAI"
                ),
                "instructions": "Scan the QR code with your authenticator app, then verify with a code",
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"MFA setup failed: {exc}",
            ) from exc

    @app.post("/api/v1/auth/mfa/verify-setup")
    async def mfa_verify_setup(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify MFA setup by confirming a TOTP code.

        Request body:
            device_id (str): MFA device ID from setup
            code (str): 6-digit code from authenticator app
            user_id (str): User ID

        Returns:
            Verification status
        """
        device_id = payload.get("device_id")
        code = payload.get("code")
        user_id = payload.get("user_id")

        if not all([device_id, code, user_id]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="device_id, code, and user_id required",
            )

        try:
            from guideai.auth.mfa_service import MfaService
            import os

            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            mfa_key = os.environ.get("MFA_ENCRYPTION_KEY")
            if not mfa_key:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="MFA not configured",
                )

            mfa_service = MfaService(mfa_key)

            # Get encrypted secret from database
            # Note: We need to get all devices including unverified for setup verification
            devices = user_service.get_user_mfa_devices(user_id, verified_only=False)
            device = next((d for d in devices if d["id"] == device_id), None)

            if not device:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="MFA device not found",
                )

            if device.get("is_verified"):
                return {
                    "status": "already_verified",
                    "device_id": device_id,
                }

            # Get the secret (need to query separately as it's not in the safe dict)
            encrypted_secret = user_service.get_mfa_device_secret(device_id, user_id)
            if not encrypted_secret:
                # Unverified devices need a different query
                with user_service._connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT secret_encrypted FROM mfa_devices WHERE id = %s AND user_id = %s",
                            (device_id, user_id),
                        )
                        row = cur.fetchone()
                        encrypted_secret = row[0] if row else None

            if not encrypted_secret:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="MFA device secret not found",
                )

            # Decrypt and verify
            secret = mfa_service.decrypt_secret(encrypted_secret)
            if not mfa_service.verify_code(secret, code):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid verification code",
                )

            # Mark device as verified
            user_service.verify_mfa_device(device_id)

            # Set as primary if it's the first verified device
            existing_devices = user_service.get_user_mfa_devices(user_id, verified_only=True)
            if len(existing_devices) <= 1:  # Just this one
                user_service.set_primary_mfa_device(user_id, device_id)

            return {
                "status": "verified",
                "device_id": device_id,
                "is_primary": len(existing_devices) <= 1,
                "message": "MFA device verified and activated",
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"MFA verification failed: {exc}",
            ) from exc

    @app.post("/api/v1/auth/mfa/verify")
    async def mfa_verify(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify an MFA code during login.

        Request body:
            user_id (str): User ID
            code (str): 6-digit TOTP code or backup code

        Returns:
            Verification result
        """
        user_id = payload.get("user_id")
        code = payload.get("code")

        if not all([user_id, code]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id and code required",
            )

        try:
            from guideai.auth.mfa_service import MfaService
            import os

            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            mfa_key = os.environ.get("MFA_ENCRYPTION_KEY")
            if not mfa_key:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="MFA not configured",
                )

            mfa_service = MfaService(mfa_key)

            # Get user's verified MFA devices
            devices = user_service.get_user_mfa_devices(user_id, verified_only=True)

            if not devices:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No MFA devices configured for this user",
                )

            # Try TOTP verification on each device
            for device in devices:
                if device["device_type"] == "totp":
                    encrypted_secret = user_service.get_mfa_device_secret(device["id"], user_id)
                    if encrypted_secret:
                        secret = mfa_service.decrypt_secret(encrypted_secret)
                        if mfa_service.verify_code(secret, code):
                            user_service.update_mfa_device_last_used(device["id"])
                            return {
                                "status": "verified",
                                "method": "totp",
                                "device_id": device["id"],
                            }

            # If TOTP failed, could be a backup code (implement if needed)
            # For now, just return failure
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid MFA code",
            )

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"MFA verification failed: {exc}",
            ) from exc

    @app.get("/api/v1/auth/mfa/devices")
    async def list_mfa_devices(
        user_id: str = Query(..., description="User ID"),
    ) -> Dict[str, Any]:
        """
        List MFA devices for a user.

        Query params:
            user_id: User ID

        Returns:
            List of MFA devices (secrets excluded)
        """
        try:
            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            devices = user_service.get_user_mfa_devices(user_id, verified_only=True)

            return {
                "user_id": user_id,
                "devices": devices,
                "has_mfa": len(devices) > 0,
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list MFA devices: {exc}",
            ) from exc

    @app.delete("/api/v1/auth/mfa/devices/{device_id}")
    async def delete_mfa_device(
        device_id: str,
        user_id: str = Query(..., description="User ID"),
    ) -> Dict[str, Any]:
        """
        Delete an MFA device.

        Path params:
            device_id: MFA device ID

        Query params:
            user_id: User ID (for verification)

        Returns:
            Deletion status
        """
        try:
            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            # Check if this is the only MFA device
            devices = user_service.get_user_mfa_devices(user_id, verified_only=True)
            if len(devices) <= 1:
                # Allow deletion but warn that MFA will be disabled
                pass

            deleted = user_service.delete_mfa_device(device_id, user_id)

            if not deleted:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="MFA device not found",
                )

            remaining_devices = user_service.get_user_mfa_devices(user_id, verified_only=True)

            return {
                "status": "deleted",
                "device_id": device_id,
                "mfa_still_enabled": len(remaining_devices) > 0,
                "remaining_devices": len(remaining_devices),
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete MFA device: {exc}",
            ) from exc

    @app.get("/api/v1/auth/mfa/status")
    async def mfa_status(
        user_id: str = Query(..., description="User ID"),
    ) -> Dict[str, Any]:
        """
        Check MFA status for a user.

        Query params:
            user_id: User ID

        Returns:
            MFA configuration status
        """
        try:
            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            has_mfa = user_service.user_has_verified_mfa(user_id)
            devices = user_service.get_user_mfa_devices(user_id, verified_only=True)

            return {
                "user_id": user_id,
                "mfa_enabled": has_mfa,
                "device_count": len(devices),
                "primary_device": next(
                    (d for d in devices if d.get("is_primary")), None
                ),
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get MFA status: {exc}",
            ) from exc

    # ===== IDENTITY LINKING ENDPOINTS =====

    @app.post("/api/v1/auth/identity/link")
    async def link_oauth_identity(
        provider: str = Body(..., description="OAuth provider (github, google)"),
        oauth_access_token: str = Body(..., description="OAuth access token"),
        oauth_refresh_token: Optional[str] = Body(None, description="OAuth refresh token"),
        password_confirmation: Optional[str] = Body(None, description="Password for manual linking"),
        target_user_id: Optional[str] = Body(None, description="User ID to link to (for manual linking)"),
    ) -> Dict[str, Any]:
        """
        Link an OAuth identity to an internal user account.

        This endpoint handles:
        1. Auto-linking for new users (creates account)
        2. Auto-linking when OAuth email matches existing verified user
        3. Manual linking with password confirmation (for security)

        Returns:
            Linking result with user and identity info
        """
        try:
            from guideai.auth.identity_linking_service import IdentityLinkingService, LinkingResult
            from guideai.auth.providers.github import GitHubProvider
            from guideai.auth.providers.google import GoogleProvider

            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            # Get the appropriate OAuth provider
            if provider == "github":
                oauth_provider = GitHubProvider()
            elif provider == "google":
                oauth_provider = GoogleProvider()
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported OAuth provider: {provider}",
                )

            # Validate the token and get user info
            oauth_user_info = oauth_provider.validate_token(oauth_access_token)
            if not oauth_user_info:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid OAuth token or unable to fetch user info",
                )

            # Link the identity
            linking_service = IdentityLinkingService(user_service)
            result = linking_service.link_identity(
                oauth_user_info=oauth_user_info,
                oauth_access_token=oauth_access_token,
                oauth_refresh_token=oauth_refresh_token,
                password_confirmation=password_confirmation,
                target_user_id=target_user_id,
            )

            # Map result to response
            if result.result == LinkingResult.REQUIRES_PASSWORD:
                return {
                    "status": "requires_confirmation",
                    "result": result.result.value,
                    "message": result.message,
                    "requires_email": result.requires_email,
                }
            elif result.result in (LinkingResult.INVALID_PASSWORD, LinkingResult.ERROR):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result.message,
                )

            # Success cases
            response = {
                "status": "success",
                "result": result.result.value,
                "message": result.message,
            }

            if result.user:
                response["user"] = {
                    "id": result.user.id,
                    "username": result.user.username,
                    "email": result.user.email,
                    "email_verified": result.user.email_verified,
                    "display_name": result.user.display_name,
                }

            if result.federated_identity:
                response["identity"] = {
                    "id": result.federated_identity.id,
                    "provider": result.federated_identity.provider,
                    "provider_user_id": result.federated_identity.provider_user_id,
                    "provider_email": result.federated_identity.provider_email,
                    "provider_username": result.federated_identity.provider_username,
                }

            return response

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to link identity: {exc}",
            ) from exc

    @app.post("/api/v1/auth/identity/unlink")
    async def unlink_oauth_identity(
        user_id: str = Body(..., description="User ID"),
        provider: str = Body(..., description="OAuth provider to unlink (github, google)"),
        password_confirmation: str = Body(..., description="Password to confirm unlinking"),
    ) -> Dict[str, Any]:
        """
        Unlink an OAuth identity from a user account.

        Requires password confirmation for security.
        Cannot unlink the last authentication method without setting a password.

        Returns:
            Unlinking result
        """
        try:
            from guideai.auth.identity_linking_service import IdentityLinkingService

            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            linking_service = IdentityLinkingService(user_service)
            success, message = linking_service.unlink_identity(
                user_id=user_id,
                provider=provider,
                password_confirmation=password_confirmation,
            )

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=message,
                )

            return {
                "status": "success",
                "message": message,
                "provider": provider,
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to unlink identity: {exc}",
            ) from exc

    @app.get("/api/v1/auth/identity/providers")
    async def list_linked_providers(
        user_id: str = Query(..., description="User ID"),
    ) -> Dict[str, Any]:
        """
        List all OAuth providers linked to a user account.

        Returns:
            List of linked OAuth identities
        """
        try:
            from guideai.auth.identity_linking_service import IdentityLinkingService

            user_service = container.internal_auth_provider.user_service
            if not user_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            linking_service = IdentityLinkingService(user_service)
            identities = linking_service.get_user_identities(user_id)

            # Get user info to include in response
            user = user_service.get_user_by_id(user_id)

            return {
                "user_id": user_id,
                "has_password": user.hashed_password is not None if user else False,
                "linked_providers": [
                    {
                        "id": identity.id,
                        "provider": identity.provider,
                        "provider_user_id": identity.provider_user_id,
                        "provider_email": identity.provider_email,
                        "provider_username": identity.provider_username,
                        "provider_display_name": identity.provider_display_name,
                        "provider_avatar_url": identity.provider_avatar_url,
                        "created_at": identity.created_at.isoformat() if identity.created_at else None,
                    }
                    for identity in identities
                ],
                "provider_count": len(identities),
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list providers: {exc}",
            ) from exc

    @app.get("/api/v1/telemetry/events")
    def get_telemetry_events(
        event_type: Optional[str] = Query(None),
        since: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
    ) -> Dict[str, Any]:
        """
        Fetch telemetry events from staging observability stack.
        Note: This is a placeholder - actual implementation depends on telemetry backend.
        """
        # TODO: Implement actual telemetry query against backend storage
        # For now, return empty list to allow tests to proceed
        return {
            "events": [],
            "count": 0,
            "message": "Telemetry query not yet implemented - placeholder endpoint",
            "filters": {
                "event_type": event_type,
                "since": since,
                "limit": limit,
            },
        }

    @app.get("/device/activate", response_class=HTMLResponse)
    def show_device_activation_form(user_code: Optional[str] = None) -> HTMLResponse:
        normalized = ""
        session: Optional[DeviceAuthorizationSession] = None
        error: Optional[str] = None

        if user_code:
            try:
                normalized = _normalize_user_code(user_code)
                session = container.device_flow_manager.describe_user_code(normalized)
            except ValueError as exc:
                error = str(exc)
                normalized = user_code
            except UserCodeNotFoundError:
                error = "No consent request found for that code."
                normalized = user_code

        return _render_device_activation_page(
            user_code=normalized or (user_code or ""),
            session=session,
            error=error,
        )

    # Backwards-compatible aliases for device activation.
    # Some clients/proxies expect a versioned `/v1/device/authorize` path.
    @app.get("/api/v1/device/authorize", response_class=HTMLResponse)
    def show_device_activation_form_v1(user_code: Optional[str] = None) -> HTMLResponse:
        return show_device_activation_form(user_code=user_code)

    @app.post("/device/activate", response_class=HTMLResponse)
    def submit_device_activation(
        user_code: str = Form(...),
        action: str = Form(...),
        approver: str = Form("web-reviewer"),
        roles: Optional[str] = Form(None),
        reason: Optional[str] = Form(None),
        mfa_verified: Optional[str] = Form(None),
    ) -> HTMLResponse:
        try:
            normalized = _normalize_user_code(user_code)
        except ValueError as exc:
            return _render_device_activation_page(user_code=user_code, error=str(exc))

        action_key = action.lower().strip()
        roles_value = roles or "STRATEGIST"
        role_list = [role.strip() for role in roles_value.split(",") if role.strip()]
        mfa_flag = bool(mfa_verified)

        session: Optional[DeviceAuthorizationSession]
        message: Optional[str] = None
        error: Optional[str] = None

        try:
            if action_key == "lookup":
                session = container.device_flow_manager.describe_user_code(normalized)
                message = "Consent request loaded."
            elif action_key == "approve":
                session = container.device_flow_manager.approve_user_code(
                    normalized,
                    approver,
                    approver_surface="WEB",
                    roles=role_list,
                    mfa_verified=mfa_flag,
                )
                message = "Consent approved successfully."
            elif action_key == "deny":
                session = container.device_flow_manager.deny_user_code(
                    normalized,
                    approver,
                    approver_surface="WEB",
                    reason=reason,
                )
                message = "Consent request denied."
            else:
                session = None
                error = "Unsupported action requested."
        except UserCodeNotFoundError:
            session = None
            error = "No consent request found for that code."
        except DeviceCodeExpiredError as exc:
            session = None
            error = str(exc)
        except DeviceFlowError as exc:
            session = None
            error = str(exc)

        return _render_device_activation_page(
            user_code=normalized,
            session=session,
            message=message,
            error=error,
        )

    @app.post("/api/v1/device/authorize", response_class=HTMLResponse)
    def submit_device_activation_v1(
        user_code: str = Form(...),
        action: str = Form(...),
        approver: str = Form("web-reviewer"),
        roles: Optional[str] = Form(None),
        reason: Optional[str] = Form(None),
        mfa_verified: Optional[str] = Form(None),
    ) -> HTMLResponse:
        return submit_device_activation(
            user_code=user_code,
            action=action,
            approver=approver,
            roles=roles,
            reason=reason,
            mfa_verified=mfa_verified,
        )

    @app.get("/api/v1/activate")
    def activate_redirect(user_code: Optional[str] = None) -> Response:
        target = "/api/v1/device/authorize"
        if user_code:
            target = f"{target}?user_code={user_code}"
        return RedirectResponse(url=target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    @app.get("/favicon.ico")
    def favicon() -> Response:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/v1/auth/grants")
    def ensure_grant(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Request an authorization grant for a tool and scopes."""
        try:
            return container.agent_auth_adapter.ensure_grant(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Grant request failed: {exc}",
            ) from exc

    @app.get("/api/v1/auth/grants")
    def list_grants(
        agent_id: str = Query(..., description="Agent ID"),
        user_id: Optional[str] = Query(None),
        tool_name: Optional[str] = Query(None),
        include_expired: bool = Query(False),
    ) -> List[Dict[str, Any]]:
        """List authorization grants for an agent."""
        try:
            filters = {
                "agent_id": agent_id,
                "include_expired": include_expired,
            }
            if user_id:
                filters["user_id"] = user_id
            if tool_name:
                filters["tool_name"] = tool_name
            return container.agent_auth_adapter.list_grants(filters)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list grants: {exc}",
            ) from exc

    @app.post("/api/v1/auth/policy-preview")
    def policy_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Preview policy evaluation without creating a grant."""
        try:
            return container.agent_auth_adapter.policy_preview(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Policy preview failed: {exc}",
            ) from exc

    @app.delete("/api/v1/auth/grants/{grant_id}")
    def revoke_grant(
        grant_id: str,
        revoked_by: str = Query(..., description="ID of user/system revoking grant"),
        reason: Optional[str] = Query(None, description="Reason for revocation"),
    ) -> Dict[str, Any]:
        """Revoke a specific authorization grant."""
        try:
            payload = {"revoked_by": revoked_by}
            if reason:
                payload["reason"] = reason
            return container.agent_auth_adapter.revoke_grant(grant_id, payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    @app.post("/api/v1/security/scan-secrets", status_code=status.HTTP_200_OK)
    def scan_secrets(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run gitleaks secret scan and return findings.

        Request body:
            paths (list[str], optional): Paths to scan (default: ["."])
            redact (bool, optional): Redact secrets in output (default: true)
            report_format (str, optional): Output format - "json" or "table" (default: "json")
            fail_on_findings (bool, optional): Return error status if secrets found (default: false)
            audit_archive_path (str, optional): Path to archive scan results

        Returns:
            Dictionary with:
            - scan_id: Unique identifier for this scan
            - status: "PASSED" or "FAILED"
            - findings_count: Number of potential secrets found
            - findings: List of finding objects (if any)
            - started_at: ISO timestamp of scan start
            - finished_at: ISO timestamp of scan completion
            - report_path: Path to saved report (if audit_archive_path provided)
        """
        import subprocess
        import tempfile
        from datetime import datetime, timezone

        scan_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        paths = payload.get("paths", ["."])
        redact = payload.get("redact", True)
        fail_on_findings = payload.get("fail_on_findings", False)
        audit_archive_path = payload.get("audit_archive_path")

        # Create temp file for report
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
            report_path = Path(tmp.name)

        try:
            # Build gitleaks command
            cmd = [
                "pre-commit", "run", "gitleaks", "--all-files",
                "--hook-stage", "manual", "--",
                "--report-format", "json",
                "--report-path", str(report_path),
            ]
            if redact:
                cmd.append("--redact")

            # Add paths if specified
            for path in paths:
                cmd.extend(["--", path])

            # Run scan
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
            )

            # Parse findings
            findings: List[Dict[str, Any]] = []
            if report_path.exists():
                raw = report_path.read_text(encoding="utf-8")
                if raw.strip():
                    try:
                        data = json.loads(raw)
                        if isinstance(data, list):
                            findings = data
                        elif isinstance(data, dict) and "findings" in data:
                            findings = data.get("findings", [])
                    except json.JSONDecodeError:
                        pass

            finished_at = datetime.now(timezone.utc).isoformat()
            scan_status = "FAILED" if findings else "PASSED"

            # Archive report if requested
            saved_report_path = None
            if audit_archive_path:
                archive_dir = Path(audit_archive_path).expanduser().resolve()
                archive_dir.mkdir(parents=True, exist_ok=True)
                saved_report = archive_dir / f"scan_{scan_id}.json"
                saved_report.write_text(json.dumps({
                    "scan_id": scan_id,
                    "status": scan_status,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "findings": findings,
                }, indent=2))
                saved_report_path = str(saved_report)

            response = {
                "scan_id": scan_id,
                "status": scan_status,
                "findings_count": len(findings),
                "findings": findings,
                "started_at": started_at,
                "finished_at": finished_at,
                "report_path": saved_report_path,
            }

            if fail_on_findings and findings:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "message": f"Secret scan found {len(findings)} potential secret(s)",
                        **response,
                    },
                )

            return response

        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Secret scan timed out after 120 seconds",
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="pre-commit or gitleaks not installed. Run: pip install pre-commit && pre-commit install",
            )
        finally:
            # Cleanup temp file
            if report_path.exists():
                report_path.unlink(missing_ok=True)

    @app.get("/api/v1/security/scan-secrets/history")
    def get_scan_history(
        limit: int = Query(default=10, ge=1, le=100),
        archive_path: str = Query(default="security/scan_reports"),
    ) -> Dict[str, Any]:
        """Get history of past secret scans from archive.

        Query parameters:
            limit: Maximum number of scans to return (default: 10, max: 100)
            archive_path: Path to scan archive directory

        Returns:
            Dictionary with list of past scan summaries.
        """
        archive_dir = Path(archive_path).expanduser().resolve()
        scans: List[Dict[str, Any]] = []

        if archive_dir.exists():
            scan_files = sorted(
                archive_dir.glob("scan_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:limit]

            for scan_file in scan_files:
                try:
                    data = json.loads(scan_file.read_text())
                    scans.append({
                        "scan_id": data.get("scan_id"),
                        "status": data.get("status"),
                        "findings_count": len(data.get("findings", [])),
                        "started_at": data.get("started_at"),
                        "finished_at": data.get("finished_at"),
                        "report_file": scan_file.name,
                    })
                except (json.JSONDecodeError, KeyError):
                    continue

        return {
            "scans": scans,
            "total": len(scans),
            "archive_path": str(archive_dir),
        }

    # ------------------------------------------------------------------
    # Raze Structured Logging
    # ------------------------------------------------------------------
    if RAZE_AVAILABLE and container.raze_service is not None:
        # Add Raze log routes at /api/v1/logs/*
        log_routes = create_log_routes(container.raze_service, tags=["logs"])
        app.include_router(log_routes, prefix="/api")

        # Optionally add middleware for automatic request logging
        # Disabled by default to avoid noise; enable via env var
        if os.getenv("RAZE_ENABLE_MIDDLEWARE", "").lower() in ("true", "1", "yes"):
            app.add_middleware(
                RazeMiddleware,
                service=container.raze_service,
                service_name="guideai-api",
                exclude_paths={"/health", "/metrics", "/api/v1/logs/ingest"},
            )

    # ------------------------------------------------------------------
    # Multi-tenant Organization Management
    # ------------------------------------------------------------------
    if MULTI_TENANT_AVAILABLE and container.org_service is not None:
        # Add organization management routes at /api/v1/orgs/*
        org_routes = create_org_routes(
            org_service=container.org_service,
            invitation_service=container.invitation_service,
            get_user_id=_require_user_id,
            tags=["organizations"],
        )
        app.include_router(org_routes, prefix="/api")

    # ------------------------------------------------------------------
    # Projects (Personal projects always available)
    # ------------------------------------------------------------------
    app.include_router(
        create_project_routes(
            store=container.project_store,
            get_user_id=_require_user_id,
            tags=["projects"],
        ),
        prefix="/api",
    )

    # ------------------------------------------------------------------
    # Board Management (Unified WorkItem CRUD)
    # ------------------------------------------------------------------
    # Add board routes for Agile hierarchy management
    board_routes = create_board_routes(
        board_service=container.board_service,
        tags=["boards"],
    )
    app.include_router(board_routes, prefix="/api")

    # ------------------------------------------------------------------
    # Billing Service
    # ------------------------------------------------------------------
    if BILLING_AVAILABLE and container.billing_service is not None:
        # Add billing routes at /api/v1/billing/*
        billing_routes = create_billing_router(
            billing_service=container.billing_service,
        )
        app.include_router(billing_routes, prefix="/api")

    # ------------------------------------------------------------------
    # Operations & Monitoring
    # ------------------------------------------------------------------
    @app.get("/health")
    def health() -> Dict[str, Any]:
        """Health check endpoint with detailed service status and pool metrics.

        Returns:
            Dictionary with overall health status and per-service details including:
            - status: "healthy" or "degraded"
            - services: List of service health checks
            - pools: Connection pool statistics for PostgreSQL services
        """
        from guideai.storage import postgres_metrics

        services_health = []
        pools_stats = []
        overall_healthy = True

        # Check each service adapter
        service_checks = [
            ("action", container.action_service),
            ("behavior", container.behavior_service),
            ("compliance", container.compliance_service),
            ("workflow", container.workflow_service),
            ("run", container.run_service),
        ]

        for service_name, service in service_checks:
            try:
                # Check if service has PostgresPool
                if hasattr(service, "_pool"):
                    pool = service._pool
                    pool_stats = pool.get_pool_stats()
                    pools_stats.append(pool_stats)

                    # Service is degraded if checked_out >= pool_size (no available connections)
                    is_healthy = pool_stats["available"] > 0
                    services_health.append({
                        "service": service_name,
                        "status": "healthy" if is_healthy else "degraded",
                        "pool": pool_stats,
                    })
                    overall_healthy = overall_healthy and is_healthy
                else:
                    # Non-pooled service (in-memory, etc.)
                    services_health.append({
                        "service": service_name,
                        "status": "healthy",
                        "pool": None,
                    })
            except Exception as exc:
                services_health.append({
                    "service": service_name,
                    "status": "error",
                    "error": str(exc),
                })
                overall_healthy = False

        return {
            "status": "healthy" if overall_healthy else "degraded",
            "services": services_health,
            "pools_summary": {
                "total_checked_out": sum(p["checked_out"] for p in pools_stats),
                "total_available": sum(p["available"] for p in pools_stats),
                "total_pool_size": sum(p["pool_size"] for p in pools_stats),
            } if pools_stats else None,
        }

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus metrics endpoint exposing connection pool and transaction metrics.

        Returns:
            Prometheus exposition format metrics including:
            - guideai_pool_connections_*: Pool utilization metrics
            - guideai_transaction_*: Transaction execution metrics
            - guideai_query_*: Query performance metrics
            - guideai_embedding_*: Embedding model performance metrics (Phase 2)
            - guideai_retrieval_*: BCI retrieval latency and quality metrics (Phase 2)
        """
        try:
            from prometheus_client import REGISTRY, generate_latest
            # Use prometheus_client's default registry which includes embedding metrics
            metrics_data = generate_latest(REGISTRY).decode("utf-8")
        except ImportError:
            # Fallback to postgres-only metrics if prometheus_client not installed
            from guideai.storage import postgres_metrics

            # Update all registered pool metrics before export
            for service_name, service in [
                ("action", container.action_service),
                ("behavior", container.behavior_service),
                ("compliance", container.compliance_service),
                ("workflow", container.workflow_service),
                ("run", container.run_service),
            ]:
                if hasattr(service, "_pool") and hasattr(service._pool._engine, "_update_pool_metrics"):
                    service._pool._engine._update_pool_metrics()  # type: ignore[attr-defined]

            metrics_data = postgres_metrics.get_metrics()

        return Response(content=metrics_data, media_type="text/plain; version=0.0.4")

    # Add CORS middleware last so it wraps everything (outermost layer)
    # This ensures CORS headers are present even on 500 errors from inner layers
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


app = create_app()
"""Default application exported for `uvicorn guideai.api:app`."""
