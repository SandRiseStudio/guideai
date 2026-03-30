"""Adaptive Bootstrap — workspace profiling and knowledge pack selection.

Implements E2 (GUIDEAI-276) of the Knowledge Pack architecture.
See docs/GUIDEAI_KNOWLEDGE_PACK_ARCHITECTURE.md §6.3, §8.
"""

from guideai.bootstrap.profile import (
    ProfileDetectionResult,
    WorkspaceProfile,
    WorkspaceSignal,
)
from guideai.bootstrap.detector import WorkspaceDetector
from guideai.bootstrap.service import BootstrapResult, BootstrapService

__all__ = [
    "BootstrapResult",
    "BootstrapService",
    "ProfileDetectionResult",
    "WorkspaceDetector",
    "WorkspaceProfile",
    "WorkspaceSignal",
]
