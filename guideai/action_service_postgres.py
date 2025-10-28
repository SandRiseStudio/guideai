"""Actionfrom __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from copy import deepcopy
from typing import Dict, List, Optionalimplementation with PostgreSQL backend.

Provides WORM (Write-Once-Read-Many) storage for platform actions with replay tracking.
Supports both in-memory (for testing) and PostgreSQL (for production) backends.

Schema: schema/migrations/004_create_action_service.sql
Contract: ACTION_SERVICE_CONTRACT.md
"""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from copy import deepcopy
from typing import Dict, List, Optional

from .action_contracts import (
    Action,
    ActionCreateRequest,
    Actor,
    ReplayRequest,
    ReplayStatus,
    utc_now_iso,
)
from .telemetry import TelemetryClient
from guideai.storage.postgres_pool import PostgresPool


class ActionServiceError(Exception):
    """Base error for ActionService operations."""


class ActionNotFoundError(ActionServiceError):
    """Raised when an action is not found in the backing store."""


class ReplayNotFoundError(ActionServiceError):
    """Raised when a replay job is unknown."""


class ActionService:
    """In-memory ActionService stub for parity testing.

    The service mimics the behavior described in `ACTION_SERVICE_CONTRACT.md` while
    remaining lightweight enough for unit tests. It stores actions in memory and
    simulates replay jobs with deterministic outcomes.

    For production use, instantiate PostgresActionService with a DSN instead.
    """

    def __init__(self, telemetry: Optional[TelemetryClient] = None) -> None:
        self._actions: Dict[str, Action] = {}
        self._replays: Dict[str, ReplayStatus] = {}
        self._telemetry = telemetry or TelemetryClient.noop()

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------
    def create_action(self, request: ActionCreateRequest, actor: Actor) -> Action:
        """Create a new action record and return the stored entity."""

        checksum = request.checksum or self._calculate_checksum(request)
        action = Action(
            action_id=str(uuid.uuid4()),
            timestamp=utc_now_iso(),
            actor=actor,
            artifact_path=request.artifact_path,
            summary=request.summary,
            behaviors_cited=list(request.behaviors_cited),
            metadata=deepcopy(request.metadata),
            related_run_id=request.related_run_id,
            audit_log_event_id=request.audit_log_event_id,
            checksum=checksum,
            replay_status="NOT_STARTED",
        )
        self._actions[action.action_id] = action
        self._telemetry.emit_event(
            event_type="action_recorded",
            payload={
                "artifact_path": action.artifact_path,
                "summary": action.summary,
                "behaviors_cited": list(action.behaviors_cited),
                "metadata": deepcopy(action.metadata),
                "related_run_id": action.related_run_id,
                "audit_log_event_id": action.audit_log_event_id,
            },
            actor=self._actor_payload(actor),
            action_id=action.action_id,
            run_id=action.related_run_id,
        )
        return deepcopy(action)

    def list_actions(self) -> List[Action]:
        """Return all actions sorted by timestamp ascending."""

        return [deepcopy(action) for action in sorted(self._actions.values(), key=lambda a: a.timestamp)]

    def get_action(self, action_id: str) -> Action:
        """Fetch a single action by identifier."""

        if action_id not in self._actions:
            raise ActionNotFoundError(f"Action '{action_id}' not found")
        return deepcopy(self._actions[action_id])

    # ------------------------------------------------------------------
    # Replay Operations
    # ------------------------------------------------------------------
    def replay_actions(self, request: ReplayRequest, actor: Actor) -> ReplayStatus:
        """Simulate replaying a set of actions."""

        missing = [action_id for action_id in request.action_ids if action_id not in self._actions]
        if missing:
            raise ActionNotFoundError(f"Cannot replay missing actions: {missing}")

        replay_id = str(uuid.uuid4())
        succeeded = []
        failed: List[str] = []

        self._telemetry.emit_event(
            event_type="action_replay_start",
            payload={
                "action_ids": list(request.action_ids),
                "strategy": request.strategy,
                "options": {
                    "skip_existing": request.options.skip_existing,
                    "dry_run": request.options.dry_run,
                },
            },
            actor=self._actor_payload(actor),
            action_id=replay_id,
        )

        for action_id in request.action_ids:
            action = self._actions[action_id]
            if request.options.skip_existing and action.replay_status == "SUCCEEDED":
                continue

            if request.options.dry_run:
                # Dry run does not mutate state but records the intent.
                continue

            # Simulate successful replays for stub purposes.
            succeeded.append(action_id)
            self._actions[action_id].replay_status = "SUCCEEDED"

        progress = 1.0 if not request.options.dry_run else 0.0
        status = "SUCCEEDED" if not failed else "FAILED"
        logs = [
            f"Replay triggered by {actor.id} using strategy={request.strategy}",
            f"Actions processed: {len(request.action_ids)}",
        ]
        replay_status = ReplayStatus(
            replay_id=replay_id,
            status=status,
            progress=progress,
            logs=logs,
            failed_action_ids=failed,
        )
        self._replays[replay_id] = replay_status
        self._telemetry.emit_event(
            event_type="action_replay_complete",
            payload={
                "action_ids": list(request.action_ids),
                "status": status,
                "succeeded": list(succeeded),
                "failed": list(failed),
            },
            actor=self._actor_payload(actor),
            action_id=replay_id,
        )
        return deepcopy(replay_status)

    def get_replay_status(self, replay_id: str) -> ReplayStatus:
        """Retrieve an existing replay job status."""

        if replay_id not in self._replays:
            raise ReplayNotFoundError(f"Replay '{replay_id}' not found")
        return deepcopy(self._replays[replay_id])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _calculate_checksum(request: ActionCreateRequest) -> str:
        """Generate a deterministic checksum for the action summary and artifact."""

        hasher = hashlib.sha256()
        hasher.update(request.artifact_path.encode("utf-8"))
        hasher.update(request.summary.encode("utf-8"))
        hasher.update("::".join(request.behaviors_cited).encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def _actor_payload(actor: Actor) -> Dict[str, str]:
        """Normalize actor metadata for telemetry envelopes."""

        return {
            "id": actor.id,
            "role": actor.role,
            "surface": actor.surface.lower(),
        }


class PostgresActionService:
    """PostgreSQL-backed ActionService for production use.

    Stores actions in the actions table and replays in the replays table
    using the schema defined in schema/migrations/004_create_action_service.sql.

    Args:
        dsn: PostgreSQL connection string (e.g., postgresql://user:pass@localhost:5435/guideai_action)
        telemetry: Optional telemetry client for event emission
    """

    def __init__(self, dsn: str, telemetry: Optional[TelemetryClient] = None) -> None:
        self._dsn = dsn
        self._telemetry = telemetry or TelemetryClient.noop()
        self._pool = PostgresPool(self._dsn)
        self._ensure_psycopg2()

    def _ensure_psycopg2(self) -> None:
        """Verify psycopg2 is available."""
        try:
            import psycopg2  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise SystemExit(
                "❌ psycopg2 is not installed. Install with: pip install -e '.[postgres]'"
            ) from exc

    @contextmanager
    def _connection(self, *, autocommit: bool = True):
        """Acquire a pooled PostgreSQL connection with optional transaction control."""
        with self._pool.connection(autocommit=autocommit) as conn:
            yield conn

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------
    def create_action(self, request: ActionCreateRequest, actor: Actor) -> Action:
        """Create a new action record in PostgreSQL."""

        import psycopg2  # type: ignore[import-not-found]
        from psycopg2.extras import Json

        checksum = request.checksum or ActionService._calculate_checksum(request)
        action_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO actions (
                        action_id, timestamp, actor_id, actor_role, actor_surface,
                        artifact_path, summary, behaviors_cited, metadata,
                        related_run_id, audit_log_event_id, checksum, replay_status
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    RETURNING action_id, timestamp, actor_id, actor_role, actor_surface,
                              artifact_path, summary, behaviors_cited, metadata,
                              related_run_id, audit_log_event_id, checksum, replay_status;
                    """,
                    (
                        action_id,
                        timestamp,
                        actor.id,
                        actor.role,
                        actor.surface,
                        request.artifact_path,
                        request.summary,
                        Json(request.behaviors_cited),
                        Json(request.metadata),
                        request.related_run_id,
                        request.audit_log_event_id,
                        checksum,
                        "NOT_STARTED",
                    ),
                )
                row = cur.fetchone()

        action = Action(
            action_id=str(row[0]),
            timestamp=row[1].isoformat(),
            actor=Actor(id=row[2], role=row[3], surface=row[4]),
            artifact_path=row[5],
            summary=row[6],
            behaviors_cited=row[7],
            metadata=row[8],
            related_run_id=str(row[9]) if row[9] else None,
            audit_log_event_id=str(row[10]) if row[10] else None,
            checksum=row[11],
            replay_status=row[12],
        )

        self._telemetry.emit_event(
            event_type="action_recorded",
            payload={
                "artifact_path": action.artifact_path,
                "summary": action.summary,
                "behaviors_cited": list(action.behaviors_cited),
                "metadata": dict(action.metadata),
                "related_run_id": action.related_run_id,
                "audit_log_event_id": action.audit_log_event_id,
            },
            actor=ActionService._actor_payload(actor),
            action_id=action.action_id,
            run_id=action.related_run_id,
        )

        return action

    def list_actions(self) -> List[Action]:
        """Return all actions sorted by timestamp ascending."""

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT action_id, timestamp, actor_id, actor_role, actor_surface,
                           artifact_path, summary, behaviors_cited, metadata,
                           related_run_id, audit_log_event_id, checksum, replay_status
                    FROM actions
                    ORDER BY timestamp ASC;
                    """
                )
                rows = cur.fetchall()

        actions = []
        for row in rows:
            actions.append(
                Action(
                    action_id=str(row[0]),
                    timestamp=row[1].isoformat(),
                    actor=Actor(id=row[2], role=row[3], surface=row[4]),
                    artifact_path=row[5],
                    summary=row[6],
                    behaviors_cited=row[7],
                    metadata=row[8],
                    related_run_id=str(row[9]) if row[9] else None,
                    audit_log_event_id=str(row[10]) if row[10] else None,
                    checksum=row[11],
                    replay_status=row[12],
                )
            )
        return actions

    def get_action(self, action_id: str) -> Action:
        """Fetch a single action by identifier."""

        import psycopg2  # type: ignore[import-not-found]

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT action_id, timestamp, actor_id, actor_role, actor_surface,
                           artifact_path, summary, behaviors_cited, metadata,
                           related_run_id, audit_log_event_id, checksum, replay_status
                    FROM actions
                    WHERE action_id = %s;
                    """,
                    (action_id,),
                )
                row = cur.fetchone()

        if not row:
            raise ActionNotFoundError(f"Action '{action_id}' not found")

        return Action(
            action_id=str(row[0]),
            timestamp=row[1].isoformat(),
            actor=Actor(id=row[2], role=row[3], surface=row[4]),
            artifact_path=row[5],
            summary=row[6],
            behaviors_cited=row[7],
            metadata=row[8],
            related_run_id=str(row[9]) if row[9] else None,
            audit_log_event_id=str(row[10]) if row[10] else None,
            checksum=row[11],
            replay_status=row[12],
        )

    # ------------------------------------------------------------------
    # Replay Operations
    # ------------------------------------------------------------------
    def replay_actions(self, request: ReplayRequest, actor: Actor) -> ReplayStatus:
        """Execute replay of specified actions."""

        import psycopg2  # type: ignore[import-not-found]
        from psycopg2.extras import Json

        # Validate all action_ids exist
        with self._connection() as conn:
            with conn.cursor() as cur:
                # Convert action_ids to UUID array for PostgreSQL
                cur.execute(
                    """
                    SELECT action_id FROM actions WHERE action_id::text = ANY(%s);
                    """,
                    (list(request.action_ids),),
                )
                found = {str(row[0]) for row in cur.fetchall()}

        missing = [aid for aid in request.action_ids if aid not in found]
        if missing:
            raise ActionNotFoundError(f"Cannot replay missing actions: {missing}")

        replay_id = str(uuid.uuid4())
        succeeded = []
        failed: List[str] = []

        self._telemetry.emit_event(
            event_type="action_replay_start",
            payload={
                "action_ids": list(request.action_ids),
                "strategy": request.strategy,
                "options": {
                    "skip_existing": request.options.skip_existing,
                    "dry_run": request.options.dry_run,
                },
            },
            actor=ActionService._actor_payload(actor),
            action_id=replay_id,
        )

        # Process each action
        if not request.options.dry_run:
            with self._connection(autocommit=False) as conn:
                with conn.cursor() as cur:
                    for action_id in request.action_ids:
                        # Check current status if skip_existing is enabled
                        if request.options.skip_existing:
                            cur.execute(
                                "SELECT replay_status FROM actions WHERE action_id = %s;",
                                (action_id,),
                            )
                            row = cur.fetchone()
                            if row and row[0] == "SUCCEEDED":
                                continue

                        # Update replay status
                        cur.execute(
                            "UPDATE actions SET replay_status = 'SUCCEEDED' WHERE action_id = %s;",
                            (action_id,),
                        )
                        succeeded.append(action_id)

        progress = 1.0 if not request.options.dry_run else 0.0
        status = "SUCCEEDED" if not failed else "FAILED"
        logs = [
            f"Replay triggered by {actor.id} using strategy={request.strategy}",
            f"Actions processed: {len(request.action_ids)}",
        ]

        # Store replay status
        with self._connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO replays (replay_id, status, progress, logs, failed_action_ids)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING replay_id, status, progress, logs, failed_action_ids;
                    """,
                    (replay_id, status, progress, Json(logs), Json(failed)),
                )
                row = cur.fetchone()

        if not row:
            raise ActionServiceError("Failed to store replay status")

        replay_status = ReplayStatus(
            replay_id=str(row[0]),
            status=row[1],
            progress=row[2],
            logs=row[3],
            failed_action_ids=row[4],
        )

        self._telemetry.emit_event(
            event_type="action_replay_complete",
            payload={
                "action_ids": list(request.action_ids),
                "status": status,
                "succeeded": list(succeeded),
                "failed": list(failed),
            },
            actor=ActionService._actor_payload(actor),
            action_id=replay_id,
        )

        return replay_status

    def get_replay_status(self, replay_id: str) -> ReplayStatus:
        """Retrieve an existing replay job status."""

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT replay_id, status, progress, logs, failed_action_ids
                    FROM replays
                    WHERE replay_id = %s;
                    """,
                    (replay_id,),
                )
                row = cur.fetchone()

        if not row:
            raise ReplayNotFoundError(f"Replay '{replay_id}' not found")

        return ReplayStatus(
            replay_id=str(row[0]),
            status=row[1],
            progress=row[2],
            logs=row[3],
            failed_action_ids=row[4],
        )
