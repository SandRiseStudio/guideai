"""Knowledge Pack system — portable, versioned expertise bundles for GuideAI.

See docs/GUIDEAI_KNOWLEDGE_PACK_ARCHITECTURE.md for full design.
"""

from guideai.knowledge_pack.builder import (
    KnowledgePackArtifact,
    PackBuilder,
    PackBuildConfig,
)
from guideai.knowledge_pack.overlay_rules import (
    OverlayClassifier,
    Role,
    RoleClassificationRule,
    Surface,
    SurfaceClassificationRule,
    TaskClassificationRule,
    TaskFamily,
    default_classifier,
    filter_overlays_by_role,
    filter_overlays_by_surface,
    filter_overlays_by_task,
)
from guideai.knowledge_pack.extractor import (
    BehaviorFragment,
    DoctrineFragment,
    ExtractionResult,
    PlaybookFragment,
    SourceExtractor,
)
from guideai.knowledge_pack.schema import (
    KnowledgePackManifest,
    OverlayFragment,
    OverlayKind,
    PackConstraints,
    PackScope,
    PackSource,
    PackSourceType,
    SourceScope,
    ValidationResult,
    LintIssue,
)
from guideai.knowledge_pack.source_registry import (
    DriftResult,
    RegisterSourceRequest,
    SourceNotFoundError,
    SourceRecord,
    SourceRegistryError,
    SourceRegistryService,
)

__all__ = [
    "BehaviorFragment",
    "DoctrineFragment",
    "DriftResult",
    "ExtractionResult",
    "KnowledgePackArtifact",
    "KnowledgePackManifest",
    "LintIssue",
    "OverlayClassifier",
    "OverlayFragment",
    "OverlayKind",
    "PackBuilder",
    "PackBuildConfig",
    "PackConstraints",
    "PackScope",
    "PackSource",
    "PackSourceType",
    "PlaybookFragment",
    "RegisterSourceRequest",
    "Role",
    "RoleClassificationRule",
    "SourceExtractor",
    "SourceNotFoundError",
    "SourceRecord",
    "SourceRegistryError",
    "SourceRegistryService",
    "SourceScope",
    "Surface",
    "SurfaceClassificationRule",
    "TaskClassificationRule",
    "TaskFamily",
    "ValidationResult",
    "default_classifier",
    "filter_overlays_by_role",
    "filter_overlays_by_surface",
    "filter_overlays_by_task",
]
