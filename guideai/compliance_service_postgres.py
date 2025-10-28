"""PostgreSQL backend for ComplianceService."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency resolution
    from psycopg2 import extras as pg_extras  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - handled in runtime guard
    pg_extras = None  # type: ignore[assignment]

from .action_contracts import Actor, utc_now_iso
from .compliance_service import Checklist, ChecklistNotFoundError, ChecklistStep
from .telemetry import TelemetryClient
from guideai.storage.postgres_pool import PostgresPool


class PostgresComplianceService:
    """ComplianceService backed by PostgreSQL for production persistence.

    Implements the full contract from COMPLIANCE_SERVICE_CONTRACT.md with:
    - Checklist CRUD operations with coverage scoring
    - Step recording with automatic coverage recalculation
    - Validation operations with missing/failed/warnings reporting
    - JSONB support for compliance_category, evidence, behaviors_cited
    - CASCADE delete for referential integrity
    - UNIQUE constraint enforcement on checklist_id+title
    """

    def __init__(
        self,
        dsn: str,
        telemetry_client: Optional[TelemetryClient] = None,
        min_conn: int = 2,
        max_conn: int = 10,
    ) -> None:
        """Initialize PostgreSQL connection pool.

        Args:
            dsn: PostgreSQL connection string
            telemetry_client: Optional telemetry client for event emission
            min_conn: Minimum connections in pool
            max_conn: Maximum connections in pool
        """
        # min_conn/max_conn retained for API compatibility; pooling limits are
        # now governed via PostgresPool configuration (see GUIDEAI_PG_POOL_* env vars).
        self._ensure_psycopg2()
        assert pg_extras is not None  # satisfy type checkers

        self._dsn = dsn
        self._telemetry = telemetry_client or TelemetryClient.noop()
        self._extras: Any = pg_extras
        self._pool = PostgresPool(dsn)

    def _ensure_psycopg2(self) -> None:
        if pg_extras is None:
            raise SystemExit(
                "❌ psycopg2 is not installed. Install with: pip install -e '.[postgres]'"
            )

    @contextmanager
    def _connection(self, *, autocommit: bool = True):
        with self._pool.connection(autocommit=autocommit) as conn:
            yield conn

    def create_checklist(
        self,
        title: str,
        description: str,
        template_id: Optional[str] = None,
        milestone: Optional[str] = None,
        compliance_category: Optional[List[str]] = None,
    ) -> Checklist:
        """Create a new compliance checklist.

        Args:
            title: Checklist title
            description: Checklist description
            template_id: Optional template identifier
            milestone: Optional milestone linkage
            compliance_category: List of compliance categories

        Returns:
            Created Checklist object
        """
        checklist_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        compliance_category = compliance_category or []

        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO checklists (
                        checklist_id, title, description, template_id,
                        milestone, compliance_category, created_at,
                        coverage_score, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        checklist_id,
                        title,
                        description,
                        template_id,
                        milestone,
                        self._extras.Json(compliance_category),
                        created_at,
                        0.0,  # Initial coverage
                        self._extras.Json({}),
                    ),
                )

        self._telemetry.emit_event(
            event_type="compliance.checklist.created",
            payload={
                "checklist_id": checklist_id,
                "title": title,
                "template_id": template_id,
                "milestone": milestone,
                "compliance_category": compliance_category,
            },
        )

        return Checklist(
            checklist_id=checklist_id,
            title=title,
            description=description,
            template_id=template_id,
            milestone=milestone,
            compliance_category=compliance_category,
            steps=[],
            created_at=created_at,
            completed_at=None,
            coverage_score=0.0,
        )

    def get_checklist(self, checklist_id: str) -> Checklist:
        """Retrieve a checklist by ID with all steps.

        Args:
            checklist_id: Checklist identifier

        Returns:
            Checklist object with steps loaded

        Raises:
            ChecklistNotFoundError: If checklist doesn't exist
        """
        with self._connection() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT checklist_id, title, description, template_id,
                           milestone, compliance_category, created_at,
                           completed_at, coverage_score
                    FROM checklists
                    WHERE checklist_id = %s
                    """,
                    (checklist_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise ChecklistNotFoundError(f"Checklist {checklist_id} not found")

                cur.execute(
                    """
                    SELECT step_id, checklist_id, title, status,
                           actor_id, actor_role, actor_surface,
                           evidence, behaviors_cited, related_run_id,
                           audit_log_event_id, validation_result, created_at
                    FROM checklist_steps
                    WHERE checklist_id = %s
                    ORDER BY created_at ASC
                    """,
                    (checklist_id,),
                )
                step_rows = cur.fetchall()

        steps = [
            ChecklistStep(
                step_id=str(s["step_id"]),
                checklist_id=str(s["checklist_id"]),
                timestamp=s["created_at"].isoformat(),
                actor=Actor(
                    id=s["actor_id"],
                    role=s["actor_role"],
                    surface=s["actor_surface"],
                ),
                title=s["title"],
                status=s["status"],
                evidence=s["evidence"] or {},
                behaviors_cited=s["behaviors_cited"] or [],
                related_run_id=s["related_run_id"],
                audit_log_event_id=s["audit_log_event_id"],
                validation_result=s["validation_result"] or {},
            )
            for s in step_rows
        ]

        return Checklist(
            checklist_id=str(row["checklist_id"]),
            title=row["title"],
            description=row["description"],
            template_id=row["template_id"],
            milestone=row["milestone"],
            compliance_category=row["compliance_category"] or [],
            steps=steps,
            created_at=row["created_at"].isoformat(),
            completed_at=(row["completed_at"].isoformat() if row["completed_at"] else None),
            coverage_score=float(row["coverage_score"]),
        )

    def list_checklists(
        self,
        milestone: Optional[str] = None,
        compliance_category: Optional[List[str]] = None,
        status_filter: Optional[str] = None,
    ) -> List[Checklist]:
        """List checklists with optional filters.

        Args:
            milestone: Filter by milestone
            compliance_category: Filter by any category in list
            status_filter: 'COMPLETED' or 'ACTIVE'

        Returns:
            List of matching Checklist objects (without steps loaded)
        """
        query = """
            SELECT checklist_id, title, description, template_id,
                   milestone, compliance_category, created_at,
                   completed_at, coverage_score
            FROM checklists
            WHERE 1=1
        """
        params: List[Any] = []

        if milestone:
            query += " AND milestone = %s"
            params.append(milestone)

        if compliance_category:
            query += " AND compliance_category @> %s"
            params.append(self._extras.Json(compliance_category))

        if status_filter == "COMPLETED":
            query += " AND completed_at IS NOT NULL"
        elif status_filter == "ACTIVE":
            query += " AND completed_at IS NULL"

        query += " ORDER BY created_at DESC"

        with self._connection() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()

        return [
            Checklist(
                checklist_id=str(row["checklist_id"]),
                title=row["title"],
                description=row["description"] or "",
                template_id=row["template_id"],
                milestone=row["milestone"],
                compliance_category=row["compliance_category"] or [],
                steps=[],  # Don't load steps for list operation
                created_at=row["created_at"].isoformat(),
                completed_at=(row["completed_at"].isoformat() if row["completed_at"] else None),
                coverage_score=float(row["coverage_score"]),
            )
            for row in rows
        ]

    def record_step(
        self,
        checklist_id: str,
        title: str,
        status: str,
        actor: Actor,
        evidence: Optional[Dict] = None,
        behaviors_cited: Optional[List[str]] = None,
        related_run_id: Optional[str] = None,
        audit_log_event_id: Optional[str] = None,
        validation_result: Optional[Dict] = None,
    ) -> ChecklistStep:
        """Record a checklist step and recalculate coverage.

        Args:
            checklist_id: Parent checklist ID
            title: Step title
            status: Step status (PENDING/IN_PROGRESS/COMPLETED/FAILED/SKIPPED)
            actor: Actor who performed the step
            evidence: Evidence dictionary
            behaviors_cited: List of behavior IDs cited
            related_run_id: Optional related run ID
            audit_log_event_id: Optional audit log event ID
            validation_result: Validation result dictionary

        Returns:
            Created ChecklistStep object
        """
        step_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        evidence = evidence or {}
        behaviors_cited = behaviors_cited or []
        validation_result = validation_result or {}

        with self._connection(autocommit=False) as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO checklist_steps (
                        step_id, checklist_id, title, status,
                        actor_id, actor_role, actor_surface,
                        evidence, behaviors_cited, related_run_id,
                        audit_log_event_id, validation_result, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        step_id,
                        checklist_id,
                        title,
                        status,
                        actor.id,
                        actor.role,
                        actor.surface,
                        self._extras.Json(evidence),
                        self._extras.Json(behaviors_cited),
                        related_run_id,
                        audit_log_event_id,
                        self._extras.Json(validation_result),
                        created_at,
                    ),
                )

                cur.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE status IN ('COMPLETED', 'FAILED', 'SKIPPED'))::REAL
                           / NULLIF(COUNT(*), 0) AS coverage
                    FROM checklist_steps
                    WHERE checklist_id = %s
                    """,
                    (checklist_id,),
                )
                coverage_row = cur.fetchone()
                coverage_score = (
                    float(coverage_row["coverage"])
                    if coverage_row and coverage_row["coverage"]
                    else 0.0
                )

                cur.execute(
                    """
                    SELECT COUNT(*) = 0 AS all_terminal
                    FROM checklist_steps
                    WHERE checklist_id = %s
                      AND status NOT IN ('COMPLETED', 'FAILED', 'SKIPPED')
                    """,
                    (checklist_id,),
                )
                all_terminal_row = cur.fetchone()
                all_terminal = bool(all_terminal_row["all_terminal"]) if all_terminal_row else False

                if all_terminal:
                    cur.execute(
                        """
                        UPDATE checklists
                        SET coverage_score = %s,
                            completed_at = %s
                        WHERE checklist_id = %s
                          AND completed_at IS NULL
                        """,
                        (coverage_score, created_at, checklist_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE checklists
                        SET coverage_score = %s
                        WHERE checklist_id = %s
                        """,
                        (coverage_score, checklist_id),
                    )

        self._telemetry.emit_event(
            event_type="compliance.step.recorded",
            actor={"id": actor.id, "role": actor.role, "surface": actor.surface},
            payload={
                "step_id": step_id,
                "checklist_id": checklist_id,
                "title": title,
                "status": status,
                "coverage_score": coverage_score,
            },
        )

        return ChecklistStep(
            step_id=step_id,
            checklist_id=checklist_id,
            timestamp=created_at,
            actor=actor,
            title=title,
            status=status,
            evidence=evidence,
            behaviors_cited=behaviors_cited,
            related_run_id=related_run_id,
            audit_log_event_id=audit_log_event_id,
            validation_result=validation_result,
        )

    def validate_checklist(self, checklist_id: str) -> Dict:
        """Validate checklist and return missing/failed/warnings.

        Args:
            checklist_id: Checklist to validate

        Returns:
            ValidateChecklistResponse dict with:
                - valid: bool
                - coverage_score: float
                - missing_steps: list of step titles with PENDING status
                - failed_steps: list of step titles with FAILED status
                - warnings: list of step titles with SKIPPED status
        """
        self._telemetry.emit_event(
            event_type="compliance.validation.triggered",
            payload={"checklist_id": checklist_id},
        )

        with self._connection() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT coverage_score
                    FROM checklists
                    WHERE checklist_id = %s
                    """,
                    (checklist_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise ChecklistNotFoundError(f"Checklist {checklist_id} not found")
                coverage_score = float(row["coverage_score"])

                cur.execute(
                    """
                    SELECT title, status
                    FROM checklist_steps
                    WHERE checklist_id = %s
                    ORDER BY created_at ASC
                    """,
                    (checklist_id,),
                )
                steps = cur.fetchall()

        missing_steps = [s["title"] for s in steps if s["status"] == "PENDING"]
        failed_steps = [s["title"] for s in steps if s["status"] == "FAILED"]
        warnings = [s["title"] for s in steps if s["status"] == "SKIPPED"]

        valid = not missing_steps and not failed_steps

        result = {
            "valid": valid,
            "coverage_score": coverage_score,
            "missing_steps": missing_steps,
            "failed_steps": failed_steps,
            "warnings": warnings,
        }

        self._telemetry.emit_event(
            event_type="compliance.validation.completed",
            payload={
                "checklist_id": checklist_id,
                "valid": valid,
                "coverage_score": coverage_score,
            },
        )

        return result
