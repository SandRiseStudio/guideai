"""GuideAI CLI providing secret scanning and ActionService parity commands."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from guideai.action_service import ActionService
from guideai.adapters import (
    CLITaskAssignmentAdapter,
    CLIActionServiceAdapter,
    CLIBehaviorServiceAdapter,
    CLIComplianceServiceAdapter,
    CLIWorkflowServiceAdapter,
)
from guideai.compliance_service import ComplianceService
from guideai.behavior_service import BehaviorService
from guideai.task_assignments import TaskAssignmentService
from guideai.telemetry import FileTelemetrySink, TelemetryClient
from guideai.workflow_service import WorkflowService

DEFAULT_OUTPUT = Path("security/scan_reports/latest.json")
DEFAULT_ACTOR_ID = "local-cli"
DEFAULT_ACTOR_ROLE = "STRATEGIST"

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

    _ACTION_SERVICE = ActionService()
    _ACTION_ADAPTER = CLIActionServiceAdapter(_ACTION_SERVICE)
    _TASK_SERVICE = None
    _TASK_ADAPTER = None
    _COMPLIANCE_SERVICE = None
    _COMPLIANCE_ADAPTER = None
    _BEHAVIOR_SERVICE = None
    _BEHAVIOR_ADAPTER = None


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
    return 1


if __name__ == "__main__":
    sys.exit(main())
