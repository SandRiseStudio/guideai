"""RunService PostgreSQL implementation."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - imported lazily for optional dependency
    from psycopg2 import extras as pg_extras  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - handled at runtime
    pg_extras = None  # type: ignore[assignment]

from .action_contracts import Actor
from .run_contracts import (
    Run,
    RunCompletion,
    RunCreateRequest,
    RunProgressUpdate,
    RunStatus,
    RunStep,
    utc_now_iso,
)
from .telemetry import TelemetryClient
from guideai.storage.postgres_pool import PostgresPool


class RunServiceError(Exception):
    """Base error for RunService operations."""


class RunNotFoundError(RunServiceError):
    """Raised when a run could not be found in the backing store."""


class PostgresRunService:
    """PostgreSQL-backed run orchestration service.

    Parity implementation with SQLite RunService, using the shared SQLAlchemy-backed
    PostgresPool for connection management and JSONB for structured data
    (behavior_ids, outputs, metadata).

    Args:
        dsn: PostgreSQL connection string (postgresql://user:pass@host:port/dbname)
        telemetry: Optional telemetry client for event emission
    min_conn: Minimum connection pool size (retained for compatibility; ignored)
    max_conn: Maximum connection pool size (retained for compatibility; ignored)
    """

    def __init__(
        self,
        dsn: str,
        *,
        telemetry: Optional[TelemetryClient] = None,
        min_conn: int = 2,
        max_conn: int = 10,
    ) -> None:
        # `min_conn` and `max_conn` retained for API compatibility; the shared
        # SQLAlchemy-backed PostgresPool governs pooling configuration via
        # environment variables (GUIDEAI_PG_POOL_*).
        self._ensure_psycopg2()
        assert pg_extras is not None  # for type checkers

        self._dsn = dsn
        self._telemetry = telemetry or TelemetryClient.noop()
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

    # ------------------------------------------------------------------
    # Public API (parity with RunService)
    # ------------------------------------------------------------------
    def create_run(self, request: RunCreateRequest) -> Run:
        """Create a new run with PENDING status."""
        run_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        actor = request.actor

        metadata = self._build_metadata(request)
        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO runs (
                        run_id, created_at, updated_at,
                        actor_id, actor_role, actor_surface,
                        status, workflow_id, workflow_name,
                        template_id, template_name,
                        behavior_ids, current_step, progress_pct,
                        message, started_at, completed_at, duration_ms,
                        outputs, error, metadata
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    """,
                    (
                        run_id,
                        created_at,
                        created_at,
                        actor.id,
                        actor.role,
                        actor.surface,
                        RunStatus.PENDING,
                        request.workflow_id,
                        request.workflow_name,
                        request.template_id,
                        request.template_name,
                        self._extras.Json(request.behavior_ids),
                        None,  # current_step
                        0.0,  # progress_pct
                        request.initial_message,
                        None,  # started_at
                        None,  # completed_at
                        None,  # duration_ms
                        self._extras.Json({}),  # outputs
                        None,  # error
                        self._extras.Json(metadata),
                    ),
                )

        run = self.get_run(run_id)
        self._telemetry.emit_event(
            event_type="run.created",
            actor=asdict(actor),
            run_id=run_id,
            payload={
                "status": run.status,
                "workflow_id": run.workflow_id,
                "template_id": run.template_id,
                "behavior_count": len(run.behavior_ids),
            },
        )
        return run

    def get_run(self, run_id: str) -> Run:
        """Retrieve a single run by ID."""
        row = self._fetch_run_row(run_id)
        if row is None:
            raise RunNotFoundError(f"Run '{run_id}' not found")
        return self._row_to_run(row)

    def list_runs(
        self,
        *,
        status: Optional[str] = None,
        workflow_id: Optional[str] = None,
        template_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Run]:
        """List runs with optional filters."""
        clauses: List[str] = []
        params: List[Any] = []

        if status:
            clauses.append("status = %s")
            params.append(status)
        if workflow_id:
            clauses.append("workflow_id = %s")
            params.append(workflow_id)
        if template_id:
            clauses.append("template_id = %s")
            params.append(template_id)

        where_clause = ""
        if clauses:
            where_clause = "WHERE " + " AND ".join(clauses)

        params.append(limit)
        query = f"""
            SELECT * FROM runs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
        """

        with self._connection() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()

        return [self._row_to_run(dict(row)) for row in rows]

    def update_run(self, run_id: str, update: RunProgressUpdate) -> Run:
        """Update run progress/status and optionally upsert a step."""
        row = self._fetch_run_row(run_id)
        if row is None:
            raise RunNotFoundError(f"Run '{run_id}' not found")

        run = self._row_to_run(row)
        now = utc_now_iso()
        new_status = update.status or run.status
        progress_pct = update.progress_pct if update.progress_pct is not None else run.progress_pct
        message = update.message if update.message is not None else run.message
        started_at = run.started_at
        completed_at = run.completed_at
        duration_ms = run.duration_ms

        # Auto-populate timestamps
        if new_status == RunStatus.RUNNING and not started_at:
            started_at = now
        if new_status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED} and not completed_at:
            completed_at = now
            duration_ms = self._calculate_duration_ms(run.created_at, completed_at)

        # Merge metadata
        metadata = dict(run.metadata)
        if update.metadata:
            metadata.update(update.metadata)
        if update.tokens_generated is not None:
            metadata.setdefault("tokens", {})["generated"] = update.tokens_generated
        if update.tokens_baseline is not None:
            metadata.setdefault("tokens", {})["baseline"] = update.tokens_baseline

        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE runs
                    SET
                        status = %s,
                        progress_pct = %s,
                        message = %s,
                        current_step = %s,
                        started_at = %s,
                        completed_at = %s,
                        duration_ms = %s,
                        metadata = %s,
                        updated_at = %s
                    WHERE run_id = %s
                    """,
                    (
                        new_status,
                        progress_pct,
                        message,
                        update.step_id or run.current_step,
                        started_at,
                        completed_at,
                        duration_ms,
                        self._extras.Json(metadata),
                        now,
                        run_id,
                    ),
                )
                if update.step_id:
                    self._upsert_step(
                        cur,
                        run_id=run_id,
                        step_id=update.step_id,
                        name=update.step_name or update.step_id,
                        status=update.step_status or new_status,
                        progress_pct=update.progress_pct,
                        metadata=update.metadata,
                    )

        updated_run = self.get_run(run_id)
        self._telemetry.emit_event(
            event_type="run.progress",
            actor=asdict(updated_run.actor),
            run_id=run_id,
            payload={
                "status": updated_run.status,
                "progress_pct": updated_run.progress_pct,
                "current_step": updated_run.current_step,
                "message": updated_run.message,
            },
        )
        return updated_run

    def complete_run(self, run_id: str, completion: RunCompletion) -> Run:
        """Mark a run as completed/failed/cancelled with final outputs."""
        row = self._fetch_run_row(run_id)
        if row is None:
            raise RunNotFoundError(f"Run '{run_id}' not found")

        run = self._row_to_run(row)
        now = utc_now_iso()
        completed_at = now
        duration_ms = self._calculate_duration_ms(run.started_at or run.created_at, completed_at)
        status = completion.status
        progress_pct = 100.0 if status == RunStatus.COMPLETED else run.progress_pct
        merged_metadata = self._merge_metadata(run.metadata, completion.metadata)

        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE runs
                    SET
                        status = %s,
                        progress_pct = %s,
                        completed_at = %s,
                        duration_ms = %s,
                        outputs = %s,
                        message = %s,
                        error = %s,
                        metadata = %s,
                        updated_at = %s
                    WHERE run_id = %s
                    """,
                    (
                        status,
                        progress_pct,
                        completed_at,
                        duration_ms,
                        self._extras.Json(completion.outputs or {}),
                        completion.message,
                        completion.error,
                        self._extras.Json(merged_metadata),
                        now,
                        run_id,
                    ),
                )

        updated_run = self.get_run(run_id)
        self._telemetry.emit_event(
            event_type="run.completed",
            actor=asdict(updated_run.actor),
            run_id=run_id,
            payload={
                "status": updated_run.status,
                "duration_ms": updated_run.duration_ms,
                "error": updated_run.error,
            },
        )
        return updated_run

    def cancel_run(self, run_id: str, reason: Optional[str] = None) -> Run:
        """Cancel a run and mark it as complete with CANCELLED status."""
        completion = RunCompletion(
            status=RunStatus.CANCELLED,
            message=reason or "Run cancelled",
        )
        return self.complete_run(run_id, completion)

    def delete_run(self, run_id: str) -> None:
        """Delete a run (CASCADE will remove run_steps)."""
        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM runs WHERE run_id = %s", (run_id,))
                if cur.rowcount == 0:
                    raise RunNotFoundError(f"Run '{run_id}' not found")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _fetch_run_row(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single run row as a dict."""
        with self._connection() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def _row_to_run(self, row: Dict[str, Any]) -> Run:
        """Convert a PostgreSQL row dict to a Run dataclass."""
        actor = Actor(
            id=row["actor_id"],
            role=row["actor_role"],
            surface=row["actor_surface"],
        )
        steps = self._fetch_steps(row["run_id"])

        # JSONB columns are already deserialized
        behavior_ids = row["behavior_ids"] if isinstance(row["behavior_ids"], list) else []
        outputs = row["outputs"] if isinstance(row["outputs"], dict) else {}
        metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}

        return Run(
            run_id=row["run_id"],
            created_at=row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
            updated_at=row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"],
            actor=actor,
            status=row["status"],
            workflow_id=row["workflow_id"],
            workflow_name=row["workflow_name"],
            template_id=row["template_id"],
            template_name=row["template_name"],
            behavior_ids=behavior_ids,
            current_step=row["current_step"],
            progress_pct=row["progress_pct"],
            message=row["message"],
            started_at=row["started_at"].isoformat() if row["started_at"] and hasattr(row["started_at"], "isoformat") else row["started_at"],
            completed_at=row["completed_at"].isoformat() if row["completed_at"] and hasattr(row["completed_at"], "isoformat") else row["completed_at"],
            duration_ms=row["duration_ms"],
            outputs=outputs,
            error=row["error"],
            metadata=metadata,
            steps=steps,
        )

    def _fetch_steps(self, run_id: str) -> List[RunStep]:
        """Fetch all steps for a run, ordered by started_at."""
        with self._connection() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM run_steps
                    WHERE run_id = %s
                    ORDER BY started_at ASC, step_id ASC
                    """,
                    (run_id,),
                )
                rows = cur.fetchall()

        steps = []
        for row in rows:
            metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
            steps.append(
                RunStep(
                    step_id=row["step_id"],
                    name=row["name"],
                    status=row["status"],
                    started_at=row["started_at"].isoformat() if row["started_at"] and hasattr(row["started_at"], "isoformat") else row["started_at"],
                    completed_at=row["completed_at"].isoformat() if row["completed_at"] and hasattr(row["completed_at"], "isoformat") else row["completed_at"],
                    progress_pct=row["progress_pct"],
                    metadata=metadata,
                )
            )
        return steps

    def _upsert_step(
        self,
        cur: Any,
        *,
        run_id: str,
        step_id: str,
        name: str,
        status: str,
        progress_pct: Optional[float],
        metadata: Optional[Dict[str, Any]],
    ) -> None:
        """Insert or update a run step."""
        now = utc_now_iso()
        metadata_dict = metadata or {}

        # Check if step exists
        cur.execute(
            "SELECT metadata, progress_pct, completed_at FROM run_steps WHERE run_id = %s AND step_id = %s",
            (run_id, step_id),
        )
        row = cur.fetchone()

        if row:
            # Update existing step
            existing_metadata = row[0] if isinstance(row[0], dict) else {}
            merged_metadata = self._merge_metadata(existing_metadata, metadata_dict)
            updated_progress = progress_pct if progress_pct is not None else row[1]
            completed_at = row[2]
            if status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                completed_at = now

            cur.execute(
                """
                UPDATE run_steps
                SET name = %s,
                    status = %s,
                    progress_pct = %s,
                    metadata = %s,
                    completed_at = %s
                WHERE run_id = %s AND step_id = %s
                """,
                (
                    name,
                    status,
                    updated_progress,
                    self._extras.Json(merged_metadata),
                    completed_at,
                    run_id,
                    step_id,
                ),
            )
        else:
            # Insert new step
            cur.execute(
                """
                INSERT INTO run_steps (
                    run_id, step_id, name, status, started_at, completed_at, progress_pct, metadata
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (run_id, step_id) DO NOTHING
                """,
                (
                    run_id,
                    step_id,
                    name,
                    status,
                    now,
                    None,
                    progress_pct,
                    self._extras.Json(metadata_dict),
                ),
            )

    def _build_metadata(self, request: RunCreateRequest) -> Dict[str, Any]:
        """Build initial metadata from request."""
        metadata = dict(request.metadata)
        if request.total_steps is not None:
            metadata.setdefault("execution", {})["total_steps"] = request.total_steps
        return metadata

    def _merge_metadata(
        self,
        original: Dict[str, Any],
        additional: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge two metadata dicts."""
        merged = dict(original)
        if additional:
            merged.update(additional)
        return merged

    @staticmethod
    def _calculate_duration_ms(start_iso: Optional[str], end_iso: str) -> Optional[int]:
        """Calculate duration in milliseconds between two ISO timestamps."""
        if not start_iso:
            return None
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        delta = end - start
        return int(delta.total_seconds() * 1000)

    def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            self._pool.close()

    def __enter__(self) -> PostgresRunService:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
