"""Workflow Engine Foundation for Strategist/Teacher/Student templates.

Implements behavior-conditioned inference (BCI) integration with the BehaviorService,
enabling runtime template execution that injects retrieved behaviors into prompts.

Aligns with:
- PRD.md: Milestone 1 Workflow Engine Foundation
- AGENTS.md: Strategist/Teacher/Student role definitions
- MCP_SERVER_DESIGN.md: Control-plane orchestration patterns
"""

from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from guideai.action_contracts import Actor, utc_now_iso
from guideai.telemetry import TelemetryClient


# Module-level telemetry client
_telemetry = TelemetryClient.noop()


def set_telemetry_client(client: TelemetryClient) -> None:
    """Set the module-level telemetry client."""
    global _telemetry
    _telemetry = client


def emit_event(event_type: str, payload: Dict[str, Any]) -> None:
    """Emit a telemetry event using the module client."""
    _telemetry.emit_event(event_type=event_type, payload=payload)


class WorkflowRole(str, Enum):
    """Role focus for workflow templates (matches BehaviorService role_focus)."""

    STRATEGIST = "STRATEGIST"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    MULTI_ROLE = "MULTI_ROLE"


class WorkflowStatus(str, Enum):
    """Execution status for workflow runs."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class TemplateStep:
    """Individual step within a workflow template."""

    step_id: str
    name: str
    description: str
    prompt_template: str
    behavior_injection_point: str  # Placeholder like {{BEHAVIORS}} in prompt
    required_behaviors: List[str] = field(default_factory=list)  # Behavior IDs to inject
    validation_rules: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowTemplate:
    """Template definition for Strategist/Teacher/Student workflows."""

    template_id: str
    name: str
    description: str
    role_focus: WorkflowRole
    steps: List[TemplateStep]
    created_at: str
    created_by: Actor
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        data = asdict(self)
        data["role_focus"] = self.role_focus.value
        data["created_by"] = asdict(self.created_by)
        data["steps"] = [asdict(step) for step in self.steps]
        return data


@dataclass
class WorkflowRunStep:
    """Runtime execution state for a template step."""

    step_id: str
    status: WorkflowStatus
    prompt_rendered: str  # Prompt with behaviors injected
    behaviors_used: List[str]
    output: Optional[str] = None
    token_count: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


@dataclass
class WorkflowRun:
    """Runtime execution record for a workflow template."""

    run_id: str
    template_id: str
    template_name: str
    role_focus: WorkflowRole
    status: WorkflowStatus
    actor: Actor
    steps: List[WorkflowRunStep]
    started_at: str
    completed_at: Optional[str] = None
    total_tokens: int = 0
    behaviors_cited: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        data = asdict(self)
        data["role_focus"] = self.role_focus.value
        data["status"] = self.status.value
        data["actor"] = asdict(self.actor)
        data["steps"] = [
            {**asdict(step), "status": step.status.value}
            for step in self.steps
        ]
        return data


class WorkflowService:
    """Service for workflow template management and execution with BCI."""

    def __init__(self, db_path: Path, behavior_service=None):
        """Initialize the WorkflowService with SQLite backend.

        Args:
            db_path: Path to SQLite database file
            behavior_service: Optional BehaviorService instance for behavior retrieval
        """
        self.db_path = db_path
        self.behavior_service = behavior_service
        self._init_db()

    def _init_db(self) -> None:
        """Create database schema if not exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_templates (
                    template_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    role_focus TEXT NOT NULL,
                    version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by_id TEXT NOT NULL,
                    created_by_role TEXT NOT NULL,
                    created_by_surface TEXT NOT NULL,
                    template_data TEXT NOT NULL,
                    tags TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    template_name TEXT NOT NULL,
                    role_focus TEXT NOT NULL,
                    status TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    actor_surface TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    total_tokens INTEGER DEFAULT 0,
                    run_data TEXT NOT NULL,
                    FOREIGN KEY (template_id) REFERENCES workflow_templates(template_id)
                )
            """)

            conn.commit()

    def create_template(
        self,
        name: str,
        description: str,
        role_focus: WorkflowRole,
        steps: List[TemplateStep],
        actor: Actor,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowTemplate:
        """Create a new workflow template.

        Args:
            name: Template name
            description: Template description
            role_focus: Primary role (STRATEGIST/TEACHER/STUDENT/MULTI_ROLE)
            steps: List of template steps with behavior injection points
            actor: Actor creating the template
            tags: Optional tags for categorization
            metadata: Optional additional metadata

        Returns:
            Created WorkflowTemplate
        """
        template_id = f"wf-{uuid4().hex[:12]}"
        created_at = utc_now_iso()

        template = WorkflowTemplate(
            template_id=template_id,
            name=name,
            description=description,
            role_focus=role_focus,
            steps=steps,
            created_at=created_at,
            created_by=actor,
            tags=tags or [],
            metadata=metadata or {},
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO workflow_templates (
                    template_id, name, description, role_focus, version,
                    created_at, created_by_id, created_by_role, created_by_surface,
                    template_data, tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    name,
                    description,
                    role_focus.value,
                    template.version,
                    created_at,
                    actor.id,
                    actor.role,
                    actor.surface,
                    json.dumps(template.to_dict()),
                    json.dumps(tags or []),
                ),
            )
            conn.commit()

        emit_event(
            "workflow.template.created",
            {
                "template_id": template_id,
                "name": name,
                "role_focus": role_focus.value,
                "step_count": len(steps),
                "actor": asdict(actor),
            },
        )

        return template

    def get_template(self, template_id: str) -> Optional[WorkflowTemplate]:
        """Retrieve a workflow template by ID.

        Args:
            template_id: Template identifier

        Returns:
            WorkflowTemplate if found, None otherwise
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT template_data FROM workflow_templates WHERE template_id = ?",
                (template_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            data = json.loads(row["template_data"])
            return WorkflowTemplate(
                template_id=data["template_id"],
                name=data["name"],
                description=data["description"],
                role_focus=WorkflowRole(data["role_focus"]),
                steps=[
                    TemplateStep(**step) for step in data["steps"]
                ],
                created_at=data["created_at"],
                created_by=Actor(**data["created_by"]),
                version=data["version"],
                tags=data["tags"],
                metadata=data["metadata"],
            )

    def list_templates(
        self,
        role_focus: Optional[WorkflowRole] = None,
        tags: Optional[List[str]] = None,
    ) -> List[WorkflowTemplate]:
        """List workflow templates with optional filters.

        Args:
            role_focus: Filter by role (optional)
            tags: Filter by tags (optional)

        Returns:
            List of matching WorkflowTemplate instances
        """
        query = "SELECT template_data FROM workflow_templates WHERE 1=1"
        params: List[Any] = []

        if role_focus:
            query += " AND role_focus = ?"
            params.append(role_focus.value)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            templates = []
            for row in rows:
                data = json.loads(row["template_data"])

                # Filter by tags if specified
                if tags and not any(tag in data["tags"] for tag in tags):
                    continue

                templates.append(
                    WorkflowTemplate(
                        template_id=data["template_id"],
                        name=data["name"],
                        description=data["description"],
                        role_focus=WorkflowRole(data["role_focus"]),
                        steps=[TemplateStep(**step) for step in data["steps"]],
                        created_at=data["created_at"],
                        created_by=Actor(**data["created_by"]),
                        version=data["version"],
                        tags=data["tags"],
                        metadata=data["metadata"],
                    )
                )

            return templates

    def run_workflow(
        self,
        template_id: str,
        actor: Actor,
        behavior_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRun:
        """Execute a workflow template with behavior-conditioned inference.

        Args:
            template_id: Template to execute
            actor: Actor running the workflow
            behavior_ids: Optional list of behavior IDs to inject (auto-retrieves if None)
            metadata: Optional run metadata

        Returns:
            WorkflowRun with execution state
        """
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        run_id = f"run-{uuid4().hex[:12]}"
        started_at = utc_now_iso()

        # Initialize run with pending steps
        run = WorkflowRun(
            run_id=run_id,
            template_id=template_id,
            template_name=template.name,
            role_focus=template.role_focus,
            status=WorkflowStatus.PENDING,
            actor=actor,
            steps=[],
            started_at=started_at,
            metadata=metadata or {},
        )

        emit_event(
            "workflow.run.started",
            {
                "run_id": run_id,
                "template_id": template_id,
                "role_focus": template.role_focus.value,
                "actor": asdict(actor),
            },
        )

        # Store run record
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, template_id, template_name, role_focus, status,
                    actor_id, actor_role, actor_surface, started_at, run_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    template_id,
                    template.name,
                    template.role_focus.value,
                    WorkflowStatus.PENDING.value,
                    actor.id,
                    actor.role,
                    actor.surface,
                    started_at,
                    json.dumps(run.to_dict()),
                ),
            )
            conn.commit()

        return run

    def inject_behaviors(
        self,
        prompt_template: str,
        injection_point: str,
        behavior_ids: List[str],
    ) -> Tuple[str, List[str]]:
        """Inject behaviors into a prompt template at the specified point.

        Args:
            prompt_template: Template string with injection point
            injection_point: Placeholder to replace (e.g., {{BEHAVIORS}})
            behavior_ids: List of behavior IDs to inject

        Returns:
            Tuple of (rendered_prompt, behaviors_used)
        """
        behaviors_used = []
        behavior_text = ""

        if self.behavior_service and behavior_ids:
            behaviors = []
            for bid in behavior_ids:
                behavior = self.behavior_service.get_behavior(bid)
                if behavior:
                    behaviors.append(behavior)
                    behaviors_used.append(bid)

            # Format behaviors for injection
            if behaviors:
                behavior_text = "\n\n## Available Behaviors\n\n"
                for b in behaviors:
                    behavior_text += f"- **{b['name']}**: {b['description']}\n"
                behavior_text += "\nReference these behaviors by name when applicable.\n"

        # Replace injection point
        rendered = prompt_template.replace(injection_point, behavior_text)

        return rendered, behaviors_used

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        """Retrieve a workflow run by ID.

        Args:
            run_id: Run identifier

        Returns:
            WorkflowRun if found, None otherwise
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT run_data FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            data = json.loads(row["run_data"])
            return WorkflowRun(
                run_id=data["run_id"],
                template_id=data["template_id"],
                template_name=data["template_name"],
                role_focus=WorkflowRole(data["role_focus"]),
                status=WorkflowStatus(data["status"]),
                actor=Actor(**data["actor"]),
                steps=[
                    WorkflowRunStep(
                        step_id=s["step_id"],
                        status=WorkflowStatus(s["status"]),
                        prompt_rendered=s["prompt_rendered"],
                        behaviors_used=s["behaviors_used"],
                        output=s.get("output"),
                        token_count=s.get("token_count"),
                        started_at=s.get("started_at"),
                        completed_at=s.get("completed_at"),
                        error=s.get("error"),
                    )
                    for s in data["steps"]
                ],
                started_at=data["started_at"],
                completed_at=data.get("completed_at"),
                total_tokens=data["total_tokens"],
                behaviors_cited=data["behaviors_cited"],
                metadata=data["metadata"],
            )

    def update_run_status(
        self,
        run_id: str,
        status: WorkflowStatus,
        total_tokens: Optional[int] = None,
    ) -> None:
        """Update workflow run status and token count.

        Args:
            run_id: Run identifier
            status: New status
            total_tokens: Optional updated token count
        """
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        run.status = status
        if total_tokens is not None:
            run.total_tokens = total_tokens

        if status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
            run.completed_at = utc_now_iso()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?, total_tokens = ?, completed_at = ?, run_data = ?
                WHERE run_id = ?
                """,
                (
                    status.value,
                    run.total_tokens,
                    run.completed_at,
                    json.dumps(run.to_dict()),
                    run_id,
                ),
            )
            conn.commit()

        emit_event(
            "workflow.run.status_changed",
            {
                "run_id": run_id,
                "status": status.value,
                "total_tokens": run.total_tokens,
            },
        )
