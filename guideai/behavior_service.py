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
        """Create a new behavior and initial draft version."""

        behavior_id = str(uuid.uuid4())
        version = "1.0.0"
        timestamp = utc_now_iso()

        # Generate embedding if not provided
        if request.embedding is None:
            embedding_text = f"{request.name} {request.description} {request.instruction}"
            request.embedding = self._generate_embedding(embedding_text)

        embedding_checksum = self._calculate_embedding_checksum(request.embedding)

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Insert behavior
                cur.execute(
                    """
                    INSERT INTO behaviors (
                        behavior_id, name, description, tags, created_at, updated_at, latest_version, status, namespace
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        DEFAULT_BEHAVIOR_NAMESPACE,
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

        self._pool.run_transaction(
            "behavior.create_draft",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={
                "behavior_id": behavior_id,
                "version": version,
                "role_focus": request.role_focus,
            },
            executor=_execute,
            telemetry=self._telemetry,
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

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

        return version_obj

    def update_behavior_draft(self, request: UpdateBehaviorDraftRequest, actor: Actor) -> BehaviorVersion:
        """Update an existing draft or in-review behavior version."""

        version = self._fetch_behavior_version(request.behavior_id, request.version)
        if version.status not in {"DRAFT", "IN_REVIEW"}:
            raise BehaviorVersionError(
                f"Cannot update behavior {request.behavior_id} version {request.version}: status={version.status}"
            )

        def _execute(conn: Any) -> List[str]:
            with conn.cursor() as cur:
                # Update behavior version fields
                updates = []
                values = []

                # Auto-generate embedding if instruction changes and no embedding provided
                if request.instruction is not None and request.embedding is None:
                    # Fetch current behavior details to construct full text
                    # Note: This is a bit expensive inside a transaction, but necessary for consistency
                    # Alternatively, we could just use the instruction, but name/desc are better.
                    # For now, let's just use the instruction + existing name/desc if we can get them easily.
                    # Or simpler: just use the instruction for the embedding update if name/desc aren't changing.
                    # But wait, we need the full text.
                    # Let's fetch the current version first (outside the transaction ideally, but we are inside _execute).
                    # Actually, we fetched `version` at the start of the method.
                    # We also need the behavior name/desc.
                    # Let's keep it simple: if instruction changes, we try to regenerate.
                    # We'll need to fetch the behavior to get name/desc.
                    cur.execute("SELECT name, description FROM behaviors WHERE behavior_id = %s", (request.behavior_id,))
                    row = cur.fetchone()
                    if row:
                        name, description = row
                        embedding_text = f"{name} {description} {request.instruction}"
                        request.embedding = self._generate_embedding(embedding_text)

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
        """Move a draft version into review."""

        version_obj = self._fetch_behavior_version(behavior_id, version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError(
                f"Only drafts can be submitted for review (status={version_obj.status})."
            )

        timestamp = utc_now_iso()

        def _execute(conn: Any) -> None:
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
        """Approve a behavior version and mark it active."""

        version_obj = self._fetch_behavior_version(request.behavior_id, request.version)
        if version_obj.status not in {"IN_REVIEW", "DRAFT"}:
            raise BehaviorVersionError(f"Cannot approve version with status={version_obj.status}.")

        def _execute(conn: Any) -> None:
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

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

        return deprecated

    def delete_behavior_draft(self, behavior_id: str, version: str, actor: Actor) -> None:
        """Delete a draft version."""

        version_obj = self._fetch_behavior_version(behavior_id, version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError("Only draft versions can be deleted.")

        def _execute(conn: Any) -> None:
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
                    "SELECT * FROM behaviors WHERE behavior_id = %s",
                    (behavior_id,),
                )
                row = cur.fetchone()
        except psycopg2.errors.InvalidTextRepresentation:
            # Invalid UUID format - treat as not found
            raise BehaviorNotFoundError(f"Behavior '{behavior_id}' not found")

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

    def _fetch_behaviors_with_versions(
        self, status: Optional[str] = None, namespace: Optional[str] = None
    ) -> List[Tuple[Behavior, List[BehaviorVersion]]]:
        """Fetch behaviors with their versions in a single optimized JOIN query.

        This method eliminates N+1 query problems by fetching all behaviors and their
        versions in one database round trip, reducing query count from 1+N to 1.

        Performance improvement: ~13x faster for list operations under load.

        Returns:
            List of (behavior, versions) tuples, where versions are ordered by:
            - APPROVED status first
            - Then by effective_from DESC
        """
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Single JOIN query replaces separate fetches
            query = """
                SELECT
                    b.behavior_id, b.name, b.description, b.tags, b.created_at,
                    b.updated_at, b.latest_version, b.status, b.namespace,
                    bv.version, bv.instruction, bv.trigger_keywords, bv.role_focus,
                    bv.status as version_status, bv.examples, bv.metadata, bv.embedding_checksum,
                    bv.embedding, bv.effective_from, bv.effective_to, bv.created_by, bv.approval_action_id
                FROM behaviors b
                LEFT JOIN behavior_versions bv ON b.behavior_id = bv.behavior_id
                WHERE 1=1
            """
            params = []

            if status:
                query += " AND b.status = %s"
                params.append(status)

            if namespace:
                query += " AND COALESCE(b.namespace, %s) = %s"
                params.extend([DEFAULT_BEHAVIOR_NAMESPACE, namespace])

            query += " ORDER BY b.updated_at DESC, bv.status = 'APPROVED' DESC, bv.effective_from DESC"

            cur.execute(query, params)
            rows = cur.fetchall()

        # Group results by behavior_id since we're now getting all versions
        from collections import defaultdict
        behavior_map: Dict[str, Tuple[Behavior, List[BehaviorVersion]]] = {}

        for row in rows:
            behavior_id = str(row[0])

            # Create or reuse Behavior object
            if behavior_id not in behavior_map:
                behavior = Behavior(
                    behavior_id=str(row[0]),
                    name=row[1],
                    description=row[2],
                    tags=row[3] or [],
                    created_at=str(row[4]),
                    updated_at=str(row[5]),
                    latest_version=row[6],
                    status=row[7],
                    namespace=row[8] if row[8] else DEFAULT_BEHAVIOR_NAMESPACE,
                )
                behavior_map[behavior_id] = (behavior, [])

            # Add BehaviorVersion if exists
            if row[9] is not None:  # version exists (index shifted by 1 due to namespace)
                version = BehaviorVersion(
                    behavior_id=str(row[0]),
                    version=row[9],
                    instruction=row[10],
                    trigger_keywords=row[11] or [],
                    role_focus=row[12],
                    status=row[13] or "DRAFT",
                    examples=row[14] or [],
                    metadata=row[15] or {},
                    embedding_checksum=row[16],
                    embedding=self._parse_embedding(row[17]),
                    effective_from=str(row[18]),
                    effective_to=str(row[19]) if row[19] else None,
                    created_by=row[20],
                    approval_action_id=str(row[21]) if row[21] else None,
                )
                behavior_map[behavior_id][1].append(version)

        # Return in order (already sorted by b.updated_at DESC in query)
        return list(behavior_map.values())

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
        """Convert PostgreSQL row to Behavior object."""
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))
        return Behavior(
            behavior_id=str(data["behavior_id"]),
            name=data["name"],
            description=data["description"],
            tags=json.loads(data["tags"]) if isinstance(data["tags"], str) else data["tags"],
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            latest_version=data["latest_version"],
            status=data["status"],
            namespace=data.get("namespace", DEFAULT_BEHAVIOR_NAMESPACE),
        )

    @staticmethod
    def _row_to_behavior_version(row: tuple, description) -> BehaviorVersion:
        """Convert PostgreSQL row to BehaviorVersion object."""
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

        return BehaviorVersion(
            behavior_id=str(data["behavior_id"]),
            version=data["version"],
            instruction=data["instruction"],
            role_focus=data["role_focus"],
            status=data["status"],
            trigger_keywords=json.loads(data["trigger_keywords"]) if isinstance(data["trigger_keywords"], str) else data["trigger_keywords"],
            examples=json.loads(data["examples"]) if isinstance(data["examples"], str) else data["examples"],
            metadata=json.loads(data["metadata"]) if isinstance(data["metadata"], str) else data["metadata"],
            effective_from=str(data["effective_from"]),
            effective_to=str(data["effective_to"]) if data.get("effective_to") else None,
            created_by=data["created_by"],
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
        """Get aggregated effectiveness metrics for behaviors."""
        conn = self._ensure_connection()

        # Build query with optional status filter
        status_clause = ""
        params: List[Any] = []
        if status_filter:
            status_clause = "WHERE b.status = %s"
            params.append(status_filter)

        # Sort column mapping with safety check
        sort_columns = {
            "usage_count": "COALESCE(f.usage_count, 0)",
            "avg_accuracy": "COALESCE(f.avg_relevance, 0)",
            "token_reduction": "COALESCE(f.avg_token_reduction, 0)",
            "name": "b.name",
        }
        order_column = sort_columns.get(sort_by, sort_columns["usage_count"])

        params.append(limit)

        with conn.cursor() as cur:
            # Query behaviors with aggregated feedback metrics
            cur.execute(
                f"""
                SELECT
                    b.behavior_id,
                    b.name,
                    b.status,
                    b.updated_at,
                    COALESCE(f.usage_count, 0) as usage_count,
                    COALESCE(f.avg_relevance, 0) as avg_relevance,
                    COALESCE(f.avg_helpfulness, 0) as avg_helpfulness,
                    COALESCE(f.avg_token_reduction, 0) as avg_token_reduction,
                    COALESCE(f.feedback_count, 0) as feedback_count
                FROM behaviors b
                LEFT JOIN (
                    SELECT
                        behavior_id,
                        COUNT(*) as usage_count,
                        AVG(relevance_score) as avg_relevance,
                        AVG(helpfulness_score) as avg_helpfulness,
                        AVG(token_reduction_observed) as avg_token_reduction,
                        COUNT(*) as feedback_count
                    FROM behavior_feedback
                    GROUP BY behavior_id
                ) f ON b.behavior_id = f.behavior_id
                {status_clause}
                ORDER BY {order_column} DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

            # Get aggregate stats
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_behaviors,
                    COUNT(*) FILTER (WHERE status = 'APPROVED') as approved_count,
                    COUNT(*) FILTER (WHERE status = 'DRAFT') as draft_count,
                    COUNT(*) FILTER (WHERE status = 'DEPRECATED') as deprecated_count
                FROM behaviors
                """
            )
            totals = cur.fetchone()

            cur.execute(
                """
                SELECT
                    COUNT(*) as total_feedback,
                    AVG(relevance_score) as overall_avg_relevance,
                    AVG(token_reduction_observed) as overall_avg_token_reduction
                FROM behavior_feedback
                """
            )
            feedback_stats = cur.fetchone()

        behaviors = []
        for row in rows:
            data = dict(zip(columns, row))
            behaviors.append({
                "behavior_id": data["behavior_id"],
                "name": data["name"],
                "status": data["status"],
                "updated_at": str(data["updated_at"]),
                "usage_count": int(data["usage_count"]),
                "avg_relevance": float(data["avg_relevance"]) if data["avg_relevance"] else 0.0,
                "avg_helpfulness": float(data["avg_helpfulness"]) if data["avg_helpfulness"] else 0.0,
                "avg_token_reduction": float(data["avg_token_reduction"]) if data["avg_token_reduction"] else 0.0,
                "feedback_count": int(data["feedback_count"]),
            })

        return {
            "behaviors": behaviors,
            "summary": {
                "total_behaviors": totals[0] if totals else 0,
                "approved_count": totals[1] if totals else 0,
                "draft_count": totals[2] if totals else 0,
                "deprecated_count": totals[3] if totals else 0,
                "total_feedback": feedback_stats[0] if feedback_stats else 0,
                "overall_avg_relevance": float(feedback_stats[1]) if feedback_stats and feedback_stats[1] else 0.0,
                "overall_avg_token_reduction": float(feedback_stats[2]) if feedback_stats and feedback_stats[2] else 0.0,
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
        """Record curator feedback for a behavior."""
        # Validate behavior exists
        self._fetch_behavior(behavior_id)

        feedback_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO behavior_feedback (
                        feedback_id, behavior_id, relevance_score, helpfulness_score,
                        token_reduction_observed, comment, actor_id, context, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        feedback_id,
                        behavior_id,
                        relevance_score,
                        helpfulness_score,
                        token_reduction_observed,
                        comment,
                        actor_id,
                        json.dumps(context or {}),
                        timestamp,
                    ),
                )

        self._pool.run_transaction(
            "behavior.record_feedback",
            service_prefix="behavior",
            actor={"id": actor_id, "role": "curator", "surface": "api"},
            metadata={
                "behavior_id": behavior_id,
                "feedback_id": feedback_id,
                "relevance_score": relevance_score,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._telemetry.emit_event(
            event_type="behaviors.feedback_recorded",
            payload={
                "behavior_id": behavior_id,
                "feedback_id": feedback_id,
                "relevance_score": relevance_score,
                "helpfulness_score": helpfulness_score,
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
        """Get feedback entries for a specific behavior."""
        self._fetch_behavior(behavior_id)  # Validate behavior exists

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT feedback_id, behavior_id, relevance_score, helpfulness_score,
                       token_reduction_observed, comment, actor_id, context, created_at
                FROM behavior_feedback
                WHERE behavior_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (behavior_id, limit),
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        return [
            {
                **dict(zip(columns, row)),
                "context": json.loads(row[7]) if row[7] else {},
                "created_at": str(row[8]),
            }
            for row in rows
        ]

    def get_benchmark_results(self, limit: int = 20) -> Dict[str, Any]:
        """Get latest benchmark results."""
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT benchmark_id, run_date, corpus_size, sample_size,
                       avg_retrieval_latency_ms, p95_retrieval_latency_ms, p99_retrieval_latency_ms,
                       accuracy_at_k, recall_at_k, actor_id, metadata
                FROM behavior_benchmarks
                ORDER BY run_date DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        results = []
        for row in rows:
            data = dict(zip(columns, row))
            results.append({
                "benchmark_id": data["benchmark_id"],
                "run_date": str(data["run_date"]),
                "corpus_size": data["corpus_size"],
                "sample_size": data["sample_size"],
                "avg_retrieval_latency_ms": float(data["avg_retrieval_latency_ms"]) if data["avg_retrieval_latency_ms"] else 0.0,
                "p95_retrieval_latency_ms": float(data["p95_retrieval_latency_ms"]) if data["p95_retrieval_latency_ms"] else 0.0,
                "p99_retrieval_latency_ms": float(data["p99_retrieval_latency_ms"]) if data["p99_retrieval_latency_ms"] else 0.0,
                "accuracy_at_k": data.get("accuracy_at_k", {}),
                "recall_at_k": data.get("recall_at_k", {}),
                "actor_id": data["actor_id"],
                "metadata": json.loads(data["metadata"]) if data.get("metadata") else {},
            })

        return {"benchmarks": results, "total": len(results)}

    def trigger_benchmark(
        self,
        corpus_path: Optional[str] = None,
        sample_size: int = 100,
        actor_id: str = "system",
    ) -> Dict[str, Any]:
        """Trigger a new benchmark run (creates a pending record)."""
        benchmark_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO behavior_benchmarks (
                        benchmark_id, run_date, corpus_size, sample_size,
                        avg_retrieval_latency_ms, p95_retrieval_latency_ms, p99_retrieval_latency_ms,
                        accuracy_at_k, recall_at_k, actor_id, metadata, status
                    ) VALUES (%s, %s, 0, %s, 0, 0, 0, '{}', '{}', %s, %s, %s)
                    """,
                    (
                        benchmark_id,
                        timestamp,
                        sample_size,
                        actor_id,
                        json.dumps({"corpus_path": corpus_path, "triggered_at": timestamp}),
                        "PENDING",
                    ),
                )

        self._pool.run_transaction(
            "behavior.trigger_benchmark",
            service_prefix="behavior",
            actor={"id": actor_id, "role": "system", "surface": "api"},
            metadata={"benchmark_id": benchmark_id, "sample_size": sample_size},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return {
            "benchmark_id": benchmark_id,
            "status": "PENDING",
            "sample_size": sample_size,
            "triggered_at": timestamp,
        }
