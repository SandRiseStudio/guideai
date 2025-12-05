"""GuideAI Midnighter Integration

Thin wrapper that wires MidnighterService hooks to GuideAI services:
- BehaviorService for behavior retrieval
- Raze for structured logging
- ActionService for audit trail
"""

from typing import Optional, Dict, Any, TYPE_CHECKING
import os

from mdnt import MidnighterService, MidnighterHooks

if TYPE_CHECKING:
    from guideai.behavior_service import BehaviorService
    from raze import RazeLogger


def create_midnighter_service(
    behavior_service: Optional["BehaviorService"] = None,
    logger: Optional["RazeLogger"] = None,
    backend: Optional[str] = None,
    models_dir: Optional[str] = None,
) -> MidnighterService:
    """Create MidnighterService with GuideAI integration.

    This factory function wires Midnighter's hooks to GuideAI services,
    providing behavior retrieval, structured logging, and telemetry.

    Args:
        behavior_service: BehaviorService instance for behavior retrieval.
            If not provided, will attempt to import and instantiate.
        logger: RazeLogger instance for structured logging.
            If not provided, will use print fallback.
        backend: Training backend ("openai" or "local").
            Defaults to MDNT_BACKEND env var or "openai".
        models_dir: Directory for local model checkpoints.
            Defaults to MDNT_MODELS_DIR env var.

    Returns:
        Configured MidnighterService instance.

    Example:
        ```python
        from guideai.midnighter import create_midnighter_service
        from guideai.behavior_service import BehaviorService

        behavior_service = BehaviorService()
        service = create_midnighter_service(behavior_service=behavior_service)

        # Generate corpus from handbook behaviors
        corpus = service.generate_corpus_from_behaviors(
            name="bc-sft-corpus",
            behavior_ids=["behavior_use_raze_for_logging"],
            sample_count=100,
        )
        ```
    """
    # Resolve backend
    resolved_backend = backend or os.environ.get("MDNT_BACKEND", "openai")
    resolved_models_dir = models_dir or os.environ.get("MDNT_MODELS_DIR", "./models")

    # Create hooks wired to GuideAI services
    hooks = _create_guideai_hooks(behavior_service, logger)

    return MidnighterService(
        hooks=hooks,
        backend=resolved_backend,
        models_dir=resolved_models_dir,
    )


def _create_guideai_hooks(
    behavior_service: Optional["BehaviorService"] = None,
    logger: Optional["RazeLogger"] = None,
) -> MidnighterHooks:
    """Create MidnighterHooks wired to GuideAI services.

    Args:
        behavior_service: BehaviorService for behavior retrieval.
        logger: RazeLogger for structured logging.

    Returns:
        Configured MidnighterHooks.
    """
    # Attempt to import and instantiate services if not provided
    if behavior_service is None:
        behavior_service = _get_behavior_service()

    if logger is None:
        logger = _get_raze_logger()

    def get_behavior(behavior_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve behavior from BehaviorService."""
        if behavior_service is None:
            return None
        try:
            behavior = behavior_service.get_behavior(behavior_id)
            if behavior:
                return behavior if isinstance(behavior, dict) else behavior.to_dict() if hasattr(behavior, "to_dict") else vars(behavior)
            return None
        except Exception:
            return None

    def on_metric(event_type: str, data: Dict[str, Any]) -> None:
        """Emit metric via Raze logger."""
        if logger is None:
            return
        try:
            logger.info(
                f"midnighter.{event_type}",
                event_type=event_type,
                **data,
            )
        except Exception:
            pass  # Don't fail on telemetry errors

    return MidnighterHooks(
        get_behavior=get_behavior,
        on_metric=on_metric,
    )


def _get_behavior_service() -> Optional["BehaviorService"]:
    """Attempt to get default BehaviorService instance."""
    try:
        from guideai.behavior_service import BehaviorService
        return BehaviorService()
    except ImportError:
        return None


def _get_raze_logger() -> Optional["RazeLogger"]:
    """Attempt to get Raze logger for midnighter context."""
    try:
        from raze import RazeLogger
        return RazeLogger(service_name="midnighter")
    except ImportError:
        return None


__all__ = [
    "create_midnighter_service",
    "MidnighterService",
    "MidnighterHooks",
]
