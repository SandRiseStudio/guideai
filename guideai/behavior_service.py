"""BehaviorService runtime implementation with PostgreSQL persistence."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from guideai.storage.postgres_pool import PostgresPool

from .action_contracts import Actor, utc_now_iso
from .telemetry import TelemetryClient

_BEHAVIOR_PG_DSN_ENV = "GUIDEAI_BEHAVIOR_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://guideai_behavior:dev_behavior_pass@localhost:5433/behaviors"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Behavior:
    behavior_id: str
    name: str
    description: str
    tags: List[str]
    created_at: str
    updated_at: str
    latest_version: str
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "behavior_id": self.behavior_id,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "latest_version": self.latest_version,
            "status": self.status,
        }


@dataclass(frozen=True)
class BehaviorVersion:
    behavior_id: str
    version: str
    instruction: str
    role_focus: str
    status: str
    trigger_keywords: List[str]
    examples: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    effective_from: str
    effective_to: Optional[str]
    created_by: str
    approval_action_id: Optional[str]
    embedding_checksum: Optional[str]
    embedding: Optional[List[float]] = None

    def to_dict(self, include_metadata: bool = True) -> Dict[str, Any]:
        payload = {
            "behavior_id": self.behavior_id,
            "version": self.version,
            "instruction": self.instruction,
            "role_focus": self.role_focus,
            "status": self.status,
            "trigger_keywords": list(self.trigger_keywords),
            "examples": [dict(example) for example in self.examples],
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "created_by": self.created_by,
            "approval_action_id": self.approval_action_id,
            "embedding_checksum": self.embedding_checksum,
        }
        if include_metadata:
            payload["metadata"] = dict(self.metadata)
            if self.embedding is not None:
                payload["embedding"] = list(self.embedding)
        return payload


@dataclass(frozen=True)
class BehaviorSearchResult:
    behavior: Behavior
    active_version: BehaviorVersion
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "behavior": self.behavior.to_dict(),
            "active_version": self.active_version.to_dict(),
            "score": self.score,
        }


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


@dataclass
class CreateBehaviorDraftRequest:
    name: str
    description: str
    instruction: str
    role_focus: str
    trigger_keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    embedding: Optional[List[float]] = None
    base_version: Optional[str] = None


@dataclass
class UpdateBehaviorDraftRequest:
    behavior_id: str
    version: str
    instruction: Optional[str] = None
    description: Optional[str] = None
    trigger_keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    examples: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    embedding: Optional[List[float]] = None


@dataclass
class ApproveBehaviorRequest:
    behavior_id: str
    version: str
    effective_from: str
    approval_action_id: Optional[str] = None


@dataclass
class DeprecateBehaviorRequest:
    behavior_id: str
    version: str
    effective_to: str
    successor_behavior_id: Optional[str] = None


@dataclass
class SearchBehaviorsRequest:
    query: Optional[str] = None
    tags: Optional[List[str]] = None
    role_focus: Optional[str] = None
    status: Optional[str] = None
    limit: int = 25


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BehaviorServiceError(Exception):
    """Base error for behavior operations."""


class BehaviorNotFoundError(BehaviorServiceError):
    """Raised when a behavior is missing."""


class BehaviorVersionError(BehaviorServiceError):
    """Raised when version transitions are invalid."""


class PersistenceError(BehaviorServiceError):
    """Raised when the underlying store fails."""


# ---------------------------------------------------------------------------
# BehaviorService implementation
# ---------------------------------------------------------------------------


class BehaviorService:
    """PostgreSQL-backed behavior service runtime."""

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
        behavior_retriever: Optional[Any] = None,
    ) -> None:
        self._dsn = self._resolve_dsn(dsn)
        self._telemetry = telemetry or TelemetryClient.noop()
        self._behavior_retriever = behavior_retriever
        self._pool = PostgresPool(self._dsn)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_behavior_draft(self, request: CreateBehaviorDraftRequest, actor: Actor) -> BehaviorVersion:
        """Create a new behavior and initial draft version."""

        behavior_id = str(uuid.uuid4())
        version = "1.0.0"
        timestamp = utc_now_iso()
        embedding_checksum = self._calculate_embedding_checksum(request.embedding)

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Insert behavior
            cur.execute(
                """
                INSERT INTO behaviors (
                    behavior_id, name, description, tags, created_at, updated_at, latest_version, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    behavior_id,
                    request.name,
                    request.description,
                    json.dumps(request.tags),
                    timestamp,
                    timestamp,
                    version,
                    "DRAFT",
                ),
            )
            # Insert behavior version
            cur.execute(
                """
                INSERT INTO behavior_versions (
                    behavior_id, version, instruction, role_focus, status,
                    trigger_keywords, examples, metadata, effective_from, effective_to,
                    created_by, approval_action_id, embedding_checksum, embedding
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    behavior_id,
                    version,
                    request.instruction,
                    request.role_focus,
                    "DRAFT",
                    json.dumps(request.trigger_keywords),
                    json.dumps(request.examples),
                    json.dumps(request.metadata),
                    timestamp,
                    None,
                    actor.id,
                    None,
                    embedding_checksum,
                    json.dumps(request.embedding) if request.embedding else None,
                ),
            )

        behavior = self._fetch_behavior(behavior_id)
        version_obj = self._fetch_behavior_version(behavior_id, version)
        self._telemetry.emit_event(
            event_type="behaviors.draft_created",
            payload={
                "behavior_id": behavior_id,
                "version": version,
                "tags": list(request.tags),
                "role_focus": request.role_focus,
            },
            actor=self._actor_payload(actor),
        )
        return version_obj

    def update_behavior_draft(self, request: UpdateBehaviorDraftRequest, actor: Actor) -> BehaviorVersion:
        """Update an existing draft or in-review behavior version."""

        version = self._fetch_behavior_version(request.behavior_id, request.version)
        if version.status not in {"DRAFT", "IN_REVIEW"}:
            raise BehaviorVersionError(
                f"Cannot update behavior {request.behavior_id} version {request.version}: status={version.status}"
            )

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Update behavior version fields
            updates = []
            values = []
            if request.instruction is not None:
                updates.append("instruction = %s")
                values.append(request.instruction)
            if request.trigger_keywords is not None:
                updates.append("trigger_keywords = %s")
                values.append(json.dumps(request.trigger_keywords))
            if request.examples is not None:
                updates.append("examples = %s")
                values.append(json.dumps(request.examples))
            if request.metadata is not None:
                updates.append("metadata = %s")
                values.append(json.dumps(request.metadata))
            if request.embedding is not None:
                updates.append("embedding = %s")
                values.append(json.dumps(request.embedding))
                updates.append("embedding_checksum = %s")
                values.append(self._calculate_embedding_checksum(request.embedding))

            if updates:
                values.extend([request.behavior_id, request.version])
                cur.execute(
                    f"UPDATE behavior_versions SET {', '.join(updates)} WHERE behavior_id = %s AND version = %s",
                    values,
                )

            # Update behavior table if needed
            behavior_updates = []
            behavior_values = []
            if request.description is not None:
                behavior_updates.append("description = %s")
                behavior_values.append(request.description)
            if request.tags is not None:
                behavior_updates.append("tags = %s")
                behavior_values.append(json.dumps(request.tags))
            if behavior_updates:
                behavior_updates.append("updated_at = %s")
                behavior_values.append(utc_now_iso())
                behavior_values.append(request.behavior_id)
                cur.execute(
                    f"UPDATE behaviors SET {', '.join(behavior_updates)} WHERE behavior_id = %s",
                    behavior_values,
                )

        updated_version = self._fetch_behavior_version(request.behavior_id, request.version)
        self._telemetry.emit_event(
            event_type="behaviors.draft_updated",
            payload={
                "behavior_id": request.behavior_id,
                "version": request.version,
                "updated_fields": [k.split()[0] for k in updates],
            },
            actor=self._actor_payload(actor),
        )
        return updated_version

    def submit_for_review(self, behavior_id: str, version: str, actor: Actor) -> BehaviorVersion:
        """Move a draft version into review."""

        version_obj = self._fetch_behavior_version(behavior_id, version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError(
                f"Only drafts can be submitted for review (status={version_obj.status})."
            )

        conn = self._ensure_connection()
        timestamp = utc_now_iso()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE behavior_versions
                   SET status = %s, effective_from = %s
                 WHERE behavior_id = %s AND version = %s
                """,
                ("IN_REVIEW", timestamp, behavior_id, version),
            )
            cur.execute(
                "UPDATE behaviors SET status = %s, updated_at = %s WHERE behavior_id = %s",
                ("IN_REVIEW", timestamp, behavior_id),
            )

        updated = self._fetch_behavior_version(behavior_id, version)
        self._telemetry.emit_event(
            event_type="behaviors.submitted_for_review",
            payload={"behavior_id": behavior_id, "version": version},
            actor=self._actor_payload(actor),
        )
        return updated

    def approve_behavior(self, request: ApproveBehaviorRequest, actor: Actor) -> BehaviorVersion:
        """Approve a behavior version and mark it active."""

        version_obj = self._fetch_behavior_version(request.behavior_id, request.version)
        if version_obj.status not in {"IN_REVIEW", "DRAFT"}:
            raise BehaviorVersionError(f"Cannot approve version with status={version_obj.status}.")

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE behavior_versions
                   SET status = %s, effective_from = %s, approval_action_id = %s
                 WHERE behavior_id = %s AND version = %s
                """,
                ("APPROVED", request.effective_from, request.approval_action_id, request.behavior_id, request.version),
            )
            cur.execute(
                """
                UPDATE behaviors
                   SET latest_version = %s, status = %s, updated_at = %s
                 WHERE behavior_id = %s
                """,
                (request.version, "APPROVED", utc_now_iso(), request.behavior_id),
            )
            cur.execute(
                """
                UPDATE behavior_versions
                   SET status = 'DEPRECATED', effective_to = %s
                 WHERE behavior_id = %s AND version != %s AND status = 'APPROVED' AND effective_to IS NULL
                """,
                (request.effective_from, request.behavior_id, request.version),
            )

        approved = self._fetch_behavior_version(request.behavior_id, request.version)
        self._telemetry.emit_event(
            event_type="behaviors.approved",
            payload={
                "behavior_id": request.behavior_id,
                "version": request.version,
                "approval_action_id": request.approval_action_id,
            },
            actor=self._actor_payload(actor),
        )

        # Trigger index rebuild when behaviors are approved
        if self._behavior_retriever is not None:
            try:
                rebuild_result = self._behavior_retriever.rebuild_index()
                self._telemetry.emit_event(
                    event_type="bci.behavior_retriever.auto_rebuild",
                    payload={
                        "trigger": "behavior_approved",
                        "behavior_id": request.behavior_id,
                        "version": request.version,
                        "rebuild_status": rebuild_result.get("status"),
                        "behavior_count": rebuild_result.get("behavior_count", 0),
                        "mode": rebuild_result.get("mode"),
                    },
                )
            except Exception as exc:
                self._telemetry.emit_event(
                    event_type="bci.behavior_retriever.auto_rebuild_failed",
                    payload={
                        "trigger": "behavior_approved",
                        "behavior_id": request.behavior_id,
                        "error": str(exc),
                    },
                )

        return approved

    def deprecate_behavior(self, request: DeprecateBehaviorRequest, actor: Actor) -> BehaviorVersion:
        """Deprecate an active behavior version."""

        version_obj = self._fetch_behavior_version(request.behavior_id, request.version)
        if version_obj.status != "APPROVED":
            raise BehaviorVersionError("Only approved versions can be deprecated.")

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE behavior_versions
                   SET status = %s, effective_to = %s
                 WHERE behavior_id = %s AND version = %s
                """,
                ("DEPRECATED", request.effective_to, request.behavior_id, request.version),
            )
            cur.execute(
                "UPDATE behaviors SET status = %s, updated_at = %s WHERE behavior_id = %s",
                ("DEPRECATED", utc_now_iso(), request.behavior_id),
            )

        deprecated = self._fetch_behavior_version(request.behavior_id, request.version)
        self._telemetry.emit_event(
            event_type="behaviors.deprecated",
            payload={
                "behavior_id": request.behavior_id,
                "version": request.version,
                "successor_behavior_id": request.successor_behavior_id,
            },
            actor=self._actor_payload(actor),
        )
        return deprecated

    def delete_behavior_draft(self, behavior_id: str, version: str, actor: Actor) -> None:
        """Delete a draft version."""

        version_obj = self._fetch_behavior_version(behavior_id, version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError("Only draft versions can be deleted.")

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM behavior_versions WHERE behavior_id = %s AND version = %s",
                (behavior_id, version),
            )
            cur.execute(
                "SELECT COUNT(*) FROM behavior_versions WHERE behavior_id = %s",
                (behavior_id,),
            )
            remaining = cur.fetchone()[0]
            if remaining == 0:
                cur.execute("DELETE FROM behaviors WHERE behavior_id = %s", (behavior_id,))

        self._telemetry.emit_event(
            event_type="behaviors.draft_deleted",
            payload={"behavior_id": behavior_id, "version": version},
            actor=self._actor_payload(actor),
        )

    def get_behavior(self, behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """Get a behavior and its versions."""

        behavior = self._fetch_behavior(behavior_id)
        versions = self._fetch_behavior_versions(behavior_id)
        if version:
            versions = [v for v in versions if v.version == version]
            if not versions:
                raise BehaviorVersionError(f"Version {version} not found for behavior {behavior_id}")
        return {
            "behavior": behavior.to_dict(),
            "versions": [v.to_dict() for v in versions],
        }

    def list_behaviors(
        self,
        *,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        role_focus: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List behaviors matching criteria."""

        rows = self._fetch_behaviors(status=status)
        results = []
        for behavior in rows:
            active_versions = self._fetch_behavior_versions(behavior.behavior_id)
            if role_focus:
                active_versions = [v for v in active_versions if v.role_focus == role_focus]
                if not active_versions:
                    continue
            if tags:
                if not set(tags).issubset(set(behavior.tags)):
                    continue
            results.append({
                "behavior": behavior.to_dict(),
                "active_version": active_versions[0].to_dict() if active_versions else None,
            })
        return results

    def search_behaviors(self, request: SearchBehaviorsRequest, actor: Optional[Actor] = None) -> List[BehaviorSearchResult]:
        """Search behaviors by query, tags, role focus."""

        query = (request.query or "").lower()
        behaviors = self._fetch_behaviors(status=request.status)
        matches: List[BehaviorSearchResult] = []

        for behavior in behaviors:
            versions = self._fetch_behavior_versions(behavior.behavior_id)
            active = next((v for v in versions if v.status == "APPROVED"), versions[0] if versions else None)
            if not active:
                continue
            if request.role_focus and active.role_focus != request.role_focus:
                continue
            if request.tags and not set(request.tags).issubset(set(behavior.tags)):
                continue

            score = self._calculate_score(query, behavior, active)
            if request.query and score == 0.0:
                continue
            matches.append(BehaviorSearchResult(behavior=behavior, active_version=active, score=score))

        matches.sort(key=lambda result: result.score, reverse=True)
        limited = matches[: request.limit]

        self._telemetry.emit_event(
            event_type="behaviors.search_performed",
            payload={
                "query": request.query or "",
                "tags": request.tags or [],
                "role_focus": request.role_focus,
                "status": request.status,
                "results": len(limited),
            },
            actor=self._actor_payload(actor) if actor else None,
        )
        return limited

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connection(self):
        """Acquire a pooled PostgreSQL connection proxy."""
        return self._pool.proxy()

    def _fetch_behavior(self, behavior_id: str) -> Behavior:
        """Fetch a single behavior by ID."""
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM behaviors WHERE behavior_id = %s",
                (behavior_id,),
            )
            row = cur.fetchone()

        if row is None:
            raise BehaviorNotFoundError(f"Behavior '{behavior_id}' not found")
        return self._row_to_behavior(row, cur.description)

    def _fetch_behaviors(self, status: Optional[str] = None) -> List[Behavior]:
        """Fetch behaviors optionally filtered by status."""
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM behaviors WHERE status = %s ORDER BY updated_at DESC",
                    (status,),
                )
            else:
                cur.execute("SELECT * FROM behaviors ORDER BY updated_at DESC")
            rows = cur.fetchall()
            desc = cur.description

        return [self._row_to_behavior(row, desc) for row in rows]

    def _fetch_behavior_version(self, behavior_id: str, version: str) -> BehaviorVersion:
        """Fetch a single behavior version."""
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM behavior_versions WHERE behavior_id = %s AND version = %s",
                (behavior_id, version),
            )
            row = cur.fetchone()

        if row is None:
            raise BehaviorVersionError(f"Version '{version}' not found for behavior '{behavior_id}'")
        return self._row_to_behavior_version(row, cur.description)

    def _fetch_behavior_versions(self, behavior_id: str) -> List[BehaviorVersion]:
        """Fetch all versions for a behavior."""
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM behavior_versions
                 WHERE behavior_id = %s
                 ORDER BY status = 'APPROVED' DESC, effective_from DESC
                """,
                (behavior_id,),
            )
            rows = cur.fetchall()
            desc = cur.description

        return [self._row_to_behavior_version(row, desc) for row in rows]

    @staticmethod
    def _calculate_embedding_checksum(embedding: Optional[Iterable[float]]) -> Optional[str]:
        """Calculate SHA256 checksum of embedding."""
        if embedding is None:
            return None
        encoded = json.dumps(list(embedding))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _calculate_score(query: str, behavior: Behavior, version: BehaviorVersion) -> float:
        """Simple text matching score for search."""
        if not query:
            return 1.0
        haystacks = [
            behavior.name.lower(),
            behavior.description.lower(),
            " ".join(behavior.tags).lower(),
            version.instruction.lower(),
            " ".join(version.trigger_keywords).lower(),
        ]
        matches = sum(1 for haystack in haystacks if query in haystack)
        return matches / len(haystacks)

    @staticmethod
    def _resolve_dsn(dsn: Optional[str]) -> str:
        """Resolve PostgreSQL DSN from argument or environment."""
        if dsn:
            return dsn
        env_dsn = os.getenv(_BEHAVIOR_PG_DSN_ENV)
        if env_dsn:
            return env_dsn
        return _DEFAULT_PG_DSN

    @staticmethod
    def _actor_payload(actor: Actor) -> Dict[str, str]:
        """Convert Actor to telemetry payload."""
        return {
            "id": actor.id,
            "role": actor.role,
            "surface": actor.surface,
        }

    @staticmethod
    def _row_to_behavior(row: tuple, description) -> Behavior:
        """Convert PostgreSQL row to Behavior object."""
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))
        return Behavior(
            behavior_id=data["behavior_id"],
            name=data["name"],
            description=data["description"],
            tags=json.loads(data["tags"]) if isinstance(data["tags"], str) else data["tags"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            latest_version=data["latest_version"],
            status=data["status"],
        )

    @staticmethod
    def _row_to_behavior_version(row: tuple, description) -> BehaviorVersion:
        """Convert PostgreSQL row to BehaviorVersion object."""
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))
        return BehaviorVersion(
            behavior_id=data["behavior_id"],
            version=data["version"],
            instruction=data["instruction"],
            role_focus=data["role_focus"],
            status=data["status"],
            trigger_keywords=json.loads(data["trigger_keywords"]) if isinstance(data["trigger_keywords"], str) else data["trigger_keywords"],
            examples=json.loads(data["examples"]) if isinstance(data["examples"], str) else data["examples"],
            metadata=json.loads(data["metadata"]) if isinstance(data["metadata"], str) else data["metadata"],
            effective_from=data["effective_from"],
            effective_to=data.get("effective_to"),
            created_by=data["created_by"],
            approval_action_id=data.get("approval_action_id"),
            embedding_checksum=data.get("embedding_checksum"),
            embedding=json.loads(data["embedding"]) if data.get("embedding") else None,
        )
