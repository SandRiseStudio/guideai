"""Surface-specific adapters that wrap the core ActionService."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar

from .action_contracts import (
    Action,
    ActionCreateRequest,
    Actor,
    ReplayOptions,
    ReplayRequest,
    ReplayStatus,
)
from .action_service import ActionService
from .behavior_service import (
    ApproveBehaviorRequest,
    BehaviorService,
    CreateBehaviorDraftRequest,
    DeprecateBehaviorRequest,
    SearchBehaviorsRequest,
    UpdateBehaviorDraftRequest,
)
from .bci_contracts import (
    BatchComposePromptRequest,
    ComposePromptRequest,
    ComputeTokenSavingsRequest,
    DetectPatternsRequest,
    ParseCitationsRequest,
    RetrieveRequest,
    SegmentTraceRequest,
    ScoreReusabilityRequest,
    TraceFormat,
    ValidateCitationsRequest,
    SerializableDataclass,
)
from .bci_service import BCIService
from .task_assignments import TaskAssignmentService
from .reflection_contracts import ReflectRequest
from .reflection_service import ReflectionService
from .run_contracts import Run, RunCompletion, RunCreateRequest, RunProgressUpdate
from .run_service import RunService, RunStatus
from .device_flow import (
    DeviceFlowManager,
    DeviceAuthorizationSession,
    DevicePollResult,
)


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

    def get_replay_status(self, replay_id: str) -> Dict[str, Any]:
        return self._format_replay(self._service.get_replay_status(replay_id))


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


class BehaviorAdapterBase:
    """Shared helpers for BehaviorService adapters."""

    def __init__(self, service: BehaviorService, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _build_actor(self, actor_payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=actor_payload.get("id", "unknown"),
            role=actor_payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )

    @staticmethod
    def _format_search_results(results: Iterable[Any]) -> List[Dict[str, Any]]:
        formatted: List[Dict[str, Any]] = []
        for result in results:
            formatted.append(result.to_dict())
        return formatted

    @staticmethod
    def _normalize_embedding(raw: Any) -> Optional[List[float]]:
        if raw is None:
            return None
        if isinstance(raw, list):
            return [float(value) for value in raw]
        # Accept comma-separated strings for CLI convenience.
        if isinstance(raw, str):
            if not raw.strip():
                return None
            return [float(part.strip()) for part in raw.split(",")]
        raise ValueError("Embedding must be a list of numeric values")

    def _behavior_detail(self, behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        return self._service.get_behavior(behavior_id, version)


class RestBehaviorServiceAdapter(BehaviorAdapterBase):
    """REST-style adapter for BehaviorService."""

    def __init__(self, service: BehaviorService) -> None:
        super().__init__(service, surface="REST_API")

    def list_behaviors(self, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        params = params or {}
        return self._service.list_behaviors(
            status=params.get("status"),
            tags=params.get("tags"),
            role_focus=params.get("role_focus"),
        )

    def search_behaviors(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        actor_payload = payload.get("actor", {})
        actor = self._build_actor(actor_payload) if actor_payload else None
        limit = payload.get("limit", 25)
        request = SearchBehaviorsRequest(
            query=payload.get("query"),
            tags=list(payload.get("tags", [])) or None,
            role_focus=payload.get("role_focus"),
            status=payload.get("status"),
            limit=min(int(limit), 100),
        )
        results = self._service.search_behaviors(request, actor=actor)
        return self._format_search_results(results)

    def create_draft(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = CreateBehaviorDraftRequest(
            name=payload["name"],
            description=payload["description"],
            instruction=payload["instruction"],
            role_focus=payload["role_focus"],
            trigger_keywords=list(payload.get("trigger_keywords", [])),
            tags=list(payload.get("tags", [])),
            metadata=dict(payload.get("metadata", {})),
            examples=list(payload.get("examples", [])),
            embedding=self._normalize_embedding(payload.get("embedding")),
            base_version=payload.get("base_version"),
        )
        version = self._service.create_behavior_draft(request, actor)
        return self._behavior_detail(version.behavior_id)

    def update_draft(self, behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = UpdateBehaviorDraftRequest(
            behavior_id=behavior_id,
            version=version,
            instruction=payload.get("instruction"),
            description=payload.get("description"),
            trigger_keywords=list(payload.get("trigger_keywords", [])) if "trigger_keywords" in payload else None,
            tags=list(payload.get("tags", [])) if "tags" in payload else None,
            examples=list(payload.get("examples", [])) if "examples" in payload else None,
            metadata=dict(payload.get("metadata", {})) if "metadata" in payload else None,
            embedding=self._normalize_embedding(payload.get("embedding")) if "embedding" in payload else None,
        )
        self._service.update_behavior_draft(request, actor)
        return self._behavior_detail(behavior_id, version)

    def submit_for_review(self, behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        updated = self._service.submit_for_review(behavior_id, version, actor)
        return self._behavior_detail(updated.behavior_id, updated.version)

    def approve(self, behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = ApproveBehaviorRequest(
            behavior_id=behavior_id,
            version=payload["version"],
            effective_from=payload["effective_from"],
            approval_action_id=payload.get("approval_action_id"),
        )
        self._service.approve_behavior(request, actor)
        return self._behavior_detail(behavior_id, request.version)

    def deprecate(self, behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = DeprecateBehaviorRequest(
            behavior_id=behavior_id,
            version=payload["version"],
            effective_to=payload["effective_to"],
            successor_behavior_id=payload.get("successor_behavior_id"),
        )
        self._service.deprecate_behavior(request, actor)
        return self._behavior_detail(behavior_id, request.version)

    def delete_draft(self, behavior_id: str, version: str, payload: Dict[str, Any]) -> None:
        actor = self._build_actor(payload.get("actor", {}))
        self._service.delete_behavior_draft(behavior_id, version, actor)

    def get_behavior(self, behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        return self._behavior_detail(behavior_id, version)


class CLIBehaviorServiceAdapter(BehaviorAdapterBase):
    """CLI-focused adapter for BehaviorService."""

    def __init__(self, service: BehaviorService) -> None:
        super().__init__(service, surface="CLI")

    def list(self, status: Optional[str] = None, tags: Optional[List[str]] = None, role_focus: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._service.list_behaviors(status=status, tags=tags, role_focus=role_focus)

    def search(
        self,
        *,
        query: Optional[str],
        tags: Optional[List[str]],
        role_focus: Optional[str],
        status: Optional[str],
        limit: int,
        actor_id: str,
        actor_role: str,
    ) -> List[Dict[str, Any]]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = SearchBehaviorsRequest(
            query=query,
            tags=tags,
            role_focus=role_focus,
            status=status,
            limit=min(limit, 100),
        )
        results = self._service.search_behaviors(request, actor=actor)
        return self._format_search_results(results)

    def create(
        self,
        *,
        name: str,
        description: str,
        instruction: str,
        role_focus: str,
        trigger_keywords: List[str],
        tags: List[str],
        metadata: Dict[str, Any],
        examples: List[Dict[str, Any]],
        embedding: Optional[List[float]],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = CreateBehaviorDraftRequest(
            name=name,
            description=description,
            instruction=instruction,
            role_focus=role_focus,
            trigger_keywords=trigger_keywords,
            tags=tags,
            metadata=metadata,
            examples=examples,
            embedding=embedding,
        )
        version = self._service.create_behavior_draft(request, actor)
        return self._behavior_detail(version.behavior_id)

    def update(
        self,
        *,
        behavior_id: str,
        version: str,
        instruction: Optional[str],
        description: Optional[str],
        trigger_keywords: Optional[List[str]],
        tags: Optional[List[str]],
        metadata: Optional[Dict[str, Any]],
        examples: Optional[List[Dict[str, Any]]],
        embedding: Optional[List[float]],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = UpdateBehaviorDraftRequest(
            behavior_id=behavior_id,
            version=version,
            instruction=instruction,
            description=description,
            trigger_keywords=trigger_keywords,
            tags=tags,
            examples=examples,
            metadata=metadata,
            embedding=embedding,
        )
        self._service.update_behavior_draft(request, actor)
        return self._behavior_detail(behavior_id, version)

    def submit(self, behavior_id: str, version: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        updated = self._service.submit_for_review(behavior_id, version, actor)
        return self._behavior_detail(updated.behavior_id, updated.version)

    def approve(
        self,
        *,
        behavior_id: str,
        version: str,
        effective_from: str,
        approval_action_id: Optional[str],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = ApproveBehaviorRequest(
            behavior_id=behavior_id,
            version=version,
            effective_from=effective_from,
            approval_action_id=approval_action_id,
        )
        self._service.approve_behavior(request, actor)
        return self._behavior_detail(behavior_id, version)

    def deprecate(
        self,
        *,
        behavior_id: str,
        version: str,
        effective_to: str,
        successor_behavior_id: Optional[str],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = DeprecateBehaviorRequest(
            behavior_id=behavior_id,
            version=version,
            effective_to=effective_to,
            successor_behavior_id=successor_behavior_id,
        )
        self._service.deprecate_behavior(request, actor)
        return self._behavior_detail(behavior_id, version)

    def delete_draft(self, behavior_id: str, version: str, actor_id: str, actor_role: str) -> None:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        self._service.delete_behavior_draft(behavior_id, version, actor)

    def get(self, behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        return self._behavior_detail(behavior_id, version)


class MCPBehaviorServiceAdapter(BehaviorAdapterBase):
    """Adapter mimicking MCP tool invocation payloads for BehaviorService."""

    def __init__(self, service: BehaviorService) -> None:
        super().__init__(service, surface="MCP")

    def list(self, payload: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        payload = payload or {}
        return self._service.list_behaviors(
            status=payload.get("status"),
            tags=payload.get("tags"),
            role_focus=payload.get("role_focus"),
        )

    def search(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        actor = self._build_actor(payload.get("actor", {}))
        request = SearchBehaviorsRequest(
            query=payload.get("query"),
            tags=list(payload.get("tags", [])) or None,
            role_focus=payload.get("role_focus"),
            status=payload.get("status"),
            limit=min(int(payload.get("limit", 25)), 100),
        )
        results = self._service.search_behaviors(request, actor=actor)
        return self._format_search_results(results)

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = CreateBehaviorDraftRequest(
            name=payload["name"],
            description=payload["description"],
            instruction=payload["instruction"],
            role_focus=payload["role_focus"],
            trigger_keywords=list(payload.get("trigger_keywords", [])),
            tags=list(payload.get("tags", [])),
            metadata=dict(payload.get("metadata", {})),
            examples=list(payload.get("examples", [])),
            embedding=self._normalize_embedding(payload.get("embedding")),
            base_version=payload.get("base_version"),
        )
        version = self._service.create_behavior_draft(request, actor)
        return self._behavior_detail(version.behavior_id)

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = UpdateBehaviorDraftRequest(
            behavior_id=payload["behavior_id"],
            version=payload["version"],
            instruction=payload.get("instruction"),
            description=payload.get("description"),
            trigger_keywords=list(payload.get("trigger_keywords", [])) if "trigger_keywords" in payload else None,
            tags=list(payload.get("tags", [])) if "tags" in payload else None,
            examples=list(payload.get("examples", [])) if "examples" in payload else None,
            metadata=dict(payload.get("metadata", {})) if "metadata" in payload else None,
            embedding=self._normalize_embedding(payload.get("embedding")) if "embedding" in payload else None,
        )
        self._service.update_behavior_draft(request, actor)
        return self._behavior_detail(request.behavior_id, request.version)

    def submit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        updated = self._service.submit_for_review(payload["behavior_id"], payload["version"], actor)
        return self._behavior_detail(updated.behavior_id, updated.version)

    def approve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = ApproveBehaviorRequest(
            behavior_id=payload["behavior_id"],
            version=payload["version"],
            effective_from=payload["effective_from"],
            approval_action_id=payload.get("approval_action_id"),
        )
        self._service.approve_behavior(request, actor)
        return self._behavior_detail(request.behavior_id, request.version)

    def deprecate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = DeprecateBehaviorRequest(
            behavior_id=payload["behavior_id"],
            version=payload["version"],
            effective_to=payload["effective_to"],
            successor_behavior_id=payload.get("successor_behavior_id"),
        )
        self._service.deprecate_behavior(request, actor)
        return self._behavior_detail(request.behavior_id, request.version)

    def delete_draft(self, payload: Dict[str, Any]) -> None:
        actor = self._build_actor(payload.get("actor", {}))
        self._service.delete_behavior_draft(payload["behavior_id"], payload["version"], actor)

    def get(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._behavior_detail(payload["behavior_id"], payload.get("version"))


class BaseTaskAdapter:
    """Common adapter utilities for task assignments."""

    def __init__(self, service: TaskAssignmentService) -> None:
        self._service = service

    def _list(self, function: str | None, agent: str | None = None) -> List[Dict[str, Any]]:
        return self._service.list_assignments(function=function, agent=agent)


class RestTaskAssignmentAdapter(BaseTaskAdapter):
    """Mimics REST API payloads for task assignment queries."""

    def __init__(self, service: TaskAssignmentService) -> None:
        super().__init__(service)

    def list_assignments(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        function = payload.get("function") if isinstance(payload, dict) else None
        agent = payload.get("agent") if isinstance(payload, dict) else None
        return self._list(function, agent)


class CLITaskAssignmentAdapter(BaseTaskAdapter):
    """Adapter backing CLI task assignment commands."""

    def __init__(self, service: TaskAssignmentService) -> None:
        super().__init__(service)

    def list_assignments(self, function: str | None = None, agent: str | None = None) -> List[Dict[str, Any]]:
        return self._list(function, agent)


class MCPTaskAssignmentAdapter(BaseTaskAdapter):
    """Adapter providing MCP task listing parity."""

    def __init__(self, service: TaskAssignmentService) -> None:
        super().__init__(service)

    def list_assignments(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        function = payload.get("function") if isinstance(payload, dict) else None
        agent = payload.get("agent") if isinstance(payload, dict) else None
        return self._list(function, agent)


# ------------------------------------------------------------------
# Compliance Service Adapters
# ------------------------------------------------------------------

class BaseComplianceAdapter:
    """Common utilities for compliance adapters."""

    surface: str

    def __init__(self, service: Any, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _build_actor(self, actor_payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=actor_payload.get("id", "unknown"),
            role=actor_payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )


class RestComplianceServiceAdapter(BaseComplianceAdapter):
    """Mimics REST API payloads/behavior for compliance operations."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="REST_API")

    def create_checklist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        checklist = self._service.create_checklist(
            title=payload["title"],
            description=payload.get("description", ""),
            template_id=payload.get("template_id"),
            milestone=payload.get("milestone"),
            compliance_category=list(payload.get("compliance_category", [])),
            actor=actor,
        )
        return checklist.to_dict()

    def get_checklist(self, checklist_id: str) -> Dict[str, Any]:
        return self._service.get_checklist(checklist_id).to_dict()

    def list_checklists(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        checklists = self._service.list_checklists(
            milestone=payload.get("milestone"),
            compliance_category=payload.get("compliance_category"),
            status_filter=payload.get("status_filter"),
        )
        return [checklist.to_dict() for checklist in checklists]

    def record_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .compliance_service import RecordStepRequest

        actor = self._build_actor(payload.get("actor", {}))
        request = RecordStepRequest(
            checklist_id=payload["checklist_id"],
            title=payload["title"],
            status=payload["status"],
            evidence=payload.get("evidence", {}),
            behaviors_cited=list(payload.get("behaviors_cited", [])),
            related_run_id=payload.get("related_run_id"),
        )
        step = self._service.record_step(request, actor)
        return step.to_dict()

    def validate_checklist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        result = self._service.validate_checklist(payload["checklist_id"], actor)
        return result.to_dict()


class CLIComplianceServiceAdapter(BaseComplianceAdapter):
    """Adapter backing CLI compliance commands."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="CLI")

    def create_checklist(
        self,
        title: str,
        description: str,
        template_id: str | None,
        milestone: str | None,
        compliance_category: List[str],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        checklist = self._service.create_checklist(
            title=title,
            description=description,
            template_id=template_id,
            milestone=milestone,
            compliance_category=compliance_category,
            actor=actor,
        )
        return checklist.to_dict()

    def get_checklist(self, checklist_id: str) -> Dict[str, Any]:
        return self._service.get_checklist(checklist_id).to_dict()

    def list_checklists(
        self,
        milestone: str | None = None,
        compliance_category: List[str] | None = None,
        status_filter: str | None = None,
    ) -> List[Dict[str, Any]]:
        checklists = self._service.list_checklists(
            milestone=milestone,
            compliance_category=compliance_category,
            status_filter=status_filter,
        )
        return [checklist.to_dict() for checklist in checklists]

    def record_step(
        self,
        checklist_id: str,
        title: str,
        status: str,
        evidence: Dict[str, Any] | None,
        behaviors_cited: List[str] | None,
        related_run_id: str | None,
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        from .compliance_service import RecordStepRequest

        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = RecordStepRequest(
            checklist_id=checklist_id,
            title=title,
            status=status,
            evidence=evidence or {},
            behaviors_cited=behaviors_cited or [],
            related_run_id=related_run_id,
        )
        step = self._service.record_step(request, actor)
        return step.to_dict()

    def validate_checklist(self, checklist_id: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        result = self._service.validate_checklist(checklist_id, actor)
        return result.to_dict()


class MCPComplianceServiceAdapter(BaseComplianceAdapter):
    """Adapter simulating MCP compliance tool invocations."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="MCP")

    def create_checklist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        checklist = self._service.create_checklist(
            title=payload["title"],
            description=payload.get("description", ""),
            template_id=payload.get("template_id"),
            milestone=payload.get("milestone"),
            compliance_category=list(payload.get("compliance_category", [])),
            actor=actor,
        )
        return checklist.to_dict()

    def get_checklist(self, checklist_id: str) -> Dict[str, Any]:
        return self._service.get_checklist(checklist_id).to_dict()

    def list_checklists(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        checklists = self._service.list_checklists(
            milestone=payload.get("milestone"),
            compliance_category=payload.get("compliance_category"),
            status_filter=payload.get("status_filter"),
        )
        return [checklist.to_dict() for checklist in checklists]

    def record_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .compliance_service import RecordStepRequest

        actor = self._build_actor(payload.get("actor", {}))
        request = RecordStepRequest(
            checklist_id=payload["checklist_id"],
            title=payload["title"],
            status=payload["status"],
            evidence=payload.get("evidence", {}),
            behaviors_cited=list(payload.get("behaviors_cited", [])),
            related_run_id=payload.get("related_run_id"),
        )
        step = self._service.record_step(request, actor)
        return step.to_dict()

    def validate_checklist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        result = self._service.validate_checklist(payload["checklist_id"], actor)
        return result.to_dict()


# Run Service Adapters


class BaseRunServiceAdapter:
    """Shared utilities for RunService surfaces."""

    surface: str

    def __init__(self, service: RunService, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _format_run(self, run: Run) -> Dict[str, Any]:
        return run.to_dict()

    def _format_runs(self, runs: Iterable[Run]) -> List[Dict[str, Any]]:
        return [self._format_run(run) for run in runs]

    def _build_actor(self, payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=payload.get("id", "unknown"),
            role=payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )


class CLIRunServiceAdapter(BaseRunServiceAdapter):
    """Adapter backing CLI run commands."""

    def __init__(self, service: RunService) -> None:
        super().__init__(service, surface="CLI")

    def create_run(
        self,
        *,
        actor_id: str,
        actor_role: str,
        workflow_id: str | None = None,
        workflow_name: str | None = None,
        template_id: str | None = None,
        template_name: str | None = None,
        behavior_ids: List[str] | None = None,
        metadata: Dict[str, Any] | None = None,
        initial_message: str | None = None,
        total_steps: int | None = None,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = RunCreateRequest(
            actor=actor,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            template_id=template_id,
            template_name=template_name,
            behavior_ids=list(behavior_ids or []),
            metadata=metadata or {},
            initial_message=initial_message,
            total_steps=total_steps,
        )
        run = self._service.create_run(request)
        return self._format_run(run)

    def get_run(self, run_id: str) -> Dict[str, Any]:
        return self._format_run(self._service.get_run(run_id))

    def list_runs(
        self,
        *,
        status: str | None = None,
        workflow_id: str | None = None,
        template_id: str | None = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        runs = self._service.list_runs(
            status=status,
            workflow_id=workflow_id,
            template_id=template_id,
            limit=limit,
        )
        return self._format_runs(runs)

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        progress_pct: float | None = None,
        message: str | None = None,
        step_id: str | None = None,
        step_name: str | None = None,
        step_status: str | None = None,
        tokens_generated: int | None = None,
        tokens_baseline: int | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        update = RunProgressUpdate(
            status=status,
            progress_pct=progress_pct,
            message=message,
            step_id=step_id,
            step_name=step_name,
            step_status=step_status,
            tokens_generated=tokens_generated,
            tokens_baseline=tokens_baseline,
            metadata=metadata or {},
        )
        run = self._service.update_run(run_id, update)
        return self._format_run(run)

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        outputs: Dict[str, Any] | None = None,
        message: str | None = None,
        error: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        completion = RunCompletion(
            status=status,
            outputs=outputs or {},
            message=message,
            error=error,
            metadata=metadata or {},
        )
        run = self._service.complete_run(run_id, completion)
        return self._format_run(run)

    def cancel_run(self, run_id: str, *, reason: str | None = None) -> Dict[str, Any]:
        run = self._service.cancel_run(run_id, reason=reason)
        return self._format_run(run)

    def delete_run(self, run_id: str) -> None:
        self._service.delete_run(run_id)


class RestRunServiceAdapter(BaseRunServiceAdapter):
    """REST-style adapter for RunService endpoints."""

    def __init__(self, service: RunService) -> None:
        super().__init__(service, surface="REST_API")

    def create_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = RunCreateRequest(
            actor=actor,
            workflow_id=payload.get("workflow_id"),
            workflow_name=payload.get("workflow_name"),
            template_id=payload.get("template_id"),
            template_name=payload.get("template_name"),
            behavior_ids=list(payload.get("behavior_ids", [])),
            metadata=payload.get("metadata", {}),
            initial_message=payload.get("initial_message"),
            total_steps=payload.get("total_steps"),
        )
        run = self._service.create_run(request)
        return self._format_run(run)

    def get_run(self, run_id: str) -> Dict[str, Any]:
        return self._format_run(self._service.get_run(run_id))

    def list_runs(self, payload: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        payload = payload or {}
        runs = self._service.list_runs(
            status=payload.get("status"),
            workflow_id=payload.get("workflow_id"),
            template_id=payload.get("template_id"),
            limit=payload.get("limit", 50),
        )
        return self._format_runs(runs)

    def update_run(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        update = RunProgressUpdate(
            status=payload.get("status"),
            progress_pct=payload.get("progress_pct"),
            message=payload.get("message"),
            step_id=payload.get("step_id"),
            step_name=payload.get("step_name"),
            step_status=payload.get("step_status"),
            tokens_generated=payload.get("tokens_generated"),
            tokens_baseline=payload.get("tokens_baseline"),
            metadata=payload.get("metadata", {}),
        )
        run = self._service.update_run(run_id, update)
        return self._format_run(run)

    def complete_run(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        completion = RunCompletion(
            status=payload["status"],
            outputs=payload.get("outputs", {}),
            message=payload.get("message"),
            error=payload.get("error"),
            metadata=payload.get("metadata", {}),
        )
        run = self._service.complete_run(run_id, completion)
        return self._format_run(run)

    def cancel_run(self, run_id: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        reason = (payload or {}).get("reason")
        run = self._service.cancel_run(run_id, reason=reason)
        return self._format_run(run)

    def delete_run(self, run_id: str) -> None:
        self._service.delete_run(run_id)


class MCPRunServiceAdapter(BaseRunServiceAdapter):
    """Adapter simulating MCP tool interactions for runs."""

    def __init__(self, service: RunService) -> None:
        super().__init__(service, surface="MCP")

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = RunCreateRequest(
            actor=actor,
            workflow_id=payload.get("workflow_id"),
            workflow_name=payload.get("workflow_name"),
            template_id=payload.get("template_id"),
            template_name=payload.get("template_name"),
            behavior_ids=list(payload.get("behavior_ids", [])),
            metadata=payload.get("metadata", {}),
            initial_message=payload.get("initial_message"),
            total_steps=payload.get("total_steps"),
        )
        run = self._service.create_run(request)
        return self._format_run(run)

    def list(self, payload: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        payload = payload or {}
        runs = self._service.list_runs(
            status=payload.get("status"),
            workflow_id=payload.get("workflow_id"),
            template_id=payload.get("template_id"),
            limit=payload.get("limit", 50),
        )
        return self._format_runs(runs)

    def get(self, run_id: str) -> Dict[str, Any]:
        return self._format_run(self._service.get_run(run_id))

    def update(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        update = RunProgressUpdate(
            status=payload.get("status"),
            progress_pct=payload.get("progress_pct"),
            message=payload.get("message"),
            step_id=payload.get("step_id"),
            step_name=payload.get("step_name"),
            step_status=payload.get("step_status"),
            tokens_generated=payload.get("tokens_generated"),
            tokens_baseline=payload.get("tokens_baseline"),
            metadata=payload.get("metadata", {}),
        )
        run = self._service.update_run(run_id, update)
        return self._format_run(run)

    def complete(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        completion = RunCompletion(
            status=payload["status"],
            outputs=payload.get("outputs", {}),
            message=payload.get("message"),
            error=payload.get("error"),
            metadata=payload.get("metadata", {}),
        )
        run = self._service.complete_run(run_id, completion)
        return self._format_run(run)

    def cancel(self, run_id: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        reason = (payload or {}).get("reason")
        run = self._service.cancel_run(run_id, reason=reason)
        return self._format_run(run)

    def delete(self, run_id: str) -> None:
        self._service.delete_run(run_id)


# Workflow Service Adapters


class BaseWorkflowAdapter:
    """Base adapter for Workflow Service integrations."""

    surface: str

    def __init__(self, service: Any, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _build_actor(self, payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=payload.get("id", "unknown"),
            role=payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )


class CLIWorkflowServiceAdapter(BaseWorkflowAdapter):
    """Adapter for CLI workflow commands."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="CLI")

    def create_template(
        self,
        name: str,
        description: str,
        role_focus: str,
        steps: List[Dict[str, Any]],
        tags: List[str] | None,
        metadata: Dict[str, Any] | None,
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        from .workflow_service import TemplateStep, WorkflowRole

        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        template_steps = [
            TemplateStep(
                step_id=step.get("step_id", f"step-{idx}"),
                name=step["name"],
                description=step["description"],
                prompt_template=step["prompt_template"],
                behavior_injection_point=step.get("behavior_injection_point", "{{BEHAVIORS}}"),
                required_behaviors=step.get("required_behaviors", []),
                validation_rules=step.get("validation_rules", {}),
                metadata=step.get("metadata", {}),
            )
            for idx, step in enumerate(steps)
        ]
        template = self._service.create_template(
            name=name,
            description=description,
            role_focus=WorkflowRole(role_focus),
            steps=template_steps,
            actor=actor,
            tags=tags,
            metadata=metadata,
        )
        return template.to_dict()

    def get_template(self, template_id: str) -> Dict[str, Any] | None:
        template = self._service.get_template(template_id)
        return template.to_dict() if template else None

    def list_templates(
        self,
        role_focus: str | None = None,
        tags: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        from .workflow_service import WorkflowRole

        role = WorkflowRole(role_focus) if role_focus else None
        templates = self._service.list_templates(role_focus=role, tags=tags)
        return [template.to_dict() for template in templates]

    def run_workflow(
        self,
        template_id: str,
        behavior_ids: List[str] | None,
        metadata: Dict[str, Any] | None,
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        run = self._service.run_workflow(
            template_id=template_id,
            actor=actor,
            behavior_ids=behavior_ids,
            metadata=metadata,
        )
        return run.to_dict()

    def get_run(self, run_id: str) -> Dict[str, Any] | None:
        run = self._service.get_run(run_id)
        return run.to_dict() if run else None


# ------------------------------------------------------------------
# BCI Service Adapters
# ------------------------------------------------------------------

_BCIRequestT = TypeVar("_BCIRequestT", bound=SerializableDataclass)


class BaseBCIAdapter:
    """Shared utilities for BCI adapters."""

    def __init__(self, service: BCIService, surface: str) -> None:
        self._service = service
        self.surface = surface

    @staticmethod
    def _from_payload(payload: Dict[str, Any], cls: Type[_BCIRequestT]) -> _BCIRequestT:
        return cls.from_dict(payload)


class RestBCIAdapter(BaseBCIAdapter):
    """REST-style adapter for BCI endpoints."""

    def __init__(self, service: BCIService) -> None:
        super().__init__(service, surface="REST_API")

    def retrieve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, RetrieveRequest)
        return self._service.retrieve(request).to_dict()

    def retrieve_hybrid(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, RetrieveRequest)
        return self._service.retrieve_hybrid(request).to_dict()

    def rebuild_index(self) -> Dict[str, Any]:
        return self._service.rebuild_index()

    def compose_prompt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ComposePromptRequest)
        return self._service.compose_prompt(request).to_dict()

    def compose_batch_prompts(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, BatchComposePromptRequest)
        return self._service.compose_prompts_batch(request).to_dict()

    def parse_citations(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ParseCitationsRequest)
        return self._service.parse_citations(request).to_dict()

    def validate_citations(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ValidateCitationsRequest)
        return self._service.validate_citations(request).to_dict()

    def compute_token_savings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ComputeTokenSavingsRequest)
        return self._service.compute_token_savings(request).to_dict()

    def segment_trace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, SegmentTraceRequest)
        return self._service.segment_trace(request).to_dict()

    def detect_patterns(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, DetectPatternsRequest)
        return self._service.detect_patterns(request).to_dict()

    def score_reusability(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ScoreReusabilityRequest)
        return self._service.score_reusability(request).to_dict()


class MCPBCIAdapter(BaseBCIAdapter):
    """Adapter mapping MCP tool names to BCI service calls."""

    def __init__(self, service: BCIService) -> None:
        super().__init__(service, surface="MCP")

    def retrieve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, RetrieveRequest)
        return self._service.retrieve(request).to_dict()

    def retrieveHybrid(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802 - MCP naming parity
        request = self._from_payload(payload, RetrieveRequest)
        return self._service.retrieve_hybrid(request).to_dict()

    def rebuildIndex(self) -> Dict[str, Any]:  # noqa: N802
        return self._service.rebuild_index()

    def composePrompt(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ComposePromptRequest)
        return self._service.compose_prompt(request).to_dict()

    def composeBatchPrompts(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, BatchComposePromptRequest)
        return self._service.compose_prompts_batch(request).to_dict()

    def parseCitations(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ParseCitationsRequest)
        return self._service.parse_citations(request).to_dict()

    def validateCitations(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ValidateCitationsRequest)
        return self._service.validate_citations(request).to_dict()

    def computeTokenSavings(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ComputeTokenSavingsRequest)
        return self._service.compute_token_savings(request).to_dict()

    def segmentTrace(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, SegmentTraceRequest)
        return self._service.segment_trace(request).to_dict()

    def detectPatterns(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, DetectPatternsRequest)
        return self._service.detect_patterns(request).to_dict()

    def scoreReusability(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ScoreReusabilityRequest)
        return self._service.score_reusability(request).to_dict()



class BaseReflectionAdapter:
    """Shared utilities for ReflectionService adapters."""

    def __init__(self, service: ReflectionService, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _parse(self, payload: Dict[str, Any]) -> ReflectRequest:
        return ReflectRequest.from_dict(payload)


class RestReflectionAdapter(BaseReflectionAdapter):
    """REST adapter exposing reflection extraction."""

    def __init__(self, service: ReflectionService) -> None:
        super().__init__(service, surface="REST_API")

    def extract(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._parse(payload)
        return self._service.reflect(request).to_dict()


class CLIReflectionAdapter(BaseReflectionAdapter):
    """CLI adapter translating flags into reflection requests."""

    def __init__(self, service: ReflectionService) -> None:
        super().__init__(service, surface="CLI")

    def reflect(
        self,
        *,
        trace_text: str,
        trace_format: str,
        run_id: Optional[str],
        max_candidates: int,
        min_quality_score: float,
        include_examples: bool,
        preferred_tags: Optional[List[str]],
    ) -> Dict[str, Any]:
        request = ReflectRequest(
            trace_text=trace_text,
            trace_format=TraceFormat(trace_format),
            run_id=run_id,
            max_candidates=max(1, max_candidates),
            min_quality_score=min_quality_score,
            include_examples=include_examples,
            preferred_tags=preferred_tags,
        )
        return self._service.reflect(request).to_dict()


class MCPReflectionAdapter(BaseReflectionAdapter):
    """Adapter for MCP reflection tool invocations."""

    def __init__(self, service: ReflectionService) -> None:
        super().__init__(service, surface="MCP")

    def extract(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802 - MCP naming parity
        request = self._parse(payload)
        return self._service.reflect(request).to_dict()


class RestWorkflowServiceAdapter(BaseWorkflowAdapter):
    """Adapter for REST API workflow endpoints."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="REST_API")

    def create_template(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .workflow_service import TemplateStep, WorkflowRole

        actor = self._build_actor(payload.get("actor", {}))
        steps_data = payload.get("steps", [])
        template_steps = [
            TemplateStep(
                step_id=step.get("step_id", f"step-{idx}"),
                name=step["name"],
                description=step["description"],
                prompt_template=step["prompt_template"],
                behavior_injection_point=step.get("behavior_injection_point", "{{BEHAVIORS}}"),
                required_behaviors=step.get("required_behaviors", []),
                validation_rules=step.get("validation_rules", {}),
                metadata=step.get("metadata", {}),
            )
            for idx, step in enumerate(steps_data)
        ]
        template = self._service.create_template(
            name=payload["name"],
            description=payload["description"],
            role_focus=WorkflowRole(payload["role_focus"]),
            steps=template_steps,
            actor=actor,
            tags=payload.get("tags"),
            metadata=payload.get("metadata"),
        )
        return template.to_dict()

    def get_template(self, template_id: str) -> Dict[str, Any] | None:
        template = self._service.get_template(template_id)
        return template.to_dict() if template else None

    def list_templates(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        from .workflow_service import WorkflowRole

        role_focus = payload.get("role_focus")
        role = WorkflowRole(role_focus) if role_focus else None
        templates = self._service.list_templates(
            role_focus=role,
            tags=payload.get("tags"),
        )
        return [template.to_dict() for template in templates]

    def run_workflow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        run = self._service.run_workflow(
            template_id=payload["template_id"],
            actor=actor,
            behavior_ids=payload.get("behavior_ids"),
            metadata=payload.get("metadata"),
        )
        return run.to_dict()

    def get_run(self, run_id: str) -> Dict[str, Any] | None:
        run = self._service.get_run(run_id)
        return run.to_dict() if run else None

    def update_run_status(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .workflow_service import WorkflowStatus

        status = WorkflowStatus(payload["status"])
        self._service.update_run_status(
            run_id=run_id,
            status=status,
            total_tokens=payload.get("total_tokens"),
        )
        run = self._service.get_run(run_id)
        return run.to_dict() if run else {}


class MCPWorkflowServiceAdapter(BaseWorkflowAdapter):
    """Adapter for MCP tool workflow invocations."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="MCP")

    def create_template(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .workflow_service import TemplateStep, WorkflowRole

        actor = self._build_actor(payload.get("actor", {}))
        steps_data = payload.get("steps", [])
        template_steps = [
            TemplateStep(
                step_id=step.get("step_id", f"step-{idx}"),
                name=step["name"],
                description=step["description"],
                prompt_template=step["prompt_template"],
                behavior_injection_point=step.get("behavior_injection_point", "{{BEHAVIORS}}"),
                required_behaviors=step.get("required_behaviors", []),
                validation_rules=step.get("validation_rules", {}),
                metadata=step.get("metadata", {}),
            )
            for idx, step in enumerate(steps_data)
        ]
        template = self._service.create_template(
            name=payload["name"],
            description=payload["description"],
            role_focus=WorkflowRole(payload["role_focus"]),
            steps=template_steps,
            actor=actor,
            tags=payload.get("tags"),
            metadata=payload.get("metadata"),
        )
        return template.to_dict()

    def get_template(self, template_id: str) -> Dict[str, Any] | None:
        template = self._service.get_template(template_id)
        return template.to_dict() if template else None

    def list_templates(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        from .workflow_service import WorkflowRole

        role_focus = payload.get("role_focus")
        role = WorkflowRole(role_focus) if role_focus else None
        templates = self._service.list_templates(
            role_focus=role,
            tags=payload.get("tags"),
        )
        return [template.to_dict() for template in templates]

    def run_workflow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        run = self._service.run_workflow(
            template_id=payload["template_id"],
            actor=actor,
            behavior_ids=payload.get("behavior_ids"),
            metadata=payload.get("metadata"),
        )
        return run.to_dict()

    def get_run(self, run_id: str) -> Dict[str, Any] | None:
        run = self._service.get_run(run_id)
        return run.to_dict() if run else None


# ============================================================================
# MetricsService Adapters
# ============================================================================


class BaseMetricsServiceAdapter:
    """Shared utilities for MetricsService surfaces."""

    surface: str

    def __init__(self, service: Any, surface: str) -> None:
        """Initialize adapter.

        Args:
            service: MetricsService instance
            surface: Surface name (CLI, REST_API, MCP)
        """
        self._service = service
        self.surface = surface

    def _format_summary(self, summary: Any) -> Dict[str, Any]:
        """Format MetricsSummary as dict."""
        from dataclasses import asdict
        return asdict(summary)

    def _format_export(self, export: Any) -> Dict[str, Any]:
        """Format MetricsExportResult as dict."""
        from dataclasses import asdict
        return asdict(export)

    def _format_subscription(self, subscription: Any) -> Dict[str, Any]:
        """Format MetricsSubscription as dict."""
        from dataclasses import asdict
        return asdict(subscription)


class CLIMetricsServiceAdapter(BaseMetricsServiceAdapter):
    """Adapter backing CLI metrics commands."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="CLI")

    def get_summary(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Get metrics summary.

        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            use_cache: Whether to use cached data

        Returns:
            MetricsSummary as dict
        """
        summary = self._service.get_summary(
            start_date=start_date,
            end_date=end_date,
            use_cache=use_cache,
        )
        return self._format_summary(summary)

    def export_metrics(
        self,
        *,
        format: str = "json",
        start_date: str | None = None,
        end_date: str | None = None,
        metrics: List[str] | None = None,
        include_raw_events: bool = False,
    ) -> Dict[str, Any]:
        """Export metrics data.

        Args:
            format: Export format ('json', 'csv', 'parquet')
            start_date: Start date for export
            end_date: End date for export
            metrics: List of metric names to export
            include_raw_events: Whether to include raw telemetry

        Returns:
            MetricsExportResult as dict
        """
        from guideai.metrics_contracts import MetricsExportRequest

        request = MetricsExportRequest(
            format=format,
            start_date=start_date,
            end_date=end_date,
            metrics=list(metrics or []),
            include_raw_events=include_raw_events,
        )
        export = self._service.export_metrics(request)
        return self._format_export(export)


class RestMetricsServiceAdapter(BaseMetricsServiceAdapter):
    """REST-style adapter for MetricsService endpoints."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="REST_API")

    def get_summary(self, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Get metrics summary from HTTP query parameters.

        Args:
            payload: Query parameters (start_date, end_date, use_cache)

        Returns:
            MetricsSummary as dict
        """
        payload = payload or {}
        summary = self._service.get_summary(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            use_cache=payload.get("use_cache", True),
        )
        return self._format_summary(summary)

    def export_metrics(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Export metrics from HTTP POST body.

        Args:
            payload: Export request fields

        Returns:
            MetricsExportResult as dict
        """
        from guideai.metrics_contracts import MetricsExportRequest

        request = MetricsExportRequest(
            format=payload.get("format", "json"),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            metrics=list(payload.get("metrics", [])),
            include_raw_events=payload.get("include_raw_events", False),
        )
        export = self._service.export_metrics(request)
        return self._format_export(export)

    def create_subscription(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create real-time metrics subscription.

        Args:
            payload: Subscription parameters (metrics, refresh_interval_seconds)

        Returns:
            MetricsSubscription as dict
        """
        subscription = self._service.create_subscription(
            metrics=payload.get("metrics"),
            refresh_interval_seconds=payload.get("refresh_interval_seconds", 30),
        )
        return self._format_subscription(subscription)

    def cancel_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Cancel subscription.

        Args:
            subscription_id: Subscription to cancel

        Returns:
            Status dict
        """
        cancelled = self._service.cancel_subscription(subscription_id)
        return {"cancelled": cancelled, "subscription_id": subscription_id}


class MCPMetricsServiceAdapter(BaseMetricsServiceAdapter):
    """Adapter simulating MCP tool interactions for metrics."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="MCP")

    def get_summary(self, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """MCP metrics.getSummary tool.

        Args:
            payload: Optional filters (start_date, end_date)

        Returns:
            MetricsSummary as dict
        """
        payload = payload or {}
        summary = self._service.get_summary(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            use_cache=payload.get("use_cache", True),
        )
        return self._format_summary(summary)

    def export(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP metrics.export tool.

        Args:
            payload: Export request fields

        Returns:
            MetricsExportResult as dict
        """
        from guideai.metrics_contracts import MetricsExportRequest

        request = MetricsExportRequest(
            format=payload.get("format", "json"),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            metrics=list(payload.get("metrics", [])),
            include_raw_events=payload.get("include_raw_events", False),
        )
        export = self._service.export_metrics(request)
        return self._format_export(export)

    def subscribe(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP metrics.subscribe tool (creates subscription).

        Args:
            payload: Subscription parameters

        Returns:
            MetricsSubscription as dict
        """
        subscription = self._service.create_subscription(
            metrics=payload.get("metrics"),
            refresh_interval_seconds=payload.get("refresh_interval_seconds", 30),
        )
        return self._format_subscription(subscription)


# ============================================================================
# AgentOrchestratorService Adapters
# ============================================================================


class BaseAgentOrchestratorAdapter:
    """Shared adapter utilities for AgentOrchestratorService surfaces."""

    surface: str

    def __init__(self, service: Any, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _format_assignment(self, assignment: Any) -> Dict[str, Any]:
        return assignment.to_dict()


class CLIAgentOrchestratorAdapter(BaseAgentOrchestratorAdapter):
    """Adapter backing CLI agent orchestration commands."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="CLI")

    def assign_agent(
        self,
        *,
        run_id: Optional[str],
        requested_agent_id: Optional[str],
        stage: str,
        context: Optional[Dict[str, Any]],
        requested_by: Dict[str, Any],
    ) -> Dict[str, Any]:
        assignment = self._service.assign_agent(
            run_id=run_id,
            requested_agent_id=requested_agent_id,
            stage=stage,
            context=context,
            requested_by=requested_by,
        )
        return self._format_assignment(assignment)

    def switch_agent(
        self,
        *,
        assignment_id: str,
        target_agent_id: str,
        reason: Optional[str],
        allow_downgrade: bool,
        stage: Optional[str],
        issued_by: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        assignment = self._service.switch_agent(
            assignment_id=assignment_id,
            target_agent_id=target_agent_id,
            reason=reason,
            allow_downgrade=allow_downgrade,
            stage=stage,
            issued_by=issued_by,
        )
        return self._format_assignment(assignment)

    def get_status(
        self,
        *,
        run_id: Optional[str],
        assignment_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        assignment = self._service.get_status(run_id=run_id, assignment_id=assignment_id)
        return self._format_assignment(assignment) if assignment else None


# =============================================================================
# AgentAuth Service Adapters
# =============================================================================


class BaseAgentAuthServiceAdapter:
    """Base adapter for AgentAuth operations across surfaces."""

    def __init__(self, client: Any, surface: str = "UNKNOWN") -> None:
        self._client = client
        self.surface = surface

    def _format_grant(self, grant: Any) -> Dict[str, Any]:
        """Convert GrantMetadata to dict."""
        from dataclasses import asdict
        return asdict(grant)

    def _format_obligation(self, obligation: Any) -> Dict[str, Any]:
        """Convert Obligation to dict."""
        from dataclasses import asdict
        return asdict(obligation)


class CLIAgentAuthServiceAdapter(BaseAgentAuthServiceAdapter):
    """Adapter for CLI auth commands."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, surface="CLI")

    def ensure_grant(
        self,
        agent_id: str,
        tool_name: str,
        scopes: List[str],
        user_id: Optional[str] = None,
        context: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """CLI: guideai auth ensure-grant"""
        from .agent_auth import EnsureGrantRequest

        request = EnsureGrantRequest(
            agent_id=agent_id,
            surface=self.surface,
            tool_name=tool_name,
            scopes=scopes,
            user_id=user_id,
            context=context or {},
        )
        response = self._client.ensure_grant(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.consent_url:
            result["consent_url"] = response.consent_url
            result["consent_request_id"] = response.consent_request_id
        if response.grant:
            result["grant"] = self._format_grant(response.grant)
        if response.audit_action_id:
            result["audit_action_id"] = response.audit_action_id

        return result

    def list_grants(
        self,
        agent_id: str,
        user_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        include_expired: bool = False,
    ) -> List[Dict[str, Any]]:
        """CLI: guideai auth list-grants"""
        from .agent_auth import ListGrantsRequest

        request = ListGrantsRequest(
            agent_id=agent_id,
            user_id=user_id,
            tool_name=tool_name,
            include_expired=include_expired,
        )
        grants = self._client.list_grants(request)
        return [self._format_grant(grant) for grant in grants]

    def policy_preview(
        self,
        agent_id: str,
        tool_name: str,
        scopes: List[str],
        user_id: Optional[str] = None,
        context: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """CLI: guideai auth policy-preview"""
        from .agent_auth import PolicyPreviewRequest

        request = PolicyPreviewRequest(
            agent_id=agent_id,
            tool_name=tool_name,
            scopes=scopes,
            user_id=user_id,
            context=context or {},
        )
        response = self._client.policy_preview(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.bundle_version:
            result["bundle_version"] = response.bundle_version
        if response.obligations:
            result["obligations"] = [self._format_obligation(o) for o in response.obligations]

        return result

    def revoke_grant(
        self,
        grant_id: str,
        revoked_by: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """CLI: guideai auth revoke"""
        from .agent_auth import RevokeGrantRequest

        request = RevokeGrantRequest(
            grant_id=grant_id,
            revoked_by=revoked_by,
            reason=reason,
        )
        response = self._client.revoke_grant(request)

        result: Dict[str, Any] = {
            "grant_id": response.grant_id,
            "success": response.success,
        }
        if response.reason:
            result["reason"] = response.reason.value

        return result


class RestAgentAuthServiceAdapter(BaseAgentAuthServiceAdapter):
    """Adapter for REST API auth endpoints."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, surface="API")

    def ensure_grant(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST: POST /v1/auth/grants"""
        from .agent_auth import EnsureGrantRequest

        request = EnsureGrantRequest(
            agent_id=payload["agent_id"],
            surface=self.surface,
            tool_name=payload["tool_name"],
            scopes=payload["scopes"],
            user_id=payload.get("user_id"),
            context=payload.get("context", {}),
        )
        response = self._client.ensure_grant(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.consent_url:
            result["consent_url"] = response.consent_url
            result["consent_request_id"] = response.consent_request_id
        if response.grant:
            result["grant"] = self._format_grant(response.grant)
        if response.audit_action_id:
            result["audit_action_id"] = response.audit_action_id

        return result

    def list_grants(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """REST: GET /v1/auth/grants"""
        from .agent_auth import ListGrantsRequest

        request = ListGrantsRequest(
            agent_id=payload["agent_id"],
            user_id=payload.get("user_id"),
            tool_name=payload.get("tool_name"),
            include_expired=payload.get("include_expired", False),
        )
        grants = self._client.list_grants(request)
        return [self._format_grant(grant) for grant in grants]

    def policy_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST: POST /v1/auth/policy/preview"""
        from .agent_auth import PolicyPreviewRequest

        request = PolicyPreviewRequest(
            agent_id=payload["agent_id"],
            tool_name=payload["tool_name"],
            scopes=payload["scopes"],
            user_id=payload.get("user_id"),
            context=payload.get("context", {}),
        )
        response = self._client.policy_preview(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.bundle_version:
            result["bundle_version"] = response.bundle_version
        if response.obligations:
            result["obligations"] = [self._format_obligation(o) for o in response.obligations]

        return result

    def revoke_grant(self, grant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST: DELETE /v1/auth/grants/{grant_id}"""
        from .agent_auth import RevokeGrantRequest

        request = RevokeGrantRequest(
            grant_id=grant_id,
            revoked_by=payload["revoked_by"],
            reason=payload.get("reason"),
        )
        response = self._client.revoke_grant(request)

        result: Dict[str, Any] = {
            "grant_id": response.grant_id,
            "success": response.success,
        }
        if response.reason:
            result["reason"] = response.reason.value

        return result


class MCPAgentAuthServiceAdapter(BaseAgentAuthServiceAdapter):
    """Adapter simulating MCP tool interactions for AgentAuth."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, surface="MCP")

    def ensure_grant(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP auth.ensureGrant tool."""
        from .agent_auth import EnsureGrantRequest

        request = EnsureGrantRequest(
            agent_id=payload["agent_id"],
            surface=payload.get("surface", "MCP"),
            tool_name=payload["tool_name"],
            scopes=payload["scopes"],
            user_id=payload.get("user_id"),
            context=payload.get("context", {}),
        )
        response = self._client.ensure_grant(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.consent_url:
            result["consent_url"] = response.consent_url
            result["consent_request_id"] = response.consent_request_id
        if response.grant:
            result["grant"] = self._format_grant(response.grant)
        if response.audit_action_id:
            result["audit_action_id"] = response.audit_action_id

        return result

    def list_grants(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """MCP auth.listGrants tool."""
        from .agent_auth import ListGrantsRequest

        request = ListGrantsRequest(
            agent_id=payload["agent_id"],
            user_id=payload.get("user_id"),
            tool_name=payload.get("tool_name"),
            include_expired=payload.get("include_expired", False),
        )
        grants = self._client.list_grants(request)
        return [self._format_grant(grant) for grant in grants]

    def policy_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP auth.policy.preview tool."""
        from .agent_auth import PolicyPreviewRequest

        request = PolicyPreviewRequest(
            agent_id=payload["agent_id"],
            tool_name=payload["tool_name"],
            scopes=payload["scopes"],
            user_id=payload.get("user_id"),
            context=payload.get("context", {}),
        )
        response = self._client.policy_preview(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.bundle_version:
            result["bundle_version"] = response.bundle_version
        if response.obligations:
            result["obligations"] = [self._format_obligation(o) for o in response.obligations]

        return result

    def revoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP auth.revoke tool."""
        from .agent_auth import RevokeGrantRequest

        request = RevokeGrantRequest(
            grant_id=payload["grant_id"],
            revoked_by=payload["revoked_by"],
            reason=payload.get("reason"),
        )
        response = self._client.revoke_grant(request)

        result: Dict[str, Any] = {
            "grant_id": response.grant_id,
            "success": response.success,
        }
        if response.reason:
            result["reason"] = response.reason.value

        return result


class BaseDeviceFlowAdapter:
    """Surface-specific wrapper around DeviceFlowManager."""

    def __init__(self, manager: DeviceFlowManager, surface: str) -> None:
        self._manager = manager
        self.surface = surface

    @staticmethod
    def _normalize_user_code(user_code: str) -> str:
        stripped = "".join(ch for ch in user_code if ch.isalnum())
        if not stripped:
            raise ValueError("user_code must contain letters or numbers")
        upper = stripped.upper()
        if len(upper) >= 8:
            midpoint = len(upper) // 2
            return f"{upper[:midpoint]}-{upper[midpoint:]}"
        return upper

    @staticmethod
    def _format_session(session: DeviceAuthorizationSession) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "device_code": session.device_code,
            "user_code": session.user_code,
            "client_id": session.client_id,
            "scopes": list(session.scopes),
            "surface": session.surface,
            "status": session.status.value,
            "verification_uri": session.verification_uri,
            "verification_uri_complete": session.verification_uri_complete,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "poll_interval": session.poll_interval,
        }
        if session.approved_at:
            payload["approved_at"] = session.approved_at.isoformat()
        if session.denied_at:
            payload["denied_at"] = session.denied_at.isoformat()
        if session.denied_reason:
            payload["denied_reason"] = session.denied_reason
        return payload

    @staticmethod
    def _format_poll_result(result: DevicePollResult) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "status": result.status.value,
            "retry_after": result.retry_after,
            "expires_in": result.expires_in,
            "client_id": result.client_id,
            "scopes": list(result.scopes or []),
        }
        if result.denied_reason:
            payload["denied_reason"] = result.denied_reason
        if result.tokens:
            payload.update(
                {
                    "access_token": result.tokens.access_token,
                    "refresh_token": result.tokens.refresh_token,
                    "token_type": result.tokens.token_type,
                    "access_token_expires_at": result.tokens.access_token_expires_at.isoformat(),
                    "refresh_token_expires_at": result.tokens.refresh_token_expires_at.isoformat(),
                }
            )
        return payload

    def start_authorization(
        self,
        *,
        client_id: str,
        scopes: List[str],
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        session = self._manager.start_authorization(
            client_id=client_id,
            scopes=scopes,
            surface=self.surface,
            metadata=metadata,
        )
        return self._format_session(session)

    def lookup_user_code(self, user_code: str) -> Dict[str, Any]:
        normalized = self._normalize_user_code(user_code)
        session = self._manager.describe_user_code(normalized)
        return self._format_session(session)

    def poll(self, device_code: str) -> Dict[str, Any]:
        result = self._manager.poll_device_code(device_code)
        return self._format_poll_result(result)

    def refresh(self, refresh_token: str) -> Dict[str, Any]:
        session = self._manager.refresh_access_token(refresh_token)
        tokens = session.tokens
        assert tokens is not None, "refreshed session must include tokens"
        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "access_token_expires_at": tokens.access_token_expires_at.isoformat(),
            "refresh_token_expires_at": tokens.refresh_token_expires_at.isoformat(),
            "access_expires_in": tokens.access_expires_in(),
            "refresh_expires_in": tokens.refresh_expires_in(),
            "client_id": session.client_id,
            "scopes": list(session.scopes),
        }

    def approve(
        self,
        user_code: str,
        *,
        approver: str,
        roles: Optional[List[str]] = None,
        mfa_verified: bool = False,
    ) -> Dict[str, Any]:
        normalized = self._normalize_user_code(user_code)
        session = self._manager.approve_user_code(
            normalized,
            approver,
            approver_surface=self.surface,
            roles=roles,
            mfa_verified=mfa_verified,
        )
        return self._format_session(session)

    def deny(
        self,
        user_code: str,
        *,
        approver: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized = self._normalize_user_code(user_code)
        session = self._manager.deny_user_code(
            normalized,
            approver,
            approver_surface=self.surface,
            reason=reason,
        )
        return self._format_session(session)


class CLIDeviceFlowAdapter(BaseDeviceFlowAdapter):
    """Device flow adapter scoped to CLI surface."""

    def __init__(self, manager: DeviceFlowManager) -> None:
        super().__init__(manager, surface="CLI")


class MCPDeviceFlowAdapter(BaseDeviceFlowAdapter):
    """Device flow adapter scoped to MCP surface."""

    def __init__(self, manager: DeviceFlowManager) -> None:
        super().__init__(manager, surface="MCP")
