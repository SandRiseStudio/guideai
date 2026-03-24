"""GuideAI Midnighter Integration — OSS Stub.

The full implementation has moved to guideai-enterprise.
Install guideai-enterprise[midnighter] for BC-SFT training integration.
"""

try:
    from guideai_enterprise.midnighter import (
        create_midnighter_service,
        MidnighterService,
        MidnighterHooks,
    )
except ImportError:

    def create_midnighter_service(**kwargs):  # type: ignore[misc]
        raise ImportError(
            "Midnighter integration requires guideai-enterprise. "
            "Install with: pip install guideai-enterprise[midnighter]"
        )

    MidnighterService = None  # type: ignore[assignment,misc]
    MidnighterHooks = None  # type: ignore[assignment,misc]

__all__ = [
    "create_midnighter_service",
    "MidnighterService",
    "MidnighterHooks",
]
