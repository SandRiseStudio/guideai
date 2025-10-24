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
import webbrowser
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from guideai.action_service import ActionService
from guideai.adapters import (
    CLIAgentAuthServiceAdapter,
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
from guideai.metrics_service import MetricsService
from guideai.reflection_service import ReflectionService
from guideai.reflection_contracts import TraceFormat
from guideai.run_service import RunService
from guideai.task_assignments import TaskAssignmentService
from guideai.telemetry import FileTelemetrySink, TelemetryClient
from guideai.workflow_service import WorkflowService
from guideai.auth_tokens import (
    AuthTokenBundle,
    TokenStore,
    TokenStoreError,
    get_default_token_store,
)

DEFAULT_OUTPUT = Path("security/scan_reports/latest.json")
DEFAULT_ACTOR_ID = "local-cli"
DEFAULT_ACTOR_ROLE = "STRATEGIST"
DEFAULT_TELEMETRY_EVENTS_PATH = Path.home() / ".guideai" / "telemetry" / "events.jsonl"

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
        db_path = Path.home() / ".guideai" / "workflows.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _WORKFLOW_SERVICE = WorkflowService(db_path=db_path, behavior_service=_BEHAVIOR_SERVICE)
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
    global _REFLECTION_SERVICE, _REFLECTION_ADAPTER, _BEHAVIOR_SERVICE, _BCI_SERVICE
    if _BEHAVIOR_SERVICE is None:
        _BEHAVIOR_SERVICE = BehaviorService()
    if _BCI_SERVICE is None:
        _BCI_SERVICE = BCIService(behavior_service=_BEHAVIOR_SERVICE)
    if _REFLECTION_SERVICE is None:
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
        telemetry_path = DEFAULT_TELEMETRY_EVENTS_PATH
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry = TelemetryClient(
            sink=FileTelemetrySink(telemetry_path),
            default_actor={
                "id": DEFAULT_ACTOR_ID,
                "role": DEFAULT_ACTOR_ROLE,
                "surface": "CLI",
            },
        )
        _DEVICE_FLOW_MANAGER = DeviceFlowManager(telemetry=telemetry)
    return _DEVICE_FLOW_MANAGER


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
    compliance_validate_parser.add_argument("checklist_id", help="Checklist identifier")
    compliance_validate_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    compliance_validate_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    compliance_validate_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
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
        help="Execute a workflow template with behavior-conditioned inference",
    )
    workflow_run_parser.add_argument("template_id", help="Template to execute")
    workflow_run_parser.add_argument(
        "--behavior",
        dest="behavior_ids",
        action="append",
        default=[],
        help="Behavior ID to inject (repeatable, auto-retrieves if omitted)",
    )
    workflow_run_parser.add_argument("--metadata-file", help="Path to JSON run metadata")
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

    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Telemetry utilities",
    )
    telemetry_subparsers = telemetry_parser.add_subparsers(dest="telemetry_command")

    telemetry_emit_parser = telemetry_subparsers.add_parser(
        "emit",
        help="Emit a telemetry event",
    )
    telemetry_emit_parser.add_argument("--event-type", required=True, help="Telemetry event type")
    telemetry_emit_parser.add_argument(
        "--payload",
        default="{}",
        help="JSON payload for the event",
    )
    telemetry_emit_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    telemetry_emit_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    telemetry_emit_parser.add_argument(
        "--actor-surface",
        default="CLI",
        help="Surface emitting the event (e.g., CLI, VSCODE, WEB)",
    )
    telemetry_emit_parser.add_argument("--run-id", help="Associated workflow run identifier")
    telemetry_emit_parser.add_argument("--action-id", help="Associated action identifier")
    telemetry_emit_parser.add_argument("--session-id", help="Telemetry session identifier")
    telemetry_emit_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    analytics_parser = subparsers.add_parser(
        "analytics",
        help="Analytics utilities",
    )
    analytics_subparsers = analytics_parser.add_subparsers(dest="analytics_command")

    analytics_project_parser = analytics_subparsers.add_parser(
        "project-kpi",
        help="Project telemetry events into PRD KPI fact collections",
    )
    analytics_project_parser.add_argument(
        "--input",
        default=str(DEFAULT_TELEMETRY_EVENTS_PATH),
        help="Path to telemetry JSONL input (defaults to ~/.guideai/telemetry/events.jsonl)",
    )
    analytics_project_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format for the KPI summary",
    )
    analytics_project_parser.add_argument(
        "--facts-output",
        dest="facts_output",
        help="Optional path to write the full KPI projection as JSON",
    )

    # Analytics warehouse query subcommands
    analytics_summary_parser = analytics_subparsers.add_parser(
        "kpi-summary",
        help="Query KPI summary from DuckDB analytics warehouse",
    )
    analytics_summary_parser.add_argument(
        "--start-date",
        dest="start_date",
        help="Start date filter (YYYY-MM-DD format)",
    )
    analytics_summary_parser.add_argument(
        "--end-date",
        dest="end_date",
        help="End date filter (YYYY-MM-DD format)",
    )
    analytics_summary_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    analytics_behavior_usage_parser = analytics_subparsers.add_parser(
        "behavior-usage",
        help="Query behavior usage facts from analytics warehouse",
    )
    analytics_behavior_usage_parser.add_argument(
        "--start-date",
        dest="start_date",
        help="Start date filter (YYYY-MM-DD format)",
    )
    analytics_behavior_usage_parser.add_argument(
        "--end-date",
        dest="end_date",
        help="End date filter (YYYY-MM-DD format)",
    )
    analytics_behavior_usage_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of records to return (1-1000)",
    )
    analytics_behavior_usage_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    analytics_token_savings_parser = analytics_subparsers.add_parser(
        "token-savings",
        help="Query token savings facts from analytics warehouse",
    )
    analytics_token_savings_parser.add_argument(
        "--start-date",
        dest="start_date",
        help="Start date filter (YYYY-MM-DD format)",
    )
    analytics_token_savings_parser.add_argument(
        "--end-date",
        dest="end_date",
        help="End date filter (YYYY-MM-DD format)",
    )
    analytics_token_savings_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of records to return (1-1000)",
    )
    analytics_token_savings_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    analytics_compliance_coverage_parser = analytics_subparsers.add_parser(
        "compliance-coverage",
        help="Query compliance coverage facts from analytics warehouse",
    )
    analytics_compliance_coverage_parser.add_argument(
        "--start-date",
        dest="start_date",
        help="Start date filter (YYYY-MM-DD format)",
    )
    analytics_compliance_coverage_parser.add_argument(
        "--end-date",
        dest="end_date",
        help="End date filter (YYYY-MM-DD format)",
    )
    analytics_compliance_coverage_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of records to return (1-1000)",
    )
    analytics_compliance_coverage_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    metrics_parser = subparsers.add_parser(
        "metrics",
        help="Real-time metrics aggregation and streaming",
    )
    metrics_subparsers = metrics_parser.add_subparsers(dest="metrics_command")

    metrics_summary_parser = metrics_subparsers.add_parser(
        "summary",
        help="Get real-time metrics summary with PRD KPI targets",
    )
    metrics_summary_parser.add_argument(
        "--start-date",
        dest="start_date",
        help="ISO timestamp for start of date range (optional)",
    )
    metrics_summary_parser.add_argument(
        "--end-date",
        dest="end_date",
        help="ISO timestamp for end of date range (optional)",
    )
    metrics_summary_parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        help="Bypass cache and fetch fresh data",
    )
    metrics_summary_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    metrics_export_parser = metrics_subparsers.add_parser(
        "export",
        help="Export metrics data to file or stdout",
    )
    metrics_export_parser.add_argument(
        "--format",
        dest="export_format",
        choices=("json", "csv", "parquet"),
        default="json",
        help="Export file format",
    )
    metrics_export_parser.add_argument(
        "--start-date",
        dest="start_date",
        help="ISO timestamp for start of date range (optional)",
    )
    metrics_export_parser.add_argument(
        "--end-date",
        dest="end_date",
        help="ISO timestamp for end of date range (optional)",
    )
    metrics_export_parser.add_argument(
        "--metric",
        dest="metrics",
        action="append",
        default=[],
        help="Specific metric to include (repeatable, empty = all)",
    )
    metrics_export_parser.add_argument(
        "--include-raw-events",
        dest="include_raw_events",
        action="store_true",
        help="Include raw telemetry events in export",
    )
    metrics_export_parser.add_argument(
        "--output",
        dest="output_file",
        help="Output file path (if omitted, writes to stdout)",
    )
    metrics_export_parser.add_argument(
        "--output-format",
        dest="output_format",
        choices=("json", "table"),
        default="json",
        help="CLI output format (for export metadata)",
    )

    # AgentAuth CLI parser setup
    auth_parser = subparsers.add_parser(
        "auth",
        help="Authentication and authorization for tool invocations",
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")

    # auth ensure-grant
    auth_ensure_grant_parser = auth_subparsers.add_parser(
        "ensure-grant",
        help="Request or reuse a grant for tool access",
    )
    auth_ensure_grant_parser.add_argument(
        "--agent-id",
        dest="agent_id",
        required=True,
        help="ID of the agent requesting access",
    )
    auth_ensure_grant_parser.add_argument(
        "--tool-name",
        dest="tool_name",
        required=True,
        help="Name of the tool being accessed",
    )
    auth_ensure_grant_parser.add_argument(
        "--scopes",
        dest="scopes",
        nargs="+",
        required=True,
        help="Scopes required for the operation",
    )
    auth_ensure_grant_parser.add_argument(
        "--user-id",
        dest="user_id",
        help="ID of the user (if applicable)",
    )
    auth_ensure_grant_parser.add_argument(
        "--context",
        dest="context",
        nargs="*",
        help="Context key=value pairs (e.g., project_id=123 env=prod)",
    )
    auth_ensure_grant_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    # auth list-grants
    auth_list_grants_parser = auth_subparsers.add_parser(
        "list-grants",
        help="List active grants with optional filtering",
    )
    auth_list_grants_parser.add_argument(
        "--agent-id",
        dest="agent_id",
        required=True,
        help="Agent ID to list grants for",
    )
    auth_list_grants_parser.add_argument(
        "--user-id",
        dest="user_id",
        help="Filter by user ID",
    )
    auth_list_grants_parser.add_argument(
        "--tool-name",
        dest="tool_name",
        help="Filter by tool name",
    )
    auth_list_grants_parser.add_argument(
        "--include-expired",
        dest="include_expired",
        action="store_true",
        help="Include expired grants in results",
    )
    auth_list_grants_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    # auth policy-preview
    auth_policy_preview_parser = auth_subparsers.add_parser(
        "policy-preview",
        help="Preview policy decision without creating a grant",
    )
    auth_policy_preview_parser.add_argument(
        "--agent-id",
        dest="agent_id",
        required=True,
        help="ID of the agent requesting access",
    )
    auth_policy_preview_parser.add_argument(
        "--tool-name",
        dest="tool_name",
        required=True,
        help="Name of the tool being accessed",
    )
    auth_policy_preview_parser.add_argument(
        "--scopes",
        dest="scopes",
        nargs="+",
        required=True,
        help="Scopes required for the operation",
    )
    auth_policy_preview_parser.add_argument(
        "--user-id",
        dest="user_id",
        help="ID of the user (if applicable)",
    )
    auth_policy_preview_parser.add_argument(
        "--context",
        dest="context",
        nargs="*",
        help="Context key=value pairs (e.g., project_id=123 env=prod)",
    )
    auth_policy_preview_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    # auth revoke
    auth_revoke_parser = auth_subparsers.add_parser(
        "revoke",
        help="Revoke an active grant by ID",
    )
    auth_revoke_parser.add_argument(
        "--grant-id",
        dest="grant_id",
        required=True,
        help="ID of the grant to revoke",
    )
    auth_revoke_parser.add_argument(
        "--revoked-by",
        dest="revoked_by",
        required=True,
        help="Identity revoking the grant (user ID, admin ID, etc.)",
    )
    auth_revoke_parser.add_argument(
        "--reason",
        dest="reason",
        help="Optional reason for revocation",
    )
    auth_revoke_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    # auth login (device code flow)
    auth_login_parser = auth_subparsers.add_parser(
        "login",
        help="Authenticate this CLI via device code flow",
    )
    auth_login_parser.add_argument(
        "--client-id",
        dest="client_id",
        default="guideai.cli",
        help="Client identifier used when initiating device flow",
    )
    auth_login_parser.add_argument(
        "--scope",
        dest="scopes",
        action="append",
        default=[],
        help="Requested OAuth scope (repeatable; defaults to actions.read)",
    )
    auth_login_parser.add_argument(
        "--open-browser",
        dest="open_browser",
        action="store_true",
        help="Launch the verification URL in the default browser",
    )
    auth_login_parser.add_argument(
        "--timeout",
        dest="timeout",
        type=int,
        default=600,
        help="Seconds to wait for approval before timing out",
    )
    auth_login_parser.add_argument(
        "--quiet",
        dest="quiet",
        action="store_true",
        help="Suppress polling status updates",
    )
    auth_login_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        help="Permit plaintext token storage when keychain is unavailable",
    )

    # auth refresh (token rotation)
    auth_refresh_parser = auth_subparsers.add_parser(
        "refresh",
        help="Refresh cached access token using the stored refresh token",
    )
    auth_refresh_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        help="Permit plaintext token storage when keychain is unavailable",
    )
    auth_refresh_parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="Refresh even if the cached access token is still valid",
    )
    auth_refresh_parser.add_argument(
        "--quiet",
        dest="quiet",
        action="store_true",
        help="Suppress output on successful refresh",
    )

    # auth status
    auth_status_parser = auth_subparsers.add_parser(
        "status",
        help="Display cached authentication token metadata",
    )
    auth_status_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )
    auth_status_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        help="Permit plaintext token storage when keychain is unavailable",
    )

    # auth logout
    auth_logout_parser = auth_subparsers.add_parser(
        "logout",
        help="Clear cached authentication tokens",
    )
    auth_logout_parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    auth_logout_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        help="Permit plaintext token storage when keychain is unavailable",
    )

    # auth consent management
    auth_consent_parser = auth_subparsers.add_parser(
        "consent",
        help="Lookup or resolve pending consent codes",
    )
    auth_consent_subparsers = auth_consent_parser.add_subparsers(dest="consent_command")
    auth_consent_subparsers.required = True

    auth_consent_lookup_parser = auth_consent_subparsers.add_parser(
        "lookup",
        help="Show scope and status for a consent user code",
    )
    auth_consent_lookup_parser.add_argument(
        "--user-code",
        dest="user_code",
        required=True,
        help="User-facing consent code",
    )
    auth_consent_lookup_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    auth_consent_approve_parser = auth_consent_subparsers.add_parser(
        "approve",
        help="Approve a consent request using the provided user code",
    )
    auth_consent_approve_parser.add_argument(
        "--user-code",
        dest="user_code",
        required=True,
        help="User-facing consent code",
    )
    auth_consent_approve_parser.add_argument(
        "--actor-id",
        dest="actor_id",
        default=DEFAULT_ACTOR_ID,
        help="Identifier recorded as the approver",
    )
    auth_consent_approve_parser.add_argument(
        "--role",
        dest="roles",
        action="append",
        default=[DEFAULT_ACTOR_ROLE],
        help="Approver role context (repeatable)",
    )
    auth_consent_approve_parser.add_argument(
        "--mfa-verified",
        dest="mfa_verified",
        action="store_true",
        help="Confirm that MFA has been satisfied for high-risk scopes",
    )

    auth_consent_deny_parser = auth_consent_subparsers.add_parser(
        "deny",
        help="Deny a consent request",
    )
    auth_consent_deny_parser.add_argument(
        "--user-code",
        dest="user_code",
        required=True,
        help="User-facing consent code",
    )
    auth_consent_deny_parser.add_argument(
        "--actor-id",
        dest="actor_id",
        default=DEFAULT_ACTOR_ID,
        help="Identifier recorded as the approver",
    )
    auth_consent_deny_parser.add_argument(
        "--reason",
        dest="reason",
        help="Optional reason noted with the denial",
    )

    reflection_parser = subparsers.add_parser(
        "reflection",
        help="Extract reusable behavior candidates from a trace",
    )
    reflection_parser.add_argument(
        "--trace",
        dest="trace_text",
        help="Inline chain-of-thought or plan text to analyze",
    )
    reflection_parser.add_argument(
        "--trace-file",
        help="Path to a file containing the trace to analyze",
    )
    reflection_parser.add_argument(
        "--trace-format",
        choices=[fmt.value for fmt in TraceFormat],
        default=TraceFormat.CHAIN_OF_THOUGHT.value,
        help="Format of the supplied trace (default: chain_of_thought)",
    )
    reflection_parser.add_argument("--run-id", dest="run_id", help="Optional workflow run identifier")
    reflection_parser.add_argument(
        "--max-candidates",
        dest="max_candidates",
        type=int,
        default=5,
        help="Maximum number of candidates to return (default: 5)",
    )
    reflection_parser.add_argument(
        "--min-score",
        dest="min_score",
        type=float,
        default=0.6,
        help="Minimum confidence (0-1) required to include a candidate (default: 0.6)",
    )
    reflection_parser.add_argument(
        "--no-examples",
        action="store_true",
        help="Skip embedding supporting step examples in the response",
    )
    reflection_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Preferred tag to assign to generated candidates (repeatable)",
    )
    reflection_parser.add_argument(
        "--output",
        choices=("json", "table"),
        default="json",
        help="Output format for the reflection result",
    )

    # BCI subcommands
    bci_parser = subparsers.add_parser(
        "bci",
        help="Behavior-Conditioned Inference utilities",
    )
    bci_subparsers = bci_parser.add_subparsers(dest="bci_command")

    bci_retrieve_parser = bci_subparsers.add_parser(
        "retrieve",
        help="Retrieve relevant behaviors via semantic/keyword search",
    )
    bci_retrieve_parser.add_argument("--query", required=True, help="Natural language query to search for behaviors")
    bci_retrieve_parser.add_argument(
        "--top-k",
        dest="top_k",
        type=int,
        default=5,
        help="Maximum number of behaviors to return (default: 5)",
    )
    bci_retrieve_parser.add_argument(
        "--strategy",
        choices=[strategy.value for strategy in RetrievalStrategy],
        default=RetrievalStrategy.HYBRID.value,
        help="Retrieval strategy to use",
    )
    bci_retrieve_parser.add_argument(
        "--role-focus",
        choices=[role.value for role in RoleFocus],
        help="Filter behaviors by role focus",
    )
    bci_retrieve_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Filter behaviors by tag (repeatable)",
    )
    bci_retrieve_parser.add_argument(
        "--include-metadata",
        action="store_true",
        help="Include behavior metadata in the response",
    )
    bci_retrieve_parser.add_argument(
        "--embedding-weight",
        dest="embedding_weight",
        type=float,
        default=0.7,
        help="Weight for embedding similarity when using hybrid strategy (default: 0.7)",
    )
    bci_retrieve_parser.add_argument(
        "--keyword-weight",
        dest="keyword_weight",
        type=float,
        default=0.3,
        help="Weight for keyword similarity when using hybrid strategy (default: 0.3)",
    )
    bci_retrieve_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    bci_compose_parser = bci_subparsers.add_parser(
        "compose-prompt",
        help="Compose a prompt using selected behaviors",
    )
    bci_compose_parser.add_argument("--query", required=True, help="Task or query to include in the prompt")
    bci_compose_parser.add_argument(
        "--behaviors-file",
        required=True,
        help="Path to JSON array of behavior snippets (behavior_id, name, instruction, optional citation_label, role_focus)",
    )
    bci_compose_parser.add_argument(
        "--citation-mode",
        choices=[mode.value for mode in CitationMode],
        default=CitationMode.EXPLICIT.value,
        help="Citation mode for rendered prompt",
    )
    bci_compose_parser.add_argument(
        "--prompt-format",
        dest="prompt_format",
        choices=[fmt.value for fmt in PromptFormat],
        default=PromptFormat.LIST.value,
        help="Prompt rendering format",
    )
    bci_compose_parser.add_argument(
        "--citation-instruction",
        dest="citation_instruction",
        help="Override the default citation instruction",
    )
    bci_compose_parser.add_argument(
        "--max-behaviors",
        dest="max_behaviors",
        type=int,
        help="Limit the number of behaviors included in the prompt",
    )
    bci_compose_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    bci_validate_parser = bci_subparsers.add_parser(
        "validate-citations",
        help="Validate citations in an output against prepended behaviors",
    )
    bci_validate_parser.add_argument(
        "--output-text",
        help="Inline output text to validate (mutually exclusive with --output-file)",
    )
    bci_validate_parser.add_argument(
        "--output-file",
        help="Path to file containing output text to validate",
    )
    bci_validate_parser.add_argument(
        "--prepended-file",
        required=True,
        help="Path to JSON array of prepended behaviors (behavior_name, optional behavior_id)",
    )
    bci_validate_parser.add_argument(
        "--minimum",
        dest="minimum_citations",
        type=int,
        default=1,
        help="Minimum number of citations required to be compliant",
    )
    bci_validate_parser.add_argument(
        "--allow-unlisted",
        action="store_true",
        help="Treat unlisted behaviors as warnings instead of errors",
    )
    bci_validate_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    bci_rebuild_parser = bci_subparsers.add_parser(
        "rebuild-index",
        help="Rebuild the behavior retriever semantic index",
    )
    bci_rebuild_parser.add_argument(
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
    if args.command == "telemetry" and not getattr(args, "telemetry_command", None):
        telemetry_parser.print_help()
        parser.exit(1)
    if args.command == "analytics" and not getattr(args, "analytics_command", None):
        analytics_parser.print_help()
        parser.exit(1)
    if args.command == "bci" and not getattr(args, "bci_command", None):
        bci_parser.print_help()
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


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


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

    path_override = os.environ.get("GUIDEAI_TELEMETRY_PATH")
    sink_path = Path(path_override) if path_override else Path.home() / ".guideai" / "telemetry" / "events.jsonl"
    telemetry = TelemetryClient(sink=FileTelemetrySink(sink_path), default_actor=actor)

    event = telemetry.emit_event(
        event_type=args.event_type,
        payload=payload_obj,
        actor=actor,
        run_id=args.run_id,
        action_id=args.action_id,
        session_id=args.session_id,
    )

    if args.format == "json":
        print(json.dumps(event.to_dict(), indent=2))
    else:
        print(
            f"{event.timestamp} {event.event_type} actor={event.actor['id']} surface={event.actor['surface']}"
        )
    return 0


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


def _command_auth_login(args: argparse.Namespace) -> int:
    """Perform device flow login and cache issued tokens."""

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
    try:
        result = adapter.validate_checklist(
            checklist_id=args.checklist_id,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_validation_table(result)
    else:
        _print_json(result)
    return 0

    if args.format == "table":
        _render_tasks_table(tasks)
    else:
        _print_json(tasks)
    return 0


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


# ------------------------------------------------------------------
# Run Commands
# ------------------------------------------------------------------


def _command_run_create(args: argparse.Namespace) -> int:
    """Create a new run."""
    adapter = _get_run_adapter()
    try:
        metadata = None
        if args.metadata_file:
            metadata = _load_metadata([], args.metadata_file)

        run = adapter.create_run(
            actor_id=args.actor_id,
            actor_role=args.actor_role,
            workflow_id=args.workflow_id,
            workflow_name=args.workflow_name,
            template_id=args.template_id,
            template_name=args.template_name,
            behavior_ids=args.behavior_ids or None,
            metadata=metadata,
            initial_message=args.message,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_run_table(run)
    else:
        _print_json(run)
    return 0


def _command_run_get(args: argparse.Namespace) -> int:
    """Get run details by ID."""
    adapter = _get_run_adapter()
    try:
        run = adapter.get_run(args.run_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_run_table(run)
    else:
        _print_json(run)
    return 0


def _command_run_list(args: argparse.Namespace) -> int:
    """List runs with optional filters."""
    adapter = _get_run_adapter()
    try:
        runs = adapter.list_runs(
            status=args.status,
            workflow_id=args.workflow_id,
            template_id=args.template_id,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_runs_table(runs)
    else:
        _print_json(runs)
    return 0


def _command_run_complete(args: argparse.Namespace) -> int:
    """Complete a run with final status."""
    adapter = _get_run_adapter()
    try:
        outputs = None
        if args.outputs_file:
            outputs_path = Path(args.outputs_file).expanduser().resolve()
            if not outputs_path.exists():
                print(f"Error: Outputs file not found: {outputs_path}", file=sys.stderr)
                return 2
            outputs = json.loads(outputs_path.read_text(encoding="utf-8"))

        metadata = None
        if args.metadata_file:
            metadata = _load_metadata([], args.metadata_file)

        run = adapter.complete_run(
            args.run_id,
            status=args.status,
            outputs=outputs,
            message=args.message,
            error=args.error,
            metadata=metadata,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_run_table(run)
    else:
        _print_json(run)
    return 0


def _command_run_cancel(args: argparse.Namespace) -> int:
    """Cancel a running job."""
    adapter = _get_run_adapter()
    try:
        run = adapter.cancel_run(args.run_id, reason=args.reason)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_run_table(run)
    else:
        _print_json(run)
    return 0


def _render_run_table(run: Dict[str, Any]) -> None:
    """Render a single run in table format."""
    print(f"Run ID: {run['run_id']}")
    print(f"Status: {run['status']}")
    print(f"Created: {run['created_at']}")
    print(f"Updated: {run['updated_at']}")
    if run.get('workflow_id'):
        print(f"Workflow: {run['workflow_id']}")
    if run.get('template_id'):
        print(f"Template: {run['template_id']}")
    print(f"Progress: {run['progress_pct']:.1f}%")
    if run.get('message'):
        print(f"Message: {run['message']}")
    if run.get('current_step'):
        print(f"Current Step: {run['current_step']}")
    if run.get('started_at'):
        print(f"Started: {run['started_at']}")
    if run.get('completed_at'):
        print(f"Completed: {run['completed_at']}")
    if run.get('duration_ms'):
        print(f"Duration: {run['duration_ms']}ms")
    if run.get('error'):
        print(f"Error: {run['error']}")
    if run.get('behavior_ids'):
        print(f"Behaviors: {', '.join(run['behavior_ids'])}")
    if run.get('steps'):
        print(f"\nSteps ({len(run['steps'])}):")
        for step in run['steps']:
            status_symbol = "✓" if step['status'] == "COMPLETED" else "○"
            print(f"  {status_symbol} {step['name']} ({step['status']})")


def _render_runs_table(runs: List[Dict[str, Any]]) -> None:
    """Render list of runs in table format."""
    if not runs:
        print("No runs found.")
        return

    print(f"{'Run ID':<40} {'Status':<12} {'Progress':<10} {'Created':<20} {'Workflow/Template':<30}")
    print("-" * 120)
    for run in runs:
        run_id = run['run_id'][:36]
        status = run['status']
        progress = f"{run['progress_pct']:.0f}%"
        created = run['created_at'][:19]
        ref = run.get('workflow_id') or run.get('template_id') or '-'
        print(f"{run_id:<40} {status:<12} {progress:<10} {created:<20} {ref:<30}")
    print(f"\nTotal: {len(runs)} run(s)")


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.command == "scan-secrets":
        output = Path(args.output).expanduser() if args.output else DEFAULT_OUTPUT
        output = output.resolve()
        return run_scan(output_path=output, fmt=args.format, fail_on_findings=args.fail_on_findings)
    if args.command == "record-action":
        return _command_record_action(args)
    if args.command == "list-actions":
        return _command_list_actions(args)
    if args.command == "get-action":
        return _command_get_action(args)
    if args.command == "replay-actions":
        return _command_replay_actions(args)
    if args.command == "replay-status":
        return _command_replay_status(args)
    if args.command == "tasks":
        return _command_list_tasks(args)
    if args.command == "behaviors":
        if args.behaviors_command == "create":
            return _command_behaviors_create(args)
        if args.behaviors_command == "list":
            return _command_behaviors_list(args)
        if args.behaviors_command == "search":
            return _command_behaviors_search(args)
        if args.behaviors_command == "get":
            return _command_behaviors_get(args)
        if args.behaviors_command == "update":
            return _command_behaviors_update(args)
        if args.behaviors_command == "submit":
            return _command_behaviors_submit(args)
        if args.behaviors_command == "approve":
            return _command_behaviors_approve(args)
        if args.behaviors_command == "deprecate":
            return _command_behaviors_deprecate(args)
        if args.behaviors_command == "delete-draft":
            return _command_behaviors_delete_draft(args)
        print("Error: Unknown behaviors subcommand", file=sys.stderr)
        return 1
    if args.command == "compliance":
        if args.compliance_command == "create-checklist":
            return _command_compliance_create_checklist(args)
        if args.compliance_command == "record-step":
            return _command_compliance_record_step(args)
        if args.compliance_command == "list":
            return _command_compliance_list(args)
        if args.compliance_command == "get":
            return _command_compliance_get(args)
        if args.compliance_command == "validate":
            return _command_compliance_validate(args)
        print("Error: Unknown compliance subcommand", file=sys.stderr)
        return 1
    if args.command == "telemetry":
        if args.telemetry_command == "emit":
            return _command_telemetry_emit(args)
        print("Error: Unknown telemetry subcommand", file=sys.stderr)
        return 1
    if args.command == "workflow":
        if args.workflow_command == "create-template":
            return _command_workflow_create_template(args)
        if args.workflow_command == "list-templates":
            return _command_workflow_list_templates(args)
        if args.workflow_command == "get-template":
            return _command_workflow_get_template(args)
        if args.workflow_command == "run":
            return _command_workflow_run(args)
        if args.workflow_command == "status":
            return _command_workflow_status(args)
        print("Error: Unknown workflow subcommand", file=sys.stderr)
        return 1
    if args.command == "run":
        if args.run_command == "create":
            return _command_run_create(args)
        if args.run_command == "get":
            return _command_run_get(args)
        if args.run_command == "list":
            return _command_run_list(args)
        if args.run_command == "complete":
            return _command_run_complete(args)
        if args.run_command == "cancel":
            return _command_run_cancel(args)
        print("Error: Unknown run subcommand", file=sys.stderr)
        return 1
    if args.command == "analytics":
        if args.analytics_command == "project-kpi":
            return _command_analytics_project(args)
        if args.analytics_command == "kpi-summary":
            return _command_analytics_kpi_summary(args)
        if args.analytics_command == "behavior-usage":
            return _command_analytics_behavior_usage(args)
        if args.analytics_command == "token-savings":
            return _command_analytics_token_savings(args)
        if args.analytics_command == "compliance-coverage":
            return _command_analytics_compliance_coverage(args)
        print("Error: Unknown analytics subcommand", file=sys.stderr)
        return 1
    if args.command == "metrics":
        if args.metrics_command == "summary":
            return _command_metrics_summary(args)
        if args.metrics_command == "export":
            return _command_metrics_export(args)
        print("Error: Unknown metrics subcommand", file=sys.stderr)
        return 1
    if args.command == "auth":
        if args.auth_command == "ensure-grant":
            return _command_auth_ensure_grant(args)
        if args.auth_command == "list-grants":
            return _command_auth_list_grants(args)
        if args.auth_command == "policy-preview":
            return _command_auth_policy_preview(args)
        if args.auth_command == "revoke":
            return _command_auth_revoke(args)
        if args.auth_command == "login":
            return _command_auth_login(args)
        if args.auth_command == "refresh":
            return _command_auth_refresh(args)
        if args.auth_command == "status":
            return _command_auth_status(args)
        if args.auth_command == "logout":
            return _command_auth_logout(args)
        if args.auth_command == "consent":
            if args.consent_command == "lookup":
                return _command_auth_consent_lookup(args)
            if args.consent_command == "approve":
                return _command_auth_consent_approve(args)
            if args.consent_command == "deny":
                return _command_auth_consent_deny(args)
            print("Error: Unknown auth consent subcommand", file=sys.stderr)
            return 1
        print("Error: Unknown auth subcommand", file=sys.stderr)
        return 1
    if args.command == "reflection":
        return _command_reflection(args)
    if args.command == "bci":
        if args.bci_command == "retrieve":
            return _command_bci_retrieve(args)
        if args.bci_command == "compose-prompt":
            return _command_bci_compose_prompt(args)
        if args.bci_command == "validate-citations":
            return _command_bci_validate_citations(args)
        if args.bci_command == "rebuild-index":
            return _command_bci_rebuild_index(args)
        print("Error: Unknown bci subcommand", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
