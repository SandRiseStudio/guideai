"""Surface-specific adapters that wrap the core ActionService."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .action_contracts import (
    Action,
    ActionCreateRequest,
    Actor,
    ReplayOptions,
    ReplayRequest,
    ReplayStatus,
)
from .action_service import ActionService


class BaseAdapter:
    """Common utilities for all adapters."""

    surface: str

    def __init__(self, service: ActionService, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _format_action(self, action: Action) -> Dict[str, Any]:
        return action.to_dict()

    def _format_actions(self, actions: Iterable[Action]) -> List[Dict[str, Any]]:
        return [self._format_action(action) for action in actions]

    def _format_replay(self, replay: ReplayStatus) -> Dict[str, Any]:
        return replay.to_dict()

    def _build_actor(self, actor_payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=actor_payload.get("id", "unknown"),
            role=actor_payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )


class RestActionServiceAdapter(BaseAdapter):
    """Mimics REST API payloads/behavior."""

    def __init__(self, service: ActionService) -> None:
        super().__init__(service, surface="REST_API")

    def create_action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = ActionCreateRequest(
            artifact_path=payload["artifact_path"],
            summary=payload["summary"],
            behaviors_cited=list(payload.get("behaviors_cited", [])),
            metadata=payload.get("metadata", {}),
            related_run_id=payload.get("related_run_id"),
            checksum=payload.get("checksum"),
            audit_log_event_id=payload.get("audit_log_event_id"),
        )
        action = self._service.create_action(request, actor)
        return self._format_action(action)

    def list_actions(self) -> List[Dict[str, Any]]:
        return self._format_actions(self._service.list_actions())

    def get_action(self, action_id: str) -> Dict[str, Any]:
        return self._format_action(self._service.get_action(action_id))

    def replay_actions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        options_payload = payload.get("options", {})
        request = ReplayRequest(
            action_ids=list(payload["action_ids"]),
            strategy=payload.get("strategy", "SEQUENTIAL"),
            options=ReplayOptions(
                skip_existing=options_payload.get("skip_existing", False),
                dry_run=options_payload.get("dry_run", False),
            ),
        )
        replay = self._service.replay_actions(request, actor)
        return self._format_replay(replay)

    def get_replay_status(self, replay_id: str) -> Dict[str, Any]:
        return self._format_replay(self._service.get_replay_status(replay_id))


class CLIActionServiceAdapter(BaseAdapter):
    """Adapter that would back the CLI commands."""

    def __init__(self, service: ActionService) -> None:
        super().__init__(service, surface="CLI")

    def record_action(
        self,
        artifact_path: str,
        summary: str,
        behaviors_cited: List[str],
        metadata: Dict[str, Any],
        actor_id: str,
        actor_role: str,
        checksum: str | None = None,
        related_run_id: str | None = None,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = ActionCreateRequest(
            artifact_path=artifact_path,
            summary=summary,
            behaviors_cited=list(behaviors_cited),
            metadata=metadata,
            related_run_id=related_run_id,
            checksum=checksum,
        )
        action = self._service.create_action(request, actor)
        return self._format_action(action)

    def list_actions(self) -> List[Dict[str, Any]]:
        return self._format_actions(self._service.list_actions())

    def get_action(self, action_id: str) -> Dict[str, Any]:
        return self._format_action(self._service.get_action(action_id))

    def replay_actions(
        self,
        action_ids: List[str],
        actor_id: str,
        actor_role: str,
        strategy: str = "SEQUENTIAL",
        skip_existing: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = ReplayRequest(
            action_ids=list(action_ids),
            strategy=strategy,
        )
        request.options.skip_existing = skip_existing
        request.options.dry_run = dry_run
        replay = self._service.replay_actions(request, actor)
        return self._format_replay(replay)


class MCPActionServiceAdapter(BaseAdapter):
    """Adapter simulating MCP tool invocations."""

    def __init__(self, service: ActionService) -> None:
        super().__init__(service, surface="MCP")

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = ActionCreateRequest(
            artifact_path=payload["artifact_path"],
            summary=payload["summary"],
            behaviors_cited=list(payload.get("behaviors_cited", [])),
            metadata=payload.get("metadata", {}),
            related_run_id=payload.get("related_run_id"),
            checksum=payload.get("checksum"),
            audit_log_event_id=payload.get("audit_log_event_id"),
        )
        action = self._service.create_action(request, actor)
        return self._format_action(action)

    def list(self) -> List[Dict[str, Any]]:
        return self._format_actions(self._service.list_actions())

    def get(self, action_id: str) -> Dict[str, Any]:
        return self._format_action(self._service.get_action(action_id))

    def replay(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        options_payload = payload.get("options", {})
        replay_request = ReplayRequest(
            action_ids=list(payload["action_ids"]),
            strategy=payload.get("strategy", "SEQUENTIAL"),
            options=ReplayOptions(
                skip_existing=options_payload.get("skip_existing", False),
                dry_run=options_payload.get("dry_run", False),
            ),
        )
        replay = self._service.replay_actions(replay_request, actor)
        return self._format_replay(replay)

    def get_replay_status(self, replay_id: str) -> Dict[str, Any]:
        return self._format_replay(self._service.get_replay_status(replay_id))
