"""ActionService stub implementation aligning with the documented contract."""

from __future__ import annotations

import hashlib
import uuid
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
