"""BehaviorService runtime implementation with PostgreSQL persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import psycopg2.errors

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

from guideai.storage.postgres_pool import PostgresPool
from guideai.storage.redis_cache import get_cache
from .utils.dsn import resolve_postgres_dsn

from .action_contracts import Actor, utc_now_iso
from .telemetry import TelemetryClient

_BEHAVIOR_PG_DSN_ENV = "GUIDEAI_BEHAVIOR_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://guideai_behavior:dev_behavior_pass@localhost:6433/behaviors"
DEFAULT_BEHAVIOR_NAMESPACE = "core"


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
    namespace: str = DEFAULT_BEHAVIOR_NAMESPACE

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
            "namespace": self.namespace,
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
    namespace: Optional[str] = DEFAULT_BEHAVIOR_NAMESPACE


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
        self._embedding_model = None

    def _get_embedding_model(self):
        """Lazy load the embedding model."""
        if self._embedding_model is None and SentenceTransformer is not None:
            model_name = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
            self._embedding_model = SentenceTransformer(model_name)
        return self._embedding_model

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using sentence-transformers."""
        model = self._get_embedding_model()
        if model is None:
            return None
        # Force numpy array return
        embedding = model.encode(text, convert_to_numpy=True)
        # Type checker might still be confused, but runtime is safe
        if hasattr(embedding, "tolist"):
            return embedding.tolist()  # type: ignore
        return list(embedding)  # type: ignore

    @staticmethod
    def _parse_embedding(raw_embedding: Any) -> Optional[List[float]]:
        """Parse embedding from database format to List[float].

        PostgreSQL BYTEA columns return memoryview objects via psycopg2.
        The embedding is stored as JSON string, so we need to decode and parse it.
        """
        if raw_embedding is None:
            return None
        if isinstance(raw_embedding, memoryview):
            return json.loads(raw_embedding.tobytes().decode('utf-8'))
        elif isinstance(raw_embedding, bytes):
            return json.loads(raw_embedding.decode('utf-8'))
        elif isinstance(raw_embedding, str):
            return json.loads(raw_embedding)
        elif isinstance(raw_embedding, list):
            return raw_embedding
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_behavior_draft(self, request: CreateBehaviorDraftRequest, actor: Actor) -> BehaviorVersion:
        """Create a new behavior and initial draft version.

        Uses actual DB schema: behavior.behaviors (id, keywords, is_active, is_deprecated, version)
        and behavior.behavior_versions (id, behavior_id, version, name, description, triggers, steps, etc.)
        """

        behavior_id = str(uuid.uuid4())
        version = 1  # Integer version in DB schema
        timestamp = utc_now_iso()

        # Generate embedding if not provided
        if request.embedding is None:
            embedding_text = f"{request.name} {request.description} {request.instruction}"
            request.embedding = self._generate_embedding(embedding_text)

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Insert behavior into actual schema
                # DB columns: id, org_id, name, namespace, description, category, triggers, steps, role,
                #             confidence_threshold, keywords, version, is_active, is_deprecated, created_at, updated_at
                cur.execute(
                    """
                    INSERT INTO behavior.behaviors (
                        id, name, namespace, description, category, triggers, steps, role,
                        confidence_threshold, keywords, version, is_active, is_deprecated, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        behavior_id,
                        request.name,
                        DEFAULT_BEHAVIOR_NAMESPACE,
                        request.description,
                        request.role_focus or "general",  # category
                        json.dumps(request.trigger_keywords),  # triggers as JSONB
                        json.dumps(request.examples),  # steps as JSONB
                        request.role_focus or "Student",  # role
                        0.8,  # confidence_threshold
                        request.tags,  # keywords as varchar[]
                        version,
                        False,  # is_active (draft)
                        False,  # is_deprecated
                        timestamp,
                        timestamp,
                    ),
                )
                # Insert behavior version
                # DB columns: id, behavior_id, version, name, description, triggers, steps, change_reason, changed_by, created_at
                cur.execute(
                    """
                    INSERT INTO behavior.behavior_versions (
                        id, behavior_id, version, name, description, triggers, steps, change_reason, changed_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()),  # version record id
                        behavior_id,
                        version,
                        request.name,
                        request.instruction,  # description in versions = instruction
                        json.dumps(request.trigger_keywords),
                        json.dumps(request.examples),
                        "Initial draft",
                        actor.id,
                        timestamp,
                    ),
                )

        self._pool.run_transaction(
            "behavior.create_draft",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={
                "behavior_id": behavior_id,
                "version": str(version),
                "role_focus": request.role_focus,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        behavior = self._fetch_behavior(behavior_id)
        version_obj = self._fetch_behavior_version(behavior_id, str(version))
        self._telemetry.emit_event(
            event_type="behaviors.draft_created",
            payload={
                "behavior_id": behavior_id,
                "version": str(version),
                "tags": list(request.tags),
                "role_focus": request.role_focus,
            },
            actor=self._actor_payload(actor),
        )

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

        return version_obj

    def update_behavior_draft(self, request: UpdateBehaviorDraftRequest, actor: Actor) -> BehaviorVersion:
        """Update an existing draft or in-review behavior version.

        Uses actual DB schema: behavior.behaviors and behavior.behavior_versions
        """

        version = self._fetch_behavior_version(request.behavior_id, request.version)
        if version.status not in {"DRAFT", "IN_REVIEW"}:
            raise BehaviorVersionError(
                f"Cannot update behavior {request.behavior_id} version {request.version}: status={version.status}"
            )

        def _execute(conn: Any) -> List[str]:
            with conn.cursor() as cur:
                # Update behavior version fields
                # DB columns: name, description (=instruction), triggers (=trigger_keywords), steps (=examples)
                updates = []
                values = []

                if request.instruction is not None:
                    updates.append("description = %s")  # instruction stored as description in version table
                    values.append(request.instruction)
                if request.trigger_keywords is not None:
                    updates.append("triggers = %s")
                    values.append(json.dumps(request.trigger_keywords))
                if request.examples is not None:
                    updates.append("steps = %s")
                    values.append(json.dumps(request.examples))

                if updates:
                    values.extend([request.behavior_id, request.version])
                    cur.execute(
                        f"UPDATE behavior.behavior_versions SET {', '.join(updates)} WHERE behavior_id = %s AND version = %s::int",
                        values,
                    )

                # Update behavior table if needed
                # DB columns: name, description, keywords (=tags), triggers, steps, updated_at
                behavior_updates = []
                behavior_values = []
                if request.description is not None:
                    behavior_updates.append("description = %s")
                    behavior_values.append(request.description)
                if request.tags is not None:
                    behavior_updates.append("keywords = %s")
                    behavior_values.append(request.tags)  # varchar[] directly
                if request.trigger_keywords is not None:
                    behavior_updates.append("triggers = %s")
                    behavior_values.append(json.dumps(request.trigger_keywords))
                if request.examples is not None:
                    behavior_updates.append("steps = %s")
                    behavior_values.append(json.dumps(request.examples))
                if behavior_updates:
                    behavior_updates.append("updated_at = %s")
                    behavior_values.append(utc_now_iso())
                    behavior_values.append(request.behavior_id)
                    cur.execute(
                        f"UPDATE behavior.behaviors SET {', '.join(behavior_updates)} WHERE id = %s",
                        behavior_values,
                    )
                return [k.split()[0] for k in updates]

        updated_fields = self._pool.run_transaction(
            "behavior.update_draft",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={
                "behavior_id": request.behavior_id,
                "version": request.version,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        updated_version = self._fetch_behavior_version(request.behavior_id, request.version)
        self._telemetry.emit_event(
            event_type="behaviors.draft_updated",
            payload={
                "behavior_id": request.behavior_id,
                "version": request.version,
                "updated_fields": updated_fields,
            },
            actor=self._actor_payload(actor),
        )

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

        return updated_version

    def submit_for_review(self, behavior_id: str, version: str, actor: Actor) -> BehaviorVersion:
        """Move a draft version into review.

        Note: The actual DB schema doesn't have a status column in behavior_versions.
        We track review state via is_active flag on the behaviors table.
        For now, we just update timestamps and log the event.
        """

        version_obj = self._fetch_behavior_version(behavior_id, version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError(
                f"Only drafts can be submitted for review (status={version_obj.status})."
            )

        timestamp = utc_now_iso()

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Update behavior_versions with change_reason to track review submission
                cur.execute(
                    """
                    UPDATE behavior.behavior_versions
                       SET change_reason = %s
                     WHERE behavior_id = %s AND version = %s::int
                    """,
                    (f"Submitted for review at {timestamp}", behavior_id, version),
                )
                # Update behaviors timestamp
                cur.execute(
                    "UPDATE behavior.behaviors SET updated_at = %s WHERE id = %s",
                    (timestamp, behavior_id),
                )

        self._pool.run_transaction(
            operation="submit_for_review",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={"behavior_id": behavior_id, "version": version},
            executor=_execute,
            telemetry=self._telemetry,
        )

        updated = self._fetch_behavior_version(behavior_id, version)
        self._telemetry.emit_event(
            event_type="behaviors.submitted_for_review",
            payload={"behavior_id": behavior_id, "version": version},
            actor=self._actor_payload(actor),
        )
        return updated

    def approve_behavior(self, request: ApproveBehaviorRequest, actor: Actor) -> BehaviorVersion:
        """Approve a behavior version and mark it active.

        Uses actual DB schema: is_active/is_deprecated flags instead of status column
        """

        version_obj = self._fetch_behavior_version(request.behavior_id, request.version)
        if version_obj.status not in {"IN_REVIEW", "DRAFT"}:
            raise BehaviorVersionError(f"Cannot approve version with status={version_obj.status}.")

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Update behavior_versions change_reason
                cur.execute(
                    """
                    UPDATE behavior.behavior_versions
                       SET change_reason = %s
                     WHERE behavior_id = %s AND version = %s::int
                    """,
                    (f"Approved at {request.effective_from}", request.behavior_id, request.version),
                )
                # Update behaviors: set is_active=true, update version and timestamp
                cur.execute(
                    """
                    UPDATE behavior.behaviors
                       SET version = %s::int, is_active = true, is_deprecated = false, updated_at = %s
                     WHERE id = %s
                    """,
                    (request.version, utc_now_iso(), request.behavior_id),
                )

        self._pool.run_transaction(
            "behavior.approve",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={
                "behavior_id": request.behavior_id,
                "version": request.version,
                "approval_action_id": request.approval_action_id,
            },
            executor=_execute,
            telemetry=self._telemetry,
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

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

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
        """Deprecate an active behavior version.

        Uses actual DB schema: is_deprecated flag instead of status column
        """

        version_obj = self._fetch_behavior_version(request.behavior_id, request.version)
        if version_obj.status != "APPROVED":
            raise BehaviorVersionError("Only approved versions can be deprecated.")

        timestamp = utc_now_iso()
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Update behavior_versions change_reason
            cur.execute(
                """
                UPDATE behavior.behavior_versions
                   SET change_reason = %s
                 WHERE behavior_id = %s AND version = %s::int
                """,
                (f"Deprecated at {request.effective_to}", request.behavior_id, request.version),
            )
            # Update behaviors: set is_deprecated=true
            cur.execute(
                """
                UPDATE behavior.behaviors
                   SET is_deprecated = true, is_active = false, deprecation_reason = %s, updated_at = %s
                 WHERE id = %s
                """,
                (f"Deprecated, successor: {request.successor_behavior_id or 'none'}", timestamp, request.behavior_id),
            )
        conn.commit()

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

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

        return deprecated

    def delete_behavior_draft(self, behavior_id: str, version: str, actor: Actor) -> None:
        """Delete a draft version.

        Uses actual DB schema: behavior.behaviors and behavior.behavior_versions
        """

        version_obj = self._fetch_behavior_version(behavior_id, version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError("Only draft versions can be deleted.")

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM behavior.behavior_versions WHERE behavior_id = %s AND version = %s::int",
                    (behavior_id, version),
                )
                cur.execute(
                    "SELECT COUNT(*) FROM behavior.behavior_versions WHERE behavior_id = %s",
                    (behavior_id,),
                )
                remaining = cur.fetchone()[0]
                if remaining == 0:
                    cur.execute("DELETE FROM behavior.behaviors WHERE id = %s", (behavior_id,))

        self._pool.run_transaction(
            "behavior.delete_draft",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={
                "behavior_id": behavior_id,
                "version": version,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

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
        """List behaviors matching criteria.

        Uses optimized JOIN query + Redis caching to achieve P95 <100ms:
        1. Check cache for matching query (5-min TTL)
        2. If miss, fetch from DB with optimized JOIN
        3. Cache result for subsequent requests

        Cache invalidated on: create_behavior_draft, approve_behavior, deprecate_behavior
        """

        # Build cache key from query parameters
        cache = get_cache()
        cache_params = {}
        if status:
            cache_params['status'] = status
        if tags:
            cache_params['tags'] = sorted(tags)  # Sort for consistent hashing
        if role_focus:
            cache_params['role_focus'] = role_focus

        cache_key = cache._make_key('behavior', 'list', cache_params if cache_params else None)

        # Try cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Cache miss - fetch from database with optimized query
        behavior_tuples = self._fetch_behaviors_with_versions(status=status)
        results = []

        for behavior, active_versions in behavior_tuples:
            # Filter by role_focus if specified
            if role_focus:
                active_versions = [v for v in active_versions if v.role_focus == role_focus]
                if not active_versions:
                    continue

            # Filter by tags if specified
            if tags:
                if not set(tags).issubset(set(behavior.tags)):
                    continue

            results.append({
                "behavior": behavior.to_dict(),
                "active_version": active_versions[0].to_dict() if active_versions else None,
            })

        # Cache result using centralized TTL (30 minutes)
        from guideai.storage.redis_cache import get_ttl
        cache.set(cache_key, results, ttl=get_ttl('behavior', 'list'))

        return results

    def search_behaviors(self, request: SearchBehaviorsRequest, actor: Optional[Actor] = None) -> List[BehaviorSearchResult]:
        """Search behaviors by query, tags, role focus.

        Uses optimized JOIN query to eliminate N+1 performance problem.
        Results are cached with explicit invalidation on write operations.
        """
        # Build cache key from search parameters
        cache = get_cache()
        from guideai.storage.redis_cache import get_ttl

        cache_params = {
            'query': (request.query or "").lower(),
            'status': request.status,
            'namespace': request.namespace,
            'role_focus': request.role_focus,
            'tags': sorted(request.tags) if request.tags else [],
            'limit': request.limit,
        }
        cache_key = cache._make_key('behavior', 'search', cache_params)

        # Try cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            # Deserialize from cached dict format
            return [
                BehaviorSearchResult(
                    behavior=Behavior(**r['behavior']),
                    active_version=BehaviorVersion(**r['active_version']) if r.get('active_version') else None,
                    score=r['score']
                )
                for r in cached_result
            ]

        query = (request.query or "").lower()
        # Use optimized fetch that gets behaviors + versions in single query
        behavior_tuples = self._fetch_behaviors_with_versions(
            status=request.status,
            namespace=request.namespace
        )
        matches: List[BehaviorSearchResult] = []

        for behavior, versions in behavior_tuples:
            # Get active (APPROVED) version or first version
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

        # Cache the result
        cached_data = [
            {
                'behavior': r.behavior.to_dict(),
                'active_version': r.active_version.to_dict() if r.active_version else None,
                'score': r.score
            }
            for r in limited
        ]
        cache.set(cache_key, cached_data, ttl=get_ttl('behavior', 'search'))

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
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM behavior.behaviors WHERE id = %s",
                    (behavior_id,),
                )
                row = cur.fetchone()
                desc = cur.description
        except psycopg2.errors.InvalidTextRepresentation:
            # Invalid UUID format - treat as not found
            raise BehaviorNotFoundError(f"Behavior '{behavior_id}' not found")

        if row is None:
            raise BehaviorNotFoundError(f"Behavior '{behavior_id}' not found")
        return self._row_to_behavior(row, desc)

    def _fetch_behaviors(self, status: Optional[str] = None) -> List[Behavior]:
        """Fetch behaviors optionally filtered by status."""
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            if status:
                # Map status to is_active/is_deprecated
                if status == "APPROVED":
                    cur.execute(
                        "SELECT * FROM behavior.behaviors WHERE is_active = true AND is_deprecated = false ORDER BY updated_at DESC"
                    )
                elif status == "DEPRECATED":
                    cur.execute(
                        "SELECT * FROM behavior.behaviors WHERE is_deprecated = true ORDER BY updated_at DESC"
                    )
                elif status == "DRAFT":
                    cur.execute(
                        "SELECT * FROM behavior.behaviors WHERE is_active = false AND is_deprecated = false ORDER BY updated_at DESC"
                    )
                else:
                    cur.execute("SELECT * FROM behavior.behaviors ORDER BY updated_at DESC")
            else:
                cur.execute("SELECT * FROM behavior.behaviors ORDER BY updated_at DESC")
            rows = cur.fetchall()
            desc = cur.description

        return [self._row_to_behavior(row, desc) for row in rows]

    def _fetch_behaviors_with_versions(
        self, status: Optional[str] = None, namespace: Optional[str] = None
    ) -> List[Tuple[Behavior, List[BehaviorVersion]]]:
        """Fetch behaviors with their versions in a single optimized JOIN query.

        This method eliminates N+1 query problems by fetching all behaviors and their
        versions in one database round trip, reducing query count from 1+N to 1.

        Performance improvement: ~13x faster for list operations under load.

        Note: Maps actual DB schema (behavior.behaviors with 'id', 'keywords', 'is_active')
        to the Behavior/BehaviorVersion dataclasses expected by the service layer.

        Returns:
            List of (behavior, versions) tuples, where versions are ordered by version DESC.
        """
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Query actual DB schema and map to expected fields
            # DB: id, keywords (varchar[]), is_active, is_deprecated, version (int)
            # Code expects: behavior_id, tags (list), status (str), latest_version (str)
            query = """
                SELECT
                    b.id, b.name, b.description, b.keywords, b.created_at,
                    b.updated_at, b.version, b.is_active, b.is_deprecated, b.namespace,
                    b.category, b.role, b.triggers, b.steps, b.confidence_threshold,
                    bv.id as version_id, bv.version as bv_version, bv.name as bv_name,
                    bv.description as bv_description, bv.triggers as bv_triggers,
                    bv.steps as bv_steps, bv.change_reason, bv.changed_by, bv.created_at as bv_created_at
                FROM behavior.behaviors b
                LEFT JOIN behavior.behavior_versions bv ON b.id = bv.behavior_id
                WHERE 1=1
            """
            params = []

            # Map status filter to is_active/is_deprecated
            if status:
                if status == "APPROVED":
                    query += " AND b.is_active = true AND b.is_deprecated = false"
                elif status == "DEPRECATED":
                    query += " AND b.is_deprecated = true"
                elif status == "DRAFT":
                    query += " AND b.is_active = false AND b.is_deprecated = false"

            if namespace:
                query += " AND COALESCE(b.namespace, %s) = %s"
                params.extend([DEFAULT_BEHAVIOR_NAMESPACE, namespace])

            query += " ORDER BY b.updated_at DESC, bv.version DESC"

            cur.execute(query, params)
            rows = cur.fetchall()

        # Group results by behavior_id since we're now getting all versions
        behavior_map: Dict[str, Tuple[Behavior, List[BehaviorVersion]]] = {}

        for row in rows:
            behavior_id = str(row[0])
            # Map is_active/is_deprecated to status string
            is_active = row[7]
            is_deprecated = row[8]
            if is_deprecated:
                derived_status = "DEPRECATED"
            elif is_active:
                derived_status = "APPROVED"
            else:
                derived_status = "DRAFT"

            # Create or reuse Behavior object
            if behavior_id not in behavior_map:
                behavior = Behavior(
                    behavior_id=str(row[0]),
                    name=row[1],
                    description=row[2] or "",
                    tags=list(row[3]) if row[3] else [],  # keywords (varchar[]) -> tags
                    created_at=str(row[4]) if row[4] else "",
                    updated_at=str(row[5]) if row[5] else "",
                    latest_version=str(row[6]) if row[6] else "1",  # version (int) -> latest_version (str)
                    status=derived_status,
                    namespace=row[9] if row[9] else DEFAULT_BEHAVIOR_NAMESPACE,
                )
                behavior_map[behavior_id] = (behavior, [])

            # Add BehaviorVersion if exists (bv_version is at index 16)
            if row[16] is not None:
                # Map behavior_versions schema to BehaviorVersion dataclass
                # DB has: id, behavior_id, version, name, description, triggers, steps, change_reason, changed_by, created_at
                # Code expects: behavior_id, version, instruction, role_focus, status, trigger_keywords, examples, metadata, ...
                version = BehaviorVersion(
                    behavior_id=str(row[0]),
                    version=str(row[16]),  # bv.version
                    instruction=row[18] or "",  # bv.description -> instruction
                    trigger_keywords=row[19] if isinstance(row[19], list) else [],  # bv.triggers -> trigger_keywords
                    role_focus=row[11] or "Student",  # b.role -> role_focus
                    status=derived_status,  # Inherit from parent behavior
                    examples=row[20] if isinstance(row[20], list) else [],  # bv.steps -> examples
                    metadata={},
                    embedding_checksum=None,
                    embedding=None,
                    effective_from=str(row[23]) if row[23] else "",  # bv.created_at -> effective_from
                    effective_to=None,
                    created_by=row[22] or "",  # bv.changed_by -> created_by
                    approval_action_id=None,
                )
                behavior_map[behavior_id][1].append(version)

        # Return in order (already sorted by b.updated_at DESC in query)
        return list(behavior_map.values())

    def _fetch_behavior_version(self, behavior_id: str, version: str) -> BehaviorVersion:
        """Fetch a single behavior version.

        Uses actual DB schema: behavior.behavior_versions joined with behavior.behaviors
        to get role information.
        """
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Join with behaviors to get role and is_active/is_deprecated for status
            cur.execute(
                """
                SELECT bv.id, bv.behavior_id, bv.version, bv.name, bv.description,
                       bv.triggers, bv.steps, bv.change_reason, bv.changed_by, bv.created_at,
                       b.role, b.is_active, b.is_deprecated
                FROM behavior.behavior_versions bv
                JOIN behavior.behaviors b ON b.id = bv.behavior_id
                WHERE bv.behavior_id = %s AND bv.version = %s::int
                """,
                (behavior_id, version),
            )
            row = cur.fetchone()
            desc = cur.description

        if row is None:
            raise BehaviorVersionError(f"Version '{version}' not found for behavior '{behavior_id}'")

        # Use helper method to convert row to BehaviorVersion
        return self._row_to_behavior_version(row, desc)

    def _fetch_behavior_versions(self, behavior_id: str) -> List[BehaviorVersion]:
        """Fetch all versions for a behavior.

        Uses actual DB schema: behavior.behavior_versions
        """
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Join with behaviors to get role and is_active/is_deprecated for status
            cur.execute(
                """
                SELECT bv.id, bv.behavior_id, bv.version, bv.name, bv.description,
                       bv.triggers, bv.steps, bv.change_reason, bv.changed_by, bv.created_at,
                       b.role, b.is_active, b.is_deprecated
                FROM behavior.behavior_versions bv
                JOIN behavior.behaviors b ON b.id = bv.behavior_id
                WHERE bv.behavior_id = %s
                ORDER BY bv.version DESC
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
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    @classmethod
    def _calculate_score(cls, query: str, behavior: Behavior, version: BehaviorVersion) -> float:
        """Approximate text match score using keyword overlap."""
        query_tokens = cls._tokenize(query)
        if not query_tokens:
            return 1.0

        haystack_tokens: List[str] = []
        for content in (
            behavior.name,
            behavior.description,
            " ".join(behavior.tags),
            version.instruction,
            " ".join(version.trigger_keywords),
        ):
            haystack_tokens.extend(cls._tokenize(content))

        if not haystack_tokens:
            return 0.0

        token_set = set(haystack_tokens)
        matches = sum(1 for token in query_tokens if token in token_set)
        return matches / len(query_tokens)

    @staticmethod
    def _resolve_dsn(dsn: Optional[str]) -> str:
        """Resolve PostgreSQL DSN from argument or environment."""
        return resolve_postgres_dsn(
            service="BEHAVIOR",
            explicit_dsn=dsn,
            env_var=_BEHAVIOR_PG_DSN_ENV,
            default_dsn=_DEFAULT_PG_DSN,
        )

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
        """Convert PostgreSQL row to Behavior object.

        Maps actual DB schema (id, keywords, is_active, is_deprecated, version)
        to Behavior dataclass (behavior_id, tags, status, latest_version).
        """
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))

        # Map is_active/is_deprecated to status string
        is_active = data.get("is_active", True)
        is_deprecated = data.get("is_deprecated", False)
        if is_deprecated:
            derived_status = "DEPRECATED"
        elif is_active:
            derived_status = "APPROVED"
        else:
            derived_status = "DRAFT"

        # Handle both old schema (behavior_id) and new schema (id)
        behavior_id = data.get("behavior_id") or data.get("id")

        # Handle both old schema (tags as JSONB) and new schema (keywords as varchar[])
        tags_data = data.get("tags") or data.get("keywords") or []
        if isinstance(tags_data, str):
            tags = json.loads(tags_data)
        else:
            tags = list(tags_data) if tags_data else []

        return Behavior(
            behavior_id=str(behavior_id),
            name=data["name"],
            description=data.get("description") or "",
            tags=tags,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            latest_version=str(data.get("latest_version") or data.get("version") or "1"),
            status=data.get("status") or derived_status,
            namespace=data.get("namespace", DEFAULT_BEHAVIOR_NAMESPACE),
        )

    @staticmethod
    def _row_to_behavior_version(row: tuple, description) -> BehaviorVersion:
        """Convert PostgreSQL row to BehaviorVersion object.

        Handles both old schema (instruction, trigger_keywords, examples) and
        new schema (description, triggers, steps) columns.
        """
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))

        # Handle embedding deserialization from BYTEA column
        # psycopg2 returns memoryview for BYTEA, need to convert properly
        embedding = None
        raw_embedding = data.get("embedding")
        if raw_embedding is not None:
            if isinstance(raw_embedding, memoryview):
                embedding = json.loads(raw_embedding.tobytes().decode('utf-8'))
            elif isinstance(raw_embedding, bytes):
                embedding = json.loads(raw_embedding.decode('utf-8'))
            elif isinstance(raw_embedding, str):
                embedding = json.loads(raw_embedding)
            elif isinstance(raw_embedding, list):
                embedding = raw_embedding

        # Map new schema columns to expected dataclass fields
        # New schema: description -> instruction, triggers -> trigger_keywords, steps -> examples
        instruction = data.get("instruction") or data.get("description", "")

        # Handle triggers/trigger_keywords - can be JSONB (dict/list) or string
        raw_triggers = data.get("trigger_keywords") or data.get("triggers")
        if isinstance(raw_triggers, str):
            trigger_keywords = json.loads(raw_triggers)
        elif isinstance(raw_triggers, list):
            trigger_keywords = raw_triggers
        else:
            trigger_keywords = []

        # Handle examples/steps - can be JSONB (dict/list) or string
        raw_examples = data.get("examples") or data.get("steps")
        if isinstance(raw_examples, str):
            examples = json.loads(raw_examples)
        elif isinstance(raw_examples, list):
            examples = raw_examples
        else:
            examples = []

        # Handle metadata
        raw_metadata = data.get("metadata", {})
        if isinstance(raw_metadata, str):
            metadata = json.loads(raw_metadata)
        elif raw_metadata is None:
            metadata = {}
        else:
            metadata = raw_metadata

        # Derive status from is_active/is_deprecated if available
        if "is_deprecated" in data and "is_active" in data:
            if data["is_deprecated"]:
                status = "DEPRECATED"
            elif data["is_active"]:
                status = "APPROVED"
            else:
                status = "DRAFT"
        else:
            status = data.get("status", "DRAFT")

        # Use role from join or role_focus column
        role_focus = data.get("role_focus") or data.get("role", "Student")

        # Handle effective_from/created_at
        effective_from = data.get("effective_from") or data.get("created_at", "")

        # Handle created_by/changed_by
        created_by = data.get("created_by") or data.get("changed_by", "")

        return BehaviorVersion(
            behavior_id=str(data["behavior_id"]),
            version=str(data["version"]),  # Convert int to string for consistency
            instruction=instruction,
            role_focus=role_focus,
            status=status,
            trigger_keywords=trigger_keywords,
            examples=examples,
            metadata=metadata,
            effective_from=str(effective_from) if effective_from else "",
            effective_to=str(data["effective_to"]) if data.get("effective_to") else None,
            created_by=created_by,
            approval_action_id=str(data["approval_action_id"]) if data.get("approval_action_id") else None,
            embedding_checksum=data.get("embedding_checksum"),
            embedding=embedding,
        )

    # ------------------------------------------------------------------
    # Effectiveness & Benchmark Methods
    # ------------------------------------------------------------------

    def get_effectiveness_metrics(
        self,
        status_filter: Optional[str] = None,
        sort_by: str = "usage_count",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get aggregated effectiveness metrics for behaviors.

        Note: behavior_feedback table doesn't exist in current schema,
        so we return behaviors with zero feedback metrics for now.
        """
        conn = self._ensure_connection()

        # Build query with optional status filter (map to is_active/is_deprecated)
        status_clause = ""
        params: List[Any] = []
        if status_filter:
            if status_filter == "APPROVED":
                status_clause = "WHERE b.is_active = true AND b.is_deprecated = false"
            elif status_filter == "DEPRECATED":
                status_clause = "WHERE b.is_deprecated = true"
            elif status_filter == "DRAFT":
                status_clause = "WHERE b.is_active = false AND b.is_deprecated = false"

        params.append(limit)

        with conn.cursor() as cur:
            # Query behaviors - behavior_feedback doesn't exist, so no join
            cur.execute(
                f"""
                SELECT
                    b.id,
                    b.name,
                    b.is_active,
                    b.is_deprecated,
                    b.updated_at
                FROM behavior.behaviors b
                {status_clause}
                ORDER BY b.updated_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

            # Get aggregate stats using is_active/is_deprecated
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_behaviors,
                    COUNT(*) FILTER (WHERE is_active = true AND is_deprecated = false) as approved_count,
                    COUNT(*) FILTER (WHERE is_active = false AND is_deprecated = false) as draft_count,
                    COUNT(*) FILTER (WHERE is_deprecated = true) as deprecated_count
                FROM behavior.behaviors
                """
            )
            totals = cur.fetchone()

        behaviors = []
        for row in rows:
            # Map is_active/is_deprecated to status string
            is_active = row[2]
            is_deprecated = row[3]
            if is_deprecated:
                derived_status = "DEPRECATED"
            elif is_active:
                derived_status = "APPROVED"
            else:
                derived_status = "DRAFT"

            behaviors.append({
                "behavior_id": str(row[0]),
                "name": row[1],
                "status": derived_status,
                "updated_at": str(row[4]) if row[4] else "",
                "usage_count": 0,  # No feedback table yet
                "avg_relevance": 0.0,
                "avg_helpfulness": 0.0,
                "avg_token_reduction": 0.0,
                "feedback_count": 0,
            })

        return {
            "behaviors": behaviors,
            "summary": {
                "total_behaviors": totals[0] if totals else 0,
                "approved_count": totals[1] if totals else 0,
                "draft_count": totals[2] if totals else 0,
                "deprecated_count": totals[3] if totals else 0,
                "total_feedback": 0,  # No feedback table yet
                "overall_avg_relevance": 0.0,
                "overall_avg_token_reduction": 0.0,
            },
        }

    def record_feedback(
        self,
        behavior_id: str,
        relevance_score: int,
        helpfulness_score: Optional[int],
        token_reduction_observed: Optional[float],
        comment: Optional[str],
        actor_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record curator feedback for a behavior.

        Note: behavior_feedback table doesn't exist in current schema.
        This method validates the behavior exists and logs the feedback
        via telemetry only.
        """
        # Validate behavior exists
        self._fetch_behavior(behavior_id)

        feedback_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        # Log feedback via telemetry since table doesn't exist
        self._telemetry.emit_event(
            event_type="behaviors.feedback_recorded",
            payload={
                "behavior_id": behavior_id,
                "feedback_id": feedback_id,
                "relevance_score": relevance_score,
                "helpfulness_score": helpfulness_score,
                "token_reduction_observed": token_reduction_observed,
                "comment": comment,
            },
            actor={"id": actor_id, "role": "curator", "surface": "api"},
        )

        return {
            "feedback_id": feedback_id,
            "behavior_id": behavior_id,
            "relevance_score": relevance_score,
            "helpfulness_score": helpfulness_score,
            "token_reduction_observed": token_reduction_observed,
            "created_at": timestamp,
        }

    def get_feedback(self, behavior_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get feedback entries for a specific behavior.

        Note: behavior_feedback table doesn't exist in current schema.
        Returns empty list.
        """
        self._fetch_behavior(behavior_id)  # Validate behavior exists
        return []  # No feedback table yet

    def get_benchmark_results(self, limit: int = 20) -> Dict[str, Any]:
        """Get latest benchmark results.

        Note: behavior_benchmarks table doesn't exist in current schema.
        Returns empty list.
        """
        return {"benchmarks": [], "total": 0}

    def trigger_benchmark(
        self,
        corpus_path: Optional[str] = None,
        sample_size: int = 100,
        actor_id: str = "system",
    ) -> Dict[str, Any]:
        """Trigger a new benchmark run.

        Note: behavior_benchmarks table doesn't exist in current schema.
        Logs to telemetry instead.
        """
        benchmark_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        # Log via telemetry since table doesn't exist
        if self._telemetry:
            self._telemetry.info(
                "behavior_benchmark_triggered",
                benchmark_id=benchmark_id,
                sample_size=sample_size,
                corpus_path=corpus_path,
                actor_id=actor_id,
                timestamp=timestamp,
            )

        return {
            "benchmark_id": benchmark_id,
            "status": "NOT_IMPLEMENTED",
            "message": "Benchmark table not available in current schema",
            "sample_size": sample_size,
            "triggered_at": timestamp,
        }
