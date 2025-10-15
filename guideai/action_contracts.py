"""Data contracts for the ActionService stub.

These structures align with the schemas defined in `ACTION_SERVICE_CONTRACT.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    """Return the current timestamp in RFC3339 format."""

    return datetime.now(timezone.utc).isoformat()


@dataclass
class Actor:
    """Represents the actor performing an action."""

    id: str
    role: str
    surface: str


@dataclass
class Action:
    """Stored action record with parity-ready serialization."""

    action_id: str
    timestamp: str
    actor: Actor
    artifact_path: str
    summary: str
    behaviors_cited: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    related_run_id: Optional[str] = None
    audit_log_event_id: Optional[str] = None
    checksum: str = ""
    replay_status: str = "NOT_STARTED"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""

        data = asdict(self)
        data["actor"] = asdict(self.actor)
        return data


@dataclass
class ActionCreateRequest:
    """Incoming payload for creating an action."""

    artifact_path: str
    summary: str
    behaviors_cited: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    related_run_id: Optional[str] = None
    checksum: Optional[str] = None
    audit_log_event_id: Optional[str] = None


@dataclass
class ReplayOptions:
    skip_existing: bool = False
    dry_run: bool = False


@dataclass
class ReplayRequest:
    """Request payload for replaying actions."""

    action_ids: List[str]
    strategy: str = "SEQUENTIAL"
    options: ReplayOptions = field(default_factory=ReplayOptions)


@dataclass
class ReplayStatus:
    """State of a replay job."""

    replay_id: str
    status: str
    progress: float
    logs: List[str] = field(default_factory=list)
    failed_action_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
