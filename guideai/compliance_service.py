"""ComplianceService stub implementation aligning with COMPLIANCE_SERVICE_CONTRACT.md."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Dict, List, Optional

from .action_contracts import Actor, utc_now_iso
from .telemetry import TelemetryClient


class ComplianceServiceError(Exception):
    """Base error for ComplianceService operations."""


class ChecklistNotFoundError(ComplianceServiceError):
    """Raised when a checklist is not found in the backing store."""


class StepNotFoundError(ComplianceServiceError):
    """Raised when a step is not found within a checklist."""


class ChecklistStep:
    """Represents a single checklist step with evidence and validation results."""

    def __init__(
        self,
        step_id: str,
        checklist_id: str,
        timestamp: str,
        actor: Actor,
        title: str,
        status: str,
        evidence: Optional[Dict] = None,
        behaviors_cited: Optional[List[str]] = None,
        related_run_id: Optional[str] = None,
        audit_log_event_id: Optional[str] = None,
        validation_result: Optional[Dict] = None,
    ) -> None:
        self.step_id = step_id
        self.checklist_id = checklist_id
        self.timestamp = timestamp
        self.actor = actor
        self.title = title
        self.status = status
        self.evidence = evidence or {}
        self.behaviors_cited = behaviors_cited or []
        self.related_run_id = related_run_id
        self.audit_log_event_id = audit_log_event_id
        self.validation_result = validation_result or {}

    def to_dict(self) -> Dict:
        """Serialize to dictionary matching the contract schema."""
        return {
            "step_id": self.step_id,
            "checklist_id": self.checklist_id,
            "timestamp": self.timestamp,
            "actor": {
                "id": self.actor.id,
                "role": self.actor.role,
                "surface": self.actor.surface,
            },
            "title": self.title,
            "status": self.status,
            "evidence": deepcopy(self.evidence),
            "behaviors_cited": list(self.behaviors_cited),
            "related_run_id": self.related_run_id,
            "audit_log_event_id": self.audit_log_event_id,
            "validation_result": deepcopy(self.validation_result),
        }


class Checklist:
    """Represents a compliance checklist with ordered steps and coverage scoring."""

    def __init__(
        self,
        checklist_id: str,
        title: str,
        description: str,
        template_id: Optional[str],
        milestone: Optional[str],
        compliance_category: List[str],
        steps: List[ChecklistStep],
        created_at: str,
        completed_at: Optional[str] = None,
        coverage_score: float = 0.0,
    ) -> None:
        self.checklist_id = checklist_id
        self.title = title
        self.description = description
        self.template_id = template_id
        self.milestone = milestone
        self.compliance_category = compliance_category
        self.steps = steps
        self.created_at = created_at
        self.completed_at = completed_at
        self.coverage_score = coverage_score

    def to_dict(self) -> Dict:
        """Serialize to dictionary matching the contract schema."""
        return {
            "checklist_id": self.checklist_id,
            "title": self.title,
            "description": self.description,
            "template_id": self.template_id,
            "milestone": self.milestone,
            "compliance_category": list(self.compliance_category),
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "coverage_score": self.coverage_score,
        }


class RecordStepRequest:
    """Request to record a new checklist step."""

    def __init__(
        self,
        checklist_id: str,
        title: str,
        status: str,
        evidence: Optional[Dict] = None,
        behaviors_cited: Optional[List[str]] = None,
        related_run_id: Optional[str] = None,
    ) -> None:
        self.checklist_id = checklist_id
        self.title = title
        self.status = status
        self.evidence = evidence or {}
        self.behaviors_cited = behaviors_cited or []
        self.related_run_id = related_run_id


class ValidateChecklistResponse:
    """Response from checklist validation including coverage score and errors."""

    def __init__(
        self,
        checklist_id: str,
        valid: bool,
        coverage_score: float,
        missing_steps: List[str],
        failed_steps: List[str],
        warnings: List[str],
    ) -> None:
        self.checklist_id = checklist_id
        self.valid = valid
        self.coverage_score = coverage_score
        self.missing_steps = missing_steps
        self.failed_steps = failed_steps
        self.warnings = warnings

    def to_dict(self) -> Dict:
        """Serialize to dictionary matching the contract schema."""
        return {
            "checklist_id": self.checklist_id,
            "valid": self.valid,
            "coverage_score": self.coverage_score,
            "missing_steps": list(self.missing_steps),
            "failed_steps": list(self.failed_steps),
            "warnings": list(self.warnings),
        }


class ComplianceService:
    """In-memory ComplianceService stub for parity testing.

    This service mimics the behavior described in `COMPLIANCE_SERVICE_CONTRACT.md` while
    remaining lightweight enough for unit tests. It stores checklists in memory and
    simulates validation with deterministic scoring.
    """

    def __init__(self, telemetry: Optional[TelemetryClient] = None) -> None:
        self._checklists: Dict[str, Checklist] = {}
        self._telemetry = telemetry or TelemetryClient.noop()

    # ------------------------------------------------------------------
    # Checklist Management
    # ------------------------------------------------------------------
    def create_checklist(
        self,
        title: str,
        description: str,
        template_id: Optional[str],
        milestone: Optional[str],
        compliance_category: List[str],
        actor: Actor,
    ) -> Checklist:
        """Create a new empty checklist and return the stored entity."""

        checklist_id = str(uuid.uuid4())
        checklist = Checklist(
            checklist_id=checklist_id,
            title=title,
            description=description,
            template_id=template_id,
            milestone=milestone,
            compliance_category=compliance_category,
            steps=[],
            created_at=utc_now_iso(),
            completed_at=None,
            coverage_score=0.0,
        )
        self._checklists[checklist_id] = checklist
        self._telemetry.emit_event(
            event_type="compliance_checklist_created",
            payload={
                "checklist_id": checklist_id,
                "title": title,
                "milestone": milestone,
                "compliance_category": list(compliance_category),
            },
            actor=self._actor_payload(actor),
            action_id=checklist_id,
        )
        return deepcopy(checklist)

    def get_checklist(self, checklist_id: str) -> Checklist:
        """Fetch a single checklist by identifier."""

        if checklist_id not in self._checklists:
            raise ChecklistNotFoundError(f"Checklist '{checklist_id}' not found")
        return deepcopy(self._checklists[checklist_id])

    def list_checklists(
        self,
        milestone: Optional[str] = None,
        compliance_category: Optional[List[str]] = None,
        status_filter: Optional[str] = None,
    ) -> List[Checklist]:
        """Return checklists filtered by milestone, category, or status."""

        filtered = []
        for checklist in self._checklists.values():
            if milestone and checklist.milestone != milestone:
                continue
            if compliance_category and not any(cat in checklist.compliance_category for cat in compliance_category):
                continue
            if status_filter:
                if status_filter == "COMPLETED" and checklist.completed_at is None:
                    continue
                if status_filter == "ACTIVE" and checklist.completed_at is not None:
                    continue
            filtered.append(deepcopy(checklist))
        return sorted(filtered, key=lambda c: c.created_at)

    # ------------------------------------------------------------------
    # Step Recording
    # ------------------------------------------------------------------
    def record_step(self, request: RecordStepRequest, actor: Actor) -> ChecklistStep:
        """Record a new step in an existing checklist and recalculate coverage."""

        if request.checklist_id not in self._checklists:
            raise ChecklistNotFoundError(f"Checklist '{request.checklist_id}' not found")

        step_id = str(uuid.uuid4())
        step = ChecklistStep(
            step_id=step_id,
            checklist_id=request.checklist_id,
            timestamp=utc_now_iso(),
            actor=actor,
            title=request.title,
            status=request.status,
            evidence=deepcopy(request.evidence),
            behaviors_cited=list(request.behaviors_cited),
            related_run_id=request.related_run_id,
            audit_log_event_id=None,  # Populated by audit integration
            validation_result={},
        )

        checklist = self._checklists[request.checklist_id]
        checklist.steps.append(step)
        checklist.coverage_score = self._calculate_coverage(checklist)

        # Mark checklist as completed if all steps are terminal
        if all(s.status in ("COMPLETED", "SKIPPED", "FAILED") for s in checklist.steps):
            checklist.completed_at = utc_now_iso()

        self._telemetry.emit_event(
            event_type="compliance_step_recorded",
            payload={
                "checklist_id": request.checklist_id,
                "step_id": step_id,
                "title": request.title,
                "status": request.status,
                "coverage_score": checklist.coverage_score,
            },
            actor=self._actor_payload(actor),
            action_id=step_id,
            run_id=request.related_run_id,
        )

        return deepcopy(step)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate_checklist(self, checklist_id: str, actor: Actor) -> ValidateChecklistResponse:
        """Validate a checklist and return coverage score with errors/warnings."""

        if checklist_id not in self._checklists:
            raise ChecklistNotFoundError(f"Checklist '{checklist_id}' not found")

        checklist = self._checklists[checklist_id]
        missing_steps: List[str] = []
        failed_steps: List[str] = []
        warnings: List[str] = []

        self._telemetry.emit_event(
            event_type="compliance_validation_triggered",
            payload={
                "checklist_id": checklist_id,
                "milestone": checklist.milestone,
            },
            actor=self._actor_payload(actor),
            action_id=checklist_id,
        )

        for step in checklist.steps:
            if step.status == "PENDING":
                missing_steps.append(step.title)
            elif step.status == "FAILED":
                failed_steps.append(step.title)
            elif step.status == "SKIPPED":
                warnings.append(f"Step '{step.title}' was skipped without completion.")

        valid = len(missing_steps) == 0 and len(failed_steps) == 0
        coverage_score = self._calculate_coverage(checklist)

        self._telemetry.emit_event(
            event_type="compliance_validation_completed",
            payload={
                "checklist_id": checklist_id,
                "valid": valid,
                "coverage_score": coverage_score,
                "failed_count": len(failed_steps),
            },
            actor=self._actor_payload(actor),
            action_id=checklist_id,
        )

        return ValidateChecklistResponse(
            checklist_id=checklist_id,
            valid=valid,
            coverage_score=coverage_score,
            missing_steps=missing_steps,
            failed_steps=failed_steps,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _calculate_coverage(checklist: Checklist) -> float:
        """Calculate coverage score as (completed + skipped) / total steps."""

        if not checklist.steps:
            return 0.0
        terminal = sum(1 for step in checklist.steps if step.status in ("COMPLETED", "SKIPPED"))
        return terminal / len(checklist.steps)

    @staticmethod
    def _actor_payload(actor: Actor) -> Dict[str, str]:
        """Normalize actor metadata for telemetry envelopes."""

        return {
            "id": actor.id,
            "role": actor.role,
            "surface": actor.surface.lower(),
        }
