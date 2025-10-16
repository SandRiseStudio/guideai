"""Surface-specific adapters that wrap the core ActionService."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

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
from .task_assignments import TaskAssignmentService


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

    def _list(self, function: str | None) -> List[Dict[str, Any]]:
        return self._service.list_assignments(function=function)


class RestTaskAssignmentAdapter(BaseTaskAdapter):
    """Mimics REST API payloads for task assignment queries."""

    def __init__(self, service: TaskAssignmentService) -> None:
        super().__init__(service)

    def list_assignments(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        function = payload.get("function") if isinstance(payload, dict) else None
        return self._list(function)


class CLITaskAssignmentAdapter(BaseTaskAdapter):
    """Adapter backing CLI task assignment commands."""

    def __init__(self, service: TaskAssignmentService) -> None:
        super().__init__(service)

    def list_assignments(self, function: str | None = None) -> List[Dict[str, Any]]:
        return self._list(function)


class MCPTaskAssignmentAdapter(BaseTaskAdapter):
    """Adapter providing MCP task listing parity."""

    def __init__(self, service: TaskAssignmentService) -> None:
        super().__init__(service)

    def list_assignments(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        function = payload.get("function") if isinstance(payload, dict) else None
        return self._list(function)


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
