"""Hybrid behavior retrieval service used by the BCI pipeline."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .behavior_service import BehaviorSearchResult, BehaviorService, SearchBehaviorsRequest
from .bci_contracts import BehaviorMatch, RetrieveRequest, RetrievalStrategy, RoleFocus
from .telemetry import TelemetryClient

try:  # pragma: no cover - optional dependency
    from sentence_transformers import SentenceTransformer  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    SentenceTransformer = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import faiss  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    faiss = None  # type: ignore

logger = logging.getLogger(__name__)

_DEFAULT_STORAGE_DIR = Path.home() / ".guideai" / "data"
_DEFAULT_INDEX_PATH = _DEFAULT_STORAGE_DIR / "behavior_index.faiss"
_DEFAULT_METADATA_PATH = _DEFAULT_STORAGE_DIR / "behavior_index.json"


class BehaviorRetriever:
    """Retrieves behaviors using semantic, keyword, or hybrid strategies.

    The retriever relies on SentenceTransformer + FAISS for semantic retrieval
    when those dependencies are available. If they are missing, it gracefully
    falls back to keyword search using :class:`BehaviorService` to preserve
    functionality during unit tests or lightweight installations.
    """

    def __init__(
        self,
        *,
        behavior_service: Optional[BehaviorService] = None,
        telemetry: Optional[TelemetryClient] = None,
        model_name: str = "BAAI/bge-m3",
        index_path: Path = _DEFAULT_INDEX_PATH,
        metadata_path: Path = _DEFAULT_METADATA_PATH,
        device: Optional[str] = None,
    ) -> None:
        self._behavior_service = behavior_service
        self._telemetry = telemetry or TelemetryClient.noop()
        self._model_name = model_name
        self._index_path = index_path
        self._metadata_path = metadata_path
        self._device = device

        self._semantic_available = SentenceTransformer is not None and faiss is not None
        self._model: Optional[Any] = None
        self._index: Any = None
        self._behavior_ids: List[str] = []
        self._behavior_cache: Dict[str, Dict[str, Any]] = {}

        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)

        if self._semantic_available:
            self._load_index()
        else:
            logger.info(
                "Semantic retrieval dependencies missing; operating in keyword-only mode."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return "semantic" if self._semantic_available else "keyword"

    def ensure_ready(self) -> Dict[str, Any]:
        if not self._semantic_available:
            return {
                "status": "degraded",
                "mode": "keyword",
                "reason": "sentence-transformers and faiss not available",
            }
        if self._index is None or not self._behavior_ids:
            return self.build_index()
        return {
            "status": "ready",
            "mode": "semantic",
            "behavior_count": len(self._behavior_ids),
            "model": self._model_name,
        }

    def build_index(self) -> Dict[str, Any]:
        if not self._semantic_available:
            return {
                "status": "degraded",
                "mode": "keyword",
                "reason": "semantic dependencies unavailable",
            }
        if self._behavior_service is None:
            return {
                "status": "error",
                "reason": "behavior service not configured",
            }

        assert faiss is not None  # narrow optional dependency for type checkers
        approved = self._behavior_service.list_behaviors(status="APPROVED")
        candidates = [entry for entry in approved if entry.get("active_version")]
        if not candidates:
            self._index = faiss.IndexFlatIP(1)
            self._behavior_ids = []
            self._behavior_cache = {}
            self._persist_index()
            return {
                "status": "ready",
                "mode": "semantic",
                "behavior_count": 0,
                "model": self._model_name,
            }

        texts = [self._build_embedding_text(entry) for entry in candidates]
        model = self._load_model()

        embeddings = model.encode(texts, convert_to_numpy=True)  # pragma: no cover - heavy path
        faiss.normalize_L2(embeddings)  # pragma: no cover - heavy path  # type: ignore[attr-defined]
        index = faiss.IndexFlatIP(embeddings.shape[1])  # pragma: no cover - heavy path
        index.add(embeddings)  # pragma: no cover - heavy path

        self._index = index  # pragma: no cover - heavy path
        self._behavior_ids = [entry["behavior"]["behavior_id"] for entry in candidates]
        self._behavior_cache = {
            entry["behavior"]["behavior_id"]: self._behavior_snapshot(entry)
            for entry in candidates
        }
        self._persist_index()
        self._telemetry.emit_event(
            event_type="bci.behavior_retriever.index_built",
            payload={
                "behavior_count": len(self._behavior_ids),
                "model_name": self._model_name,
            },
        )
        return {
            "status": "ready",
            "mode": "semantic",
            "behavior_count": len(self._behavior_ids),
            "model": self._model_name,
        }

    def retrieve(self, request: RetrieveRequest) -> List[BehaviorMatch]:
        if not self._behavior_service:
            return []

        if not self._semantic_available:
            matches = self._keyword_retrieve(request, limit=request.top_k)
            self._emit_retrieval_event(request, matches, "keyword")
            return matches

        ready = self.ensure_ready()
        if ready.get("status") != "ready":
            matches = self._keyword_retrieve(request, limit=request.top_k)
            self._emit_retrieval_event(request, matches, "keyword-degraded")
            return matches

        embedding_matches = self._embedding_retrieve(request)
        if request.strategy == RetrievalStrategy.EMBEDDING:
            matches = embedding_matches[: request.top_k]
            self._emit_retrieval_event(request, matches, "semantic")
            return matches

        keyword_matches = self._keyword_retrieve(request, limit=max(request.top_k * 3, 15))
        if request.strategy == RetrievalStrategy.KEYWORD:
            matches = keyword_matches[: request.top_k]
            self._emit_retrieval_event(request, matches, "keyword")
            return matches

        matches = self._merge_hybrid(embedding_matches, keyword_matches, request)
        self._emit_retrieval_event(request, matches, "hybrid")
        return matches

    def rebuild_index(self) -> Dict[str, Any]:
        result = self.build_index()
        result.setdefault("mode", self.mode)
        result.setdefault("status", "ready" if result.get("mode") == "semantic" else "degraded")
        result["timestamp"] = datetime.now(UTC).isoformat()
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load_model(self) -> Any:
        if not self._semantic_available:
            raise RuntimeError("Semantic retrieval dependencies unavailable")
        if self._model is None:
            logger.info("Loading behavior retriever model %s", self._model_name)
            if SentenceTransformer is None:  # pragma: no cover - defensive
                raise RuntimeError("SentenceTransformer dependency unavailable")
            self._model = SentenceTransformer(self._model_name, device=self._device)  # pragma: no cover - heavy path
        return self._model

    def _load_index(self) -> None:
        if not self._index_path.exists() or not self._metadata_path.exists():
            return
        try:
            assert faiss is not None  # narrow optional dependency for type checkers
            self._index = faiss.read_index(str(self._index_path))  # pragma: no cover - heavy path  # type: ignore[attr-defined]
            with self._metadata_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self._behavior_ids = payload.get("behavior_ids", [])
            self._behavior_cache = payload.get("behaviors", {})
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load behavior index; rebuilding. Error: %s", exc)
            self._index = None
            self._behavior_ids = []
            self._behavior_cache = {}

    def _persist_index(self) -> None:
        if not self._semantic_available or self._index is None:
            return
        assert faiss is not None  # narrow optional dependency for type checkers
        faiss.write_index(self._index, str(self._index_path))  # pragma: no cover - heavy path  # type: ignore[attr-defined]
        payload = {
            "model": self._model_name,
            "behavior_ids": self._behavior_ids,
            "behaviors": self._behavior_cache,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        with self._metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    @staticmethod
    def _build_embedding_text(entry: Dict[str, Any]) -> str:
        behavior = entry["behavior"]
        version = entry["active_version"]
        tags = " ".join(behavior.get("tags", []))
        metadata = version.get("metadata") or {}
        summary = metadata.get("summary") or ""
        return "\n".join(
            [
                behavior.get("name", ""),
                behavior.get("description", ""),
                version.get("instruction", ""),
                tags,
                summary,
            ]
        ).strip()

    @staticmethod
    def _behavior_snapshot(entry: Dict[str, Any]) -> Dict[str, Any]:
        behavior = entry["behavior"]
        version = entry["active_version"]
        metadata = version.get("metadata") or {}
        return {
            "behavior_id": behavior.get("behavior_id"),
            "name": behavior.get("name"),
            "description": behavior.get("description"),
            "tags": behavior.get("tags", []),
            "version": version.get("version"),
            "instruction": version.get("instruction"),
            "role_focus": version.get("role_focus"),
            "metadata": metadata,
            "citation_label": metadata.get("citation_label"),
        }

    @staticmethod
    def _role_focus_from_str(value: Optional[str]) -> Optional[RoleFocus]:
        if value is None:
            return None
        try:
            return RoleFocus(value)
        except ValueError:
            return None

    def _to_behavior_match(
        self,
        *,
        record: Dict[str, Any],
        score: float,
        strategy_breakdown: Dict[str, float],
        include_metadata: bool,
    ) -> BehaviorMatch:
        metadata = record.get("metadata") if include_metadata else None
        citation_label = record.get("citation_label")
        if not citation_label and metadata:
            citation_label = metadata.get("citation_label")
        if not citation_label:
            citation_label = record.get("name")
        return BehaviorMatch(
            behavior_id=record.get("behavior_id", ""),
            name=record.get("name", ""),
            version=record.get("version", ""),
            instruction=record.get("instruction", ""),
            score=float(score),
            description=record.get("description"),
            role_focus=self._role_focus_from_str(record.get("role_focus")),
            tags=list(record.get("tags", [])),
            strategy_breakdown=strategy_breakdown,
            citation_label=citation_label,
            metadata=metadata,
        )

    def _embedding_retrieve(self, request: RetrieveRequest) -> List[BehaviorMatch]:
        if not self._semantic_available or self._index is None or not self._behavior_ids:
            return []
        assert faiss is not None  # narrow optional dependency for type checkers

        model = self._load_model()
        query_vec = model.encode([request.query], convert_to_numpy=True)  # pragma: no cover - heavy path
        faiss.normalize_L2(query_vec)  # pragma: no cover - heavy path  # type: ignore[attr-defined]

        multiplier = 2 if request.strategy == RetrievalStrategy.HYBRID else 1
        k = min(len(self._behavior_ids), max(request.top_k, 1) * multiplier)
        if k == 0:
            return []

        scores, indices = self._index.search(query_vec, k)  # pragma: no cover - heavy path
        scores_list = scores[0].tolist()
        index_list = indices[0].tolist()

        matches: List[BehaviorMatch] = []
        for score, idx in zip(scores_list, index_list):
            if idx < 0 or idx >= len(self._behavior_ids):
                continue
            behavior_id = self._behavior_ids[idx]
            record = self._behavior_cache.get(behavior_id)
            if not record:
                continue
            matches.append(
                self._to_behavior_match(
                    record=record,
                    score=float(score),
                    strategy_breakdown={"embedding": float(score)},
                    include_metadata=request.include_metadata,
                )
            )
        return matches

    def _keyword_retrieve(self, request: RetrieveRequest, *, limit: int) -> List[BehaviorMatch]:
        if self._behavior_service is None:
            return []
        search_request = SearchBehaviorsRequest(
            query=request.query,
            tags=request.tags,
            role_focus=request.role_focus.value if request.role_focus else None,
            status="APPROVED",
            limit=max(limit, 1),
        )
        results = self._behavior_service.search_behaviors(search_request)
        matches: List[BehaviorMatch] = []
        for result in results[:limit]:
            record = self._from_search_result(result)
            matches.append(
                self._to_behavior_match(
                    record=record,
                    score=float(result.score),
                    strategy_breakdown={"keyword": float(result.score)},
                    include_metadata=request.include_metadata,
                )
            )
        return matches

    def _from_search_result(self, result: BehaviorSearchResult) -> Dict[str, Any]:
        metadata = result.active_version.metadata
        return {
            "behavior_id": result.behavior.behavior_id,
            "name": result.behavior.name,
            "description": result.behavior.description,
            "tags": list(result.behavior.tags),
            "version": result.active_version.version,
            "instruction": result.active_version.instruction,
            "role_focus": result.active_version.role_focus,
            "metadata": metadata,
            "citation_label": (metadata or {}).get("citation_label") if metadata else None,
        }

    def _merge_hybrid(
        self,
        embedding_matches: List[BehaviorMatch],
        keyword_matches: List[BehaviorMatch],
        request: RetrieveRequest,
    ) -> List[BehaviorMatch]:
        combined: Dict[str, BehaviorMatch] = {}
        for match in embedding_matches:
            breakdown = dict(match.strategy_breakdown or {})
            combined_score = breakdown.get("embedding", match.score)
            combined[match.behavior_id] = replace(
                match,
                score=combined_score * request.embedding_weight,
                strategy_breakdown={"embedding": breakdown.get("embedding", match.score)},
            )

        for match in keyword_matches:
            breakdown = dict(match.strategy_breakdown or {})
            keyword_score = breakdown.get("keyword", match.score)
            if match.behavior_id in combined:
                existing = combined[match.behavior_id]
                existing_breakdown = dict(existing.strategy_breakdown or {})
                existing_breakdown.setdefault("embedding", existing_breakdown.get("embedding", existing.score))
                existing_breakdown["keyword"] = keyword_score
                combined_score = (
                    existing_breakdown.get("embedding", 0.0) * request.embedding_weight
                    + keyword_score * request.keyword_weight
                )
                combined[match.behavior_id] = replace(
                    existing,
                    score=combined_score,
                    strategy_breakdown=existing_breakdown,
                )
            else:
                combined[match.behavior_id] = replace(
                    match,
                    score=keyword_score * request.keyword_weight,
                    strategy_breakdown={"keyword": keyword_score},
                )

        ranked = sorted(combined.values(), key=lambda match: match.score, reverse=True)
        return ranked[: request.top_k]

    def _emit_retrieval_event(
        self,
        request: RetrieveRequest,
        matches: Sequence[BehaviorMatch],
        mode: str,
    ) -> None:
        try:
            self._telemetry.emit_event(
                event_type="bci.behavior_retriever.retrieve",
                payload={
                    "mode": mode,
                    "query_length": len(request.query or ""),
                    "strategy": request.strategy.value,
                    "top_k": request.top_k,
                    "returned": len(matches),
                },
            )
        except Exception:  # pragma: no cover - telemetry should not break retrieval
            logger.debug("Telemetry emission failed", exc_info=True)
