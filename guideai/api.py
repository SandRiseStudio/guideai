"""FastAPI application exposing GuideAI service stubs over HTTP."""

from __future__ import annotations

import html
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Response, status, Request, Form
from fastapi.responses import HTMLResponse

from .action_service import (
    ActionNotFoundError,
    ActionService,
    ActionServiceError,
    ReplayNotFoundError,
)
from .adapters import (
    RestActionServiceAdapter,
    RestAgentAuthServiceAdapter,
    RestBehaviorServiceAdapter,
    RestBCIAdapter,
    RestComplianceServiceAdapter,
    RestMetricsServiceAdapter,
    RestReflectionAdapter,
    RestRunServiceAdapter,
    RestTaskAssignmentAdapter,
    RestWorkflowServiceAdapter,
)
from .behavior_service import (
    BehaviorNotFoundError,
    BehaviorService,
    BehaviorServiceError,
)
from .compliance_service import (
    ChecklistNotFoundError,
    ComplianceService,
    ComplianceServiceError,
)
from .agent_auth import AgentAuthClient
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
from .reflection_service import ReflectionService
from .run_service import RunService, RunNotFoundError


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
        telemetry = TelemetryClient(
            sink=create_sink_from_env(),
            default_actor={
                "id": "guideai-api",
                "role": "SYSTEM",
                "surface": "api",
            },
        )

        # Core services and adapters
        self.action_service = ActionService(telemetry=telemetry)
        self.action_adapter = RestActionServiceAdapter(self.action_service)

        self.compliance_service = ComplianceService(telemetry=telemetry)
        self.compliance_adapter = RestComplianceServiceAdapter(self.compliance_service)

        # BehaviorService now uses PostgreSQL DSN from environment or default
        # behavior_db_path parameter is deprecated (was SQLite path)
        self.behavior_service = BehaviorService(
            dsn=None,  # Uses GUIDEAI_BEHAVIOR_PG_DSN environment variable
            telemetry=telemetry,
        )
        self.behavior_adapter = RestBehaviorServiceAdapter(self.behavior_service)

        self.behavior_retriever = BehaviorRetriever(
            behavior_service=self.behavior_service,
            telemetry=telemetry,
        )
        setattr(self.behavior_service, "_behavior_retriever", self.behavior_retriever)

        self.bci_service = BCIService(
            behavior_service=self.behavior_service,
            telemetry=telemetry,
            behavior_retriever=self.behavior_retriever,
        )
        self.bci_adapter = RestBCIAdapter(self.bci_service)

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

        # RunService still uses SQLite (will be migrated in Priority 1.2)
        run_db_path = Path.home() / ".guideai" / "runs.db"
        run_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_service = RunService(db_path=run_db_path, telemetry=telemetry)
        self.run_adapter = RestRunServiceAdapter(self.run_service)

        self.task_service = TaskAssignmentService()
        self.task_adapter = RestTaskAssignmentAdapter(self.task_service)

        self.telemetry_projector = TelemetryKPIProjector()

        try:
            self.analytics_warehouse = AnalyticsWarehouse()
        except RuntimeError as exc:  # duckdb optional dependency
            self.analytics_warehouse = _UnavailableWarehouse(str(exc))

        warehouse_path = getattr(self.analytics_warehouse, "db_path", None)
        self.metrics_service = MetricsService(warehouse_path=warehouse_path)
        self.metrics_adapter = RestMetricsServiceAdapter(self.metrics_service)

        self.agent_auth_client = AgentAuthClient(telemetry=telemetry)
        self.agent_auth_adapter = RestAgentAuthServiceAdapter(self.agent_auth_client)

        self.device_flow_manager = DeviceFlowManager(telemetry=telemetry)


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
                    box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
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
                    transition: transform 0.15s ease, box-shadow 0.15s ease;
                }}
                button:hover {{
                    transform: translateY(-1px);
                    box-shadow: 0 6px 14px rgba(15, 23, 42, 0.12);
                }}
                .btn.primary {{
                    background: linear-gradient(135deg, #2563eb, #3b82f6);
                    color: #fff;
                }}
                .btn.danger {{
                    background: linear-gradient(135deg, #dc2626, #f97316);
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
) -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(title="GuideAI API", version="0.1.0")
    container = _ServiceContainer(
        behavior_db_path=behavior_db_path,
        workflow_db_path=workflow_db_path,
    )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    @app.post("/v1/actions", status_code=status.HTTP_201_CREATED)
    def create_action(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.action_adapter.create_action(payload)
        except ActionServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/actions")
    def list_actions() -> List[Dict[str, Any]]:
        return container.action_adapter.list_actions()

    @app.get("/v1/actions/{action_id}")
    def get_action(action_id: str) -> Dict[str, Any]:
        try:
            return container.action_adapter.get_action(action_id)
        except ActionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/v1/actions:replay", status_code=status.HTTP_202_ACCEPTED)
    def replay_actions(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.action_adapter.replay_actions(payload)
        except ActionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ActionServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/actions/replays/{replay_id}")
    def get_replay_status(replay_id: str) -> Dict[str, Any]:
        try:
            return container.action_adapter.get_replay_status(replay_id)
        except (ActionNotFoundError, ReplayNotFoundError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Behaviors
    # ------------------------------------------------------------------
    @app.get("/v1/behaviors")
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

    @app.post("/v1/behaviors", status_code=status.HTTP_201_CREATED)
    def create_behavior(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.create_draft(payload)
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/behaviors:search")
    def search_behaviors(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            return container.behavior_adapter.search_behaviors(payload)
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/behaviors/{behavior_id}")
    def get_behavior(behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.get_behavior(behavior_id, version)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.patch("/v1/behaviors/{behavior_id}/versions/{version}")
    def update_behavior(behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.update_draft(behavior_id, version, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/behaviors/{behavior_id}/versions/{version}:submit")
    def submit_behavior(behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.submit_for_review(behavior_id, version, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/behaviors/{behavior_id}:approve")
    def approve_behavior(behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.approve(behavior_id, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/behaviors/{behavior_id}:deprecate")
    def deprecate_behavior(behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.deprecate(behavior_id, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.delete("/v1/behaviors/{behavior_id}/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_behavior_draft(behavior_id: str, version: str, payload: Dict[str, Any]) -> Response:
        try:
            container.behavior_adapter.delete_draft(behavior_id, version, payload)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------
    @app.post("/v1/workflows/templates", status_code=status.HTTP_201_CREATED)
    def create_workflow_template(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.workflow_adapter.create_template(payload)
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/workflows/templates")
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

    @app.get("/v1/workflows/templates/{template_id}")
    def get_workflow_template(template_id: str) -> Dict[str, Any]:
        template = container.workflow_adapter.get_template(template_id)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow template not found")
        return template

    @app.post("/v1/workflows/runs", status_code=status.HTTP_201_CREATED)
    def start_workflow_run(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.workflow_adapter.run_workflow(payload)
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/workflows/runs/{run_id}")
    def get_workflow_run(run_id: str) -> Dict[str, Any]:
        run = container.workflow_adapter.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")
        return run

    @app.patch("/v1/workflows/runs/{run_id}")
    def update_workflow_run(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            status_value = payload.get("status")
            if status_value is not None:
                WorkflowStatus(status_value)  # Validate value early
            return container.workflow_adapter.update_run_status(run_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # BCI
    # ------------------------------------------------------------------
    @app.post("/v1/bci:retrieve")
    def bci_retrieve(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.retrieve(payload)

    @app.post("/v1/bci/retrieve")
    def bci_retrieve_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.retrieve(payload)

    @app.post("/v1/bci:retrieveHybrid")
    def bci_retrieve_hybrid(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.retrieve_hybrid(payload)

    @app.post("/v1/bci:rebuildIndex")
    def bci_rebuild_index() -> Dict[str, Any]:
        return container.bci_adapter.rebuild_index()

    @app.post("/v1/bci/rebuild-index")
    def bci_rebuild_index_rest() -> Dict[str, Any]:
        return container.bci_adapter.rebuild_index()

    @app.post("/v1/bci:composePrompt")
    def bci_compose_prompt(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compose_prompt(payload)

    @app.post("/v1/bci/compose-prompt")
    def bci_compose_prompt_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compose_prompt(payload)

    @app.post("/v1/bci:composeBatchPrompts")
    def bci_compose_batch_prompts(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compose_batch_prompts(payload)

    @app.post("/v1/bci:parseCitations")
    def bci_parse_citations(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.parse_citations(payload)

    @app.post("/v1/bci:validateCitations")
    def bci_validate_citations(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.validate_citations(payload)

    @app.post("/v1/bci/validate-citations")
    def bci_validate_citations_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.validate_citations(payload)

    @app.post("/v1/bci:computeTokenSavings")
    def bci_compute_token_savings(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compute_token_savings(payload)

    @app.post("/v1/bci:segmentTrace")
    def bci_segment_trace(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.segment_trace(payload)

    @app.post("/v1/bci:detectPatterns")
    def bci_detect_patterns(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.detect_patterns(payload)

    @app.post("/v1/bci:scoreReusability")
    def bci_score_reusability(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.score_reusability(payload)

    # ------------------------------------------------------------------
    # Reflection
    # ------------------------------------------------------------------
    @app.post("/v1/reflection:extract")
    def reflection_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.reflection_adapter.extract(payload)

    @app.post("/v1/reflection/extract")
    def reflection_extract_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.reflection_adapter.extract(payload)

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    @app.post("/v1/runs", status_code=status.HTTP_201_CREATED)
    def create_run(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.run_adapter.create_run(payload)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/runs")
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

    @app.get("/v1/runs/{run_id}")
    def get_run(run_id: str) -> Dict[str, Any]:
        try:
            return container.run_adapter.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/v1/runs/{run_id}/progress")
    def update_run_progress(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.run_adapter.update_run(run_id, payload)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/runs/{run_id}/complete")
    def complete_run(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.run_adapter.complete_run(run_id, payload)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/runs/{run_id}/cancel")
    def cancel_run(run_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            return container.run_adapter.cancel_run(run_id, payload or {})
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.delete("/v1/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_run(run_id: str) -> None:
        try:
            container.run_adapter.delete_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Compliance
    # ------------------------------------------------------------------
    @app.post("/v1/compliance/checklists", status_code=status.HTTP_201_CREATED)
    def create_checklist(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.compliance_adapter.create_checklist(payload)
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/compliance/checklists")
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

    @app.get("/v1/compliance/checklists/{checklist_id}")
    def get_checklist(checklist_id: str) -> Dict[str, Any]:
        try:
            return container.compliance_adapter.get_checklist(checklist_id)
        except ChecklistNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/v1/compliance/checklists/{checklist_id}/steps", status_code=status.HTTP_201_CREATED)
    def record_step(checklist_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(payload)
        payload["checklist_id"] = checklist_id
        try:
            return container.compliance_adapter.record_step(payload)
        except ChecklistNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/compliance/checklists/{checklist_id}:validate")
    def validate_checklist(checklist_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(payload)
        payload["checklist_id"] = checklist_id
        try:
            return container.compliance_adapter.validate_checklist(payload)
        except ChecklistNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Task assignments
    # ------------------------------------------------------------------
    @app.post("/v1/tasks:listAssignments")
    def list_task_assignments(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            return container.task_adapter.list_assignments(payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    @app.post("/v1/analytics:projectKPI")
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

    @app.get("/v1/analytics/kpi-summary")
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

    @app.get("/v1/analytics/behavior-usage")
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

    @app.get("/v1/analytics/token-savings")
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

    @app.get("/v1/analytics/compliance-coverage")
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
    # Metrics (Real-Time Aggregation with Caching)
    # ------------------------------------------------------------------
    @app.get("/v1/metrics/summary")
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

    @app.post("/v1/metrics/export")
    def export_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Export metrics data to specified format."""
        try:
            return container.metrics_adapter.export_metrics(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Export failed: {exc}",
            ) from exc

    @app.post("/v1/metrics/subscriptions")
    def create_metrics_subscription(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new metrics subscription for real-time streaming."""
        try:
            return container.metrics_adapter.create_subscription(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Subscription creation failed: {exc}",
            ) from exc

    @app.delete("/v1/metrics/subscriptions/{subscription_id}")
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
    @app.post("/v1/auth/device", status_code=status.HTTP_201_CREATED)
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

    @app.post("/v1/auth/device/lookup")
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

    @app.post("/v1/auth/device/approve")
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

    @app.post("/v1/auth/device/deny")
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

    @app.post("/v1/auth/device/token")
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

        response: Dict[str, Any] = {
            "status": result.status.value,
            "client_id": result.client_id,
            "scopes": result.scopes,
        }
        if result.expires_in is not None:
            response["expires_in"] = result.expires_in

        if result.status is DeviceAuthorizationStatus.PENDING:
            response["retry_after"] = result.retry_after
            return response

        if result.status is DeviceAuthorizationStatus.DENIED:
            response["denied_reason"] = result.denied_reason
            return response

        if result.status is DeviceAuthorizationStatus.EXPIRED:
            return response

        assert result.tokens is not None
        tokens = result.tokens
        response.update(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "expires_in": tokens.access_expires_in(),
                "refresh_expires_in": tokens.refresh_expires_in(),
            }
        )
        return response

    @app.post("/v1/auth/device/refresh")
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

    @app.post("/v1/auth/grants")
    def ensure_grant(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Request an authorization grant for a tool and scopes."""
        try:
            return container.agent_auth_adapter.ensure_grant(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Grant request failed: {exc}",
            ) from exc

    @app.get("/v1/auth/grants")
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

    @app.post("/v1/auth/policy-preview")
    def policy_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Preview policy evaluation without creating a grant."""
        try:
            return container.agent_auth_adapter.policy_preview(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Policy preview failed: {exc}",
            ) from exc

    @app.delete("/v1/auth/grants/{grant_id}")
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

    return app


app = create_app()
"""Default application exported for `uvicorn guideai.api:app`."""
