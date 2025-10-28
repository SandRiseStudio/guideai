"""Minimal telemetry client and event structures used across guideAI stubs.

The telemetry implementation aligns with the envelope described in
`TELEMETRY_SCHEMA.md` while remaining lightweight for unit tests. Surfaces emit
structured events that can be inspected via in-memory sinks during tests or
forwarded to real backends in future implementations.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


class TelemetrySink(Protocol):
    """Protocol describing telemetry sinks."""

    def write(self, event: "TelemetryEvent") -> None:  # pragma: no cover - interface only
        ...


@dataclass(frozen=True)
class TelemetryEvent:
    """Telemetry envelope matching the documented schema."""

    event_id: str
    timestamp: str
    event_type: str
    actor: Dict[str, str]
    run_id: Optional[str]
    action_id: Optional[str]
    session_id: Optional[str]
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of the event."""

        return asdict(self)


class NullTelemetrySink:
    """Sink that silently ignores events."""

    def write(self, event: TelemetryEvent) -> None:  # pragma: no cover - intentionally no-op
        return None


class InMemoryTelemetrySink:
    """Sink that accumulates telemetry events for inspection in tests."""

    def __init__(self) -> None:
        self.events: List[TelemetryEvent] = []

    def write(self, event: TelemetryEvent) -> None:
        self.events.append(event)


class FileTelemetrySink:
    """Append-only sink that persists telemetry events to a JSONL file."""

    def __init__(self, path: Path) -> None:
        self._path = path.expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: TelemetryEvent) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")


class KafkaTelemetrySink:
    """Sink that publishes telemetry events to a Kafka topic."""

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str = "telemetry.events",
    ) -> None:
        try:
            from kafka import KafkaProducer
        except ImportError:
            raise RuntimeError(
                "kafka-python not installed. Install with: pip install kafka-python"
            )

        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        self._topic = topic

    def write(self, event: TelemetryEvent) -> None:
        self._producer.send(self._topic, value=event.to_dict())
        self._producer.flush()  # Ensure delivery for demo; remove in production


def create_sink_from_env(*, default_path: Optional[Path] = None) -> TelemetrySink:
    """Create a telemetry sink using the standard environment configuration.

    Environment variables:

    ``GUIDEAI_TELEMETRY_PG_DSN``
        When set, a :class:`PostgresTelemetrySink` will be created using the
        provided DSN.  Optionally accepts ``GUIDEAI_TELEMETRY_PG_TIMEOUT`` to
        override the connection timeout (seconds).

    ``GUIDEAI_TELEMETRY_PATH``
        When Postgres is not configured, falls back to a JSONL file sink.  This
        variable overrides the default location used by :class:`FileTelemetrySink`.
    """

    default_path = default_path or Path.home() / ".guideai" / "telemetry" / "events.jsonl"

    dsn = os.environ.get("GUIDEAI_TELEMETRY_PG_DSN")
    if dsn:
        timeout_raw = os.environ.get("GUIDEAI_TELEMETRY_PG_TIMEOUT")
        kwargs: Dict[str, Any] = {}
        if timeout_raw:
            try:
                kwargs["connect_timeout"] = int(timeout_raw)
            except ValueError as exc:
                raise ValueError("GUIDEAI_TELEMETRY_PG_TIMEOUT must be an integer") from exc

        from guideai.storage.postgres_telemetry import PostgresTelemetrySink

        try:
            return PostgresTelemetrySink(dsn, **kwargs)
        except RuntimeError as exc:
            raise RuntimeError(
                "Failed to initialise Postgres telemetry sink. Install psycopg2 and "
                "validate the connection string."
            ) from exc

    path_override = os.environ.get("GUIDEAI_TELEMETRY_PATH")
    sink_path = Path(path_override) if path_override else default_path
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    return FileTelemetrySink(sink_path)


class TelemetryClient:
    """Simple telemetry emitter supporting pluggable sinks."""

    _DEFAULT_ACTOR = {"id": "system", "role": "SYSTEM", "surface": "api"}

    def __init__(
        self,
        sink: Optional[TelemetrySink] = None,
        default_actor: Optional[Dict[str, str]] = None,
    ) -> None:
        self._sink: TelemetrySink = sink or NullTelemetrySink()
        self._default_actor = default_actor or dict(self._DEFAULT_ACTOR)

    @classmethod
    def noop(cls) -> "TelemetryClient":
        """Return a telemetry client that discards all events."""

        return cls()

    def emit_event(
        self,
        *,
        event_type: str,
        payload: Dict[str, Any],
        actor: Optional[Dict[str, str]] = None,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> TelemetryEvent:
        """Emit a telemetry event to the configured sink."""

        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        event = TelemetryEvent(
            event_id=str(uuid.uuid4()),
            timestamp=timestamp,
            event_type=event_type,
            actor=actor or self._default_actor,
            run_id=run_id,
            action_id=action_id,
            session_id=session_id,
            payload=dict(payload),
        )
        self._sink.write(event)
        return event


__all__ = [
    "TelemetrySink",
    "TelemetryEvent",
    "NullTelemetrySink",
    "InMemoryTelemetrySink",
    "FileTelemetrySink",
    "KafkaTelemetrySink",
    "create_sink_from_env",
    "TelemetryClient",
]
