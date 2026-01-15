"""GuideAI CLI providing secret scanning and ActionService parity commands."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
import yaml
from pathlib import Path
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional

from guideai.action_service import ActionService
from guideai.adapters import (
    CLIAgentAuthServiceAdapter,
    CLIAgentOrchestratorAdapter,
    CLITaskAssignmentAdapter,
    CLIActionServiceAdapter,
    CLIBehaviorServiceAdapter,
    CLIComplianceServiceAdapter,
    CLIMetricsServiceAdapter,
    CLIReflectionAdapter,
    CLIRunServiceAdapter,
    CLIWorkflowServiceAdapter,
)
from guideai.agent_auth import AgentAuthClient
from guideai.device_flow import (
    DeviceAuthorizationStatus,
    DeviceFlowManager,
    DeviceFlowError,
    DeviceCodeExpiredError,
    DeviceCodeNotFoundError,
    RefreshTokenExpiredError,
    RefreshTokenNotFoundError,
    UserCodeNotFoundError,
)
from guideai.analytics import TelemetryKPIProjector, TelemetryProjection
from guideai.bci_service import BCIService
from guideai.bci_contracts import (
    BehaviorSnippet,
    CitationMode,
    ComposePromptRequest,
    PromptFormat,
    PrependedBehavior,
    RetrieveRequest,
    RetrievalStrategy,
    RoleFocus,
    ValidateCitationsRequest,
)
from guideai.behavior_retriever import BehaviorRetriever
from guideai.compliance_service import ComplianceService
from guideai.behavior_service import BehaviorService
from guideai.agent_orchestrator_service import AgentOrchestratorService
from guideai.metrics_service import MetricsService
from guideai.reflection_service import ReflectionService
from guideai.reflection_service_postgres import PostgresReflectionService
from guideai.reflection_contracts import TraceFormat
from guideai.run_service import RunService
from guideai.task_assignments import TaskAssignmentService
from guideai.telemetry import TelemetryClient, create_sink_from_env, FileTelemetrySink, KafkaTelemetrySink
from guideai.workflow_service import WorkflowService
from guideai.utils.dsn import apply_host_overrides
from guideai.auth_tokens import (
    AuthTokenBundle,
    TokenStore,
    TokenStoreError,
    get_default_token_store,
)
from guideai.amprealize import BandwidthEnforcer

DEFAULT_OUTPUT = Path("security/scan_reports/latest.json")
DEFAULT_ACTOR_ID = "local-cli"
DEFAULT_ACTOR_ROLE = "STRATEGIST"
DEFAULT_TELEMETRY_EVENTS_PATH = Path.home() / ".guideai" / "telemetry" / "events.jsonl"
AMPREALIZE_SNAPSHOT_DIR = Path.home() / ".guideai" / "amprealize" / "snapshots"

_ACTION_SERVICE: ActionService | None = None
_ACTION_ADAPTER: CLIActionServiceAdapter | None = None
_TASK_SERVICE: TaskAssignmentService | None = None
_TASK_ADAPTER: CLITaskAssignmentAdapter | None = None
_COMPLIANCE_SERVICE: ComplianceService | None = None
_COMPLIANCE_ADAPTER: CLIComplianceServiceAdapter | None = None
_BEHAVIOR_SERVICE: BehaviorService | None = None
_BEHAVIOR_ADAPTER: CLIBehaviorServiceAdapter | None = None
_WORKFLOW_SERVICE: WorkflowService | None = None
_WORKFLOW_ADAPTER: CLIWorkflowServiceAdapter | None = None
_RUN_SERVICE: RunService | None = None
_RUN_ADAPTER: CLIRunServiceAdapter | None = None
_METRICS_SERVICE: MetricsService | None = None
_METRICS_ADAPTER: CLIMetricsServiceAdapter | None = None
_AGENT_AUTH_CLIENT: AgentAuthClient | None = None
_AGENT_AUTH_ADAPTER: CLIAgentAuthServiceAdapter | None = None
_BCI_SERVICE: BCIService | None = None
_BEHAVIOR_RETRIEVER: BehaviorRetriever | None = None
_REFLECTION_SERVICE: ReflectionService | None = None
_REFLECTION_ADAPTER: CLIReflectionAdapter | None = None
_DEVICE_FLOW_MANAGER: DeviceFlowManager | None = None
_TOKEN_STORE: TokenStore | None = None
_AGENT_ORCHESTRATOR_SERVICE: AgentOrchestratorService | None = None
_AGENT_ORCHESTRATOR_ADAPTER: CLIAgentOrchestratorAdapter | None = None


def _create_telemetry_client(default_actor: Dict[str, str]) -> TelemetryClient:
    sink = create_sink_from_env(default_path=DEFAULT_TELEMETRY_EVENTS_PATH)
    return TelemetryClient(sink=sink, default_actor=default_actor)


def _get_action_adapter() -> CLIActionServiceAdapter:
    global _ACTION_SERVICE, _ACTION_ADAPTER
    if _ACTION_SERVICE is None:
        _ACTION_SERVICE = ActionService()
    if _ACTION_ADAPTER is None:
        _ACTION_ADAPTER = CLIActionServiceAdapter(_ACTION_SERVICE)
    return _ACTION_ADAPTER


def _reset_action_state_for_testing() -> None:
    """Reinitialize service singletons used by CLI commands (test helper)."""

    global _ACTION_SERVICE, _ACTION_ADAPTER
    global _TASK_SERVICE, _TASK_ADAPTER
    global _COMPLIANCE_SERVICE, _COMPLIANCE_ADAPTER
    global _BEHAVIOR_SERVICE, _BEHAVIOR_ADAPTER
    global _WORKFLOW_SERVICE, _WORKFLOW_ADAPTER
    global _RUN_SERVICE, _RUN_ADAPTER
    global _METRICS_SERVICE, _METRICS_ADAPTER
    global _AGENT_AUTH_CLIENT, _AGENT_AUTH_ADAPTER
    global _BCI_SERVICE, _BEHAVIOR_RETRIEVER
    global _REFLECTION_SERVICE, _REFLECTION_ADAPTER
    global _DEVICE_FLOW_MANAGER, _TOKEN_STORE
    global _AGENT_ORCHESTRATOR_SERVICE, _AGENT_ORCHESTRATOR_ADAPTER

    _ACTION_SERVICE = ActionService()
    _ACTION_ADAPTER = CLIActionServiceAdapter(_ACTION_SERVICE)
    _TASK_SERVICE = None
    _TASK_ADAPTER = None
    _COMPLIANCE_SERVICE = None
    _COMPLIANCE_ADAPTER = None
    _BEHAVIOR_SERVICE = None
    _BEHAVIOR_ADAPTER = None
    _WORKFLOW_SERVICE = None
    _WORKFLOW_ADAPTER = None
    _RUN_SERVICE = None
    _RUN_ADAPTER = None
    _METRICS_SERVICE = None
    _METRICS_ADAPTER = None
    _AGENT_AUTH_CLIENT = None
    _AGENT_AUTH_ADAPTER = None
    _BCI_SERVICE = None
    _BEHAVIOR_RETRIEVER = None
    _REFLECTION_SERVICE = None
    _REFLECTION_ADAPTER = None
    _DEVICE_FLOW_MANAGER = None
    _TOKEN_STORE = None
    _AGENT_ORCHESTRATOR_SERVICE = None
    _AGENT_ORCHESTRATOR_ADAPTER = None


def _get_task_adapter() -> CLITaskAssignmentAdapter:
    global _TASK_SERVICE, _TASK_ADAPTER
    if _TASK_SERVICE is None:
        _TASK_SERVICE = TaskAssignmentService()
    if _TASK_ADAPTER is None:
        _TASK_ADAPTER = CLITaskAssignmentAdapter(_TASK_SERVICE)
    return _TASK_ADAPTER


def _get_compliance_adapter() -> CLIComplianceServiceAdapter:
    global _COMPLIANCE_SERVICE, _COMPLIANCE_ADAPTER
    if _COMPLIANCE_SERVICE is None:
        _COMPLIANCE_SERVICE = ComplianceService()
    if _COMPLIANCE_ADAPTER is None:
        _COMPLIANCE_ADAPTER = CLIComplianceServiceAdapter(_COMPLIANCE_SERVICE)
    return _COMPLIANCE_ADAPTER


def _get_behavior_adapter() -> CLIBehaviorServiceAdapter:
    global _BEHAVIOR_SERVICE, _BEHAVIOR_ADAPTER
    if _BEHAVIOR_SERVICE is None:
        _BEHAVIOR_SERVICE = BehaviorService()
    if _BEHAVIOR_ADAPTER is None:
        _BEHAVIOR_ADAPTER = CLIBehaviorServiceAdapter(_BEHAVIOR_SERVICE)
    return _BEHAVIOR_ADAPTER


def _get_workflow_adapter() -> CLIWorkflowServiceAdapter:
    global _WORKFLOW_SERVICE, _WORKFLOW_ADAPTER, _BEHAVIOR_SERVICE
    if _BEHAVIOR_SERVICE is None:
        _BEHAVIOR_SERVICE = BehaviorService()
    if _WORKFLOW_SERVICE is None:
        # WorkflowService now uses PostgreSQL DSN from environment
        _WORKFLOW_SERVICE = WorkflowService(dsn=None, behavior_service=_BEHAVIOR_SERVICE)
    if _WORKFLOW_ADAPTER is None:
        _WORKFLOW_ADAPTER = CLIWorkflowServiceAdapter(_WORKFLOW_SERVICE)
    return _WORKFLOW_ADAPTER


def _get_bci_service() -> BCIService:
    """Get or create BCIService singleton with BehaviorRetriever."""
    global _BCI_SERVICE, _BEHAVIOR_RETRIEVER, _BEHAVIOR_SERVICE
    if _BEHAVIOR_SERVICE is None:
        _BEHAVIOR_SERVICE = BehaviorService()
    if _BEHAVIOR_RETRIEVER is None:
        _BEHAVIOR_RETRIEVER = BehaviorRetriever(behavior_service=_BEHAVIOR_SERVICE)
    if _BCI_SERVICE is None:
        _BCI_SERVICE = BCIService(
            behavior_service=_BEHAVIOR_SERVICE,
            behavior_retriever=_BEHAVIOR_RETRIEVER,
        )
    return _BCI_SERVICE


def _get_reflection_adapter() -> CLIReflectionAdapter:
    """Get or create CLIReflectionAdapter singleton.

    Uses PostgreSQL backend when GUIDEAI_REFLECTION_PG_DSN is set,
    otherwise falls back to in-memory implementation.
    """
    global _REFLECTION_SERVICE, _REFLECTION_ADAPTER, _BEHAVIOR_SERVICE, _BCI_SERVICE
    if _BEHAVIOR_SERVICE is None:
        _BEHAVIOR_SERVICE = BehaviorService()
    if _BCI_SERVICE is None:
        _BCI_SERVICE = BCIService(behavior_service=_BEHAVIOR_SERVICE)
    if _REFLECTION_SERVICE is None:
        dsn = apply_host_overrides(os.environ.get("GUIDEAI_REFLECTION_PG_DSN"), "REFLECTION")
        if dsn:
            _REFLECTION_SERVICE = PostgresReflectionService(
                dsn=dsn,
                behavior_service=_BEHAVIOR_SERVICE,
                bci_service=_BCI_SERVICE,
            )
        else:
            _REFLECTION_SERVICE = ReflectionService(
                behavior_service=_BEHAVIOR_SERVICE,
                bci_service=_BCI_SERVICE,
            )
    if _REFLECTION_ADAPTER is None:
        _REFLECTION_ADAPTER = CLIReflectionAdapter(_REFLECTION_SERVICE)
    return _REFLECTION_ADAPTER


def _get_run_adapter() -> CLIRunServiceAdapter:
    """Get or create CLIRunServiceAdapter singleton."""
    global _RUN_SERVICE, _RUN_ADAPTER
    if _RUN_SERVICE is None:
        _RUN_SERVICE = RunService()
    if _RUN_ADAPTER is None:
        _RUN_ADAPTER = CLIRunServiceAdapter(_RUN_SERVICE)
    return _RUN_ADAPTER


def _get_metrics_adapter() -> CLIMetricsServiceAdapter:
    """Get or create CLIMetricsServiceAdapter singleton."""
    global _METRICS_SERVICE, _METRICS_ADAPTER
    if _METRICS_SERVICE is None:
        _METRICS_SERVICE = MetricsService()
    if _METRICS_ADAPTER is None:
        _METRICS_ADAPTER = CLIMetricsServiceAdapter(_METRICS_SERVICE)
    return _METRICS_ADAPTER


def _get_agent_auth_adapter() -> CLIAgentAuthServiceAdapter:
    """Get or create CLIAgentAuthServiceAdapter singleton."""
    global _AGENT_AUTH_CLIENT, _AGENT_AUTH_ADAPTER
    if _AGENT_AUTH_CLIENT is None:
        _AGENT_AUTH_CLIENT = AgentAuthClient()
    if _AGENT_AUTH_ADAPTER is None:
        _AGENT_AUTH_ADAPTER = CLIAgentAuthServiceAdapter(_AGENT_AUTH_CLIENT)
    return _AGENT_AUTH_ADAPTER


def _get_device_flow_manager() -> DeviceFlowManager:
    """Return the shared device flow manager instance."""

    global _DEVICE_FLOW_MANAGER
    if _DEVICE_FLOW_MANAGER is None:
        telemetry = _create_telemetry_client(
            {
                "id": DEFAULT_ACTOR_ID,
                "role": DEFAULT_ACTOR_ROLE,
                "surface": "CLI",
            }
        )
        _DEVICE_FLOW_MANAGER = DeviceFlowManager(telemetry=telemetry)
    return _DEVICE_FLOW_MANAGER


def _get_agent_orchestrator_adapter() -> CLIAgentOrchestratorAdapter:
    """Get or create CLIAgentOrchestratorAdapter singleton."""

    global _AGENT_ORCHESTRATOR_SERVICE, _AGENT_ORCHESTRATOR_ADAPTER
    if _AGENT_ORCHESTRATOR_SERVICE is None:
        _AGENT_ORCHESTRATOR_SERVICE = AgentOrchestratorService()
    if _AGENT_ORCHESTRATOR_ADAPTER is None:
        _AGENT_ORCHESTRATOR_ADAPTER = CLIAgentOrchestratorAdapter(_AGENT_ORCHESTRATOR_SERVICE)
    return _AGENT_ORCHESTRATOR_ADAPTER


def _get_token_store(*, allow_plaintext: Optional[bool] = None) -> TokenStore:
    """Lazily construct the token store used by CLI auth commands."""

    global _TOKEN_STORE
    if _TOKEN_STORE is None:
        _TOKEN_STORE = get_default_token_store(allow_plaintext=allow_plaintext)
    return _TOKEN_STORE


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


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="guideai", description="GuideAI developer tooling")
    subparsers = parser.add_subparsers(dest="command")

    scan_parser = subparsers.add_parser(
        "scan-secrets",
        help="Run repo-wide secret scan via gitleaks and emit a structured report",
    )
    scan_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format for findings",
    )
    scan_parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Return a non-zero exit code when findings are detected",
    )
    scan_parser.add_argument(
        "--output",
        type=str,
        help="Path to save the JSON report (defaults to security/scan_reports/latest.json)",
    )

    record_parser = subparsers.add_parser(
        "record-action",
        help="Record an action via ActionService and emit the stored payload",
    )
    record_parser.add_argument("--artifact", dest="artifact_path", required=True, help="Artifact path impacted")
    record_parser.add_argument("--summary", required=True, help="Human readable summary (<=160 chars)")
    record_parser.add_argument(
        "--behavior",
        dest="behaviors",
        action="append",
        required=True,
        help="Behavior identifier referenced by the action (repeat for multiple)",
    )
    record_parser.add_argument(
        "--metadata",
        dest="metadata_items",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Inline metadata key=value pairs (repeatable)",
    )
    record_parser.add_argument(
        "--metadata-file",
        dest="metadata_file",
        type=str,
        help="Path to a JSON file containing additional metadata (dict)",
    )
    record_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier (defaults to local-cli)")
    record_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role such as STRATEGIST")
    record_parser.add_argument("--related-run-id", help="Optional RunService identifier")
    record_parser.add_argument("--audit-log-event-id", help="Optional audit log event identifier")
    record_parser.add_argument("--checksum", help="Optional checksum override (SHA-256)")
    record_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format for the recorded action",
    )

    list_parser = subparsers.add_parser(
        "list-actions",
        help="List recorded actions across the current CLI session",
    )
    list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    get_parser = subparsers.add_parser(
        "get-action",
        help="Retrieve a single action by ID",
    )
    get_parser.add_argument("action_id", help="Identifier returned by record-action or list-actions")
    get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    replay_parser = subparsers.add_parser(
        "replay-actions",
        help="Trigger a replay job for one or more recorded actions",
    )
    replay_parser.add_argument("action_ids", nargs="+", help="Action identifiers to replay")
    replay_parser.add_argument(
        "--strategy",
        choices=("SEQUENTIAL", "PARALLEL"),
        default="SEQUENTIAL",
        help="Replay scheduling strategy",
    )
    replay_parser.add_argument("--skip-existing", action="store_true", help="Skip actions already replayed successfully")
    replay_parser.add_argument("--dry-run", action="store_true", help="Plan replay without executing commands")
    replay_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    replay_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    replay_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format for the replay status",
    )

    status_parser = subparsers.add_parser(
        "replay-status",
        help="Fetch the status of a previously triggered replay job",
    )
    status_parser.add_argument("replay_id", help="Identifier returned by replay-actions")
    status_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    dr_parser = subparsers.add_parser(
        "dr",
        help="Disaster recovery commands (backup, restore, status, failover)",
    )
    dr_parser.add_argument(
        "dr_args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Arguments forwarded to the DR CLI (prefix with '--' to stop argparse parsing)",
    )

    tasks_parser = subparsers.add_parser(
        "tasks",
        help="List outstanding task assignments filtered by function",
    )
    tasks_parser.add_argument(
        "--function",
        dest="function",
        help="Filter tasks by function (engineering, dx, devops, product, pm, copywriting, compliance)",
    )
    tasks_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format for the task assignments",
    )

    # Behavior subcommands
    behaviors_parser = subparsers.add_parser(
        "behaviors",
        help="Manage handbook behaviors and lifecycle",
    )
    behaviors_subparsers = behaviors_parser.add_subparsers(dest="behaviors_command")

    behaviors_create_parser = behaviors_subparsers.add_parser(
        "create",
        help="Create a new behavior draft",
    )
    behaviors_create_parser.add_argument("--name", required=True, help="Behavior name (unique)")
    behaviors_create_parser.add_argument("--description", required=True, help="Short description")
    behaviors_create_parser.add_argument("--instruction", required=True, help="Behavior instruction text")
    behaviors_create_parser.add_argument(
        "--role",
        dest="role_focus",
        required=True,
        choices=["STRATEGIST", "TEACHER", "STUDENT", "MULTI_ROLE"],
        help="Primary role this behavior targets",
    )
    behaviors_create_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Tag to apply (repeatable)",
    )
    behaviors_create_parser.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        default=[],
        help="Trigger keyword hint (repeatable)",
    )
    behaviors_create_parser.add_argument(
        "--metadata",
        dest="metadata_items",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Metadata key/value (repeatable)",
    )
    behaviors_create_parser.add_argument("--metadata-file", help="Path to JSON file with metadata object")
    behaviors_create_parser.add_argument(
        "--examples-file",
        help="Path to JSON file with example objects [{\"title\":..., \"body\":...}]",
    )
    behaviors_create_parser.add_argument(
        "--embedding",
        help="Comma-separated embedding vector (optional, length <= 1024)",
    )
    behaviors_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_list_parser = behaviors_subparsers.add_parser(
        "list",
        help="List behaviors",
    )
    behaviors_list_parser.add_argument("--status", help="Filter by behavior status")
    behaviors_list_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Filter by tag (repeatable)",
    )
    behaviors_list_parser.add_argument("--role", dest="role_focus", help="Filter by role focus")
    behaviors_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    behaviors_search_parser = behaviors_subparsers.add_parser(
        "search",
        help="Search behaviors using lexical filters",
    )
    behaviors_search_parser.add_argument("--query", help="Search query")
    behaviors_search_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Filter by tag (repeatable)",
    )
    behaviors_search_parser.add_argument("--role", dest="role_focus", help="Filter by role focus")
    behaviors_search_parser.add_argument("--status", help="Filter by status")
    behaviors_search_parser.add_argument("--limit", type=int, default=25, help="Max results (<= 100)")
    behaviors_search_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_search_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_search_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    behaviors_get_parser = behaviors_subparsers.add_parser(
        "get",
        help="Retrieve a behavior with version history",
    )
    behaviors_get_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_get_parser.add_argument("--version", help="Specific version to fetch")
    behaviors_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_update_parser = behaviors_subparsers.add_parser(
        "update",
        help="Update a draft or in-review behavior version",
    )
    behaviors_update_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_update_parser.add_argument("--version", required=True, help="Version to update")
    behaviors_update_parser.add_argument("--instruction", help="New instruction text")
    behaviors_update_parser.add_argument("--description", help="Updated description")
    behaviors_update_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        help="Replace tags (repeatable)",
    )
    behaviors_update_parser.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        help="Replace trigger keywords (repeatable)",
    )
    behaviors_update_parser.add_argument(
        "--metadata",
        dest="metadata_items",
        action="append",
        metavar="KEY=VALUE",
        help="Replace metadata entries (repeatable)",
    )
    behaviors_update_parser.add_argument("--metadata-file", help="Path to JSON metadata object")
    behaviors_update_parser.add_argument("--examples-file", help="Path to JSON examples array")
    behaviors_update_parser.add_argument("--embedding", help="Comma-separated embedding vector")
    behaviors_update_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_update_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_update_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_submit_parser = behaviors_subparsers.add_parser(
        "submit",
        help="Submit a draft for review",
    )
    behaviors_submit_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_submit_parser.add_argument("--version", required=True, help="Version to submit")
    behaviors_submit_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_submit_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_submit_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_approve_parser = behaviors_subparsers.add_parser(
        "approve",
        help="Approve a behavior version",
    )
    behaviors_approve_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_approve_parser.add_argument("--version", required=True, help="Version to approve")
    behaviors_approve_parser.add_argument(
        "--effective-from",
        dest="effective_from",
        required=True,
        help="ISO timestamp when approval becomes active",
    )
    behaviors_approve_parser.add_argument("--approval-action", dest="approval_action_id", help="Action log ID")
    behaviors_approve_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_approve_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_approve_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_deprecate_parser = behaviors_subparsers.add_parser(
        "deprecate",
        help="Deprecate an approved behavior version",
    )
    behaviors_deprecate_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_deprecate_parser.add_argument("--version", required=True, help="Version to deprecate")
    behaviors_deprecate_parser.add_argument(
        "--effective-to",
        dest="effective_to",
        required=True,
        help="ISO timestamp when version is retired",
    )
    behaviors_deprecate_parser.add_argument(
        "--successor",
        dest="successor_behavior_id",
        help="Optional successor behavior identifier",
    )
    behaviors_deprecate_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_deprecate_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_deprecate_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_delete_parser = behaviors_subparsers.add_parser(
        "delete-draft",
        help="Delete a draft behavior version",
    )
    behaviors_delete_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_delete_parser.add_argument("--version", required=True, help="Draft version to delete")
    behaviors_delete_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_delete_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")

    # Compliance subcommands
    compliance_parser = subparsers.add_parser(
        "compliance",
        help="Manage compliance checklists and steps",
    )
    compliance_subparsers = compliance_parser.add_subparsers(dest="compliance_command")

    compliance_create_parser = compliance_subparsers.add_parser(
        "create-checklist",
        help="Create a new compliance checklist",
    )
    compliance_create_parser.add_argument("--title", required=True, help="Checklist title")
    compliance_create_parser.add_argument("--description", default="", help="Checklist description")
    compliance_create_parser.add_argument("--template-id", help="Template identifier")
    compliance_create_parser.add_argument("--milestone", help="Milestone label (e.g., Milestone 1)")
    compliance_create_parser.add_argument(
        "--category",
        dest="compliance_category",
        action="append",
        required=True,
        help="Compliance category (repeatable: SOC2, GDPR, Internal)",
    )
    compliance_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    compliance_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    compliance_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    compliance_record_parser = compliance_subparsers.add_parser(
        "record-step",
        help="Record a checklist step with evidence",
    )
    compliance_record_parser.add_argument("--checklist-id", required=True, help="Checklist identifier")
    compliance_record_parser.add_argument("--title", required=True, help="Step title")
    compliance_record_parser.add_argument(
        "--status",
        required=True,
        choices=("PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "SKIPPED"),
        help="Step status",
    )
    compliance_record_parser.add_argument(
        "--evidence",
        dest="evidence_items",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Evidence metadata key=value pairs (repeatable)",
    )
    compliance_record_parser.add_argument(
        "--behavior",
        dest="behaviors_cited",
        action="append",
        default=[],
        help="Behavior identifier referenced (repeatable)",
    )
    compliance_record_parser.add_argument("--related-run-id", help="Optional RunService identifier")
    compliance_record_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    compliance_record_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    compliance_record_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    compliance_list_parser = compliance_subparsers.add_parser(
        "list",
        help="List compliance checklists",
    )
    compliance_list_parser.add_argument("--milestone", help="Filter by milestone")
    compliance_list_parser.add_argument(
        "--category",
        dest="compliance_category",
        action="append",
        help="Filter by compliance category (repeatable)",
    )
    compliance_list_parser.add_argument(
        "--status",
        choices=("ACTIVE", "COMPLETED", "FAILED"),
        help="Filter by checklist status",
    )
    compliance_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    compliance_get_parser = compliance_subparsers.add_parser(
        "get",
        help="Retrieve a single checklist by ID",
    )
    compliance_get_parser.add_argument("checklist_id", help="Checklist identifier")
    compliance_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    compliance_validate_parser = compliance_subparsers.add_parser(
        "validate",
        help="Validate a checklist and calculate coverage",
    )
    compliance_validate_parser.add_argument("checklist_id", nargs="?", help="Checklist identifier")
    compliance_validate_parser.add_argument("--action-id", help="Validate by action identifier (alternative to checklist_id)")
    compliance_validate_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    compliance_validate_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    compliance_validate_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    # Compliance policies subcommands
    compliance_policies_parser = compliance_subparsers.add_parser(
        "policies",
        help="Manage compliance policies",
    )
    compliance_policies_subparsers = compliance_policies_parser.add_subparsers(dest="policies_command")

    policies_list_parser = compliance_policies_subparsers.add_parser(
        "list",
        help="List compliance policies",
    )
    policies_list_parser.add_argument("--org-id", help="Filter by organization ID")
    policies_list_parser.add_argument("--project-id", help="Filter by project ID")
    policies_list_parser.add_argument(
        "--type",
        dest="policy_type",
        choices=("AUDIT", "SECURITY", "COMPLIANCE", "GOVERNANCE", "CUSTOM"),
        help="Filter by policy type",
    )
    policies_list_parser.add_argument(
        "--enforcement",
        dest="enforcement_level",
        choices=("ADVISORY", "WARNING", "BLOCKING"),
        help="Filter by enforcement level",
    )
    policies_list_parser.add_argument(
        "--active-only",
        action="store_true",
        default=False,
        help="Only show active policies",
    )
    policies_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    policies_create_parser = compliance_policies_subparsers.add_parser(
        "create",
        help="Create a new compliance policy",
    )
    policies_create_parser.add_argument("--name", required=True, help="Policy name")
    policies_create_parser.add_argument("--description", required=True, help="Policy description")
    policies_create_parser.add_argument(
        "--type",
        dest="policy_type",
        required=True,
        choices=("AUDIT", "SECURITY", "COMPLIANCE", "GOVERNANCE", "CUSTOM"),
        help="Policy type",
    )
    policies_create_parser.add_argument(
        "--enforcement",
        dest="enforcement_level",
        required=True,
        choices=("ADVISORY", "WARNING", "BLOCKING"),
        help="Enforcement level",
    )
    policies_create_parser.add_argument("--org-id", help="Organization ID (for org/project scope)")
    policies_create_parser.add_argument("--project-id", help="Project ID (requires --org-id)")
    policies_create_parser.add_argument("--version", default="1.0.0", help="Policy version")
    policies_create_parser.add_argument(
        "--behavior",
        dest="required_behaviors",
        action="append",
        default=[],
        help="Required behavior ID (repeatable)",
    )
    policies_create_parser.add_argument(
        "--category",
        dest="compliance_categories",
        action="append",
        default=[],
        help="Compliance category (SOC2, GDPR, etc., repeatable)",
    )
    policies_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    policies_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    policies_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    policies_get_parser = compliance_policies_subparsers.add_parser(
        "get",
        help="Retrieve a single policy by ID",
    )
    policies_get_parser.add_argument("policy_id", help="Policy identifier")
    policies_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    # Compliance audit subcommand
    compliance_audit_parser = compliance_subparsers.add_parser(
        "audit",
        help="Generate audit trail report",
    )
    compliance_audit_parser.add_argument("--run-id", help="Filter by run ID")
    compliance_audit_parser.add_argument("--checklist-id", help="Filter by checklist ID")
    compliance_audit_parser.add_argument("--action-id", help="Filter by action ID")
    compliance_audit_parser.add_argument("--start-date", help="Filter entries after this ISO timestamp")
    compliance_audit_parser.add_argument("--end-date", help="Filter entries before this ISO timestamp")
    compliance_audit_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # Workflow subcommands
    workflow_parser = subparsers.add_parser(
        "workflow",
        help="Manage workflow templates and runs",
    )
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command")

    workflow_create_parser = workflow_subparsers.add_parser(
        "create-template",
        help="Create a new workflow template",
    )
    workflow_create_parser.add_argument("--name", required=True, help="Template name")
    workflow_create_parser.add_argument("--description", required=True, help="Template description")
    workflow_create_parser.add_argument(
        "--role",
        dest="role_focus",
        required=True,
        choices=["STRATEGIST", "TEACHER", "STUDENT", "MULTI_ROLE"],
        help="Primary role for this workflow",
    )
    workflow_create_parser.add_argument(
        "--steps-file",
        required=True,
        help="Path to JSON file with step definitions array",
    )
    workflow_create_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Tag to apply (repeatable)",
    )
    workflow_create_parser.add_argument("--metadata-file", help="Path to JSON metadata object")
    workflow_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    workflow_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    workflow_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    workflow_list_parser = workflow_subparsers.add_parser(
        "list-templates",
        help="List workflow templates",
    )
    workflow_list_parser.add_argument("--role", dest="role_focus", help="Filter by role focus")
    workflow_list_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Filter by tag (repeatable)",
    )
    workflow_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    workflow_get_parser = workflow_subparsers.add_parser(
        "get-template",
        help="Retrieve a workflow template by ID",
    )
    workflow_get_parser.add_argument("template_id", help="Template identifier")
    workflow_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    workflow_run_parser = workflow_subparsers.add_parser(
        "run",
        help="Execute a workflow template",
    )
    workflow_run_parser.add_argument("template_id", help="Workflow template identifier")
    workflow_run_parser.add_argument(
        "--behavior",
        dest="behavior_ids",
        action="append",
        default=[],
        help="Behavior ID to attach (repeatable)",
    )
    workflow_run_parser.add_argument("--metadata-file", help="Path to JSON metadata object")
    workflow_run_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    workflow_run_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    workflow_run_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    workflow_status_parser = workflow_subparsers.add_parser(
        "status",
        help="Check the status of a workflow run",
    )
    workflow_status_parser.add_argument("run_id", help="Run identifier")
    workflow_status_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    # Run subcommands
    run_parser = subparsers.add_parser(
        "run",
        help="Manage workflow execution runs",
    )
    run_subparsers = run_parser.add_subparsers(dest="run_command")

    run_create_parser = run_subparsers.add_parser(
        "create",
        help="Create a new run",
    )
    run_create_parser.add_argument("--workflow-id", help="Workflow identifier")
    run_create_parser.add_argument("--workflow-name", help="Workflow name")
    run_create_parser.add_argument("--template-id", help="Template identifier")
    run_create_parser.add_argument("--template-name", help="Template name")
    run_create_parser.add_argument(
        "--behavior",
        dest="behavior_ids",
        action="append",
        default=[],
        help="Behavior ID to use (repeatable)",
    )
    run_create_parser.add_argument("--metadata-file", help="Path to JSON metadata object")
    run_create_parser.add_argument("--message", help="Initial message/description")
    run_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    run_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    run_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    run_get_parser = run_subparsers.add_parser(
        "get",
        help="Get run details by ID",
    )
    run_get_parser.add_argument("run_id", help="Run identifier")
    run_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    run_list_parser = run_subparsers.add_parser(
        "list",
        help="List runs with optional filters",
    )
    run_list_parser.add_argument("--status", help="Filter by status (PENDING/RUNNING/COMPLETED/FAILED/CANCELLED)")
    run_list_parser.add_argument("--workflow-id", help="Filter by workflow ID")
    run_list_parser.add_argument("--template-id", help="Filter by template ID")
    run_list_parser.add_argument("--limit", type=int, default=50, help="Maximum number of runs to return")
    run_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    run_complete_parser = run_subparsers.add_parser(
        "complete",
        help="Complete a run with final status",
    )
    run_complete_parser.add_argument("run_id", help="Run identifier")
    run_complete_parser.add_argument(
        "--status",
        required=True,
        choices=["COMPLETED", "FAILED"],
        help="Final run status",
    )
    run_complete_parser.add_argument("--outputs-file", help="Path to JSON outputs object")
    run_complete_parser.add_argument("--message", help="Completion message")
    run_complete_parser.add_argument("--error", help="Error message (for FAILED status)")
    run_complete_parser.add_argument("--metadata-file", help="Path to JSON metadata updates")
    run_complete_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    run_cancel_parser = run_subparsers.add_parser(
        "cancel",
        help="Cancel a running job",
    )
    run_cancel_parser.add_argument("run_id", help="Run identifier")
    run_cancel_parser.add_argument("--reason", help="Cancellation reason")
    run_cancel_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    # amprealize
    amp_parser = subparsers.add_parser(
        "amprealize",
        help="Infrastructure orchestration and plan management",
    )
    amp_subparsers = amp_parser.add_subparsers(dest="amprealize_command")
    amp_subparsers.required = True

    # amprealize plan
    amp_plan_parser = amp_subparsers.add_parser(
        "plan",
        help="Generate an execution plan from a blueprint",
    )
    amp_plan_parser.add_argument(
        "--blueprint-id",
        dest="blueprint_id",
        required=True,
        help="ID of the blueprint to plan",
    )
    amp_plan_parser.add_argument(
        "--environment",
        dest="environment",
        default="development",
        help="Target environment (development, staging, production)",
    )
    amp_plan_parser.add_argument(
        "--lifetime",
        dest="lifetime",
        default="90m",
        help="Lifetime of the environment (ISO8601 duration)",
    )
    amp_plan_parser.add_argument(
        "--compliance-tier",
        dest="compliance_tier",
        default="dev",
        choices=["dev", "prod-sim", "pci-sandbox"],
        help="Compliance tier for the environment",
    )
    amp_plan_parser.add_argument(
        "--checklist-id",
        dest="checklist_id",
        help="Compliance checklist ID to link evidence to",
    )
    amp_plan_parser.add_argument(
        "--behavior",
        dest="behaviors",
        action="append",
        default=[],
        help="Behaviors to include in the plan",
    )
    amp_plan_parser.add_argument(
        "--var",
        dest="variables",
        action="append",
        default=[],
        help="Variables in key=value format",
    )
    amp_plan_parser.add_argument(
        "--module",
        dest="active_modules",
        action="append",
        help="Module to activate (repeatable). If specified, only services in these modules are included.",
    )
    amp_plan_parser.add_argument(
        "--force-podman",
        dest="force_podman",
        action="store_true",
        default=False,
        help="Suppress warnings if a Podman VM is detected",
    )
    amp_plan_parser.add_argument(
        "--env-file",
        dest="env_file",
        help="Path to an Amprealize environment manifest (overrides GUIDEAI_ENV_FILE)",
    )
    amp_plan_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )
    amp_plan_parser.add_argument(
        "--actor-id",
        dest="actor_id",
        default=DEFAULT_ACTOR_ID,
        help="Actor identifier (defaults to local-cli)",
    )
    amp_plan_parser.add_argument(
        "--actor-role",
        dest="actor_role",
        default=DEFAULT_ACTOR_ROLE,
        help="Actor role (defaults to STRATEGIST)",
    )

    # amprealize apply
    amp_apply_parser = amp_subparsers.add_parser(
        "apply",
        help="Apply a plan or manifest to create resources",
    )
    amp_apply_parser.add_argument(
        "--plan-id",
        dest="plan_id",
        help="ID of the plan to apply",
    )
    amp_apply_parser.add_argument(
        "--manifest",
        dest="manifest_file",
        help="Path to a manifest file to apply",
    )
    amp_apply_parser.add_argument(
        "--watch",
        dest="watch",
        action="store_true",
        default=True,
        help="Watch progress until completion",
    )
    amp_apply_parser.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        default=False,
        help="Resume a paused or failed apply",
    )
    amp_apply_parser.add_argument(
        "--force-podman",
        dest="force_podman",
        action="store_true",
        default=False,
        help="Suppress warnings if a Podman VM is detected",
    )
    amp_apply_parser.add_argument(
        "--skip-resource-check",
        dest="skip_resource_check",
        action="store_true",
        default=False,
        help="Skip pre-flight resource health check",
    )
    amp_apply_parser.add_argument(
        "--min-disk-gb",
        dest="min_disk_gb",
        type=float,
        default=5.0,
        help="Minimum disk space in GB required for apply (default: 5.0)",
    )
    amp_apply_parser.add_argument(
        "--min-memory-mb",
        dest="min_memory_mb",
        type=float,
        default=1024.0,
        help="Minimum memory in MB required for apply (default: 1024)",
    )
    amp_apply_parser.add_argument(
        "--auto-cleanup",
        dest="auto_cleanup",
        action="store_true",
        default=False,
        help="Automatically clean up unused resources when disk/memory is critical",
    )
    amp_apply_parser.add_argument(
        "--auto-cleanup-aggressive",
        dest="auto_cleanup_aggressive",
        action="store_true",
        default=False,
        help="Start with aggressive cleanup (networks, pods, logs) instead of standard",
    )
    amp_apply_parser.add_argument(
        "--auto-cleanup-volumes",
        dest="auto_cleanup_include_volumes",
        action="store_true",
        default=False,
        help="Include volumes in auto-cleanup (WARNING: may lose data)",
    )
    amp_apply_parser.add_argument(
        "--auto-cleanup-retries",
        dest="auto_cleanup_max_retries",
        type=int,
        default=3,
        help="Max cleanup+recheck cycles per tier before escalating (default: 3)",
    )
    amp_apply_parser.add_argument(
        "--allow-host-resource-warning",
        dest="allow_host_resource_warning",
        action="store_true",
        default=False,
        help="Allow proceeding when host disk is low but VM is healthy (warns but continues)",
    )
    amp_apply_parser.add_argument(
        "--proactive-cleanup",
        dest="proactive_cleanup",
        action="store_true",
        default=False,
        help="Run cleanup BEFORE resource check to maximize available resources (prevents memory exhaustion)",
    )
    amp_apply_parser.add_argument(
        "--blueprint-aware-memory",
        dest="blueprint_aware_memory_check",
        action="store_true",
        default=True,
        help="Use blueprint memory estimates instead of fixed threshold (default: enabled)",
    )
    amp_apply_parser.add_argument(
        "--no-blueprint-aware-memory",
        dest="blueprint_aware_memory_check",
        action="store_false",
        help="Disable blueprint-aware memory checking (use fixed threshold instead)",
    )
    amp_apply_parser.add_argument(
        "--memory-safety-margin-mb",
        dest="memory_safety_margin_mb",
        type=float,
        default=512.0,
        help="Extra memory to require beyond blueprint estimate (default: 512 MB)",
    )
    amp_apply_parser.add_argument(
        "--auto-resolve-stale",
        dest="auto_resolve_stale",
        action="store_true",
        default=True,
        help="Automatically remove stale/exited/dead containers before apply (default: enabled)",
    )
    amp_apply_parser.add_argument(
        "--no-auto-resolve-stale",
        dest="auto_resolve_stale",
        action="store_false",
        help="Disable auto-resolve of stale containers",
    )
    amp_apply_parser.add_argument(
        "--auto-resolve-conflicts",
        dest="auto_resolve_conflicts",
        action="store_true",
        default=True,
        help="Automatically resolve port conflicts (stop conflicting containers/processes) (default: enabled)",
    )
    amp_apply_parser.add_argument(
        "--no-auto-resolve-conflicts",
        dest="auto_resolve_conflicts",
        action="store_false",
        help="Disable auto-resolve of port conflicts",
    )
    amp_apply_parser.add_argument(
        "--stale-max-age-hours",
        dest="stale_max_age_hours",
        type=float,
        default=0.0,
        help="Max age for stale container cleanup in hours (0 = all stale, -1 = skip age check)",
    )
    amp_apply_parser.add_argument(
        "--env-file",
        dest="env_file",
        help="Path to an Amprealize environment manifest (overrides GUIDEAI_ENV_FILE)",
    )
    amp_apply_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )
    amp_apply_parser.add_argument(
        "--actor-id",
        dest="actor_id",
        default=DEFAULT_ACTOR_ID,
        help="Actor identifier (defaults to local-cli)",
    )
    amp_apply_parser.add_argument(
        "--actor-role",
        dest="actor_role",
        default=DEFAULT_ACTOR_ROLE,
        help="Actor role (defaults to STRATEGIST)",
    )

    # amprealize status
    amp_status_parser = amp_subparsers.add_parser(
        "status",
        help="Check status of an amprealize run",
    )
    amp_status_parser.add_argument(
        "--run-id",
        dest="amp_run_id",
        required=True,
        help="Amprealize run ID",
    )
    amp_status_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )

    # amprealize destroy
    amp_destroy_parser = amp_subparsers.add_parser(
        "destroy",
        help="Destroy resources from an amprealize run",
    )
    amp_destroy_parser.add_argument(
        "--run-id",
        dest="amp_run_id",
        required=True,
        help="Amprealize run ID",
    )
    amp_destroy_parser.add_argument(
        "--cascade",
        dest="cascade",
        action="store_true",
        default=True,
        help="Cascade destroy dependent resources",
    )
    amp_destroy_parser.add_argument(
        "--reason",
        dest="reason",
        default="MANUAL",
        choices=["POST_TEST", "FAILED", "ABANDONED", "MANUAL"],
        help="Reason for destruction",
    )
    amp_destroy_parser.add_argument(
        "--force-podman",
        dest="force_podman",
        action="store_true",
        default=False,
        help="Suppress warnings if a Podman VM is detected",
    )
    amp_destroy_parser.add_argument(
        "--cleanup-after-destroy",
        dest="cleanup_after_destroy",
        action="store_true",
        default=True,
        help="Run resource cleanup after destroying containers (default: enabled)",
    )
    amp_destroy_parser.add_argument(
        "--no-cleanup-after-destroy",
        dest="cleanup_after_destroy",
        action="store_false",
        help="Skip post-destroy resource cleanup",
    )
    amp_destroy_parser.add_argument(
        "--cleanup-aggressive",
        dest="cleanup_aggressive",
        action="store_true",
        default=True,
        help="Use aggressive cleanup including dangling images/cache (default: enabled)",
    )
    amp_destroy_parser.add_argument(
        "--no-cleanup-aggressive",
        dest="cleanup_aggressive",
        action="store_false",
        help="Use standard cleanup (containers only)",
    )
    amp_destroy_parser.add_argument(
        "--cleanup-volumes",
        dest="cleanup_include_volumes",
        action="store_true",
        default=False,
        help="Include volumes in cleanup (WARNING: may lose data)",
    )
    amp_destroy_parser.add_argument(
        "--env-file",
        dest="env_file",
        help="Path to an Amprealize environment manifest (overrides GUIDEAI_ENV_FILE)",
    )
    amp_destroy_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )
    amp_destroy_parser.add_argument(
        "--actor-id",
        dest="actor_id",
        default=DEFAULT_ACTOR_ID,
        help="Actor identifier (defaults to local-cli)",
    )
    amp_destroy_parser.add_argument(
        "--actor-role",
        dest="actor_role",
        default=DEFAULT_ACTOR_ROLE,
        help="Actor role (defaults to STRATEGIST)",
    )

    # amprealize bootstrap
    amp_bootstrap_parser = amp_subparsers.add_parser(
        "bootstrap",
        help="Scaffold Amprealize config files into the current workspace",
    )
    amp_bootstrap_parser.add_argument(
        "--directory",
        dest="bootstrap_directory",
        default=".",
        help="Directory where config/amprealize files should be created",
    )
    amp_bootstrap_parser.add_argument(
        "--include-blueprints",
        dest="include_blueprints",
        action="store_true",
        default=False,
        help="Copy packaged blueprint samples into config/amprealize/blueprints",
    )
    amp_bootstrap_parser.add_argument(
        "--blueprint",
        dest="blueprints",
        action="append",
        default=[],
        help="Specific blueprint IDs to copy (defaults to all when --include-blueprints is set)",
    )
    amp_bootstrap_parser.add_argument(
        "--env-template",
        dest="env_template",
        help="Path to a custom environments.yaml template to copy",
    )
    amp_bootstrap_parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        default=False,
        help="Overwrite existing files if they already exist",
    )

    # amprealize machine - Podman machine management
    amp_machine_parser = amp_subparsers.add_parser(
        "machine",
        help="Manage Podman machines (macOS/Windows)",
    )
    amp_machine_subparsers = amp_machine_parser.add_subparsers(dest="machine_command")

    # amprealize machine list
    amp_machine_list_parser = amp_machine_subparsers.add_parser(
        "list",
        help="List all Podman machines",
    )
    amp_machine_list_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    # amprealize machine start
    amp_machine_start_parser = amp_machine_subparsers.add_parser(
        "start",
        help="Start a Podman machine",
    )
    amp_machine_start_parser.add_argument(
        "name",
        nargs="?",
        help="Machine name (defaults to guideai-ci or first available)",
    )

    # amprealize machine stop
    amp_machine_stop_parser = amp_machine_subparsers.add_parser(
        "stop",
        help="Stop a Podman machine",
    )
    amp_machine_stop_parser.add_argument(
        "name",
        nargs="?",
        help="Machine name (defaults to guideai-ci or current running machine)",
    )
    amp_machine_stop_parser.add_argument(
        "--all",
        dest="stop_all",
        action="store_true",
        default=False,
        help="Stop all running Podman machines",
    )

    # amprealize machine ensure
    amp_machine_ensure_parser = amp_machine_subparsers.add_parser(
        "ensure",
        help="Ensure a Podman machine is running (start if needed, create if missing)",
    )
    amp_machine_ensure_parser.add_argument(
        "name",
        nargs="?",
        default="guideai-ci",
        help="Machine name (default: guideai-ci)",
    )
    amp_machine_ensure_parser.add_argument(
        "--cpus",
        type=int,
        default=2,
        help="Number of CPUs for new machine (default: 2)",
    )
    amp_machine_ensure_parser.add_argument(
        "--memory",
        type=int,
        default=4096,
        help="Memory in MB for new machine (default: 4096)",
    )
    amp_machine_ensure_parser.add_argument(
        "--disk",
        type=int,
        default=100,
        help="Disk size in GB for new machine (default: 100)",
    )

    # amprealize machine status
    amp_machine_status_parser = amp_machine_subparsers.add_parser(
        "status",
        help="Show status of a Podman machine",
    )
    amp_machine_status_parser.add_argument(
        "name",
        nargs="?",
        help="Machine name (defaults to guideai-ci or first available)",
    )
    amp_machine_status_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    # amprealize machine resources
    amp_machine_resources_parser = amp_machine_subparsers.add_parser(
        "resources",
        help="Show resource usage for host and Podman machines",
    )
    amp_machine_resources_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )
    amp_machine_resources_parser.add_argument(
        "--check",
        action="store_true",
        help="Check resource health against minimum requirements",
    )
    amp_machine_resources_parser.add_argument(
        "--min-disk-gb",
        type=float,
        default=5.0,
        help="Minimum free disk space in GB (default: 5.0)",
    )
    amp_machine_resources_parser.add_argument(
        "--min-memory-mb",
        type=float,
        default=1024.0,
        help="Minimum free memory in MB (default: 1024)",
    )

    # amprealize machine cleanup
    amp_machine_cleanup_parser = amp_machine_subparsers.add_parser(
        "cleanup",
        help="Clean up unused resources (containers, images, cache) to free disk space",
    )
    amp_machine_cleanup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned without actually removing anything",
    )
    amp_machine_cleanup_parser.add_argument(
        "--include-volumes",
        action="store_true",
        help="Also remove unused volumes (CAUTION: may delete data)",
    )
    amp_machine_cleanup_parser.add_argument(
        "--include-networks",
        action="store_true",
        help="Also remove unused networks",
    )
    amp_machine_cleanup_parser.add_argument(
        "--include-pods",
        action="store_true",
        help="Also remove stopped pods",
    )
    amp_machine_cleanup_parser.add_argument(
        "--include-logs",
        action="store_true",
        help="Also clear container logs",
    )
    amp_machine_cleanup_parser.add_argument(
        "--aggressive",
        action="store_true",
        help="Enable ALL cleanup options (includes volumes - use with caution)",
    )
    amp_machine_cleanup_parser.add_argument(
        "--skip-containers",
        action="store_true",
        help="Skip removing stopped containers",
    )
    amp_machine_cleanup_parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Skip removing unused images",
    )
    amp_machine_cleanup_parser.add_argument(
        "--skip-cache",
        action="store_true",
        help="Skip clearing build cache",
    )
    amp_machine_cleanup_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    # amprealize cleanup - Direct container cleanup without machine management
    amp_cleanup_parser = amp_subparsers.add_parser(
        "cleanup",
        help="Clean up stale/orphaned containers and free resources",
    )
    amp_cleanup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned without actually removing anything",
    )
    amp_cleanup_parser.add_argument(
        "--stale",
        action="store_true",
        default=True,
        help="Remove stale containers (exited, dead, created) [default: True]",
    )
    amp_cleanup_parser.add_argument(
        "--no-stale",
        dest="stale",
        action="store_false",
        help="Skip stale container cleanup",
    )
    amp_cleanup_parser.add_argument(
        "--orphans",
        action="store_true",
        default=True,
        help="Remove orphaned Amprealize containers [default: True]",
    )
    amp_cleanup_parser.add_argument(
        "--no-orphans",
        dest="orphans",
        action="store_false",
        help="Skip orphaned container cleanup",
    )
    amp_cleanup_parser.add_argument(
        "--max-age-hours",
        type=float,
        default=None,
        help="Only remove stale containers older than N hours (default: any age)",
    )
    amp_cleanup_parser.add_argument(
        "--all-non-running",
        action="store_true",
        default=False,
        help="Remove ALL non-running containers (not just stale statuses)",
    )
    amp_cleanup_parser.add_argument(
        "--force-podman",
        action="store_true",
        default=False,
        help="Suppress warnings if a Podman VM is detected",
    )
    amp_cleanup_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    # ── Auth commands ───────────────────────────────────────────────────────────
    auth_parser = subparsers.add_parser(
        "auth",
        help="Authentication and consent management commands",
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")

    # auth login (device flow)
    auth_login_parser = auth_subparsers.add_parser(
        "login",
        help="Authenticate via device flow",
    )
    auth_login_parser.add_argument(
        "--provider",
        choices=("github", "google", "internal"),
        default="internal",
        help="OAuth provider to use (default: internal)",
    )
    auth_login_parser.add_argument(
        "--scopes",
        nargs="+",
        default=["behaviors.read", "behaviors.write"],
        help="Scopes to request (default: behaviors.read behaviors.write)",
    )
    auth_login_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds for device flow (default: 300)",
    )
    auth_login_parser.add_argument(
        "--client-id",
        dest="client_id",
        default="guideai-cli",
        help="Client ID for the device flow (default: guideai-cli)",
    )
    auth_login_parser.add_argument(
        "--open-browser",
        dest="open_browser",
        action="store_true",
        default=True,
        help="Automatically open browser for verification (default: true)",
    )
    auth_login_parser.add_argument(
        "--no-browser",
        dest="open_browser",
        action="store_false",
        help="Do not automatically open browser",
    )
    auth_login_parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        default=False,
        help="Suppress progress output",
    )
    auth_login_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )

    # auth register (internal auth only)
    auth_register_parser = auth_subparsers.add_parser(
        "register",
        help="Register a new user account (internal auth only)",
    )
    auth_register_parser.add_argument(
        "--username",
        help="Username for registration (prompts if not provided)",
    )
    auth_register_parser.add_argument(
        "--password",
        help="Password for registration (prompts if not provided)",
    )
    auth_register_parser.add_argument(
        "--email",
        help="Email for registration (optional)",
    )
    auth_register_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )
    auth_register_parser.add_argument(
        "--api-url",
        dest="api_url",
        default=None,
        help="API URL for registration (default: $GUIDEAI_API_URL or http://localhost:8000)",
    )

    # auth status
    auth_status_parser = auth_subparsers.add_parser(
        "status",
        help="Show current authentication status",
    )
    auth_status_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )
    auth_status_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )

    # auth logout
    auth_logout_parser = auth_subparsers.add_parser(
        "logout",
        help="Clear stored authentication tokens",
    )
    auth_logout_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )

    # auth refresh
    auth_refresh_parser = auth_subparsers.add_parser(
        "refresh",
        help="Refresh the access token using stored refresh token",
    )
    auth_refresh_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )
    auth_refresh_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )

    # auth ensure-grant
    auth_ensure_grant_parser = auth_subparsers.add_parser(
        "ensure-grant",
        help="Ensure a valid grant exists for the specified scopes",
    )
    auth_ensure_grant_parser.add_argument(
        "--scopes",
        nargs="+",
        required=True,
        help="Scopes to request grant for",
    )
    auth_ensure_grant_parser.add_argument(
        "--actor-id",
        default=DEFAULT_ACTOR_ID,
        help="Actor ID for the grant",
    )
    auth_ensure_grant_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # auth list-grants
    auth_list_grants_parser = auth_subparsers.add_parser(
        "list-grants",
        help="List all active grants for the current user",
    )
    auth_list_grants_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # auth policy-preview
    auth_policy_preview_parser = auth_subparsers.add_parser(
        "policy-preview",
        help="Preview policy decision for a scope without granting",
    )
    auth_policy_preview_parser.add_argument(
        "--scopes",
        nargs="+",
        required=True,
        help="Scopes to preview",
    )
    auth_policy_preview_parser.add_argument(
        "--actor-id",
        default=DEFAULT_ACTOR_ID,
        help="Actor ID for the preview",
    )
    auth_policy_preview_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # auth revoke
    auth_revoke_parser = auth_subparsers.add_parser(
        "revoke",
        help="Revoke an active grant",
    )
    auth_revoke_parser.add_argument(
        "grant_id",
        help="Grant ID to revoke",
    )
    auth_revoke_parser.add_argument(
        "--reason",
        default="user_request",
        help="Reason for revocation",
    )

    # auth consent-lookup
    auth_consent_lookup_parser = auth_subparsers.add_parser(
        "consent-lookup",
        help="Look up consent request details by user code",
    )
    auth_consent_lookup_parser.add_argument(
        "user_code",
        help="User code from the consent prompt (e.g., ABCD-1234)",
    )
    auth_consent_lookup_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # auth consent-approve
    auth_consent_approve_parser = auth_subparsers.add_parser(
        "consent-approve",
        help="Approve a consent request",
    )
    auth_consent_approve_parser.add_argument(
        "user_code",
        help="User code from the consent prompt (e.g., ABCD-1234)",
    )
    auth_consent_approve_parser.add_argument(
        "--actor-id",
        default=DEFAULT_ACTOR_ID,
        help="Actor ID approving the consent",
    )
    auth_consent_approve_parser.add_argument(
        "--roles",
        nargs="+",
        help="Roles to grant with consent (optional)",
    )
    auth_consent_approve_parser.add_argument(
        "--mfa-verified",
        action="store_true",
        default=False,
        help="Indicate MFA was verified for this approval",
    )

    # auth consent-deny
    auth_consent_deny_parser = auth_subparsers.add_parser(
        "consent-deny",
        help="Deny a consent request",
    )
    auth_consent_deny_parser.add_argument(
        "user_code",
        help="User code from the consent prompt (e.g., ABCD-1234)",
    )
    auth_consent_deny_parser.add_argument(
        "--actor-id",
        default=DEFAULT_ACTOR_ID,
        help="Actor ID denying the consent",
    )
    auth_consent_deny_parser.add_argument(
        "--reason",
        default="user_denied",
        help="Reason for denial",
    )

    # ── BCI commands ────────────────────────────────────────────────────────────
    bci_parser = subparsers.add_parser(
        "bci",
        help="Behavior-Conditioned Inference commands",
    )
    bci_subparsers = bci_parser.add_subparsers(dest="bci_command")

    # bci rebuild-index
    bci_rebuild_parser = bci_subparsers.add_parser(
        "rebuild-index",
        help="Rebuild the behavior retrieval index",
    )

    # bci retrieve
    bci_retrieve_parser = bci_subparsers.add_parser(
        "retrieve",
        help="Retrieve relevant behaviors for a query",
    )
    bci_retrieve_parser.add_argument("query", help="The query to retrieve behaviors for")
    bci_retrieve_parser.add_argument("--top-k", type=int, default=5, help="Number of behaviors to retrieve")
    bci_retrieve_parser.add_argument(
        "--strategy",
        choices=["semantic", "keyword", "hybrid"],
        default="hybrid",
        help="Retrieval strategy",
    )
    bci_retrieve_parser.add_argument(
        "--role",
        choices=["student", "teacher", "strategist"],
        help="Filter by role focus",
    )

    # bci compose-prompt
    bci_compose_parser = bci_subparsers.add_parser(
        "compose-prompt",
        help="Compose a BCI prompt with retrieved behaviors",
    )
    bci_compose_parser.add_argument("query", help="The user query")
    bci_compose_parser.add_argument(
        "--behaviors",
        nargs="+",
        help="Explicit behavior names to include",
    )
    bci_compose_parser.add_argument("--top-k", type=int, default=5, help="Number of behaviors to retrieve")
    bci_compose_parser.add_argument(
        "--format",
        choices=["simple", "detailed", "json"],
        default="simple",
        help="Prompt format",
    )

    # bci validate-citations
    bci_validate_parser = bci_subparsers.add_parser(
        "validate-citations",
        help="Validate behavior citations in a response",
    )
    bci_validate_parser.add_argument("response", help="The response text to validate")
    bci_validate_parser.add_argument(
        "--mode",
        choices=["strict", "lenient", "fuzzy"],
        default="strict",
        help="Citation validation mode",
    )

    # bci generate
    bci_generate_parser = bci_subparsers.add_parser(
        "generate",
        help="Generate a behavior-conditioned LLM response",
    )
    bci_generate_parser.add_argument("query", help="The query to generate a response for")
    bci_generate_parser.add_argument(
        "--behaviors",
        nargs="+",
        help="Explicit behavior names to use (default: auto-retrieve)",
    )
    bci_generate_parser.add_argument("--top-k", type=int, default=5, help="Number of behaviors to retrieve")
    bci_generate_parser.add_argument(
        "--provider",
        choices=["openai", "anthropic", "openrouter", "ollama", "together", "groq", "fireworks", "test"],
        help="LLM provider (default: from environment)",
    )
    bci_generate_parser.add_argument("--model", help="Model name (default: provider default)")
    bci_generate_parser.add_argument("--temperature", type=float, help="Sampling temperature")
    bci_generate_parser.add_argument(
        "--role",
        choices=["student", "teacher", "strategist"],
        help="Role focus for behavior retrieval",
    )
    bci_generate_parser.add_argument("--output", "-o", help="Output file path (default: stdout)")

    # bci improve
    bci_improve_parser = bci_subparsers.add_parser(
        "improve",
        help="Analyze a failed run and generate improvement suggestions",
    )
    bci_improve_parser.add_argument("run_id", help="The run ID to analyze")
    bci_improve_parser.add_argument(
        "--provider",
        choices=["openai", "anthropic", "openrouter", "ollama", "together", "groq", "fireworks", "test"],
        help="LLM provider (default: from environment)",
    )
    bci_improve_parser.add_argument("--model", help="Model name (default: provider default)")
    bci_improve_parser.add_argument("--max-behaviors", type=int, default=10, help="Max behaviors to extract")
    bci_improve_parser.add_argument("--output", "-o", help="Output file path (default: stdout)")

    # ── Audit log commands ──────────────────────────────────────────────────────
    audit_parser = subparsers.add_parser(
        "audit",
        help="Audit log WORM storage commands",
    )
    audit_subparsers = audit_parser.add_subparsers(dest="audit_command")

    # audit verify
    audit_verify_parser = audit_subparsers.add_parser(
        "verify",
        help="Verify integrity of an archived audit batch",
    )
    audit_verify_parser.add_argument(
        "--batch-id",
        required=True,
        help="Batch ID to verify",
    )
    audit_verify_parser.add_argument(
        "--public-key",
        help="Path to public key file for signature verification (optional)",
    )
    audit_verify_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )

    # audit list
    audit_list_parser = audit_subparsers.add_parser(
        "list",
        help="List archived audit batches",
    )
    audit_list_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of batches to list (default: 100)",
    )
    audit_list_parser.add_argument(
        "--prefix",
        help="S3 key prefix to filter batches",
    )
    audit_list_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )

    # audit retention
    audit_retention_parser = audit_subparsers.add_parser(
        "retention",
        help="Check retention info for an archived batch",
    )
    audit_retention_parser.add_argument(
        "--batch-id",
        required=True,
        help="Batch ID to check retention for",
    )
    audit_retention_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )

    # ── Analytics commands ──────────────────────────────────────────────────────
    analytics_parser = subparsers.add_parser(
        "analytics",
        help="Analytics warehouse queries and cost optimization",
    )
    analytics_subparsers = analytics_parser.add_subparsers(dest="analytics_command")

    # analytics project
    analytics_project_parser = analytics_subparsers.add_parser(
        "project",
        help="Project raw telemetry data to analytics warehouse",
    )
    analytics_project_parser.add_argument(
        "--start-date",
        dest="start_date",
        help="Start date for projection (YYYY-MM-DD)",
    )
    analytics_project_parser.add_argument(
        "--end-date",
        dest="end_date",
        help="End date for projection (YYYY-MM-DD)",
    )
    analytics_project_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        default="summary",
        help="Output format",
    )

    # analytics kpi-summary
    analytics_kpi_parser = analytics_subparsers.add_parser(
        "kpi-summary",
        help="Query KPI summary from DuckDB analytics warehouse",
    )
    analytics_kpi_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_kpi_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_kpi_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics project-kpi
    analytics_project_kpi_parser = analytics_subparsers.add_parser(
        "project-kpi",
        help="Project telemetry events from JSONL file into KPI facts and summary",
    )
    analytics_project_kpi_parser.add_argument(
        "--input",
        dest="input_file",
        required=True,
        help="Path to JSONL file containing telemetry events",
    )
    analytics_project_kpi_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )
    analytics_project_kpi_parser.add_argument(
        "--facts-output",
        dest="facts_output",
        help="Optional path to write full projection JSON",
    )

    # analytics behavior-usage
    analytics_behavior_parser = analytics_subparsers.add_parser(
        "behavior-usage",
        help="Query behavior usage facts from analytics warehouse",
    )
    analytics_behavior_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_behavior_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_behavior_parser.add_argument("--limit", type=int, default=50, help="Max records to return")
    analytics_behavior_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics token-savings
    analytics_tokens_parser = analytics_subparsers.add_parser(
        "token-savings",
        help="Query token savings facts from analytics warehouse",
    )
    analytics_tokens_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_tokens_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_tokens_parser.add_argument("--limit", type=int, default=50, help="Max records to return")
    analytics_tokens_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics compliance-coverage
    analytics_compliance_parser = analytics_subparsers.add_parser(
        "compliance-coverage",
        help="Query compliance coverage facts from analytics warehouse",
    )
    analytics_compliance_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_compliance_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_compliance_parser.add_argument("--limit", type=int, default=50, help="Max records to return")
    analytics_compliance_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics cost-by-service
    analytics_cost_service_parser = analytics_subparsers.add_parser(
        "cost-by-service",
        help="Query cost breakdown by service from analytics warehouse",
    )
    analytics_cost_service_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_cost_service_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_cost_service_parser.add_argument("--service", dest="service_name", help="Filter by service name")
    analytics_cost_service_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics cost-per-run
    analytics_cost_run_parser = analytics_subparsers.add_parser(
        "cost-per-run",
        help="Query cost breakdown by run from analytics warehouse",
    )
    analytics_cost_run_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_cost_run_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_cost_run_parser.add_argument("--template", dest="template_id", help="Filter by template ID")
    analytics_cost_run_parser.add_argument("--limit", type=int, default=50, help="Max records to return")
    analytics_cost_run_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics roi-summary
    analytics_roi_parser = analytics_subparsers.add_parser(
        "roi-summary",
        help="Query ROI analysis summary from analytics warehouse",
    )
    analytics_roi_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics daily-costs
    analytics_daily_parser = analytics_subparsers.add_parser(
        "daily-costs",
        help="Query daily cost summary for budget tracking",
    )
    analytics_daily_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_daily_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_daily_parser.add_argument("--limit", type=int, default=30, help="Max records to return")
    analytics_daily_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics top-expensive
    analytics_expensive_parser = analytics_subparsers.add_parser(
        "top-expensive",
        help="Query top expensive workflows from analytics warehouse",
    )
    analytics_expensive_parser.add_argument("--limit", type=int, default=10, help="Number of workflows to return")
    analytics_expensive_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # ── Telemetry commands ──────────────────────────────────────────────────────
    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Emit telemetry events",
    )
    telemetry_subparsers = telemetry_parser.add_subparsers(dest="telemetry_command")

    telemetry_emit_parser = telemetry_subparsers.add_parser(
        "emit",
        help="Emit a telemetry event",
    )
    telemetry_emit_parser.add_argument("--event-type", dest="event_type", required=True, help="Event type")
    telemetry_emit_parser.add_argument("--payload", default="{}", help="JSON event payload")
    telemetry_emit_parser.add_argument("--actor-id", dest="actor_id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    telemetry_emit_parser.add_argument("--actor-role", dest="actor_role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    telemetry_emit_parser.add_argument("--actor-surface", dest="actor_surface", default="cli", help="Actor surface")
    telemetry_emit_parser.add_argument("--run-id", dest="run_id", help="Run ID")
    telemetry_emit_parser.add_argument("--action-id", dest="action_id", help="Action ID")
    telemetry_emit_parser.add_argument("--session-id", dest="session_id", help="Session ID")
    telemetry_emit_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")
    telemetry_emit_parser.add_argument("--sink", choices=("file", "kafka"), default="file", help="Telemetry sink type")
    telemetry_emit_parser.add_argument("--telemetry-path", dest="telemetry_path", help="Output file path for file sink")
    telemetry_emit_parser.add_argument("--kafka-servers", dest="kafka_servers", help="Kafka bootstrap servers (or use KAFKA_BOOTSTRAP_SERVERS env)")

    # telemetry query
    telemetry_query_parser = telemetry_subparsers.add_parser(
        "query",
        help="Query telemetry events with filters",
    )
    telemetry_query_parser.add_argument("--event-type", dest="event_type", help="Filter by event type")
    telemetry_query_parser.add_argument("--from", dest="start_date", help="Start date (ISO format or relative e.g. '7d')")
    telemetry_query_parser.add_argument("--to", dest="end_date", help="End date (ISO format)")
    telemetry_query_parser.add_argument("--run-id", dest="run_id", help="Filter by run ID")
    telemetry_query_parser.add_argument("--action-id", dest="action_id", help="Filter by action ID")
    telemetry_query_parser.add_argument("--session-id", dest="session_id", help="Filter by session ID")
    telemetry_query_parser.add_argument("--actor-surface", dest="actor_surface", help="Filter by actor surface")
    telemetry_query_parser.add_argument("--level", choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), help="Minimum log level")
    telemetry_query_parser.add_argument("--search", help="Full-text search in message")
    telemetry_query_parser.add_argument("--limit", type=int, default=100, help="Maximum events to return")
    telemetry_query_parser.add_argument("--offset", type=int, default=0, help="Pagination offset")
    telemetry_query_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # telemetry dashboard
    telemetry_dashboard_parser = telemetry_subparsers.add_parser(
        "dashboard",
        help="Display telemetry dashboard with KPIs and token accounting",
    )
    telemetry_dashboard_parser.add_argument("--run-id", dest="run_id", help="Drill down to specific run ID for token details")
    telemetry_dashboard_parser.add_argument("--from", dest="start_date", help="Start date for daily summary")
    telemetry_dashboard_parser.add_argument("--to", dest="end_date", help="End date for daily summary")
    telemetry_dashboard_parser.add_argument("--watch", action="store_true", help="Enable live refresh (5s interval)")
    telemetry_dashboard_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # ── Agents commands ─────────────────────────────────────────────────────────
    agents_parser = subparsers.add_parser(
        "agents",
        help="Agent management commands",
    )
    agents_subparsers = agents_parser.add_subparsers(dest="agents_command")

    # agents assign
    agents_assign_parser = agents_subparsers.add_parser(
        "assign",
        help="Assign an agent to a run",
    )
    agents_assign_parser.add_argument("--run-id", dest="run_id", help="Run ID to assign agent to")
    agents_assign_parser.add_argument("--agent-id", dest="agent_id", help="Explicit agent ID to assign")
    agents_assign_parser.add_argument("--stage", default="PLANNING", help="Assignment stage (default: PLANNING)")
    agents_assign_parser.add_argument("--context", help="JSON context for heuristic selection")
    agents_assign_parser.add_argument("--context-file", dest="context_file", help="Path to JSON file with context")
    agents_assign_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # agents status
    agents_status_parser = agents_subparsers.add_parser(
        "status",
        help="Get status of an agent assignment",
    )
    agents_status_parser.add_argument("--run-id", dest="run_id", help="Run ID to check status")
    agents_status_parser.add_argument("--assignment-id", dest="assignment_id", help="Assignment ID to check status")
    agents_status_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # agents switch
    agents_switch_parser = agents_subparsers.add_parser(
        "switch",
        help="Switch to a different agent",
    )
    agents_switch_parser.add_argument("assignment_id", help="Assignment ID to modify")
    agents_switch_parser.add_argument("--target-agent-id", dest="target_agent_id", required=True, help="Target agent ID")
    agents_switch_parser.add_argument("--reason", help="Reason for switch")
    agents_switch_parser.add_argument("--stage", help="New stage after switch")
    agents_switch_parser.add_argument("--allow-downgrade", dest="allow_downgrade", action="store_true", help="Allow switching to lower tier agent")
    agents_switch_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # ── Metrics commands ────────────────────────────────────────────────────────
    metrics_parser = subparsers.add_parser(
        "metrics",
        help="Query and export metrics",
    )
    metrics_subparsers = metrics_parser.add_subparsers(dest="metrics_command")

    metrics_summary_parser = metrics_subparsers.add_parser(
        "summary",
        help="Get metrics summary",
    )
    metrics_summary_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    metrics_export_parser = metrics_subparsers.add_parser(
        "export",
        help="Export metrics to file",
    )
    metrics_export_parser.add_argument("--output", "-o", required=True, help="Output file path")
    metrics_export_parser.add_argument("--format", choices=("json", "csv"), default="json", help="Export format")

    bandwidth_check_parser = subparsers.add_parser(
        "bandwidth-check",
        help="Check current bandwidth usage against environment limits",
    )
    bandwidth_check_parser.add_argument(
        "--environment",
        default="dev",
        help="Environment to check against (default: dev)",
    )

    # ── Reflection command ──────────────────────────────────────────────────────
    reflection_parser = subparsers.add_parser(
        "reflection",
        help="Analyze traces and propose reusable behavior candidates",
    )
    trace_input_group = reflection_parser.add_mutually_exclusive_group()
    trace_input_group.add_argument(
        "--trace",
        dest="trace_text",
        help="Trace text to analyze (chain-of-thought steps)",
    )
    trace_input_group.add_argument(
        "--trace-file",
        dest="trace_file",
        help="Path to file containing trace text",
    )
    reflection_parser.add_argument(
        "--trace-format",
        dest="trace_format",
        choices=["chain_of_thought", "structured", "free_form"],
        default="chain_of_thought",
        help="Format of the trace text (default: chain_of_thought)",
    )
    reflection_parser.add_argument(
        "--run-id",
        dest="run_id",
        help="Run ID to associate with reflection results",
    )
    reflection_parser.add_argument(
        "--min-score",
        dest="min_score",
        type=float,
        default=0.6,
        help="Minimum quality score for candidate behaviors (0.0-1.0, default: 0.6)",
    )
    reflection_parser.add_argument(
        "--max-candidates",
        dest="max_candidates",
        type=int,
        default=5,
        help="Maximum number of behavior candidates to return (default: 5)",
    )
    reflection_parser.add_argument(
        "--no-examples",
        dest="no_examples",
        action="store_true",
        help="Exclude examples from candidate output",
    )
    reflection_parser.add_argument(
        "--tags",
        nargs="+",
        help="Preferred tags to assign to candidates",
    )
    reflection_parser.add_argument(
        "--output",
        choices=["json", "table"],
        default="json",
        help="Output format (default: json)",
    )

    # ── Database migration commands ─────────────────────────────────────────────
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Apply PostgreSQL schema migrations",
    )
    migrate_subparsers = migrate_parser.add_subparsers(dest="migrate_command")

    migrate_apply_parser = migrate_subparsers.add_parser(
        "apply",
        help="Apply pending schema migrations",
    )
    migrate_apply_parser.add_argument(
        "--service",
        choices=["all", "reflection", "collaboration", "behavior", "workflow", "action", "run", "metrics", "compliance"],
        default="all",
        help="Service to migrate (default: all)",
    )
    migrate_apply_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which migrations would be applied without executing",
    )

    migrate_status_parser = migrate_subparsers.add_parser(
        "status",
        help="Check migration status for all services",
    )
    migrate_status_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        parser.exit(1)
    if args.command == "behaviors" and not getattr(args, "behaviors_command", None):
        behaviors_parser.print_help()
        parser.exit(1)
    if args.command == "compliance" and not getattr(args, "compliance_command", None):
        compliance_parser.print_help()
        parser.exit(1)
    if args.command == "workflow" and not getattr(args, "workflow_command", None):
        workflow_parser.print_help()
        parser.exit(1)
    if args.command == "agents" and not getattr(args, "agents_command", None):
        agents_parser.print_help()
        parser.exit(1)
    if args.command == "telemetry" and not getattr(args, "telemetry_command", None):
        telemetry_parser.print_help()
        parser.exit(1)
    if args.command == "analytics" and not getattr(args, "analytics_command", None):
        analytics_parser.print_help()
        parser.exit(1)
    if args.command == "bci" and not getattr(args, "bci_command", None):
        bci_parser.print_help()
        parser.exit(1)
    if args.command == "amprealize" and not getattr(args, "amprealize_command", None):
        amp_parser.print_help()
        parser.exit(1)
    if args.command == "audit" and not getattr(args, "audit_command", None):
        audit_parser.print_help()
        parser.exit(1)
    if args.command == "auth" and not getattr(args, "auth_command", None):
        auth_parser.print_help()
        parser.exit(1)
    if args.command == "migrate" and not getattr(args, "migrate_command", None):
        migrate_parser.print_help()
        parser.exit(1)
    return args


def _load_metadata(items: List[str], metadata_file: Optional[str]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}

    if metadata_file:
        path = Path(metadata_file).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"Metadata file not found: {path}")
        raw = path.read_text(encoding="utf-8")
        loaded = json.loads(raw) if raw.strip() else {}
        if not isinstance(loaded, dict):
            raise ValueError("Metadata file must contain a JSON object")
        metadata.update(loaded)

    for entry in items:
        if "=" not in entry:
            raise ValueError(f"Invalid metadata entry '{entry}'. Use KEY=VALUE format.")
        key, value = entry.split("=", 1)
        metadata[key] = value

    return metadata


def _load_agent_context(context_json: Optional[str], context_file: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load agent assignment context from direct JSON or a JSON file."""

    if context_json and context_file:
        raise ValueError("Provide either --context or --context-file, not both")

    payload: Any = None
    if context_file:
        payload = _load_json_file(context_file)
    elif context_json:
        try:
            payload = json.loads(context_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Context must be valid JSON") from exc

    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Context must be a JSON object")
    return payload


def _parse_embedding_arg(raw: Optional[str]) -> Optional[List[float]]:
    if raw is None or raw.strip() == "":
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return None
    try:
        return [float(part) for part in parts]
    except ValueError as exc:  # pragma: no cover - defensive validation
        raise ValueError("Embedding must contain numeric values") from exc


def _load_examples(path: Optional[str]) -> List[Dict[str, Any]]:
    if not path:
        return []
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise ValueError(f"Examples file not found: {file_path}")
    raw = file_path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Examples file must contain a JSON array")
    normalized: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each example must be an object with keys like title/body")
        normalized.append(dict(item))
    return normalized


def _render_actions_table(actions: List[Dict[str, Any]]) -> None:
    if not actions:
        print("No actions recorded yet.")
        return

    headers = ["Action ID", "Summary", "Artifact", "Replay"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for action in actions:
        row = [
            action["action_id"],
            action["summary"],
            action["artifact_path"],
            action.get("replay_status", "UNKNOWN"),
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_behaviors_table(entries: List[Dict[str, Any]]) -> None:
    if not entries:
        print("No behaviors found.")
        return

    headers = ["Behavior ID", "Name", "Status", "Latest", "Role", "Tags"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for entry in entries:
        behavior = entry["behavior"]
        active = entry.get("active_version") or {}
        row = [
            behavior["behavior_id"],
            behavior["name"],
            behavior.get("status", "UNKNOWN"),
            behavior.get("latest_version", "-"),
            active.get("role_focus", "-"),
            ", ".join(behavior.get("tags", [])) or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_behavior_search_results(results: List[Dict[str, Any]]) -> None:
    if not results:
        print("No behaviors matched the query.")
        return

    headers = ["Score", "Behavior ID", "Name", "Status", "Role", "Tags"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for result in results:
        behavior = result["behavior"]
        active = result.get("active_version") or {}
        row = [
            f"{result.get('score', 0.0):.2f}",
            behavior["behavior_id"],
            behavior["name"],
            behavior.get("status", "UNKNOWN"),
            active.get("role_focus", "-"),
            ", ".join(behavior.get("tags", [])) or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_behavior_detail(detail: Dict[str, Any]) -> None:
    behavior = detail.get("behavior", {})
    versions = detail.get("versions", [])

    print(f"Behavior: {behavior.get('name', 'unknown')} ({behavior.get('behavior_id', '-')})")
    print(f"Status: {behavior.get('status', '-')}, Latest: {behavior.get('latest_version', '-')}")
    print(f"Tags: {', '.join(behavior.get('tags', [])) or '-'}")
    print(f"Created: {behavior.get('created_at', '-')}, Updated: {behavior.get('updated_at', '-')}")
    print()
    if not versions:
        print("No versions available.")
        return

    headers = ["Version", "Status", "Role", "Effective From", "Effective To"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []
    for version in versions:
        row = [
            version.get("version", "-"),
            version.get("status", "-"),
            version.get("role_focus", "-"),
            version.get("effective_from", "-"),
            version.get("effective_to", "-") or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _command_behaviors_create(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        metadata = _load_metadata(args.metadata_items or [], args.metadata_file)
        examples = _load_examples(args.examples_file)
        embedding = _parse_embedding_arg(args.embedding)
        result = adapter.create(
            name=args.name,
            description=args.description,
            instruction=args.instruction,
            role_focus=args.role_focus,
            trigger_keywords=args.keywords or [],
            tags=args.tags or [],
            metadata=metadata,
            examples=examples,
            embedding=embedding,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:  # pragma: no cover - CLI surface area
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_list(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        results = adapter.list(
            status=args.status,
            tags=args.tags or None,
            role_focus=args.role_focus,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(results)
    else:
        _render_behaviors_table(results)
    return 0


def _command_behaviors_search(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        results = adapter.search(
            query=args.query,
            tags=args.tags or None,
            role_focus=args.role_focus,
            status=args.status,
            limit=args.limit,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(results)
    else:
        _render_behavior_search_results(results)
    return 0


def _command_behaviors_get(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        result = adapter.get(args.behavior_id, args.version)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
                             _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_update(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        metadata = None
        if args.metadata_items or args.metadata_file:
            metadata = _load_metadata(args.metadata_items or [], args.metadata_file)
        examples = None
        if args.examples_file:
            examples = _load_examples(args.examples_file)
        embedding = _parse_embedding_arg(args.embedding) if args.embedding is not None else None
        result = adapter.update(
            behavior_id=args.behavior_id,
            version=args.version,
            instruction=args.instruction,
            description=args.description,
            trigger_keywords=args.keywords,
            tags=args.tags,
            metadata=metadata,
            examples=examples,
            embedding=embedding,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_submit(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        result = adapter.submit(
            args.behavior_id,
            args.version,
            args.actor_id,
            args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_approve(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        result = adapter.approve(
            behavior_id=args.behavior_id,
            version=args.version,
            effective_from=args.effective_from,
            approval_action_id=args.approval_action_id,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_deprecate(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        result = adapter.deprecate(
            behavior_id=args.behavior_id,
            version=args.version,
            effective_to=args.effective_to,
            successor_behavior_id=args.successor_behavior_id,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_delete_draft(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        adapter.delete_draft(args.behavior_id, args.version, args.actor_id, args.actor_role)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "format", None) == "json":
        _print_json({"status": "deleted", "behavior_id": args.behavior_id, "version": args.version})
    else:
        print(f"Deleted draft version {args.version} for behavior {args.behavior_id}")
    return 0


def _render_replay_table(payload: Dict[str, Any]) -> None:
    headers = ["Replay ID", "Status", "Progress", "Failed Count"]
    progress = f"{payload.get('progress', 0):.2f}"
    failed = payload.get("failed_action_ids", [])
    row = [payload.get("replay_id", "?"), payload.get("status", "UNKNOWN"), progress, str(len(failed))]
    widths = [max(len(header), len(value)) for header, value in zip(headers, row)]
    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    print(fmt.format(*row))


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


def _serialize_model(payload: Any) -> Any:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    if isinstance(payload, list):
        return [_serialize_model(item) for item in payload]
    if isinstance(payload, dict):
        return {key: _serialize_model(value) for key, value in payload.items()}
    return payload


def _ensure_amprealize_snapshot_dir() -> Path:
    AMPREALIZE_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return AMPREALIZE_SNAPSHOT_DIR


def _save_amprealize_snapshot(command: str, payload: Any) -> Path:
    directory = _ensure_amprealize_snapshot_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{timestamp}-{command}.json"
    path = directory / filename
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def _notify_snapshot_location(path: Path) -> None:
    print(f"[amprealize] Snapshot saved to {path}", file=sys.stderr)


def _resolve_output_format(preferred: Optional[str]) -> str:
    if preferred:
        return preferred
    return "summary" if sys.stdout.isatty() else "json"


def _render_amprealize_plan_summary(resp: Dict[str, Any], snapshot_path: Path) -> None:
    manifest = resp.get("signed_manifest") or {}
    services = manifest.get("services") or {}
    service_names = list(services.keys())
    estimates = resp.get("environment_estimates") or {}
    modules: Dict[str, int] = {}
    for spec in services.values():
        module = spec.get("module") or "default"
        modules[module] = modules.get(module, 0) + 1

    print("Amprealize Plan ready")
    print(f"  Plan ID      : {resp.get('plan_id', 'unknown')}")
    print(f"  Run ID       : {resp.get('amp_run_id', 'unknown')}")
    if manifest.get("blueprint_id"):
        print(f"  Blueprint    : {manifest['blueprint_id']}")
    if service_names:
        print(f"  Services     : {len(service_names)} ({', '.join(service_names[:5])}{'…' if len(service_names) > 5 else ''})")
    if modules:
        module_parts = [f"{name}×{count}" for name, count in sorted(modules.items())]
        print(f"  Modules      : {', '.join(module_parts)}")
    if estimates:
        print("  Estimates    :")
        cost = estimates.get("cost_estimate")
        boot = estimates.get("expected_boot_duration_s")
        memory = estimates.get("memory_footprint_mb")
        bandwidth = estimates.get("bandwidth_mbps")
        print(f"    • Cost          : ${cost:.2f}" if isinstance(cost, (int, float)) else f"    • Cost          : {cost}")
        if memory is not None:
            print(f"    • Memory        : {memory} MB")
        if bandwidth is not None:
            print(f"    • Bandwidth     : {bandwidth} Mbps")
        if boot is not None:
            print(f"    • Boot Duration : {boot}s")
        if estimates.get("region"):
            print(f"    • Region        : {estimates['region']}")
    print(f"  Snapshot     : {snapshot_path}")


def _render_amprealize_apply_summary(resp: Dict[str, Any], snapshot_path: Path, *, watched: bool) -> None:
    heading = "Amprealize Apply results" if watched else "Amprealize Apply requested"
    print(heading)
    print(f"  Run ID       : {resp.get('amp_run_id', 'unknown')}")
    if resp.get("action_id"):
        print(f"  Action ID    : {resp['action_id']}")
    outputs = resp.get("environment_outputs") or {}
    if outputs:
        keys = ", ".join(list(outputs.keys())[:5])
        print(f"  Env Outputs  : {keys}{'…' if len(outputs) > 5 else ''}")
    if resp.get("status_stream_url"):
        print(f"  Status Stream: {resp['status_stream_url']}")
    print(f"  Snapshot     : {snapshot_path}")


def _render_amprealize_status_summary(status: Dict[str, Any], snapshot_path: Path, *, include_events: int = 0) -> None:
    print("Amprealize Status")
    print(f"  Run ID       : {status.get('amp_run_id', 'unknown')}")
    print(f"  Phase        : {status.get('phase', 'UNKNOWN')}")
    progress = status.get("progress_pct")
    if progress is not None:
        print(f"  Progress     : {progress}%")
    checks = status.get("checks") or []
    if checks:
        print("  Health Checks:")
        for check in checks:
            print(f"    • {check.get('name', 'unknown')}: {check.get('status', 'UNKNOWN')} (last probe {check.get('last_probe', 'n/a')})")
    telemetry = status.get("telemetry") or {}
    if telemetry:
        print("  Telemetry    :")
        for key, value in telemetry.items():
            print(f"    • {key.replace('_', ' ').title()}: {value}")
    if include_events:
        print(f"  Events       : {include_events} captured")
    if status.get("environment_outputs_path"):
        print(f"  Outputs File : {status['environment_outputs_path']}")
    print(f"  Snapshot     : {snapshot_path}")


def _render_amprealize_destroy_summary(resp: Dict[str, Any], snapshot_path: Path) -> None:
    print("Amprealize Destroy")
    print(f"  Action ID    : {resp.get('action_id', 'unknown')}")
    report = resp.get("teardown_report") or []
    if report:
        print("  Resources    :")
        for line in report[:10]:
            print(f"    • {line}")
        if len(report) > 10:
            print(f"    • … {len(report) - 10} additional entries")
    print(f"  Snapshot     : {snapshot_path}")


def _render_amprealize_event(event: Dict[str, Any]) -> None:
    timestamp = event.get("timestamp", "?")
    status = event.get("status", "UNKNOWN")
    message = event.get("message", "")
    print(f"[{timestamp}] {status:<12} {message}")
    details = event.get("details")
    if details:
        print(f"    {json.dumps(details, sort_keys=True, default=_json_default)}")


def _render_tasks_table(tasks: List[Dict[str, Any]]) -> None:
    if not tasks:
        print("No tasks matched the provided filters.")
        return

    headers = ["Task", "Milestone", "Function", "Agent"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for task in tasks:
        row = [
            task.get("title", "?"),
            task.get("milestone", "?"),
            task.get("function", "?"),
            task.get("primary_agent", "?"),
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_checklist_table(checklists: List[Dict[str, Any]]) -> None:
    if not checklists:
        print("No checklists found.")
        return

    headers = ["Checklist ID", "Title", "Milestone", "Coverage"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for checklist in checklists:
        row = [
            checklist["checklist_id"][:8],
            checklist["title"],
            checklist.get("milestone", "-"),
            f"{checklist['coverage_score']:.1%}",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_step_table(steps: List[Dict[str, Any]]) -> None:
    if not steps:
        print("No steps found.")
        return

    headers = ["Step ID", "Title", "Status"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for step in steps:
        row = [
            step["step_id"][:8],
            step["title"],
            step["status"],
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_validation_table(result: Dict[str, Any]) -> None:
    headers = ["Checklist ID", "Valid", "Coverage", "Failed", "Missing"]
    row = [
        result["checklist_id"][:8],
        "✅" if result["valid"] else "❌",
        f"{result['coverage_score']:.1%}",
        str(len(result.get("failed_steps", []))),
        str(len(result.get("missing_steps", []))),
    ]
    widths = [max(len(header), len(value)) for header, value in zip(headers, row)]
    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    print(fmt.format(*row))

    if result.get("warnings"):
        print("\nWarnings:")
        for warning in result["warnings"]:
            print(f"  - {warning}")
    if result.get("failed_steps"):
        print("\nFailed Steps:")
        for step in result["failed_steps"]:
            print(f"  - {step}")
    if result.get("missing_steps"):
        print("\nMissing Steps:")
        for step in result["missing_steps"]:
            print(f"  - {step}")


def _command_record_action(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    try:
        metadata = _load_metadata(args.metadata_items or [], args.metadata_file)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    action = adapter.record_action(
        artifact_path=args.artifact_path,
        summary=args.summary,
        behaviors_cited=args.behaviors,
        metadata=metadata,
        actor_id=args.actor_id,
        actor_role=args.actor_role,
        checksum=args.checksum,
        related_run_id=args.related_run_id,
        audit_log_event_id=args.audit_log_event_id,
    )

    if args.format == "table":
        _render_actions_table([action])
    else:
        _print_json(action)
    return 0


def _command_list_actions(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    actions = adapter.list_actions()
    if args.format == "table":
        _render_actions_table(actions)
    else:
        _print_json(actions)
    return 0


def _command_get_action(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    try:
        action = adapter.get_action(args.action_id)
    except Exception as exc:  # pragma: no cover - delegating to caller message
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.format == "table":
        _render_actions_table([action])
    else:
        _print_json(action)
    return 0


def _command_replay_actions(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    try:
        replay = adapter.replay_actions(
            action_ids=list(args.action_ids),
            actor_id=args.actor_id,
            actor_role=args.actor_role,
            strategy=args.strategy,
            skip_existing=args.skip_existing,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_replay_table(replay)
    else:
        _print_json(replay)
    return 0


def _command_replay_status(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    try:
        replay = adapter.get_replay_status(args.replay_id)
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_replay_table(replay)
    else:
        _print_json(replay)
    return 0


def _command_dr(args: argparse.Namespace) -> int:
    """Delegate 'guideai dr' subcommands to the Click-based DR CLI."""

    try:
        from guideai import cli_dr
    except ImportError as exc:  # pragma: no cover - import guard
        print(f"Error: DR commands unavailable ({exc})", file=sys.stderr)
        return 1

    forwarded_args = list(args.dr_args or [])

    try:
        result = cli_dr.dr_group.main(
            args=forwarded_args,
            prog_name="guideai dr",
            standalone_mode=False,
        )
    except SystemExit as exc:  # Click uses SystemExit for return codes
        return int(exc.code or 0)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"DR command failed: {exc}", file=sys.stderr)
        return 1

    return int(result or 0)


def _command_list_tasks(args: argparse.Namespace) -> int:
    adapter = _get_task_adapter()
    try:
        tasks = adapter.list_assignments(function=args.function)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.format == "table":
        _render_tasks_table(tasks)
    else:
        _print_json(tasks)
    return 0


def _command_telemetry_emit(args: argparse.Namespace) -> int:
    try:
        payload_raw = args.payload or "{}"
        payload_obj = json.loads(payload_raw)
        if not isinstance(payload_obj, dict):
            raise ValueError("Payload must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    surface = args.actor_surface.replace("-", "_").lower()
    actor = {
        "id": args.actor_id,
        "role": args.actor_role,
        "surface": surface,
    }

    # Determine sink based on --sink argument
    sink_type = getattr(args, "sink", "file")

    if sink_type == "kafka":
        # Kafka sink requires bootstrap servers
        kafka_servers = getattr(args, "kafka_servers", None) or os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
        if not kafka_servers:
            print("Error: Kafka sink requires --kafka-servers or KAFKA_BOOTSTRAP_SERVERS environment variable", file=sys.stderr)
            return 2

        kafka_topic = os.environ.get("KAFKA_TOPIC_TELEMETRY_EVENTS", "telemetry.events")
        sink = KafkaTelemetrySink(bootstrap_servers=kafka_servers, topic=kafka_topic)
    else:
        # File sink
        telemetry_path = getattr(args, "telemetry_path", None)
        if telemetry_path:
            sink = FileTelemetrySink(path=Path(telemetry_path))
        else:
            # Use default from environment or in-memory fallback
            sink = create_sink_from_env()

    telemetry = TelemetryClient(sink=sink, default_actor=actor)

    event = telemetry.emit_event(
        event_type=args.event_type,
        payload=payload_obj,
        actor=actor,
        run_id=args.run_id,
        action_id=args.action_id,
        session_id=args.session_id,
    )

    # For file sink with custom path, output JSON for test validation
    if sink_type == "file" and getattr(args, "telemetry_path", None):
        print(json.dumps(event.to_dict(), indent=2))
    elif args.format == "json":
        print(json.dumps(event.to_dict(), indent=2))
    else:
        print(
            f"{event.timestamp} {event.event_type} actor={event.actor['id']} surface={event.actor['surface']}"
        )
    return 0


def _parse_relative_date(date_str: str) -> datetime:
    """Parse relative date strings like '7d', '24h', '30m' or ISO dates."""
    if not date_str:
        return datetime.now(timezone.utc)

    # Try relative format first (e.g., "7d", "24h", "30m")
    relative_pattern = r"^(\d+)([dhms])$"
    import re
    match = re.match(relative_pattern, date_str.lower())
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        delta_map = {"d": timedelta(days=value), "h": timedelta(hours=value),
                     "m": timedelta(minutes=value), "s": timedelta(seconds=value)}
        return datetime.now(timezone.utc) - delta_map[unit]

    # Try ISO format
    try:
        # Handle date-only format
        if len(date_str) == 10:
            return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use ISO format or relative (e.g., 7d, 24h, 30m)")


def _command_telemetry_query(args: argparse.Namespace) -> int:
    """Query telemetry logs using RazeService."""
    try:
        from raze import RazeService
        from raze.sinks import InMemorySink
    except ImportError:
        # Try TimescaleDB sink if available
        try:
            from raze import RazeService
            from raze.sinks import TimescaleDBSink
        except ImportError:
            print("Error: Raze package not installed. Install with: pip install raze", file=sys.stderr)
            return 1

    # Parse date range
    try:
        start_time = _parse_relative_date(args.from_date) if args.from_date else datetime.now(timezone.utc) - timedelta(days=7)
        end_time = _parse_relative_date(args.to_date) if args.to_date else datetime.now(timezone.utc)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Build query params
    query_params = {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "limit": args.limit,
        "offset": args.offset,
    }

    # Add optional filters
    if args.event_type:
        query_params["event_type"] = args.event_type
    if args.run_id:
        query_params["run_id"] = args.run_id
    if args.action_id:
        query_params["action_id"] = args.action_id
    if args.session_id:
        query_params["session_id"] = args.session_id
    if args.actor_surface:
        query_params["actor_surface"] = args.actor_surface.replace("-", "_").lower()
    if args.level:
        query_params["level"] = args.level.upper()
    if args.search:
        query_params["search"] = args.search

    # Initialize RazeService - try TimescaleDB first, fall back to file-based
    try:
        import os
        dsn = os.environ.get("RAZE_DSN") or os.environ.get("TIMESCALEDB_DSN")
        if dsn:
            from raze.sinks import TimescaleDBSink
            sink = TimescaleDBSink(dsn=dsn)
        else:
            # Fall back to JSONL file if available
            log_path = Path(os.environ.get("RAZE_LOG_PATH", ".guideai/logs/raze.jsonl"))
            if log_path.exists():
                from raze.sinks import JSONLSink
                sink = JSONLSink(path=str(log_path))
            else:
                from raze.sinks import InMemorySink
                sink = InMemorySink()

        service = RazeService(sink=sink)
        result = service.query(**query_params)
        logs = result.logs if hasattr(result, 'logs') else result
    except Exception as exc:
        print(f"Error querying logs: {exc}", file=sys.stderr)
        return 1

    # Output results
    if args.format == "json":
        output = {
            "query": query_params,
            "count": len(logs) if isinstance(logs, list) else 0,
            "logs": [log.to_dict() if hasattr(log, 'to_dict') else log for log in logs] if logs else [],
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        if not logs:
            print("No logs found matching query.")
            return 0

        print(f"\nTelemetry Logs ({len(logs)} results)")
        print("=" * 100)
        print(f"{'Timestamp':<25} {'Level':<8} {'Service':<15} {'Message':<50}")
        print("-" * 100)
        for log in logs[:args.limit]:
            log_dict = log.to_dict() if hasattr(log, 'to_dict') else log
            ts = str(log_dict.get('timestamp', 'N/A'))[:24]
            level = log_dict.get('level', 'INFO')[:7]
            service = log_dict.get('service', 'unknown')[:14]
            msg = log_dict.get('message', '')[:49]
            print(f"{ts:<25} {level:<8} {service:<15} {msg:<50}")

        if len(logs) > args.limit:
            print(f"\n... and {len(logs) - args.limit} more (use --limit to see more)")

    return 0


def _command_telemetry_dashboard(args: argparse.Namespace) -> int:
    """Display telemetry dashboard with KPIs and token accounting."""
    from .analytics.warehouse import AnalyticsWarehouse

    # Parse date range
    try:
        start_date = args.from_date if args.from_date else (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = args.to_date if args.to_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    def _fetch_and_display():
        """Fetch dashboard data and display it."""
        warehouse = AnalyticsWarehouse()

        # If specific run_id provided, show drill-down view
        if args.run_id:
            return _display_run_drilldown(warehouse, args.run_id, args.format)

        # Otherwise show summary dashboard
        try:
            kpi_summary = warehouse.get_kpi_summary(start_date=start_date, end_date=end_date)
            token_savings = warehouse.get_token_savings(start_date=start_date, end_date=end_date, limit=10)
            daily_costs = warehouse.get_daily_cost_summary(start_date=start_date, end_date=end_date)
        except Exception as exc:
            print(f"Error querying warehouse: {exc}", file=sys.stderr)
            return 1

        if args.format == "json":
            output = {
                "period": {"start": start_date, "end": end_date},
                "kpi_summary": kpi_summary,
                "token_savings": token_savings,
                "daily_costs": daily_costs,
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            _display_dashboard_table(kpi_summary, token_savings, daily_costs, start_date, end_date)

        return 0

    # Watch mode with 5-second polling
    if args.watch:
        try:
            print("Dashboard watch mode (Ctrl+C to exit, refreshes every 5s)")
            print()
            while True:
                # Clear screen for fresh display
                print("\033[2J\033[H", end="")
                print(f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
                print()
                result = _fetch_and_display()
                if result != 0:
                    return result
                import time
                time.sleep(5)
        except KeyboardInterrupt:
            print("\nWatch mode stopped.")
            return 0
    else:
        return _fetch_and_display()


def _display_run_drilldown(warehouse, run_id: str, fmt: str) -> int:
    """Display detailed token accounting for a specific run."""
    try:
        # Get run-specific data
        token_data = warehouse.get_token_savings(run_id=run_id, limit=1)
        cost_data = warehouse.get_cost_per_run(run_id=run_id)
    except Exception as exc:
        print(f"Error querying run details: {exc}", file=sys.stderr)
        return 1

    if fmt == "json":
        output = {
            "run_id": run_id,
            "token_savings": token_data,
            "cost_breakdown": cost_data,
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print(f"\nRun Detail: {run_id}")
        print("=" * 80)

        if token_data:
            record = token_data[0] if token_data else {}
            print("\nToken Accounting")
            print("-" * 40)
            print(f"  Baseline Tokens:  {record.get('baseline_tokens', 0):>12,}")
            print(f"  Actual Tokens:    {record.get('actual_tokens', 0):>12,}")
            print(f"  Tokens Saved:     {record.get('tokens_saved', 0):>12,}")
            print(f"  Savings Rate:     {record.get('savings_rate_pct', 0):>11.1f}%")
        else:
            print("\nNo token data found for this run.")

        if cost_data:
            print("\nCost Breakdown")
            print("-" * 40)
            for item in cost_data:
                service = item.get('service', 'unknown')
                cost = item.get('cost_usd', 0)
                print(f"  {service:<20} ${cost:>10.4f}")
        else:
            print("\nNo cost data found for this run.")

    return 0


def _display_dashboard_table(kpi_summary, token_savings, daily_costs, start_date, end_date):
    """Display formatted dashboard tables."""
    print(f"\n📊 Telemetry Dashboard ({start_date} to {end_date})")
    print("=" * 80)

    # KPI Summary Section
    print("\n📈 KPI Summary")
    print("-" * 40)
    if kpi_summary:
        latest = kpi_summary[-1] if kpi_summary else {}
        print(f"  Behavior Reuse Rate:   {latest.get('reuse_rate_pct', 0):>6.1f}% (Target: 70%)")
        print(f"  Token Savings Rate:    {latest.get('avg_savings_rate_pct', 0):>6.1f}% (Target: 30%)")
        print(f"  Task Completion Rate:  {latest.get('completion_rate_pct', 0):>6.1f}% (Target: 80%)")
        print(f"  Compliance Coverage:   {latest.get('avg_coverage_rate_pct', 0):>6.1f}% (Target: 95%)")
    else:
        print("  No KPI data available for this period.")

    # Token Savings Section
    print("\n💰 Token Savings (Top 10 Runs)")
    print("-" * 70)
    if token_savings:
        print(f"  {'Run ID':<36} {'Saved':>12} {'Rate':>8}")
        print(f"  {'-'*36} {'-'*12} {'-'*8}")
        total_saved = 0
        for record in token_savings[:10]:
            run_id = record.get('run_id', 'N/A')[:35]
            saved = record.get('tokens_saved', 0)
            rate = record.get('savings_rate_pct', 0)
            total_saved += saved
            print(f"  {run_id:<36} {saved:>12,} {rate:>7.1f}%")
        print(f"  {'Total':<36} {total_saved:>12,}")
    else:
        print("  No token savings data available for this period.")

    # Daily Costs Section
    print("\n📅 Daily Cost Summary")
    print("-" * 50)
    if daily_costs:
        print(f"  {'Date':<12} {'Runs':>8} {'Cost (USD)':>12}")
        print(f"  {'-'*12} {'-'*8} {'-'*12}")
        total_cost = 0
        for record in daily_costs:
            day = record.get('summary_date', 'N/A')[:10]
            runs = record.get('total_runs', 0)
            cost = record.get('total_cost_usd', 0)
            total_cost += cost
            print(f"  {day:<12} {runs:>8} ${cost:>11.2f}")
        print(f"  {'Total':<12} {'':<8} ${total_cost:>11.2f}")
    else:
        print("  No cost data available for this period.")

    print()


def _load_telemetry_events(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {index}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Event on line {index} must be a JSON object")
            events.append(payload)
    return events


def _projection_to_dict(projection: TelemetryProjection) -> Dict[str, Any]:
    return {
        "summary": projection.summary,
        "fact_behavior_usage": projection.fact_behavior_usage,
        "fact_token_savings": projection.fact_token_savings,
        "fact_execution_status": projection.fact_execution_status,
        "fact_compliance_steps": projection.fact_compliance_steps,
    }


def _render_projection_table(projection: TelemetryProjection) -> None:
    summary = projection.summary or {}

    def _fmt(value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    rows = [
        ("Total runs", summary.get("total_runs")),
        ("Runs with behaviors", summary.get("runs_with_behaviors")),
        ("Behavior reuse %", summary.get("behavior_reuse_pct")),
        ("Average token savings %", summary.get("average_token_savings_pct")),
        ("Completed runs", summary.get("completed_runs")),
        ("Terminal runs", summary.get("terminal_runs")),
        ("Task completion rate %", summary.get("task_completion_rate_pct")),
        ("Compliance coverage %", summary.get("average_compliance_coverage_pct")),
    ]

    label_width = max(len(label) for label, _ in rows)
    print("PRD KPI Summary")
    print("-" * (label_width + 20))
    for label, value in rows:
        print(f"{label:<{label_width}} : {_fmt(value)}")

    fact_rows = [
        ("fact_behavior_usage", len(projection.fact_behavior_usage)),
        ("fact_token_savings", len(projection.fact_token_savings)),
        ("fact_execution_status", len(projection.fact_execution_status)),
        ("fact_compliance_steps", len(projection.fact_compliance_steps)),
    ]

    fact_width = max(len(label) for label, _ in fact_rows)
    print()
    print("Fact row counts")
    print("-" * (fact_width + 12))
    for label, count in fact_rows:
        print(f"{label:<{fact_width}} : {count}")


# ── Agents command handlers ─────────────────────────────────────────────────────

_agent_orchestrator_service: Optional[AgentOrchestratorService] = None


def _get_agent_orchestrator_adapter() -> CLIAgentOrchestratorAdapter:
    """Get or create an AgentOrchestratorService adapter."""
    global _agent_orchestrator_service
    if _agent_orchestrator_service is None:
        _agent_orchestrator_service = AgentOrchestratorService()
    return CLIAgentOrchestratorAdapter(_agent_orchestrator_service)


def _command_agents_assign(args: argparse.Namespace) -> int:
    """Assign an agent to a run."""
    adapter = _get_agent_orchestrator_adapter()

    # Parse context from --context or --context-file
    context: Optional[Dict[str, Any]] = None
    if args.context:
        try:
            context = json.loads(args.context)
        except json.JSONDecodeError as exc:
            print(f"Error: Invalid JSON in --context: {exc}", file=sys.stderr)
            return 1
    elif args.context_file:
        context_path = Path(args.context_file).expanduser().resolve()
        if not context_path.exists():
            print(f"Error: Context file not found: {context_path}", file=sys.stderr)
            return 1
        try:
            context = json.loads(context_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Error: Invalid JSON in context file: {exc}", file=sys.stderr)
            return 1

    requested_by = {
        "actor_id": "cli-user",
        "actor_role": "STRATEGIST",
        "actor_surface": "cli",
    }

    try:
        result = adapter.assign_agent(
            run_id=args.run_id,
            requested_agent_id=getattr(args, "agent_id", None),
            stage=args.stage,
            context=context,
            requested_by=requested_by,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _render_agent_assignment_table(result)
    return 0


def _command_agents_status(args: argparse.Namespace) -> int:
    """Get status of an agent assignment."""
    if not args.run_id and not args.assignment_id:
        print("Error: Provide --assignment-id or --run-id to lookup status", file=sys.stderr)
        return 2

    adapter = _get_agent_orchestrator_adapter()

    try:
        result = adapter.get_status(
            run_id=args.run_id,
            assignment_id=args.assignment_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result is None:
        print("Error: Assignment not found", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _render_agent_assignment_table(result)
    return 0


def _command_agents_switch(args: argparse.Namespace) -> int:
    """Switch to a different agent."""
    adapter = _get_agent_orchestrator_adapter()

    issued_by = {
        "actor_id": "cli-user",
        "actor_role": "STRATEGIST",
        "actor_surface": "cli",
    }

    try:
        result = adapter.switch_agent(
            assignment_id=args.assignment_id,
            target_agent_id=args.target_agent_id,
            reason=getattr(args, "reason", None),
            allow_downgrade=getattr(args, "allow_downgrade", False),
            stage=getattr(args, "stage", None),
            issued_by=issued_by,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _render_agent_assignment_table(result)
    return 0


def _render_agent_assignment_table(assignment: Dict[str, Any]) -> None:
    """Render an agent assignment as a formatted table."""
    print("\n📋 Agent Assignment")
    print("=" * 60)
    print(f"  Assignment ID:  {assignment.get('assignment_id', 'N/A')}")
    print(f"  Run ID:         {assignment.get('run_id', 'N/A')}")
    print(f"  Stage:          {assignment.get('stage', 'N/A')}")
    print(f"  Timestamp:      {assignment.get('timestamp', 'N/A')}")

    active_agent = assignment.get("active_agent", {})
    print(f"\n🤖 Active Agent")
    print("-" * 60)
    print(f"  Agent ID:       {active_agent.get('agent_id', 'N/A')}")
    print(f"  Display Name:   {active_agent.get('display_name', 'N/A')}")
    print(f"  Tier:           {active_agent.get('tier', 'N/A')}")

    heuristics = assignment.get("heuristics_applied", {})
    if heuristics:
        print(f"\n📊 Heuristics Applied")
        print("-" * 60)
        print(f"  Selected Agent: {heuristics.get('selected_agent_id', 'N/A')}")
        print(f"  Requested:      {heuristics.get('requested_agent_id', 'N/A')}")
        print(f"  Task Type:      {heuristics.get('task_type', 'N/A')}")
        print(f"  Severity:       {heuristics.get('severity', 'N/A')}")

    history = assignment.get("history", [])
    if history:
        print(f"\n📜 History ({len(history)} event(s))")
        print("-" * 60)
        for event in history:
            print(f"  • {event.get('from_agent_id', 'N/A')} → {event.get('to_agent_id', 'N/A')}")
            print(f"    Trigger: {event.get('trigger', 'N/A')}")
            trigger_details = event.get("trigger_details", {})
            if trigger_details.get("reason"):
                print(f"    Reason: {trigger_details.get('reason')}")
    print()


def _command_analytics_project(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Error: Telemetry input not found: {input_path}", file=sys.stderr)
        return 2

    try:
        events = _load_telemetry_events(input_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    projector = TelemetryKPIProjector()
    projection = projector.project(events)

    if args.facts_output:
        output_path = Path(args.facts_output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_projection_to_dict(projection), indent=2)
        output_path.write_text(payload, encoding="utf-8")
        print(f"Projection JSON written to {output_path}", file=sys.stderr)

    if args.format == "json":
        print(json.dumps(_projection_to_dict(projection), indent=2))
    else:
        _render_projection_table(projection)
    return 0


def _command_analytics_kpi_summary(args: argparse.Namespace) -> int:
    """Query KPI summary from DuckDB analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_kpi_summary(
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No KPI summary records found.")
            return 0

        print("\nKPI Summary")
        print("=" * 80)
        for record in records:
            print(f"Period: {record.get('summary_date', 'N/A')}")
            print(f"  Behavior Reuse Rate: {record.get('reuse_rate_pct', 0):.1f}% (Target: 70%)")
            print(f"  Token Savings Rate: {record.get('avg_savings_rate_pct', 0):.1f}% (Target: 30%)")
            print(f"  Task Completion Rate: {record.get('completion_rate_pct', 0):.1f}% (Target: 80%)")
            print(f"  Compliance Coverage: {record.get('avg_coverage_rate_pct', 0):.1f}% (Target: 95%)")
            print()
    return 0


def _command_analytics_project_kpi(args: argparse.Namespace) -> int:
    """Project telemetry events from JSONL file into KPI facts and summary."""
    import dataclasses
    from pathlib import Path

    from .analytics.telemetry_kpi_projector import TelemetryKPIProjector

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Telemetry input not found: {input_path}", file=sys.stderr)
        return 2

    # Parse JSONL events
    events: list[dict] = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    # Project events to facts
    projector = TelemetryKPIProjector()
    projection = projector.project(events)

    # Convert projection to dict for serialization
    projection_dict = dataclasses.asdict(projection)

    # Write facts output if requested
    if args.facts_output:
        facts_path = Path(args.facts_output)
        facts_path.write_text(json.dumps(projection_dict, indent=2), encoding="utf-8")
        print(f"Projection JSON written to {facts_path}", file=sys.stderr)

    # Output format
    if args.format == "json":
        print(json.dumps(projection_dict, indent=2))
    else:
        summary = projection.summary
        print("\nPRD KPI Summary")
        print("=" * 80)
        print(f"  Total Runs: {summary.get('total_runs', 0)}")
        print(f"  Runs with Behaviors: {summary.get('runs_with_behaviors', 0)}")
        reuse_pct = summary.get('behavior_reuse_pct')
        print(f"  Behavior Reuse Rate: {reuse_pct:.1f}% (Target: 70%)" if reuse_pct is not None else "  Behavior Reuse Rate: N/A")
        savings_pct = summary.get('average_token_savings_pct')
        print(f"  Average Token Savings: {savings_pct:.1f}% (Target: 30%)" if savings_pct is not None else "  Average Token Savings: N/A")
        completion_pct = summary.get('task_completion_rate_pct')
        print(f"  Task Completion Rate: {completion_pct:.1f}% (Target: 80%)" if completion_pct is not None else "  Task Completion Rate: N/A")
        coverage_pct = summary.get('average_compliance_coverage_pct')
        print(f"  Compliance Coverage: {coverage_pct:.1f}% (Target: 95%)" if coverage_pct is not None else "  Compliance Coverage: N/A")
        print()
        print("Fact row counts:")
        print(f"  fact_behavior_usage: {len(projection.fact_behavior_usage)}")
        print(f"  fact_token_savings: {len(projection.fact_token_savings)}")
        print(f"  fact_execution_status: {len(projection.fact_execution_status)}")
        print(f"  fact_compliance_steps: {len(projection.fact_compliance_steps)}")
        print(f"  fact_resource_usage: {len(projection.fact_resource_usage)}")
        print(f"  fact_cost_allocation: {len(projection.fact_cost_allocation)}")

    return 0


def _command_analytics_behavior_usage(args: argparse.Namespace) -> int:
    """Query behavior usage facts from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_behavior_usage(
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No behavior usage records found.")
            return 0

        print(f"\nBehavior Usage (Top {len(records)})")
        print("=" * 80)
        print(f"{'Run ID':<40} {'Behaviors':>10} {'Timestamp':<20}")
        print("-" * 80)
        for record in records:
            run_id = record.get('run_id', 'N/A')[:38]
            behavior_count = record.get('behavior_count', 0)
            timestamp = record.get('timestamp', 'N/A')[:19]
            print(f"{run_id:<40} {behavior_count:>10} {timestamp:<20}")
        print(f"\nTotal: {len(records)} record(s)")
    return 0


def _command_analytics_token_savings(args: argparse.Namespace) -> int:
    """Query token savings facts from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_token_savings(
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No token savings records found.")
            return 0

        print(f"\nToken Savings (Top {len(records)})")
        print("=" * 80)
        print(f"{'Run ID':<40} {'Savings %':>12} {'Tokens Saved':>15}")
        print("-" * 80)
        for record in records:
            run_id = record.get('run_id', 'N/A')[:38]
            savings_pct = record.get('savings_rate_pct', 0)
            tokens_saved = record.get('tokens_saved', 0)
            print(f"{run_id:<40} {savings_pct:>11.1f}% {tokens_saved:>15,}")
        print(f"\nTotal: {len(records)} record(s)")
    return 0


def _command_analytics_compliance_coverage(args: argparse.Namespace) -> int:
    """Query compliance coverage facts from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_compliance_coverage(
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No compliance coverage records found.")
            return 0

        print(f"\nCompliance Coverage (Top {len(records)})")
        print("=" * 80)
        print(f"{'Checklist ID':<40} {'Coverage %':>12} {'Steps Done/Total':<20}")
        print("-" * 80)
        for record in records:
            checklist_id = record.get('checklist_id', 'N/A')[:38]
            coverage_pct = record.get('coverage_rate_pct', 0)
            steps_completed = record.get('steps_completed', 0)
            steps_total = record.get('steps_total', 0)
            print(f"{checklist_id:<40} {coverage_pct:>11.1f}% {steps_completed}/{steps_total:<15}")
        print(f"\nTotal: {len(records)} record(s)")
    return 0


def _command_analytics_cost_by_service(args: argparse.Namespace) -> int:
    """Query cost breakdown by service from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_cost_by_service(
            start_date=args.start_date,
            end_date=args.end_date,
            service_name=getattr(args, 'service_name', None),
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No cost records found.")
            return 0

        print("\nCost by Service")
        print("=" * 80)
        print(f"{'Service':<30} {'Total Cost':>15} {'Total Tokens':>15} {'Avg Cost/Run':>15}")
        print("-" * 80)
        total_cost = 0.0
        for record in records:
            service = record.get('service_name', 'N/A')[:28]
            cost = record.get('total_cost_usd', 0)
            tokens = record.get('total_tokens', 0)
            avg_cost = record.get('avg_cost_per_run', 0)
            total_cost += cost
            print(f"{service:<30} ${cost:>14.4f} {tokens:>15,} ${avg_cost:>14.4f}")
        print("-" * 80)
        print(f"{'TOTAL':<30} ${total_cost:>14.4f}")
    return 0


def _command_analytics_cost_per_run(args: argparse.Namespace) -> int:
    """Query cost breakdown per run from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_cost_per_run(
            start_date=args.start_date,
            end_date=args.end_date,
            template_id=getattr(args, 'template_id', None),
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No cost records found.")
            return 0

        print(f"\nCost per Run (Top {len(records)})")
        print("=" * 100)
        print(f"{'Run ID':<38} {'Template':<25} {'Cost':>12} {'Tokens':>12} {'Started':<15}")
        print("-" * 100)
        for record in records:
            run_id = record.get('run_id', 'N/A')[:36]
            template = (record.get('template_id') or 'N/A')[:23]
            cost = record.get('total_cost_usd', 0)
            tokens = record.get('total_tokens', 0)
            started = (record.get('started_at') or 'N/A')[:13]
            print(f"{run_id:<38} {template:<25} ${cost:>11.4f} {tokens:>12,} {started:<15}")
        print(f"\nTotal: {len(records)} record(s)")
    return 0


def _command_analytics_roi_summary(args: argparse.Namespace) -> int:
    """Query ROI analysis summary from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse
    from .config import get_settings

    settings = get_settings()
    warehouse = AnalyticsWarehouse()
    try:
        record = warehouse.get_roi_summary()
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"roi": record, "budget_threshold_usd": settings.cost.daily_budget_usd}, indent=2))
    else:
        if not record:
            print("No ROI data available.")
            return 0

        print("\nROI Analysis Summary")
        print("=" * 60)
        total_cost = record.get('total_cost_usd', 0)
        total_saved = record.get('total_tokens_saved', 0)
        cost_per_save = record.get('cost_per_token_saved', 0)
        efficiency = record.get('efficiency_score', 0)
        budget = settings.cost.daily_budget_usd

        print(f"  Total Cost (USD):        ${total_cost:,.4f}")
        print(f"  Total Tokens Saved:      {total_saved:,}")
        print(f"  Cost per Token Saved:    ${cost_per_save:.6f}")
        print(f"  Efficiency Score:        {efficiency:.2f}")
        print(f"  Daily Budget Threshold:  ${budget:.2f}")
        print()

        # Budget status indicator
        if total_cost > budget:
            print(f"  ⚠️  OVER BUDGET by ${total_cost - budget:.2f}")
        else:
            print(f"  ✅ Within budget (${budget - total_cost:.2f} remaining)")
    return 0


def _command_analytics_daily_costs(args: argparse.Namespace) -> int:
    """Query daily cost summary for budget tracking."""
    from .analytics.warehouse import AnalyticsWarehouse
    from .config import get_settings

    settings = get_settings()
    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_daily_cost_summary(
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    budget = settings.cost.daily_budget_usd

    if args.format == "json":
        print(json.dumps({
            "records": records,
            "count": len(records),
            "budget_threshold_usd": budget
        }, indent=2))
    else:
        if not records:
            print("No daily cost records found.")
            return 0

        print(f"\nDaily Cost Summary (Budget: ${budget:.2f}/day)")
        print("=" * 80)
        print(f"{'Date':<12} {'Daily Cost':>12} {'Total Tokens':>15} {'Runs':>8} {'Status':<10}")
        print("-" * 80)
        for record in records:
            date = str(record.get('cost_date', 'N/A'))[:10]
            cost = record.get('daily_cost_usd', 0)
            tokens = record.get('daily_tokens', 0)
            runs = record.get('run_count', 0)
            status = "⚠️ OVER" if cost > budget else "✅ OK"
            print(f"{date:<12} ${cost:>11.4f} {tokens:>15,} {runs:>8} {status:<10}")
        print(f"\nTotal: {len(records)} day(s)")
    return 0


def _command_analytics_top_expensive(args: argparse.Namespace) -> int:
    """Query top expensive workflows from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_top_expensive_workflows(limit=args.limit)
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No workflow cost records found.")
            return 0

        print(f"\nTop {len(records)} Expensive Workflows")
        print("=" * 90)
        print(f"{'Template ID':<35} {'Total Cost':>12} {'Total Tokens':>15} {'Avg Cost/Run':>15}")
        print("-" * 90)
        for record in records:
            template = (record.get('template_id') or 'ad-hoc')[:33]
            cost = record.get('total_cost_usd', 0)
            tokens = record.get('total_tokens', 0)
            avg = record.get('avg_cost_per_run', 0)
            print(f"{template:<35} ${cost:>11.4f} {tokens:>15,} ${avg:>14.4f}")
        print(f"\nTotal: {len(records)} workflow(s)")
    return 0


def _command_metrics_summary(args: argparse.Namespace) -> int:
    """Display real-time metrics summary with PRD KPI targets."""
    adapter = _get_metrics_adapter()



    use_cache = not args.no_cache
    try:
        result = adapter.get_summary(
            start_date=args.start_date,
            end_date=args.end_date,
            use_cache=use_cache,
        )
    except Exception as exc:
        print(f"Error retrieving metrics summary: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _render_metrics_summary_table(result)
    return 0


def _command_metrics_export(args: argparse.Namespace) -> int:
    """Export metrics data to file or stdout."""
    adapter = _get_metrics_adapter()

    try:
        result = adapter.export_metrics(
            format=args.export_format,
            start_date=args.start_date,
            end_date=args.end_date,
            metrics=args.metrics if args.metrics else None,
            include_raw_events=args.include_raw_events,
        )
    except Exception as exc:
        print(f"Error exporting metrics: {exc}", file=sys.stderr)
        return 1

    # Write exported data to file or stdout
    if args.output_file:
        output_path = Path(args.output_file).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if result.get("data"):
            # Inline data export
            if args.export_format == "json":
                output_path.write_text(json.dumps(result["data"], indent=2), encoding="utf-8")
            elif args.export_format == "csv":
                output_path.write_text(result["data"], encoding="utf-8")
            print(f"Exported {result.get('row_count', 0)} rows to {output_path}", file=sys.stderr)
        elif result.get("file_path"):
            # File-based export
            print(f"Export available at: {result['file_path']}", file=sys.stderr)
    else:
        # stdout export
        if result.get("data"):
            if args.export_format == "json":
                print(json.dumps(result["data"], indent=2))
            else:
                print(result["data"])

    # Display export metadata
    if args.output_format == "json":
        print(json.dumps(result, indent=2), file=sys.stderr if args.output_file else sys.stdout)
    else:
        if not args.output_file:
            print("=" * 60)
        print(f"Export ID         : {result.get('export_id', 'N/A')}", file=sys.stderr if args.output_file else sys.stdout)
        print(f"Rows              : {result.get('row_count', 0)}", file=sys.stderr if args.output_file else sys.stdout)
        print(f"Size (bytes)      : {result.get('size_bytes', 0)}", file=sys.stderr if args.output_file else sys.stdout)
    return 0


def _render_metrics_summary_table(summary: Dict[str, Any]) -> None:
    """Render metrics summary in table format with PRD targets."""
    print("GuideAI Metrics Summary")
    print("=" * 80)
    print(f"Snapshot Time     : {summary.get('snapshot_time', 'N/A')}")
    print(f"Cache Status      : {'HIT' if summary.get('cache_hit') else 'MISS'}")
    if summary.get("cache_age_seconds") is not None:
        print(f"Cache Age         : {summary['cache_age_seconds']}s")
    print()

    # PRD KPI Metrics with targets
    print("PRD Key Performance Indicators")
    print("-" * 80)

    kpis = [
        ("Behavior Reuse Rate", summary.get("behavior_reuse_pct", 0.0), 70.0),
        ("Token Savings Rate", summary.get("average_token_savings_pct", 0.0), 30.0),
        ("Task Completion Rate", summary.get("task_completion_rate_pct", 0.0), 80.0),
        ("Compliance Coverage", summary.get("average_compliance_coverage_pct", 0.0), 95.0),
    ]

    for metric_name, actual, target in kpis:
        status = "✓" if actual >= target else "✗"
        print(f"{metric_name:30} : {actual:6.2f}% (target: {target:6.2f}%) {status}")

    print()
    print("Activity Counters")
    print("-" * 80)
    print(f"Total Behaviors   : {summary.get('total_behaviors', 0)}")
    print(f"Active Runs       : {summary.get('active_runs', 0)}")
    print(f"Completed Runs    : {summary.get('completed_runs', 0)}")
    print(f"Failed Runs       : {summary.get('failed_runs', 0)}")
    print(f"Total Actions     : {summary.get('total_actions', 0)}")
    print(f"Compliance Checks : {summary.get('compliance_checks', 0)}")
    print(f"Telemetry Events  : {summary.get('telemetry_events', 0)}")


# =============================================================================
# AgentAuth CLI Commands
# =============================================================================


def _command_auth_ensure_grant(args: argparse.Namespace) -> int:
    """Handle 'guideai auth ensure-grant' command."""
    adapter = _get_agent_auth_adapter()

    # Parse context key=value pairs
    context = {}
    if args.context:
        for ctx_pair in args.context:
            if "=" in ctx_pair:
                key, value = ctx_pair.split("=", 1)
                context[key] = value

    result = adapter.ensure_grant(
        agent_id=args.agent_id,
        tool_name=args.tool_name,
        scopes=args.scopes,
        user_id=args.user_id,
        context=context if context else None,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("AgentAuth Grant Request")
        print("=" * 80)
        print(f"Decision          : {result['decision']}")
        if "reason" in result:
            print(f"Reason            : {result['reason']}")
        if "consent_url" in result:
            print(f"\nConsent Required:")
            print(f"  URL             : {result['consent_url']}")
            print(f"  Request ID      : {result['consent_request_id']}")
        if "grant" in result:
            grant = result["grant"]
            print(f"\nGrant Details:")
            print(f"  Grant ID        : {grant['grant_id']}")
            print(f"  Agent ID        : {grant['agent_id']}")
            print(f"  Tool Name       : {grant['tool_name']}")
            print(f"  Scopes          : {', '.join(grant['scopes'])}")
            print(f"  Expires         : {grant['expires_at']}")
            print(f"  Provider        : {grant['provider']}")
            if grant.get("obligations"):
                print(f"  Obligations     : {len(grant['obligations'])} obligation(s)")
        if "audit_action_id" in result:
            print(f"\nAudit Action ID   : {result['audit_action_id']}")

    return 0


def _command_auth_list_grants(args: argparse.Namespace) -> int:
    """Handle 'guideai auth list-grants' command."""
    adapter = _get_agent_auth_adapter()

    grants = adapter.list_grants(
        agent_id=args.agent_id,
        user_id=args.user_id,
        tool_name=args.tool_name,
        include_expired=args.include_expired,
    )

    if args.format == "json":
        print(json.dumps(grants, indent=2))
    else:
        if not grants:
            print("No grants found.")
            return 0

        print(f"AgentAuth Grants ({len(grants)} found)")
        print("=" * 80)
        for i, grant in enumerate(grants, 1):
            print(f"\n{i}. Grant ID: {grant['grant_id']}")
            print(f"   Agent       : {grant['agent_id']}")
            if grant.get("user_id"):
                print(f"   User        : {grant['user_id']}")
            print(f"   Tool        : {grant['tool_name']}")
            print(f"   Scopes      : {', '.join(grant['scopes'])}")
            print(f"   Issued      : {grant['issued_at']}")
            print(f"   Expires     : {grant['expires_at']}")
            print(f"   Provider    : {grant['provider']}")
            if grant.get("obligations"):
                print(f"   Obligations : {len(grant['obligations'])} obligation(s)")

    return 0


def _command_auth_policy_preview(args: argparse.Namespace) -> int:
    """Handle 'guideai auth policy-preview' command."""
    adapter = _get_agent_auth_adapter()

    # Parse context key=value pairs
    context = {}
    if args.context:
        for ctx_pair in args.context:
            if "=" in ctx_pair:
                key, value = ctx_pair.split("=", 1)
                context[key] = value

    result = adapter.policy_preview(
        agent_id=args.agent_id,
        tool_name=args.tool_name,
        scopes=args.scopes,
        user_id=args.user_id,
        context=context if context else None,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("AgentAuth Policy Preview")
        print("=" * 80)
        print(f"Decision          : {result['decision']}")
        if "reason" in result:
            print(f"Reason            : {result['reason']}")
        if "bundle_version" in result:
            print(f"Bundle Version    : {result['bundle_version']}")
        if "obligations" in result and result["obligations"]:
            print(f"\nObligations ({len(result['obligations'])}):")
            for obl in result["obligations"]:
                attrs_str = ", ".join(f"{k}={v}" for k, v in obl['attributes'].items())
                print(f"  - {obl['type']}: {attrs_str}")

    return 0


def _command_auth_revoke(args: argparse.Namespace) -> int:
    """Handle 'guideai auth revoke' command."""
    adapter = _get_agent_auth_adapter()

    result = adapter.revoke_grant(
        grant_id=args.grant_id,
        revoked_by=args.revoked_by,
        reason=args.reason,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("AgentAuth Grant Revocation")
        print("=" * 80)
        print(f"Grant ID          : {result['grant_id']}")
        print(f"Success           : {'✓ Yes' if result['success'] else '✗ No'}")
        if "reason" in result:
            print(f"Reason            : {result['reason']}")

    return 0


# ==============================================================================
# DEPRECATED: Internal Auth Functions (Kept for backward compatibility)
# These functions are deprecated as of 2026-01-09. Use OAuth instead.
# ==============================================================================


def _get_internal_auth_api_url() -> str:
    """[DEPRECATED] Get the internal auth API base URL."""
    return os.getenv("GUIDEAI_API_URL", "http://localhost:8000")


def _internal_auth_register(
    username: str,
    password: str,
    email: Optional[str] = None,
    api_url: Optional[str] = None,
) -> Dict[str, Any]:
    """[DEPRECATED] Register a user with the internal auth API.

    This function is deprecated. Use OAuth authentication instead.
    """
    raise ValueError(
        "Internal authentication has been deprecated. "
        "Please use OAuth authentication via --provider=github or --provider=google"
    )


def _internal_auth_login(
    username: str,
    password: str,
    api_url: Optional[str] = None,
) -> Dict[str, Any]:
    """[DEPRECATED] Login a user with the internal auth API.

    This function is deprecated. Use OAuth authentication instead.
    """
    raise ValueError(
        "Internal authentication has been deprecated. "
        "Please use OAuth authentication via --provider=github or --provider=google"
    )


def _save_internal_tokens(
    tokens: Dict[str, Any],
    allow_plaintext: bool = False,
) -> Path:
    """[DEPRECATED] Save internal auth tokens to provider-specific file.

    This function is deprecated. Use OAuth authentication instead.
    """
    raise ValueError(
        "Internal authentication has been deprecated. "
        "Please use OAuth authentication via --provider=github or --provider=google"
    )


def _command_auth_register(args: argparse.Namespace) -> int:
    """[DEPRECATED] Register a new user with internal authentication.

    Internal authentication (username/password) has been deprecated.
    Please use OAuth authentication instead.
    """
    print("Error: Internal user registration has been deprecated.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Please use OAuth authentication instead:", file=sys.stderr)
    print("  guideai auth login --provider=github", file=sys.stderr)
    print("  guideai auth login --provider=google", file=sys.stderr)
    return 1


def _command_auth_login(args: argparse.Namespace) -> int:
    """Perform login and cache issued tokens.

    Uses OAuth device flow with github or google providers.
    Internal auth (username/password) has been deprecated.
    """
    # Check provider - internal auth is deprecated
    provider = getattr(args, "provider", "github")
    if provider == "internal":
        return _command_auth_login_internal(args)

    # Device flow for github/google
    manager = _get_device_flow_manager()
    try:
        store = _get_token_store(allow_plaintext=args.allow_plaintext)
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    scopes = args.scopes or ["actions.read"]
    metadata = {
        "hostname": platform.node(),
        "platform": sys.platform,
        "shell": os.environ.get("SHELL", "unknown"),
        "term": os.environ.get("TERM", "unknown"),
    }

    try:
        session = manager.start_authorization(
            client_id=args.client_id,
            scopes=scopes,
            surface="CLI",
            metadata=metadata,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("GuideAI Device Authorization")
    print("=" * 80)
    print(f"Requested Scopes  : {', '.join(scopes)}")
    print(f"Verification URL  : {session.verification_uri}")
    print(f"User Code         : {session.user_code}")
    print(f"Expires In        : {session.expires_in()}s")
    print("\nVisit the URL above and enter the code to approve access.")

    if args.open_browser:
        try:
            webbrowser.open(session.verification_uri_complete)
            print("Opened verification URL in your default browser.")
        except webbrowser.Error as exc:
            print(f"Warning: unable to open browser automatically ({exc}).", file=sys.stderr)

    deadline = time.monotonic() + args.timeout if args.timeout else None
    try:
        while True:
            if deadline and time.monotonic() >= deadline:
                print("\nTimed out waiting for approval.", file=sys.stderr)
                return 2

            result = manager.poll_device_code(session.device_code)
            status = result.status
            if status is DeviceAuthorizationStatus.PENDING:
                if not args.quiet:
                    remaining = result.expires_in if result.expires_in is not None else session.expires_in()
                    retry_after = result.retry_after or session.poll_interval
                    print(
                        f"Waiting for approval... {remaining}s remaining (poll in {retry_after}s)",
                        end="\r",
                        flush=True,
                    )
                time.sleep(result.retry_after or session.poll_interval)
                continue

            print("\n", end="")
            if status is DeviceAuthorizationStatus.DENIED:
                reason = result.denied_reason or "No reason provided"
                print(f"Consent denied: {reason}", file=sys.stderr)
                return 3
            if status is DeviceAuthorizationStatus.EXPIRED:
                print("Device code expired before approval.", file=sys.stderr)
                return 2

            tokens = result.tokens
            assert tokens is not None, "Approved state must include tokens"
            issued_at = datetime.now(timezone.utc)
            bundle = AuthTokenBundle(
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                token_type=tokens.token_type,
                scopes=result.scopes or scopes,
                client_id=result.client_id or args.client_id,
                issued_at=issued_at,
                expires_at=tokens.access_token_expires_at,
                refresh_expires_at=tokens.refresh_token_expires_at,
            )
            try:
                store.save(bundle)
            except TokenStoreError as exc:
                print(f"Warning: failed to persist tokens ({exc}).", file=sys.stderr)
                return 4

            print("Login successful!")
            print(f"Access token valid until : {bundle.expires_at.isoformat()}")
            print(f"Refresh token valid until: {bundle.refresh_expires_at.isoformat()}")
            return 0
    except KeyboardInterrupt:
        print("\nLogin cancelled by user.")
        return 130


def _command_auth_login_internal(args: argparse.Namespace) -> int:
    """[DEPRECATED] Perform internal auth login with username/password.

    Internal authentication has been deprecated. Please use OAuth instead.
    """
    print("Error: Internal authentication (username/password) has been deprecated.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Please use OAuth authentication instead:", file=sys.stderr)
    print("  guideai auth login --provider=github", file=sys.stderr)
    print("  guideai auth login --provider=google", file=sys.stderr)
    return 1


def _command_auth_status(args: argparse.Namespace) -> int:
    """Display cached token status."""

    try:
        store = _get_token_store(allow_plaintext=args.allow_plaintext)
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        bundle = store.load()
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if bundle is None:
        print("No cached tokens found. Run 'guideai auth login' to authenticate.")
        return 0

    payload = {
        "client_id": bundle.client_id,
        "scopes": bundle.scopes,
        "issued_at": bundle.issued_at.isoformat(),
        "expires_at": bundle.expires_at.isoformat(),
        "refresh_expires_at": bundle.refresh_expires_at.isoformat(),
        "access_expires_in": bundle.access_expires_in(),
        "refresh_expires_in": bundle.refresh_expires_in(),
    }

    if args.format == "json":
        _print_json(payload)
    else:
        print("Cached Authentication Tokens")
        print("=" * 80)
        print(f"Client ID         : {payload['client_id']}")
        print(f"Scopes            : {', '.join(bundle.scopes)}")
        print(f"Issued At         : {payload['issued_at']}")
        print(f"Access Expires    : {payload['expires_at']} ({payload['access_expires_in']}s)")
        print(
            f"Refresh Expires   : {payload['refresh_expires_at']} ({payload['refresh_expires_in']}s)"
        )
    return 0


def _command_auth_logout(args: argparse.Namespace) -> int:
    """Clear cached authentication tokens."""

    try:
        store = _get_token_store(allow_plaintext=args.allow_plaintext)
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        bundle = store.load()
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if bundle is None:
        print("No cached tokens to remove.")
        return 0

    if not args.force:
        prompt = input("Clear cached tokens? [y/N]: ").strip().lower()
        if prompt not in {"y", "yes"}:
            print("Logout aborted.")
            return 1

    try:
        store.clear()
    except TokenStoreError as exc:
        print(f"Error clearing tokens: {exc}", file=sys.stderr)
        return 1

    print("Cached tokens removed.")
    return 0


def _command_auth_refresh(args: argparse.Namespace) -> int:
    """Refresh the cached access token using the stored refresh token."""

    try:
        store = _get_token_store(allow_plaintext=args.allow_plaintext)
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        bundle = store.load()
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if bundle is None:
        print("No cached tokens found. Run 'guideai auth login' to authenticate.")
        return 1

    if bundle.refresh_expires_in() <= 0:
        print("Refresh token expired. Run 'guideai auth login' to authenticate again.", file=sys.stderr)
        try:
            store.clear()
        except TokenStoreError as exc:
            print(f"Warning: failed to clear expired tokens ({exc}).", file=sys.stderr)
        return 2

    if bundle.is_access_valid() and not args.force:
        if not args.quiet:
            remaining = bundle.access_expires_in()
            print(f"Access token still valid for {remaining}s; skipping refresh (use --force to override).")
        return 0

    manager = _get_device_flow_manager()
    try:
        session = manager.refresh_access_token(bundle.refresh_token)
    except (RefreshTokenNotFoundError, DeviceCodeNotFoundError):
        print("Stored refresh token is no longer recognized. Run 'guideai auth login' to re-authenticate.", file=sys.stderr)
        return 2
    except RefreshTokenExpiredError:
        print("Refresh token expired. Run 'guideai auth login' to re-authenticate.", file=sys.stderr)
        try:
            store.clear()
        except TokenStoreError as exc:
            print(f"Warning: failed to clear expired tokens ({exc}).", file=sys.stderr)
        return 2
    except DeviceCodeExpiredError:
        print("Original device authorization expired. Run 'guideai auth login' to re-authenticate.", file=sys.stderr)
        return 2
    except DeviceFlowError as exc:
        print(f"Error refreshing tokens: {exc}", file=sys.stderr)
        return 1

    tokens = session.tokens
    assert tokens is not None, "refreshed session must include tokens"

    bundle.update_tokens(
        access_token=tokens.access_token,
        access_expires_at=tokens.access_token_expires_at,
        refresh_token=tokens.refresh_token,
        refresh_expires_at=tokens.refresh_token_expires_at,
    )

    try:
        store.save(bundle)
    except TokenStoreError as exc:
        print(f"Warning: refreshed tokens but failed to persist them ({exc}).", file=sys.stderr)
        return 4

    if not args.quiet:
        print("Access token refreshed successfully.")
        print(f"Access token valid until : {bundle.expires_at.isoformat()}")
        print(f"Refresh token valid until: {bundle.refresh_expires_at.isoformat()}")
    return 0


def _command_auth_consent_lookup(args: argparse.Namespace) -> int:
    """Lookup metadata for a consent code."""

    manager = _get_device_flow_manager()
    try:
        normalized = _normalize_user_code(args.user_code)
        session = manager.describe_user_code(normalized)
    except (ValueError, UserCodeNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    payload = {
        "user_code": session.user_code,
        "status": session.status.value,
        "client_id": session.client_id,
        "scopes": session.scopes,
        "surface": session.surface,
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "verification_uri": session.verification_uri,
        "verification_uri_complete": session.verification_uri_complete,
    }
    if session.approved_at:
        payload["approved_at"] = session.approved_at.isoformat()
    if session.denied_at:
        payload["denied_at"] = session.denied_at.isoformat()
        payload["denied_reason"] = session.denied_reason

    if args.format == "json":
        _print_json(payload)
    else:
        print("Consent Request Details")
        print("=" * 80)
        print(f"User Code         : {payload['user_code']}")
        print(f"Status            : {payload['status']}")
        print(f"Client ID         : {payload['client_id']}")
        print(f"Scopes            : {', '.join(session.scopes)}")
        print(f"Surface           : {payload['surface']}")
        print(f"Created At        : {payload['created_at']}")
        print(f"Expires At        : {payload['expires_at']}")
        if session.approved_at:
            print(f"Approved At       : {payload['approved_at']}")
        if session.denied_at:
            print(f"Denied At         : {payload['denied_at']} ({payload.get('denied_reason', 'n/a')})")
    return 0


def _command_auth_consent_approve(args: argparse.Namespace) -> int:
    """Approve a consent request via user code."""

    manager = _get_device_flow_manager()
    roles = args.roles or []
    try:
        normalized = _normalize_user_code(args.user_code)
        session = manager.approve_user_code(
            normalized,
            args.actor_id,
            approver_surface="CLI",
            roles=roles,
            mfa_verified=args.mfa_verified,
        )
    except (ValueError, UserCodeNotFoundError, DeviceCodeExpiredError, DeviceFlowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Consent approved.")
    if session.tokens:
        print(f"Grant issued for scopes: {', '.join(session.scopes)}")
    return 0


def _command_auth_consent_deny(args: argparse.Namespace) -> int:
    """Deny a consent request via user code."""

    manager = _get_device_flow_manager()
    try:
        normalized = _normalize_user_code(args.user_code)
        session = manager.deny_user_code(
            normalized,
            args.actor_id,
            approver_surface="CLI",
            reason=args.reason,
        )
    except (ValueError, UserCodeNotFoundError, DeviceCodeExpiredError, DeviceFlowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Consent denied.")
    if session.denied_reason:
        print(f"Reason: {session.denied_reason}")
    return 0


def _command_bci_rebuild_index(args: argparse.Namespace) -> int:
    """Rebuild the behavior retriever semantic index."""
    bci_service = _get_bci_service()

    try:
        result = bci_service.rebuild_index()
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error rebuilding index: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        print("BehaviorRetriever Index Rebuild")
        print("=" * 60)
        print(f"Status           : {result.get('status', 'unknown')}")
        if "mode" in result:
            print(f"Mode             : {result.get('mode')}")
        if "behavior_count" in result:
            print(f"Behavior Count   : {result.get('behavior_count')}")
        if "duration_ms" in result:
            print(f"Duration (ms)    : {result.get('duration_ms')}")
        error = result.get("error")
        if error:
            print(f"Error            : {error}")
    return 0


def _load_json_file(path: str) -> Any:
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise ValueError(f"File not found: {file_path}")
    raw = file_path.read_text(encoding="utf-8")
    return json.loads(raw) if raw.strip() else None


def _render_bci_retrieve_table(payload: Dict[str, Any]) -> None:
    results: List[Dict[str, Any]] = payload.get("results", [])
    if not results:
        print("No behaviors matched the query.")
    else:
        headers = ["#", "Behavior", "Score", "Role", "Tags"]
        rows: List[List[str]] = []
        widths = [len(header) for header in headers]
        for idx, result in enumerate(results, start=1):
            row = [
                str(idx),
                result.get("name", "?"),
                f"{float(result.get('score', 0.0)):.3f}",
                result.get("role_focus", "-"),
                ", ".join(result.get("tags", [])) or "-",
            ]
            rows.append(row)
            widths = [max(widths[i], len(row[i])) for i in range(len(headers))]
        fmt = " | ".join(f"{{:<{width}}}" for width in widths)
        separator = "-+-".join("-" * width for width in widths)
        print(fmt.format(*headers))
        print(separator)
        for row in rows:
            print(fmt.format(*row))

    print()
    latency = payload.get("latency_ms")
    if latency is not None:
        print(f"Latency (ms): {latency}")
    print(f"Strategy Used: {payload.get('strategy_used', 'unknown')}")
    metadata = payload.get("metadata") or {}
    if metadata:
        print("Metadata:")
        for key, value in metadata.items():
            print(f"  - {key}: {value}")


def _render_bci_compose_table(payload: Dict[str, Any]) -> None:
    print("Composed Prompt")
    print("=" * 60)
    print(payload.get("prompt", ""))
    print()
    behaviors: List[Dict[str, Any]] = payload.get("behaviors", [])
    if behaviors:
        print("Behaviors Included:")
        for behavior in behaviors:
            label = behavior.get("citation_label") or behavior.get("name")
            print(f"  - {label} ({behavior.get('behavior_id', '?')})")
    metadata = payload.get("metadata") or {}
    if metadata:
        print()
        print("Metadata:")
        for key, value in metadata.items():
            print(f"  - {key}: {value}")


def _render_bci_validate_table(payload: Dict[str, Any]) -> None:
    print("Citation Validation Summary")
    print("=" * 60)
    print(f"Total Citations : {payload.get('total_citations', 0)}")
    print(f"Valid Citations : {len(payload.get('valid_citations', []))}")
    print(f"Invalid Citations: {len(payload.get('invalid_citations', []))}")
    print(f"Compliance Rate : {payload.get('compliance_rate', 0.0)}")
    print(f"Is Compliant    : {payload.get('is_compliant', False)}")
    missing = payload.get("missing_behaviors", [])
    if missing:
        print("Missing Behaviors:")
        for name in missing:
            print(f"  - {name}")
    warnings = payload.get("warnings", [])
    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"  - {item}")
    invalid = payload.get("invalid_citations", [])
    if invalid:
        print("Invalid Citations:")
        for citation in invalid:
            text = citation.get("text") if isinstance(citation, dict) else str(citation)
            behavior_name = citation.get("behavior_name") if isinstance(citation, dict) else None
            detail = f" (behavior={behavior_name})" if behavior_name else ""
            print(f"  - {text}{detail}")


def _command_bci_generate(args: argparse.Namespace) -> int:
    """Generate a behavior-conditioned LLM response."""
    from .llm_provider import LLMConfig, ProviderType
    from .bci_contracts import RoleFocus

    bci_service = _get_bci_service()

    # Build LLM config from args
    llm_config = None
    if args.provider or args.model or args.temperature:
        config_kwargs = {}
        if args.provider:
            try:
                config_kwargs["provider"] = ProviderType(args.provider)
            except ValueError:
                print(f"Invalid provider: {args.provider}", file=sys.stderr)
                return 1
        if args.model:
            config_kwargs["model"] = args.model
        if args.temperature is not None:
            config_kwargs["temperature"] = args.temperature

        llm_config = LLMConfig.from_env()
        for key, value in config_kwargs.items():
            setattr(llm_config, key, value)

    # Parse role focus
    role_focus = None
    if args.role:
        try:
            role_focus = RoleFocus(args.role.upper())
        except ValueError:
            print(f"Invalid role: {args.role}", file=sys.stderr)
            return 1

    try:
        result = bci_service.generate_response(
            query=args.query,
            behaviors=args.behaviors,
            top_k=args.top_k,
            llm_config=llm_config,
            role_focus=role_focus,
        )

        # Format behaviors for display
        behaviors_display = "\n".join(f"- {b.name}" for b in result['behaviors_used']) if result['behaviors_used'] else "(auto-retrieved)"

        output_text = f"""# BCI Generation Result

## Query
{args.query}

## Behaviors Used
{behaviors_display}

## Response
{result['response'].content}

## Metadata
- Provider: {result['response'].provider.value}
- Model: {result['response'].model}
- Input Tokens: {result['response'].input_tokens}
- Output Tokens: {result['response'].output_tokens}
- Total Tokens: {result['response'].total_tokens}
- Token Savings (estimated): {result['token_savings']['total_saved']}
- Latency: {result['latency_ms']:.2f}ms
- LLM Latency: {result['response'].latency_ms:.2f}ms
"""

        if args.output:
            with open(args.output, "w") as f:
                f.write(output_text)
            print(f"Output written to {args.output}")
        else:
            print(output_text)

        return 0

    except Exception as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def _command_bci_improve(args: argparse.Namespace) -> int:
    """Analyze a failed run and generate improvement suggestions."""
    from .llm_provider import LLMConfig, ProviderType

    bci_service = _get_bci_service()

    # Build LLM config from args
    llm_config = None
    if args.provider or args.model:
        config_kwargs = {}
        if args.provider:
            try:
                config_kwargs["provider"] = ProviderType(args.provider)
            except ValueError:
                print(f"Invalid provider: {args.provider}", file=sys.stderr)
                return 1
        if args.model:
            config_kwargs["model"] = args.model

        llm_config = LLMConfig.from_env()
        for key, value in config_kwargs.items():
            setattr(llm_config, key, value)

    try:
        result = bci_service.improve_run(
            run_id=args.run_id,
            llm_config=llm_config,
            max_behaviors=args.max_behaviors,
        )

        output_text = f"""# Run Improvement Analysis

## Run ID
{result['run_id']}

## Detected Patterns
{chr(10).join(f"- {p['description']} (frequency={p['frequency']}, score={p['score']:.2f})" for p in result['patterns'])}

## Improvement Suggestions
{result['suggestions']}

## Behaviors Extracted
{chr(10).join(f"- {b}" for b in result['behaviors_extracted'])}

## Metadata
- Patterns Detected: {len(result['patterns'])}
- Behaviors Extracted: {len(result['behaviors_extracted'])}
- Analysis Latency: {result['latency_ms']:.2f}ms
"""

        if args.output:
            with open(args.output, "w") as f:
                f.write(output_text)
            print(f"Output written to {args.output}")
        else:
            print(output_text)

        return 0

    except Exception as exc:
        print(f"Improvement analysis failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def _command_bci_retrieve(args: argparse.Namespace) -> int:
    bci_service = _get_bci_service()
    try:
        strategy = RetrievalStrategy(args.strategy)
        role_focus = RoleFocus(args.role_focus) if args.role_focus else None
    except ValueError as exc:
        print(f"Invalid argument: {exc}", file=sys.stderr)
        return 1

    if args.top_k <= 0:
        print("--top-k must be greater than 0", file=sys.stderr)
        return 1

    request = RetrieveRequest(
        query=args.query,
        top_k=args.top_k,
        strategy=strategy,
        role_focus=role_focus,
        tags=args.tags or None,
        include_metadata=args.include_metadata,
        embedding_weight=args.embedding_weight,
        keyword_weight=args.keyword_weight,
    )

    try:
        response = bci_service.retrieve(request)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error retrieving behaviors: {exc}", file=sys.stderr)
        return 1

    payload = response.to_dict()
    if args.format == "json":
        _print_json(payload)
    else:
        _render_bci_retrieve_table(payload)
    return 0


def _command_bci_compose_prompt(args: argparse.Namespace) -> int:
    bci_service = _get_bci_service()
    try:
        behaviors_payload = _load_json_file(args.behaviors_file)
        if not isinstance(behaviors_payload, list):
            raise ValueError("Behaviors file must contain a JSON array")
        behaviors = [BehaviorSnippet.from_dict(item) for item in behaviors_payload]
        if not behaviors:
            raise ValueError("Behaviors list cannot be empty")
        citation_mode = CitationMode(args.citation_mode)
        prompt_format = PromptFormat(args.prompt_format)
    except Exception as exc:
        print(f"Error preparing compose prompt request: {exc}", file=sys.stderr)
        return 1

    request = ComposePromptRequest(
        query=args.query,
        behaviors=behaviors,
        citation_mode=citation_mode,
        format=prompt_format,
        citation_instruction=args.citation_instruction,
        max_behaviors=args.max_behaviors,
    )

    try:
        response = bci_service.compose_prompt(request)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error composing prompt: {exc}", file=sys.stderr)
        return 1

    payload = response.to_dict()
    if args.format == "json":
        _print_json(payload)
    else:
        _render_bci_compose_table(payload)
    return 0


def _command_bci_validate_citations(args: argparse.Namespace) -> int:
    if args.output_text and args.output_file:
        print("Provide either --output-text or --output-file, not both", file=sys.stderr)
        return 1

    bci_service = _get_bci_service()
    try:
        output_text = args.output_text
        if output_text is None and args.output_file:
            output_text = Path(args.output_file).expanduser().read_text(encoding="utf-8")
        if not output_text:
            raise ValueError("Either --output-text or --output-file must be provided")

        prepended_payload = _load_json_file(args.prepended_file)
        if not isinstance(prepended_payload, list):
            raise ValueError("Prepended file must contain a JSON array")
        prepended = [PrependedBehavior.from_dict(item) for item in prepended_payload]
        if not prepended:
            raise ValueError("Prepended behaviors list cannot be empty")
    except Exception as exc:
        print(f"Error preparing validation request: {exc}", file=sys.stderr)
        return 1

    request = ValidateCitationsRequest(
        output_text=output_text,
        prepended_behaviors=prepended,
        minimum_citations=args.minimum_citations,
        allow_unlisted_behaviors=args.allow_unlisted,
    )

    try:
        response = bci_service.validate_citations(request)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error validating citations: {exc}", file=sys.stderr)
        return 1

    payload = response.to_dict()
    if args.format == "json":
        _print_json(payload)
    else:
        _render_bci_validate_table(payload)
    return 0


def _parse_evidence(items: List[str]) -> Dict[str, Any]:
    """Parse key=value evidence items into a dictionary."""
    evidence: Dict[str, Any] = {}
    for entry in items:
        if "=" not in entry:
            raise ValueError(f"Invalid evidence entry '{entry}'. Use KEY=VALUE format.")
        key, value = entry.split("=", 1)
        evidence[key] = value
    return evidence


def _command_compliance_create_checklist(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        checklist = adapter.create_checklist(
            title=args.title,
            description=args.description,
            template_id=args.template_id,
            milestone=args.milestone,
            compliance_category=args.compliance_category or [],
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_checklist_table([checklist])
    else:
        _print_json(checklist)
    return 0


def _command_compliance_record_step(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        evidence = _parse_evidence(args.evidence_items or [])
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        step = adapter.record_step(
            checklist_id=args.checklist_id,
            title=args.title,
            status=args.status,
            evidence=evidence,
            behaviors_cited=args.behaviors_cited or [],
            related_run_id=args.related_run_id,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_step_table([step])
    else:
        _print_json(step)
    return 0


def _command_compliance_list(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        checklists = adapter.list_checklists(
            milestone=args.milestone,
            compliance_category=args.compliance_category,
            status_filter=args.status,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_checklist_table(checklists)
    else:
        _print_json(checklists)
    return 0


def _command_compliance_get(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        checklist = adapter.get_checklist(args.checklist_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_checklist_table([checklist])
    else:
        _print_json(checklist)
    return 0


def _command_compliance_validate(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()

    # Support either checklist_id or --action-id
    if args.action_id:
        try:
            result = adapter.validate_by_action_id(
                action_id=args.action_id,
                actor_id=args.actor_id,
                actor_role=args.actor_role,
            )
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    elif args.checklist_id:
        try:
            result = adapter.validate_checklist(
                checklist_id=args.checklist_id,
                actor_id=args.actor_id,
                actor_role=args.actor_role,
            )
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        print("Error: Either checklist_id or --action-id must be provided", file=sys.stderr)
        return 2

    if args.format == "table":
        _render_validation_table(result)
    else:
        _print_json(result)
    return 0


def _command_compliance_policies_list(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        policies = adapter.list_policies(
            org_id=args.org_id,
            project_id=args.project_id,
            policy_type=args.policy_type,
            enforcement_level=args.enforcement_level,
            is_active=True if args.active_only else None,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_policies_table(policies)
    else:
        _print_json(policies)
    return 0


def _command_compliance_policies_create(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        policy = adapter.create_policy(
            name=args.name,
            description=args.description,
            policy_type=args.policy_type,
            enforcement_level=args.enforcement_level,
            org_id=args.org_id,
            project_id=args.project_id,
            version=args.version,
            required_behaviors=args.required_behaviors or [],
            compliance_categories=args.compliance_categories or [],
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_policies_table([policy])
    else:
        _print_json(policy)
    return 0


def _command_compliance_policies_get(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        policy = adapter.get_policy(args.policy_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_policies_table([policy])
    else:
        _print_json(policy)
    return 0


def _command_compliance_audit(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        report = adapter.get_audit_trail(
            run_id=args.run_id,
            checklist_id=args.checklist_id,
            action_id=args.action_id,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_audit_trail_table(report)
    else:
        _print_json(report)
    return 0


def _render_policies_table(policies: List[Dict]) -> None:
    """Render policies as a formatted table."""
    if not policies:
        print("No policies found.")
        return

    headers = ["ID", "Name", "Type", "Enforcement", "Scope", "Active", "Version"]
    rows = []
    for p in policies:
        scope = "project" if p.get("project_id") else ("org" if p.get("org_id") else "global")
        rows.append([
            p.get("policy_id", "")[:8],
            p.get("name", ""),
            p.get("policy_type", ""),
            p.get("enforcement_level", ""),
            scope,
            "✓" if p.get("is_active") else "✗",
            p.get("version", ""),
        ])

    _print_table(headers, rows)


def _render_audit_trail_table(report: Dict) -> None:
    """Render audit trail report as a formatted table."""
    summary = report.get("summary", {})
    print(f"\n=== Audit Trail Report ===")
    print(f"Run ID: {report.get('run_id', 'N/A')}")
    print(f"Checklists: {summary.get('checklist_count', 0)}")
    print(f"Total Entries: {summary.get('total_entries', 0)}")
    print(f"Generated: {report.get('generated_at', '')}")

    status_breakdown = summary.get("status_breakdown", {})
    if status_breakdown:
        print(f"\nStatus Breakdown:")
        for status, count in status_breakdown.items():
            print(f"  {status}: {count}")

    entries = report.get("entries", [])
    if entries:
        print(f"\n--- Entries ({len(entries)}) ---")
        headers = ["Timestamp", "Checklist", "Step", "Status", "Actor", "Behaviors"]
        rows = []
        for e in entries:
            rows.append([
                e.get("timestamp", "")[:19],
                e.get("checklist_id", "")[:8],
                e.get("title", "")[:30],
                e.get("status", ""),
                f"{e.get('actor', {}).get('id', '')}@{e.get('actor', {}).get('surface', '')}",
                ", ".join(e.get("behaviors_cited", [])[:2]) + ("..." if len(e.get("behaviors_cited", [])) > 2 else ""),
            ])
        _print_table(headers, rows)


def _ensure_pre_commit_available() -> None:
    if subprocess.call(["pre-commit", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        raise RuntimeError("pre-commit CLI is required to run guideai scan-secrets")


def _run_pre_commit(report_path: Path) -> int:
    cmd: List[str] = [
        "pre-commit",
        "run",
        "gitleaks",
        "--all-files",
        "--hook-stage",
        "manual",
        "--",
        "--report-format",
        "json",
        "--report-path",
        str(report_path),
    ]
    result = subprocess.run(cmd, text=True)  # noqa: S603
    return result.returncode


def _load_findings(report_path: Path) -> List[dict]:
    if not report_path.exists():
        return []
    raw = report_path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError(f"Invalid JSON report generated by gitleaks: {exc}") from exc
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "findings" in data:
        payload = data.get("findings")
        return payload if isinstance(payload, list) else []
    return []


def _render_table(findings: List[dict]) -> None:
    if not findings:
        print("No secrets detected ✅")
        return

    print(f"Detected {len(findings)} potential secret(s):")
    for finding in findings:
        rule = finding.get("RuleID") or finding.get("rule") or "unknown_rule"
        file_path = finding.get("File") or finding.get("file") or "unknown_file"
        line = finding.get("StartLine") or finding.get("Line") or finding.get("line") or "?"
        print(f" - {rule} :: {file_path}:{line}")


def run_scan(
    *,
    output_path: Optional[Path] = None,
    fmt: str = "table",
    fail_on_findings: bool = False,
) -> int:
    _ensure_pre_commit_available()

    temp_file: Optional[Any] = None
    if output_path is None:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        report_path = Path(temp_file.name)
        temp_file.close()
    else:
        report_path = output_path.expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)

    exit_code = _run_pre_commit(report_path)
    findings = _load_findings(report_path)

    if fmt == "json":
        if output_path is None:
            print(json.dumps(findings, indent=2))
        else:
            print(f"JSON report written to {report_path}")
    else:
        _render_table(findings)

    if output_path is None and report_path.exists():
        report_path.unlink(missing_ok=True)

    if exit_code not in (0, 1):
        return exit_code

    if fail_on_findings and findings:
        return 1

    return 0


def _render_workflow_templates_table(templates: List[Dict[str, Any]]) -> None:
    if not templates:
        print("No workflow templates found.")
        return

    headers = ["Template ID", "Name", "Role", "Steps", "Tags"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for template in templates:
        row = [
            template["template_id"][:12],
            template["name"],
            template["role_focus"],
            str(len(template["steps"])),
            ", ".join(template.get("tags", [])) or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_workflow_run_table(run: Dict[str, Any]) -> None:
    headers = ["Run ID", "Template", "Status", "Total Tokens", "Behaviors"]
    row = [
        run["run_id"][:12],
        run["template_name"],
        run["status"],
        str(run.get("total_tokens", 0)),
        str(len(run.get("behaviors_cited", []))),
    ]
    widths = [max(len(header), len(value)) for header, value in zip(headers, row)]
    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    print(fmt.format(*row))


def _render_reflection_table(result: Dict[str, Any]) -> None:
    summary = result.get("summary")
    if summary:
        print(summary)
        print()
    candidates = result.get("candidates", [])
    if not candidates:
        print("No high-confidence behavior candidates found.")
        return

    headers = ["Slug", "Confidence", "Duplicate", "Tags"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for candidate in candidates:
        duplicate = candidate.get("duplicate_behavior_name") or candidate.get("duplicate_behavior_id") or "-"
        row = [
            candidate["slug"][:28],
            f"{candidate.get('confidence', 0.0):.2f}",
            duplicate,
            ", ".join(candidate.get("tags", [])).strip() or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _command_reflection(args: argparse.Namespace) -> int:
    adapter = _get_reflection_adapter()
    trace_text = args.trace_text or ""
    if not trace_text:
        if not args.trace_file:
            print("Error: provide --trace or --trace-file for reflection", file=sys.stderr)
            return 2
        trace_path = Path(args.trace_file).expanduser().resolve()
        if not trace_path.exists():
            print(f"Error: Trace file not found: {trace_path}", file=sys.stderr)
            return 2
        trace_text = trace_path.read_text(encoding="utf-8")

    min_score = max(0.0, min(1.0, args.min_score))

    try:
        result = adapter.reflect(
            trace_text=trace_text,
            trace_format=args.trace_format,
            run_id=args.run_id,
            max_candidates=args.max_candidates,
            min_quality_score=min_score,
            include_examples=not args.no_examples,
            preferred_tags=args.tags or None,
        )
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output == "table":
        _render_reflection_table(result)
    else:
        _print_json(result)
    return 0


def _command_workflow_create_template(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        # Load steps from file
        steps_path = Path(args.steps_file).expanduser().resolve()
        if not steps_path.exists():
            print(f"Error: Steps file not found: {steps_path}", file=sys.stderr)
            return 2
        steps_data = json.loads(steps_path.read_text(encoding="utf-8"))
        if not isinstance(steps_data, list):
            print("Error: Steps file must contain a JSON array", file=sys.stderr)
            return 2

        metadata = None
        if args.metadata_file:
            metadata = _load_metadata([], args.metadata_file)

        template = adapter.create_template(
            name=args.name,
            description=args.description,
            role_focus=args.role_focus,
            steps=steps_data,
            tags=args.tags or None,
            metadata=metadata,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_templates_table([template])
    else:
        _print_json(template)
    return 0


def _command_workflow_list_templates(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        templates = adapter.list_templates(
            role_focus=args.role_focus,
            tags=args.tags or None,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_templates_table(templates)
    else:
        _print_json(templates)
    return 0


def _command_workflow_get_template(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        template = adapter.get_template(args.template_id)
        if not template:
            print(f"Error: Template not found: {args.template_id}", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_templates_table([template])
    else:
        _print_json(template)
    return 0


def _command_workflow_run(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        metadata = None
        if args.metadata_file:
            metadata = _load_metadata([], args.metadata_file)

        run = adapter.run_workflow(
            template_id=args.template_id,
            behavior_ids=args.behavior_ids or None,
            metadata=metadata,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_run_table(run)
    else:
        _print_json(run)
    return 0


def _command_workflow_status(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        run = adapter.get_run(args.run_id)
        if not run:
            print(f"Error: Run not found: {args.run_id}", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_run_table(run)
    else:
        _print_json(run)
    return 0


def _get_amprealize_service() -> Any:
    """Factory for AmprealizeService with dependencies."""
    from guideai.amprealize import AmprealizeService

    # Use existing CLI adapters to get the underlying services
    action_adapter = _get_action_adapter()
    compliance_adapter = _get_compliance_adapter()
    metrics_adapter = _get_metrics_adapter()

    # The adapters wrap the service in ._service
    # We need to access the private member because the adapter doesn't expose the raw service
    # This is acceptable within the CLI module which owns the adapters
    return AmprealizeService(
        action_service=action_adapter._service,
        compliance_service=compliance_adapter._service,
        metrics_service=metrics_adapter._service,
    )


def _override_amprealize_env_file(env_file: Optional[str]) -> None:
    """Override Amprealize manifest path for the current process."""

    if env_file:
        os.environ["GUIDEAI_ENV_FILE"] = env_file


def _command_amprealize_plan(args: argparse.Namespace) -> int:
    from guideai.amprealize import PlanRequest
    from guideai.action_contracts import Actor

    _override_amprealize_env_file(args.env_file)
    service = _get_amprealize_service()
    output_mode = _resolve_output_format(getattr(args, "output", None))

    # Parse variables
    vars_dict = {}
    for v in args.variables:
        if "=" in v:
            k, val = v.split("=", 1)
            vars_dict[k] = val

    # Create actor from CLI args
    actor = Actor(
        id=args.actor_id,
        role=args.actor_role,
        surface="cli"
    )

    try:
        req = PlanRequest(
            blueprint_id=args.blueprint_id,
            environment=args.environment,
            lifetime=args.lifetime,
            compliance_tier=args.compliance_tier,
            checklist_id=args.checklist_id,
            behaviors=args.behaviors,
            variables=vars_dict,
            active_modules=args.active_modules,
            force_podman=args.force_podman
        )
        # Service.plan signature: plan(self, request: PlanRequest, actor: Actor = None)
        resp = service.plan(req, actor)
        resp_data = _serialize_model(resp)
        snapshot_path = _save_amprealize_snapshot("plan", resp_data)
        if output_mode == "json":
            _print_json(resp_data)
            _notify_snapshot_location(snapshot_path)
        else:
            _render_amprealize_plan_summary(resp_data, snapshot_path)
            print("  (use --output json for the raw payload)")
        return 0
    except Exception as e:
        print(f"Error planning: {e}", file=sys.stderr)
        return 1


def _command_amprealize_apply(args: argparse.Namespace) -> int:
    from guideai.amprealize import ApplyRequest
    from guideai.action_contracts import Actor

    _override_amprealize_env_file(args.env_file)
    service = _get_amprealize_service()
    output_mode = _resolve_output_format(getattr(args, "output", None))

    # Create actor from CLI args
    actor = Actor(
        id=args.actor_id,
        role=args.actor_role,
        surface="cli"
    )

    try:
        manifest = None
        if args.manifest_file:
            with open(args.manifest_file, "r") as f:
                if args.manifest_file.endswith(('.yaml', '.yml')):
                    manifest = yaml.safe_load(f)
                else:
                    manifest = json.load(f)

        # Handle special value -1 for stale_max_age_hours (None = skip age check)
        stale_max_age = getattr(args, "stale_max_age_hours", 0.0)
        effective_stale_max_age = None if stale_max_age == -1 else stale_max_age

        req = ApplyRequest(
            plan_id=args.plan_id,
            manifest=manifest,
            watch=args.watch,
            resume=args.resume,
            force_podman=args.force_podman,
            skip_resource_check=args.skip_resource_check,
            auto_cleanup=getattr(args, "auto_cleanup", False),
            auto_cleanup_aggressive=getattr(args, "auto_cleanup_aggressive", False),
            auto_cleanup_include_volumes=getattr(args, "auto_cleanup_include_volumes", False),
            auto_cleanup_max_retries=getattr(args, "auto_cleanup_max_retries", 3),
            allow_host_resource_warning=getattr(args, "allow_host_resource_warning", False),
            min_disk_gb=args.min_disk_gb,
            min_memory_mb=args.min_memory_mb,
            proactive_cleanup=getattr(args, "proactive_cleanup", False),
            blueprint_aware_memory_check=getattr(args, "blueprint_aware_memory_check", True),
            memory_safety_margin_mb=getattr(args, "memory_safety_margin_mb", 512.0),
            auto_resolve_stale=getattr(args, "auto_resolve_stale", True),
            auto_resolve_conflicts=getattr(args, "auto_resolve_conflicts", True),
            stale_max_age_hours=effective_stale_max_age,
        )

        if args.watch:
            resp = service.apply(req, actor)
            run_id = resp.amp_run_id
            print(f"Apply started. Watching Amprealize run {run_id} (Ctrl+C to stop viewing)")
            events: List[Dict[str, Any]] = []
            try:
                for event in service.watch(run_id):
                    event_dict = _serialize_model(event)
                    events.append(event_dict)
                    _render_amprealize_event(event_dict)
            except KeyboardInterrupt:
                print("Stopped watching apply. You can re-run with --watch to resume streaming.")
            status = service.status(run_id)
            status_dict = _serialize_model(status)
            snapshot_payload = {"status": status_dict, "events": events}
            snapshot_path = _save_amprealize_snapshot("apply-watch", snapshot_payload)
            if output_mode == "json":
                _print_json(snapshot_payload)
                _notify_snapshot_location(snapshot_path)
            else:
                _render_amprealize_status_summary(status_dict, snapshot_path, include_events=len(events))
            return 0
        resp = service.apply(req, actor)
        resp_data = _serialize_model(resp)
        snapshot_path = _save_amprealize_snapshot("apply", resp_data)
        if output_mode == "json":
            _print_json(resp_data)
            _notify_snapshot_location(snapshot_path)
        else:
            _render_amprealize_apply_summary(resp_data, snapshot_path, watched=False)
        return 0
    except Exception as e:
        print(f"Error applying: {e}", file=sys.stderr)
        return 1


def _command_amprealize_status(args: argparse.Namespace) -> int:
    service = _get_amprealize_service()
    output_mode = _resolve_output_format(getattr(args, "output", None))

    try:
        resp = service.status(args.amp_run_id)
        resp_data = _serialize_model(resp)
        snapshot_path = _save_amprealize_snapshot("status", resp_data)
        if output_mode == "json":
            _print_json(resp_data)
            _notify_snapshot_location(snapshot_path)
        else:
            _render_amprealize_status_summary(resp_data, snapshot_path)
        return 0
    except Exception as e:
        print(f"Error checking status: {e}", file=sys.stderr)
        return 1


def _command_amprealize_destroy(args: argparse.Namespace) -> int:
    from guideai.amprealize import DestroyRequest
    from guideai.action_contracts import Actor

    _override_amprealize_env_file(args.env_file)
    service = _get_amprealize_service()
    output_mode = _resolve_output_format(getattr(args, "output", None))

    # Create actor from CLI args
    actor = Actor(
        id=args.actor_id,
        role=args.actor_role,
        surface="cli"
    )

    try:
        req = DestroyRequest(
            amp_run_id=args.amp_run_id,
            cascade=args.cascade,
            reason=args.reason,
            force_podman=args.force_podman,
            cleanup_after_destroy=getattr(args, "cleanup_after_destroy", True),
            cleanup_aggressive=getattr(args, "cleanup_aggressive", True),
            cleanup_include_volumes=getattr(args, "cleanup_include_volumes", False),
        )

        resp = service.destroy(req, actor)
        resp_data = _serialize_model(resp)
        snapshot_path = _save_amprealize_snapshot("destroy", resp_data)
        if output_mode == "json":
            _print_json(resp_data)
            _notify_snapshot_location(snapshot_path)
        else:
            _render_amprealize_destroy_summary(resp_data, snapshot_path)
        return 0
    except Exception as e:
        print(f"Error destroying resources: {e}", file=sys.stderr)
        return 1


def _command_amprealize_bootstrap(args: argparse.Namespace) -> int:
    service = _get_amprealize_service()

    target_dir = Path(args.bootstrap_directory).expanduser()
    env_template = Path(args.env_template).expanduser() if args.env_template else None
    include_blueprints = args.include_blueprints or bool(args.blueprints)

    try:
        result = service.bootstrap(
            target_directory=target_dir,
            include_blueprints=include_blueprints,
            blueprints=args.blueprints or None,
            force=args.force,
            env_template=env_template,
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error bootstrapping Amprealize config: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


def _command_amprealize_cleanup(args: argparse.Namespace) -> int:
    """Clean up stale and orphaned containers."""
    from amprealize.executors import PodmanExecutor

    output_mode = getattr(args, "output", "table")
    dry_run = getattr(args, "dry_run", False)
    clean_stale = getattr(args, "stale", True)
    clean_orphans = getattr(args, "orphans", True)
    max_age_hours = getattr(args, "max_age_hours", None)
    all_non_running = getattr(args, "all_non_running", False)

    try:
        executor = PodmanExecutor()

        results = {
            "stale": {"found": 0, "removed": 0, "failed": 0, "details": []},
            "orphans": {"found": 0, "removed": 0, "details": []},
        }

        # Clean stale containers
        if clean_stale:
            stale_result = executor.cleanup_stale_containers(
                include_all=all_non_running,
                max_age_hours=max_age_hours,
                force=True,
                dry_run=dry_run,
            )

            results["stale"]["found"] = stale_result.get("total_found", 0)
            results["stale"]["removed"] = len(stale_result.get("removed", []))
            results["stale"]["failed"] = len(stale_result.get("failed", []))

            if dry_run:
                results["stale"]["details"] = stale_result.get("would_remove", [])
            else:
                results["stale"]["details"] = [
                    {"name": name, "action": "removed"}
                    for name in stale_result.get("removed", [])
                ]
                for name, error in stale_result.get("failed", []):
                    results["stale"]["details"].append({
                        "name": name, "action": "failed", "error": error
                    })

        # Clean orphaned Amprealize containers
        if clean_orphans:
            orphans = executor.find_orphaned_amprealize_containers()
            results["orphans"]["found"] = len(orphans)

            if dry_run:
                results["orphans"]["details"] = [
                    {"name": c.name, "status": c.status, "created": c.created}
                    for c in orphans
                ]
            else:
                removed = executor.cleanup_orphaned_containers()
                results["orphans"]["removed"] = removed
                results["orphans"]["details"] = [
                    {"name": c.name, "action": "removed"} for c in orphans[:removed]
                ]

        # Output results
        if output_mode == "json":
            _print_json(results)
        else:
            _render_cleanup_summary(results, dry_run)

        return 0

    except Exception as e:
        print(f"Error during cleanup: {e}", file=sys.stderr)
        return 1


def _render_cleanup_summary(results: dict, dry_run: bool) -> None:
    """Render cleanup results as a human-readable summary."""
    action_word = "Would remove" if dry_run else "Removed"

    print()
    if dry_run:
        print("=== DRY RUN - No changes made ===")
        print()

    # Stale containers
    stale = results.get("stale", {})
    if stale.get("found", 0) > 0:
        print(f"Stale Containers: {stale['found']} found")
        for item in stale.get("details", []):
            status = item.get("status", "")
            name = item.get("name", "unknown")
            if status:
                print(f"  • {name} ({status})")
            else:
                action = item.get("action", "")
                if action == "failed":
                    print(f"  ✗ {name}: {item.get('error', 'unknown error')}")
                else:
                    print(f"  ✓ {name}")
        print(f"  {action_word}: {stale.get('removed', 0)}")
        if stale.get("failed", 0) > 0:
            print(f"  Failed: {stale['failed']}")
        print()
    else:
        print("Stale Containers: None found")
        print()

    # Orphaned containers
    orphans = results.get("orphans", {})
    if orphans.get("found", 0) > 0:
        print(f"Orphaned Amprealize Containers: {orphans['found']} found")
        for item in orphans.get("details", []):
            name = item.get("name", "unknown")
            status = item.get("status", "")
            if status:
                print(f"  • {name} ({status})")
            else:
                print(f"  ✓ {name}")
        print(f"  {action_word}: {orphans.get('removed', 0)}")
        print()
    else:
        print("Orphaned Amprealize Containers: None found")
        print()

    # Summary
    total_found = stale.get("found", 0) + orphans.get("found", 0)
    total_removed = stale.get("removed", 0) + orphans.get("removed", 0)

    if dry_run:
        print(f"Total: {total_found} containers would be removed")
    else:
        print(f"Total: {total_removed} containers removed")


# ── Amprealize Machine Commands ─────────────────────────────────────────────────

def _get_podman_executor():
    """Get a PodmanExecutor instance for machine management."""
    from amprealize.executors import PodmanExecutor
    return PodmanExecutor()


def _render_machine_table(machines: list) -> None:
    """Render machine list as a table."""
    if not machines:
        print("No Podman machines found.")
        return

    # Header
    print(f"{'NAME':<25} {'STATUS':<12} {'CPUS':<6} {'MEMORY':<10} {'DISK':<10}")
    print("-" * 65)

    for m in machines:
        status = "Running" if m.running else "Stopped"
        cpus = str(m.cpus) if m.cpus else "-"
        memory = f"{m.memory_mb}MB" if m.memory_mb else "-"
        disk = f"{m.disk_gb}GB" if m.disk_gb else "-"
        print(f"{m.name:<25} {status:<12} {cpus:<6} {memory:<10} {disk:<10}")


def _command_amprealize_machine_list(args: argparse.Namespace) -> int:
    """List all Podman machines."""
    try:
        executor = _get_podman_executor()
        machines = executor.list_machines()

        if getattr(args, "output", "table") == "json":
            data = [
                {
                    "name": m.name,
                    "running": m.running,
                    "cpus": m.cpus,
                    "memory_mb": m.memory_mb,
                    "disk_gb": m.disk_gb,
                }
                for m in machines
            ]
            _print_json(data)
        else:
            _render_machine_table(machines)
        return 0
    except Exception as e:
        print(f"Error listing machines: {e}", file=sys.stderr)
        return 1


def _command_amprealize_machine_start(args: argparse.Namespace) -> int:
    """Start a Podman machine."""
    try:
        executor = _get_podman_executor()
        machines = executor.list_machines()

        # Determine which machine to start
        name = args.name
        if not name:
            # Try guideai-ci first, then first available
            guideai_machine = next((m for m in machines if m.name == "guideai-ci"), None)
            if guideai_machine:
                name = "guideai-ci"
            elif machines:
                name = machines[0].name
            else:
                print("No Podman machines found. Use 'guideai amprealize machine ensure' to create one.", file=sys.stderr)
                return 1

        # Check if already running
        machine = executor.get_machine(name)
        if machine and machine.running:
            print(f"Machine '{name}' is already running.")
            return 0

        print(f"Starting machine '{name}'...")
        executor.start_machine(name)
        print(f"✓ Machine '{name}' started successfully.")
        return 0
    except Exception as e:
        print(f"Error starting machine: {e}", file=sys.stderr)
        return 1


def _command_amprealize_machine_stop(args: argparse.Namespace) -> int:
    """Stop a Podman machine."""
    try:
        executor = _get_podman_executor()
        machines = executor.list_machines()

        if args.stop_all:
            # Stop all running machines
            running = [m for m in machines if m.running]
            if not running:
                print("No running machines to stop.")
                return 0

            for m in running:
                print(f"Stopping machine '{m.name}'...")
                executor.stop_machine(m.name)
                print(f"✓ Machine '{m.name}' stopped.")
            return 0

        # Stop a specific machine
        name = args.name
        if not name:
            # Try guideai-ci first, then first running machine
            guideai_machine = next((m for m in machines if m.name == "guideai-ci" and m.running), None)
            if guideai_machine:
                name = "guideai-ci"
            else:
                running = next((m for m in machines if m.running), None)
                if running:
                    name = running.name
                else:
                    print("No running machines to stop.")
                    return 0

        # Check if already stopped
        machine = executor.get_machine(name)
        if machine and not machine.running:
            print(f"Machine '{name}' is already stopped.")
            return 0

        print(f"Stopping machine '{name}'...")
        executor.stop_machine(name)
        print(f"✓ Machine '{name}' stopped successfully.")
        return 0
    except Exception as e:
        print(f"Error stopping machine: {e}", file=sys.stderr)
        return 1


def _command_amprealize_machine_ensure(args: argparse.Namespace) -> int:
    """Ensure a Podman machine is running (start if needed, create if missing)."""
    try:
        executor = _get_podman_executor()
        name = args.name or "guideai-ci"

        machine = executor.get_machine(name)

        if machine:
            if machine.running:
                print(f"✓ Machine '{name}' is already running.")
                return 0
            else:
                print(f"Starting existing machine '{name}'...")
                executor.start_machine(name)
                print(f"✓ Machine '{name}' started successfully.")
                return 0

        # Machine doesn't exist - create it
        print(f"Creating new machine '{name}' (cpus={args.cpus}, memory={args.memory}MB, disk={args.disk}GB)...")
        executor.init_machine(
            name=name,
            cpus=args.cpus,
            memory_mb=args.memory,
            disk_gb=args.disk,
        )

        print(f"Starting machine '{name}'...")
        executor.start_machine(name)
        print(f"✓ Machine '{name}' created and started successfully.")
        return 0
    except Exception as e:
        print(f"Error ensuring machine: {e}", file=sys.stderr)
        return 1


def _command_amprealize_machine_status(args: argparse.Namespace) -> int:
    """Show status of a Podman machine."""
    try:
        executor = _get_podman_executor()
        machines = executor.list_machines()

        # Determine which machine to show
        name = args.name
        if not name:
            # Try guideai-ci first, then first available
            guideai_machine = next((m for m in machines if m.name == "guideai-ci"), None)
            if guideai_machine:
                name = "guideai-ci"
            elif machines:
                name = machines[0].name
            else:
                print("No Podman machines found.", file=sys.stderr)
                return 1

        machine = executor.get_machine(name)
        if not machine:
            print(f"Machine '{name}' not found.", file=sys.stderr)
            return 1

        if getattr(args, "output", "table") == "json":
            # Get detailed info
            try:
                details = executor.inspect_machine(name)
            except Exception:
                details = {}

            data = {
                "name": machine.name,
                "running": machine.running,
                "cpus": machine.cpus,
                "memory_mb": machine.memory_mb,
                "disk_gb": machine.disk_gb,
                "details": details,
            }
            _print_json(data)
        else:
            status = "Running ✓" if machine.running else "Stopped ✗"
            print(f"Machine: {machine.name}")
            print(f"Status:  {status}")
            print(f"CPUs:    {machine.cpus or 'unknown'}")
            print(f"Memory:  {machine.memory_mb}MB" if machine.memory_mb else "Memory:  unknown")
            print(f"Disk:    {machine.disk_gb}GB" if machine.disk_gb else "Disk:    unknown")

        return 0
    except Exception as e:
        print(f"Error getting machine status: {e}", file=sys.stderr)
        return 1


def _command_amprealize_machine_resources(args: argparse.Namespace) -> int:
    """Show resource usage for host and Podman machines."""
    try:
        executor = _get_podman_executor()

        # Get all resources
        resources = executor.get_all_resources()

        if getattr(args, "check", False):
            # Health check mode
            healthy, warnings = executor.check_resource_health(
                min_disk_gb=args.min_disk_gb,
                min_memory_mb=args.min_memory_mb,
            )

            if getattr(args, "output", "table") == "json":
                _print_json({
                    "healthy": healthy,
                    "warnings": warnings,
                    "resources": [r.to_dict() for r in resources],
                })
            else:
                if healthy:
                    print("✓ All resources healthy")
                    print(f"  (Checked: disk >= {args.min_disk_gb}GB, memory >= {args.min_memory_mb}MB)")
                else:
                    print("✗ Resource health check FAILED")
                    for warning in warnings:
                        print(f"  • {warning}")
                    print()
                    print("  💡 To proceed with apply despite low resources, use:")
                    print("     guideai amprealize apply --skip-resource-check")

            return 0 if healthy else 1

        # Display mode
        if getattr(args, "output", "table") == "json":
            _print_json([r.to_dict() for r in resources])
        else:
            _render_resources_table(resources)

        return 0
    except Exception as e:
        print(f"Error getting resources: {e}", file=sys.stderr)
        return 1


def _render_resources_table(resources: list) -> None:
    """Render resource information as a table."""
    for resource in resources:
        source = resource.source
        if source == "host":
            print("═" * 60)
            print("HOST RESOURCES")
            print("═" * 60)
        else:
            print("─" * 60)
            print(f"MACHINE: {source.replace('machine:', '')}")
            print("─" * 60)

        # Disk
        if resource.disk:
            disk = resource.disk
            status = "🔴 CRITICAL" if disk.is_critical else ("🟡 WARNING" if disk.is_warning else "🟢 OK")
            print(f"  Disk:   {disk.used:.1f}/{disk.total:.1f} {disk.unit} ({disk.percent_used:.1f}% used) {status}")
            print(f"          Available: {disk.available:.1f} {disk.unit}")

        # Memory
        if resource.memory:
            mem = resource.memory
            status = "🔴 CRITICAL" if mem.is_critical else ("🟡 WARNING" if mem.is_warning else "🟢 OK")
            print(f"  Memory: {mem.used:.0f}/{mem.total:.0f} {mem.unit} ({mem.percent_used:.1f}% used) {status}")
            print(f"          Available: {mem.available:.0f} {mem.unit}")

        # CPU
        if resource.cpu:
            cpu = resource.cpu
            print(f"  CPU:    {cpu.used:.1f}/{cpu.total:.0f} {cpu.unit} (load avg)")

        # Warnings
        if resource.warnings:
            print("  Warnings:")
            for warning in resource.warnings:
                print(f"    ⚠️  {warning}")

        print()


def _command_amprealize_machine_cleanup(args: argparse.Namespace) -> int:
    """Clean up unused resources to free disk space."""
    try:
        executor = _get_podman_executor()

        dry_run = getattr(args, "dry_run", False)
        aggressive = getattr(args, "aggressive", False)

        result = executor.mitigate_resources(
            dry_run=dry_run,
            prune_containers=not getattr(args, "skip_containers", False),
            prune_images=not getattr(args, "skip_images", False),
            prune_volumes=getattr(args, "include_volumes", False),
            prune_cache=not getattr(args, "skip_cache", False),
            prune_networks=getattr(args, "include_networks", False),
            prune_pods=getattr(args, "include_pods", False),
            prune_logs=getattr(args, "include_logs", False),
            aggressive=aggressive,
        )

        if getattr(args, "output", "table") == "json":
            _print_json(result.to_dict())
        else:
            _render_cleanup_result(result)

        return 0 if result.success else 1
    except Exception as e:
        print(f"Error during cleanup: {e}", file=sys.stderr)
        return 1


def _render_cleanup_result(result) -> None:
    """Render cleanup result as formatted output."""
    action = "Would clean" if result.dry_run else "Cleaned"

    if result.dry_run:
        print("═" * 60)
        print("DRY RUN - No changes made")
        print("═" * 60)
    else:
        print("═" * 60)
        print("CLEANUP COMPLETE")
        print("═" * 60)

    print()

    # Summary
    if result.items_cleaned == 0:
        print("  ✓ Nothing to clean - resources already optimized")
    else:
        if result.containers_removed > 0:
            print(f"  🗑️  {action}: {result.containers_removed} stopped container(s)")
            if result.details.get("containers"):
                for c in result.details["containers"][:5]:  # Show first 5
                    print(f"      • {c.get('name', c.get('id', 'unknown'))}")
                if len(result.details["containers"]) > 5:
                    print(f"      ... and {len(result.details['containers']) - 5} more")

        if result.images_removed > 0:
            print(f"  🗑️  {action}: {result.images_removed} unused image(s)")
            if result.details.get("images"):
                for img in result.details["images"][:5]:
                    print(f"      • {img.get('name', img.get('id', 'unknown'))}")
                if len(result.details["images"]) > 5:
                    print(f"      ... and {len(result.details['images']) - 5} more")

        if result.volumes_removed > 0:
            print(f"  🗑️  {action}: {result.volumes_removed} unused volume(s)")

        if result.networks_removed > 0:
            print(f"  🗑️  {action}: {result.networks_removed} unused network(s)")
            if result.details.get("networks"):
                for net in result.details["networks"][:5]:
                    print(f"      • {net}")
                if len(result.details["networks"]) > 5:
                    print(f"      ... and {len(result.details['networks']) - 5} more")

        if result.pods_removed > 0:
            print(f"  🗑️  {action}: {result.pods_removed} stopped pod(s)")
            if result.details.get("pods"):
                for pod in result.details["pods"][:5]:
                    print(f"      • {pod}")
                if len(result.details["pods"]) > 5:
                    print(f"      ... and {len(result.details['pods']) - 5} more")

        if result.logs_truncated > 0:
            print(f"  🗑️  {action}: {result.logs_truncated} container log(s)")

        if result.cache_cleared:
            print(f"  🗑️  {action}: build cache")

        if result.space_reclaimed_mb > 0:
            if result.space_reclaimed_mb > 1024:
                print(f"\n  📊 Estimated space {'to reclaim' if result.dry_run else 'reclaimed'}: {result.space_reclaimed_mb/1024:.1f} GB")
            else:
                print(f"\n  📊 Estimated space {'to reclaim' if result.dry_run else 'reclaimed'}: {result.space_reclaimed_mb:.0f} MB")

    # Errors
    if result.errors:
        print("\n  ⚠️  Warnings/Errors:")
        for error in result.errors:
            print(f"      • {error}")

    print()

    if result.dry_run:
        print("  💡 Run without --dry-run to perform the cleanup")


def _command_scan_secrets(args: argparse.Namespace) -> int:
    return run_scan(
        output_path=Path(args.output).resolve() if args.output else DEFAULT_OUTPUT.resolve(),
        fmt=args.format,
        fail_on_findings=args.fail_on_findings,
    )


def _command_bandwidth_check(args: argparse.Namespace) -> int:
    """Check current bandwidth usage against environment limits."""
    try:
        # Load environment config to get the limit
        from guideai.amprealize import AmprealizeService

        # Initialize dependencies
        action_adapter = _get_action_adapter()
        compliance_adapter = _get_compliance_adapter()
        metrics_adapter = _get_metrics_adapter()

        service = AmprealizeService(
            action_service=action_adapter._service,
            compliance_service=compliance_adapter._service,
            metrics_service=metrics_adapter._service
        )

        # We need to know which environment we are checking for. Default to 'dev' or take from args.
        env_name = getattr(args, "environment", "dev")

        # AmprealizeService loads config in __init__ and stores in self.environments
        if env_name not in service.environments:
            print(f"Error: Environment '{env_name}' not found in configuration.", file=sys.stderr)
            return 1

        env_config = service.environments[env_name]
        limit_mbps = env_config.runtime.network_mbps

        if limit_mbps is None:
             print(f"No bandwidth limit defined for environment '{env_name}'.", file=sys.stderr)
             # We can still show usage, treat limit as infinite
             limit_mbps_val = float('inf')
        else:
             limit_mbps_val = float(limit_mbps)

        print(f"Checking bandwidth usage for environment: {env_name} (Limit: {limit_mbps_val} Mbps)")

        enforcer = BandwidthEnforcer(limit_mbps=limit_mbps)

        # Check usage
        stats = service.get_network_stats()
        usage_mbps = enforcer.get_current_usage_mbps(stats)

        print(f"Current Usage: {usage_mbps:.2f} Mbps")

        if usage_mbps > limit_mbps_val:
            print("Status: OVER LIMIT ⚠️")
            return 1
        else:
            print("Status: OK ✅")
            return 0

    except Exception as e:
        print(f"Error checking bandwidth: {e}", file=sys.stderr)
        return 1


# ── Audit Log Commands ────────────────────────────────────────────────────────

_audit_service_singleton: Optional[Any] = None


def _get_audit_service() -> Any:
    """Lazy singleton for AuditLogService."""
    global _audit_service_singleton
    if _audit_service_singleton is None:
        from guideai.services.audit_log_service import AuditLogService
        from guideai.config.settings import get_settings

        settings = get_settings()
        _audit_service_singleton = AuditLogService(settings=settings)
    return _audit_service_singleton


def _command_audit_verify(args: argparse.Namespace) -> int:
    """Verify integrity of an archived audit batch."""
    output_mode = _resolve_output_format(getattr(args, "output", None))

    try:
        service = _get_audit_service()
        public_key_path = getattr(args, "public_key", None)

        result = service.verify_archive(
            batch_id=args.batch_id,
            public_key_path=public_key_path,
        )

        if output_mode == "json":
            _print_json(result)
        else:
            print(f"Batch ID: {result.get('batch_id', args.batch_id)}")
            print(f"Archive Key: {result.get('archive_key', 'N/A')}")
            print(f"Event Count: {result.get('event_count', 'N/A')}")
            print(f"Content Hash: {result.get('content_hash', 'N/A')[:16]}...")
            print()

            if result.get("integrity_valid"):
                print("✅ Content Integrity: VALID")
            else:
                print(f"❌ Content Integrity: INVALID - {result.get('integrity_error', 'hash mismatch')}")

            if result.get("signature_valid") is True:
                print("✅ Signature: VALID")
            elif result.get("signature_valid") is False:
                print(f"❌ Signature: INVALID - {result.get('signature_error', 'verification failed')}")
            else:
                print("⚠️  Signature: NOT VERIFIED (no public key provided)")

            retention = result.get("retention_info", {})
            if retention:
                print()
                print(f"Retention Mode: {retention.get('mode', 'N/A')}")
                print(f"Retain Until: {retention.get('retain_until_date', 'N/A')}")
                print(f"Legal Hold: {retention.get('legal_hold_status', 'N/A')}")

        # Return 0 only if integrity is valid
        return 0 if result.get("integrity_valid") else 1

    except Exception as e:
        print(f"Error verifying audit batch: {e}", file=sys.stderr)
        return 1


def _command_audit_list(args: argparse.Namespace) -> int:
    """List archived audit batches."""
    output_mode = _resolve_output_format(getattr(args, "output", None))

    try:
        service = _get_audit_service()
        prefix = getattr(args, "prefix", None)
        limit = getattr(args, "limit", 100)

        batches = service.list_archives(prefix=prefix, limit=limit)

        if output_mode == "json":
            _print_json({"batches": batches, "count": len(batches)})
        else:
            if not batches:
                print("No archived audit batches found.")
                return 0

            headers = ["Batch ID", "Archived At", "Event Count", "Size (KB)"]
            widths = [len(h) for h in headers]
            rows = []

            for batch in batches:
                row = [
                    batch.get("batch_id", "-")[:36],
                    batch.get("archived_at", "-")[:19],
                    str(batch.get("event_count", "-")),
                    f"{batch.get('size_bytes', 0) / 1024:.1f}",
                ]
                rows.append(row)
                widths = [max(w, len(v)) for w, v in zip(widths, row)]

            fmt = " | ".join(f"{{:<{w}}}" for w in widths)
            separator = "-+-".join("-" * w for w in widths)

            print(fmt.format(*headers))
            print(separator)
            for row in rows:
                print(fmt.format(*row))

            print(f"\nTotal: {len(batches)} batches")

        return 0

    except Exception as e:
        print(f"Error listing audit batches: {e}", file=sys.stderr)
        return 1


def _command_audit_retention(args: argparse.Namespace) -> int:
    """Check retention info for an archived batch."""
    output_mode = _resolve_output_format(getattr(args, "output", None))

    try:
        service = _get_audit_service()

        retention = service.get_retention_info(batch_id=args.batch_id)

        if output_mode == "json":
            _print_json(retention)
        else:
            print(f"Batch ID: {args.batch_id}")
            print(f"Archive Key: {retention.get('archive_key', 'N/A')}")
            print()
            print(f"Object Lock Mode: {retention.get('mode', 'N/A')}")
            print(f"Retain Until: {retention.get('retain_until_date', 'N/A')}")
            print(f"Legal Hold: {retention.get('legal_hold_status', 'OFF')}")
            print(f"Versioned: {retention.get('is_versioned', False)}")

            if retention.get("version_id"):
                print(f"Version ID: {retention.get('version_id')}")

        return 0

    except Exception as e:
        print(f"Error getting retention info: {e}", file=sys.stderr)
        return 1


# ── Migration Commands ──────────────────────────────────────────────────────────

# Service configuration for migrations
_MIGRATION_CONFIG = {
    "behavior": {
        "migration": "001_create_behavior_service.sql",
        "dsn_env": "GUIDEAI_BEHAVIOR_PG_DSN",
        "tables": ["behaviors", "behavior_history"],
    },
    "workflow": {
        "migration": "003_create_workflow_service.sql",
        "dsn_env": "GUIDEAI_WORKFLOW_PG_DSN",
        "tables": ["workflow_templates", "workflow_runs", "workflow_steps"],
    },
    "action": {
        "migration": "004_create_action_service.sql",
        "dsn_env": "GUIDEAI_ACTION_PG_DSN",
        "tables": ["actions", "replays"],
    },
    "run": {
        "migration": "005_create_run_service.sql",
        "dsn_env": "GUIDEAI_RUN_PG_DSN",
        "tables": ["runs", "run_steps"],
    },
    "compliance": {
        "migration": "006_create_compliance_service.sql",
        "dsn_env": "GUIDEAI_COMPLIANCE_PG_DSN",
        "tables": ["compliance_checklists", "compliance_steps", "compliance_policies"],
    },
    "metrics": {
        "migration": "007_create_metrics_service.sql",
        "dsn_env": "GUIDEAI_METRICS_PG_DSN",
        "tables": ["metrics", "metric_snapshots"],
    },
    "reflection": {
        "migration": "020_create_reflection_service.sql",
        "dsn_env": "GUIDEAI_REFLECTION_PG_DSN",
        "tables": ["reflection_patterns", "behavior_candidates", "pattern_observations", "reflection_sessions"],
    },
    "collaboration": {
        "migration": "021_create_collaboration_service.sql",
        "dsn_env": "GUIDEAI_COLLABORATION_PG_DSN",
        "tables": ["workspaces", "workspace_members", "documents", "edit_operations", "comments", "activity_logs"],
    },
}


def _get_migration_path(migration_file: str) -> Path:
    """Get absolute path to a migration file."""
    repo_root = Path(__file__).parent.parent
    return repo_root / "schema" / "migrations" / migration_file


def _check_service_tables(dsn: str, tables: List[str]) -> Dict[str, bool]:
    """Check which tables exist for a service."""
    try:
        import psycopg2
    except ImportError:
        return {table: False for table in tables}

    result = {}
    try:
        with psycopg2.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                for table in tables:
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'public' AND table_name = %s
                        )
                        """,
                        (table,)
                    )
                    row = cur.fetchone()
                    result[table] = bool(row and row[0])
    except Exception:
        result = {table: False for table in tables}
    return result


def _apply_migration(dsn: str, migration_path: Path) -> bool:
    """Apply a single migration file."""
    try:
        import psycopg2
    except ImportError:
        print("  ❌ psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
        return False

    if not migration_path.exists():
        print(f"  ❌ Migration file not found: {migration_path}", file=sys.stderr)
        return False

    sql = migration_path.read_text(encoding="utf-8")

    try:
        with psycopg2.connect(dsn, connect_timeout=10) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql)
        return True
    except Exception as e:
        print(f"  ❌ Migration failed: {e}", file=sys.stderr)
        return False


def _command_migrate_apply(args: argparse.Namespace) -> int:
    """Apply pending schema migrations."""
    services = list(_MIGRATION_CONFIG.keys()) if args.service == "all" else [args.service]
    dry_run = getattr(args, "dry_run", False)

    print("=" * 70)
    print("GuideAI PostgreSQL Migration")
    print("=" * 70)
    print()

    results = []
    for service in services:
        config = _MIGRATION_CONFIG[service]
        dsn = apply_host_overrides(os.environ.get(config["dsn_env"]), service.upper())

        print(f"Service: {service}")

        if not dsn:
            print(f"  ⏭️  Skipped: {config['dsn_env']} not set")
            results.append((service, "skipped", "DSN not configured"))
            print()
            continue

        # Check existing tables
        table_status = _check_service_tables(dsn, config["tables"])
        existing = sum(1 for v in table_status.values() if v)
        total = len(config["tables"])

        if existing == total:
            print(f"  ✅ Already migrated: {existing}/{total} tables exist")
            results.append((service, "exists", f"{existing}/{total} tables"))
            print()
            continue

        migration_path = _get_migration_path(config["migration"])
        print(f"  📄 Migration: {config['migration']}")
        print(f"  📊 Tables: {existing}/{total} exist")

        if dry_run:
            print(f"  🔍 Would apply migration (dry-run)")
            results.append((service, "pending", f"{total - existing} tables to create"))
        else:
            print(f"  ⏳ Applying migration...")
            if _apply_migration(dsn, migration_path):
                print(f"  ✅ Migration applied successfully")
                results.append((service, "applied", f"{total} tables created"))
            else:
                results.append((service, "failed", "See error above"))
        print()

    # Summary
    print("=" * 70)
    print("Migration Summary")
    print("=" * 70)
    for service, status, detail in results:
        status_icon = {
            "applied": "✅",
            "exists": "✅",
            "pending": "🔍",
            "skipped": "⏭️",
            "failed": "❌",
        }.get(status, "❓")
        print(f"  {status_icon} {service}: {status} ({detail})")

    failed = sum(1 for _, status, _ in results if status == "failed")
    return 1 if failed > 0 else 0


def _command_migrate_status(args: argparse.Namespace) -> int:
    """Check migration status for all services."""
    output_mode = _resolve_output_format(getattr(args, "format", None))

    status_data = []
    for service, config in _MIGRATION_CONFIG.items():
        dsn = apply_host_overrides(os.environ.get(config["dsn_env"]), service.upper())

        entry = {
            "service": service,
            "dsn_env": config["dsn_env"],
            "dsn_configured": bool(dsn),
            "migration_file": config["migration"],
            "tables": {},
            "status": "unconfigured",
        }

        if dsn:
            table_status = _check_service_tables(dsn, config["tables"])
            entry["tables"] = table_status
            existing = sum(1 for v in table_status.values() if v)
            total = len(config["tables"])

            if existing == total:
                entry["status"] = "migrated"
            elif existing > 0:
                entry["status"] = "partial"
            else:
                entry["status"] = "pending"

        status_data.append(entry)

    if output_mode == "json":
        _print_json(status_data)
    else:
        print("=" * 70)
        print("PostgreSQL Migration Status")
        print("=" * 70)
        print()

        for entry in status_data:
            status_icon = {
                "migrated": "✅",
                "partial": "⚠️",
                "pending": "🔄",
                "unconfigured": "⏭️",
            }.get(entry["status"], "❓")

            print(f"{status_icon} {entry['service']}")
            print(f"   Env: {entry['dsn_env']}")
            print(f"   Status: {entry['status']}")

            if entry["dsn_configured"] and entry["tables"]:
                existing = sum(1 for v in entry["tables"].values() if v)
                total = len(entry["tables"])
                print(f"   Tables: {existing}/{total}")
            print()

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    if args.command == "scan-secrets":
        return _command_scan_secrets(args)
    elif args.command == "record-action":
        return _command_record_action(args)
    elif args.command == "list-actions":
        return _command_list_actions(args)
    elif args.command == "get-action":
        return _command_get_action(args)
    elif args.command == "replay-actions":
        return _command_replay_actions(args)
    elif args.command == "replay-status":
        return _command_replay_status(args)
    elif args.command == "dr":
        return _command_dr(args)
    elif args.command == "tasks":
        return _command_list_tasks(args)
    elif args.command == "behaviors":
        if args.behaviors_command == "create":
            return _command_behaviors_create(args)
        elif args.behaviors_command == "list":
            return _command_behaviors_list(args)
        elif args.behaviors_command == "search":
            return _command_behaviors_search(args)
        elif args.behaviors_command == "get":
            return _command_behaviors_get(args)
        elif args.behaviors_command == "update":
            return _command_behaviors_update(args)
        elif args.behaviors_command == "submit":
            return _command_behaviors_submit(args)
        elif args.behaviors_command == "approve":
            return _command_behaviors_approve(args)
        elif args.behaviors_command == "deprecate":
            return _command_behaviors_deprecate(args)
        elif args.behaviors_command == "delete-draft":
            return _command_behaviors_delete_draft(args)
    elif args.command == "compliance":
        if args.compliance_command == "create-checklist":
            return _command_compliance_create_checklist(args)
        elif args.compliance_command == "record-step":
            return _command_compliance_record_step(args)
        elif args.compliance_command == "list":
            return _command_compliance_list(args)
        elif args.compliance_command == "get":
            return _command_compliance_get(args)
        elif args.compliance_command == "validate":
            return _command_compliance_validate(args)
        elif args.compliance_command == "policies":
            if hasattr(args, "policies_command") and args.policies_command == "list":
                return _command_compliance_policies_list(args)
            elif hasattr(args, "policies_command") and args.policies_command == "create":
                return _command_compliance_policies_create(args)
            elif hasattr(args, "policies_command") and args.policies_command == "get":
                return _command_compliance_policies_get(args)
        elif args.compliance_command == "audit":
            return _command_compliance_audit(args)
    elif args.command == "workflow":
        if args.workflow_command == "create-template":
            return _command_workflow_create_template(args)
        elif args.workflow_command == "list-templates":
            return _command_workflow_list_templates(args)
        elif args.workflow_command == "get-template":
            return _command_workflow_get_template(args)
        elif args.workflow_command == "run":
            return _command_workflow_run(args)
        elif args.workflow_command == "status":
            return _command_workflow_status(args)
    elif args.command == "amprealize":
        if args.amprealize_command == "plan":
            return _command_amprealize_plan(args)
        elif args.amprealize_command == "apply":
            return _command_amprealize_apply(args)
        elif args.amprealize_command == "status":
            return _command_amprealize_status(args)
        elif args.amprealize_command == "destroy":
            return _command_amprealize_destroy(args)
        elif args.amprealize_command == "bootstrap":
            return _command_amprealize_bootstrap(args)
        elif args.amprealize_command == "cleanup":
            return _command_amprealize_cleanup(args)
        elif args.amprealize_command == "machine":
            if not hasattr(args, "machine_command") or not args.machine_command:
                print("Usage: guideai amprealize machine {list,start,stop,ensure,status,resources}", file=sys.stderr)
                return 1
            if args.machine_command == "list":
                return _command_amprealize_machine_list(args)
            elif args.machine_command == "start":
                return _command_amprealize_machine_start(args)
            elif args.machine_command == "stop":
                return _command_amprealize_machine_stop(args)
            elif args.machine_command == "ensure":
                return _command_amprealize_machine_ensure(args)
            elif args.machine_command == "status":
                return _command_amprealize_machine_status(args)
            elif args.machine_command == "resources":
                return _command_amprealize_machine_resources(args)
            elif args.machine_command == "cleanup":
                return _command_amprealize_machine_cleanup(args)
    elif args.command == "telemetry":
        if args.telemetry_command == "emit":
            return _command_telemetry_emit(args)
        elif args.telemetry_command == "query":
            return _command_telemetry_query(args)
        elif args.telemetry_command == "dashboard":
            return _command_telemetry_dashboard(args)
    elif args.command == "agents":
        if args.agents_command == "assign":
            return _command_agents_assign(args)
        elif args.agents_command == "status":
            return _command_agents_status(args)
        elif args.agents_command == "switch":
            return _command_agents_switch(args)
    elif args.command == "analytics":
        if args.analytics_command == "project":
            return _command_analytics_project(args)
        elif args.analytics_command == "kpi-summary":
            return _command_analytics_kpi_summary(args)
        elif args.analytics_command == "project-kpi":
            return _command_analytics_project_kpi(args)
        elif args.analytics_command == "behavior-usage":
            return _command_analytics_behavior_usage(args)
        elif args.analytics_command == "token-savings":
            return _command_analytics_token_savings(args)
        elif args.analytics_command == "compliance-coverage":
            return _command_analytics_compliance_coverage(args)
        elif args.analytics_command == "cost-by-service":
            return _command_analytics_cost_by_service(args)
        elif args.analytics_command == "cost-per-run":
            return _command_analytics_cost_per_run(args)
        elif args.analytics_command == "roi-summary":
            return _command_analytics_roi_summary(args)
        elif args.analytics_command == "daily-costs":
            return _command_analytics_daily_costs(args)
        elif args.analytics_command == "top-expensive":
            return _command_analytics_top_expensive(args)
    elif args.command == "metrics":
        if args.metrics_command == "summary":
            return _command_metrics_summary(args)
        elif args.metrics_command == "export":
            return _command_metrics_export(args)
    elif args.command == "auth":
        if args.auth_command == "ensure-grant":
            return _command_auth_ensure_grant(args)
        elif args.auth_command == "list-grants":
            return _command_auth_list_grants(args)
        elif args.auth_command == "policy-preview":
            return _command_auth_policy_preview(args)
        elif args.auth_command == "revoke":
            return _command_auth_revoke(args)
        elif args.auth_command == "register":
            return _command_auth_register(args)
        elif args.auth_command == "login":
            return _command_auth_login(args)
        elif args.auth_command == "status":
            return _command_auth_status(args)
        elif args.auth_command == "logout":
            return _command_auth_logout(args)
        elif args.auth_command == "refresh":
            return _command_auth_refresh(args)
        elif args.auth_command == "consent-lookup":
            return _command_auth_consent_lookup(args)
        elif args.auth_command == "consent-approve":
            return _command_auth_consent_approve(args)
        elif args.auth_command == "consent-deny":
            return _command_auth_consent_deny(args)
    elif args.command == "bci":
        if args.bci_command == "rebuild-index":
            return _command_bci_rebuild_index(args)
        elif args.bci_command == "retrieve":
            return _command_bci_retrieve(args)
        elif args.bci_command == "compose-prompt":
            return _command_bci_compose_prompt(args)
        elif args.bci_command == "validate-citations":
            return _command_bci_validate_citations(args)
        elif args.bci_command == "generate":
            return _command_bci_generate(args)
        elif args.bci_command == "improve":
            return _command_bci_improve(args)
    elif args.command == "audit":
        if args.audit_command == "verify":
            return _command_audit_verify(args)
        elif args.audit_command == "list":
            return _command_audit_list(args)
        elif args.audit_command == "retention":
            return _command_audit_retention(args)
    elif args.command == "reflection":
        return _command_reflection(args)
    elif args.command == "migrate":
        if args.migrate_command == "apply":
            return _command_migrate_apply(args)
        elif args.migrate_command == "status":
            return _command_migrate_status(args)

    # If no command matched or no subcommand provided
    print("Error: No command specified or command not recognized", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
