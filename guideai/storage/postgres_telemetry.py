"""PostgreSQL-backed telemetry warehouse helpers.

This module provides a ``TelemetrySink`` implementation that persists events
emitted through :class:`guideai.telemetry.TelemetryClient` into the PostgreSQL
warehouse defined in ``schema/migrations/001_create_telemetry_warehouse.sql``.

Events are stored in the append-only ``telemetry_events`` table and projected
into the fact tables that power the PRD KPI dashboards.  The warehouse exposes
materialised views for the headline metrics, and callers can invoke
``refresh_prd_metric_views`` to update them after large batches of events are
imported.

The implementation intentionally keeps dependencies optional – ``psycopg2`` is
only imported when the sink is instantiated, preserving compatibility for
installations that do not require PostgreSQL support.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, MutableSequence, Optional, Sequence

from guideai.telemetry import TelemetryEvent, TelemetrySink
from guideai.surfaces import normalize_actor_surface

__all__ = [
    "PostgresTelemetrySink",
    "PostgresTelemetryWarehouse",
    "ExecutionSpan",
]


@dataclass
class ExecutionSpan:
    """Represents an execution trace span for distributed tracing.

    Spans track individual operations within a workflow execution, providing
    visibility into performance, errors, and behavior citations.
    """
    span_id: str
    trace_id: str
    operation_name: str
    service_name: str
    start_time: datetime
    trace_timestamp: datetime
    parent_span_id: Optional[str] = None
    run_id: Optional[str] = None
    action_id: Optional[str] = None
    end_time: Optional[datetime] = None
    status: str = "RUNNING"  # RUNNING, SUCCESS, ERROR, TIMEOUT, CANCELLED
    error_message: Optional[str] = None
    token_count: Optional[int] = None
    behavior_citations: Optional[List[str]] = None
    attributes: Optional[Dict[str, Any]] = None
    events: Optional[List[Dict[str, Any]]] = None
    links: Optional[List[Dict[str, Any]]] = None


class PostgresTelemetryWarehouse:
    """Helper responsible for writing telemetry data into PostgreSQL.

    Uses shared PostgresPool for connection management with pooling,
    health checks, and automatic reconnection.

    Parameters
    ----------
    dsn:
        Connection string in the form
        ``postgresql://user:password@host:port/database``.
    connect_timeout:
        Optional connection timeout passed to psycopg2.  Defaults to 5 seconds.
        Note: This is now handled by PostgresPool via GUIDEAI_PG_CONNECT_TIMEOUT.
    """

    def __init__(self, dsn: str, *, connect_timeout: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout = connect_timeout
        self._connect()

    def _connect(self) -> None:
        try:
            import psycopg2  # type: ignore[import-not-found]
            from psycopg2.extras import Json  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "psycopg2 is required for Postgres telemetry support. Install with "
                "`pip install psycopg2-binary`."
            ) from exc

        self._psycopg2 = psycopg2
        self._json_wrapper = Json

        # Use shared PostgresPool for connection management
        from guideai.storage.postgres_pool import PostgresPool
        self._pool = PostgresPool(self._dsn, service_name="telemetry")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def write_event(self, event: TelemetryEvent) -> None:
        """Persist a telemetry event and update fact tables as needed."""

        ts = self._parse_timestamp(event.timestamp)
        actor = dict(event.actor or {})
        actor_surface = normalize_actor_surface(actor.get("surface"))
        actor["surface"] = actor_surface

        event_id = self._coerce_uuid(event.event_id)
        payload_json = self._json_wrapper(event.payload)

        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO telemetry_events (
                        event_id,
                        event_timestamp,
                        event_type,
                        actor_id,
                        actor_role,
                        actor_surface,
                        run_id,
                        action_id,
                        session_id,
                        payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id, event_timestamp) DO NOTHING
                    """,
                    (
                        str(event_id),
                        ts,
                        event.event_type,
                        actor.get("id"),
                        actor.get("role"),
                        actor_surface,
                        event.run_id,
                        event.action_id,
                        event.session_id,
                        payload_json,
                    ),
                )

        # Project event into fact tables (uses separate connection)
        with self._pool.connection(autocommit=True) as conn:
            self._project_event(conn, event, ts, actor)

    def write_events(self, events: Iterable[TelemetryEvent]) -> None:
        """Convenience helper for batch ingestion."""

        for event in events:
            self.write_event(event)

    def start_span(
        self,
        trace_id: str,
        span_id: str,
        operation_name: str,
        service_name: str = "guideai",
        *,
        parent_span_id: Optional[str] = None,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> ExecutionSpan:
        """Start a new execution trace span.

        Creates a span in RUNNING state and inserts it into execution_traces table.
        Call end_span() to mark completion and record duration/status.

        Parameters
        ----------
        trace_id:
            Unique identifier for the entire trace (typically one per workflow run).
        span_id:
            Unique identifier for this specific span.
        operation_name:
            Human-readable operation name (e.g., "BehaviorService.retrieve", "ActionService.execute").
        service_name:
            Service/component name (defaults to "guideai").
        parent_span_id:
            Optional parent span ID for nested operations.
        run_id:
            Optional workflow run ID for correlation with telemetry_events.
        action_id:
            Optional action ID for correlation with action registry.
        attributes:
            Optional metadata dictionary (stored as JSONB).

        Returns
        -------
        ExecutionSpan
            The created span object. Store this to call end_span() later.
        """
        now = datetime.now(timezone.utc)
        trace_timestamp = now
        resolved_parent_span_id = parent_span_id

        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                if parent_span_id:
                    parent_trace_ts = self._lookup_parent_trace_timestamp(cur, parent_span_id)
                    if parent_trace_ts is not None:
                        trace_timestamp = parent_trace_ts
                    else:
                        # Parent span has not been persisted yet; fall back to treating this span as a root
                        resolved_parent_span_id = None

                cur.execute(
                    """
                    INSERT INTO execution_traces (
                        span_id,
                        trace_id,
                        trace_timestamp,
                        parent_span_id,
                        run_id,
                        action_id,
                        operation_name,
                        service_name,
                        start_time,
                        status,
                        attributes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (span_id, trace_timestamp) DO NOTHING
                    """,
                    (
                        span_id,
                        trace_id,
                        trace_timestamp,
                        resolved_parent_span_id,
                        run_id,
                        action_id,
                        operation_name,
                        service_name,
                        now,
                        "RUNNING",
                        self._json_wrapper(attributes or {}),
                    ),
                )

        span = ExecutionSpan(
            span_id=span_id,
            trace_id=trace_id,
            operation_name=operation_name,
            service_name=service_name,
            start_time=now,
            trace_timestamp=trace_timestamp,
            parent_span_id=resolved_parent_span_id,
            run_id=run_id,
            action_id=action_id,
            status="RUNNING",
            attributes=attributes,
        )

        return span

    def end_span(
        self,
        span: ExecutionSpan,
        *,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
        token_count: Optional[int] = None,
        behavior_citations: Optional[List[str]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Complete an execution trace span.

        Updates the span with end_time, final status, and optional metadata.
        The duration_ms column is automatically calculated as a GENERATED column.

        Parameters
        ----------
        span:
            The span object returned from start_span().
        status:
            Final status (SUCCESS, ERROR, TIMEOUT, CANCELLED). Defaults to SUCCESS.
        error_message:
            Optional error description if status is ERROR/TIMEOUT/CANCELLED.
        token_count:
            Optional token count for LLM operations.
        behavior_citations:
            Optional list of behavior IDs referenced during this operation.
        events:
            Optional list of span events (structured log entries with timestamps).
        links:
            Optional list of links to other spans/traces.
        """
        now = datetime.now(timezone.utc)

        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    UPDATE execution_traces
                    SET end_time = %s,
                        status = %s,
                        error_message = %s,
                        token_count = %s,
                        behavior_citations = %s,
                        events = %s,
                        links = %s
                    WHERE span_id = %s
                        AND trace_timestamp = %s
                    """,
                    (
                        now,
                        status,
                        error_message,
                        token_count,
                        behavior_citations if behavior_citations else None,
                        self._json_wrapper(events) if events else None,
                        self._json_wrapper(links) if links else None,
                        span.span_id,
                        span.trace_timestamp,
                    ),
                )

        # Update local span object
        span.end_time = now
        span.status = status
        span.error_message = error_message
        span.token_count = token_count
        span.behavior_citations = behavior_citations
        span.events = events
        span.links = links

    def refresh_metric_views(self) -> None:
        with self._pool.connection(autocommit=True) as conn:
            with self._cursor(conn) as cur:
                cur.execute("SELECT refresh_prd_metric_views();")

    def close(self) -> None:
        """Close the connection pool (no-op with shared PostgresPool)."""
        # PostgresPool is shared across the application, so we don't close it
        pass

    def _ensure_connection(self):
        """Provide a pooled connection proxy for tests and admin checks."""
        return self._pool.proxy(autocommit=True)

    @contextmanager
    def _cursor(self, conn) -> Iterator[Any]:
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(timezone.utc)

    @staticmethod
    def _coerce_uuid(value: Optional[str]) -> uuid.UUID:
        if not value:
            return uuid.uuid4()
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError):
            return uuid.uuid4()

    @staticmethod
    def _coerce_int(value: Optional[object]) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Optional[object]) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_string_list(value: Optional[object]) -> List[str]:
        result: MutableSequence[str] = []
        if isinstance(value, str):
            if value:
                result.append(value)
        elif isinstance(value, Sequence):
            for item in value:
                if isinstance(item, str) and item:
                    result.append(item)
        return list(dict.fromkeys(result))  # De-dupe while preserving order

    @staticmethod
    def _lookup_parent_trace_timestamp(cursor, parent_span_id: str) -> Optional[datetime]:
        cursor.execute(
            """
            SELECT trace_timestamp
            FROM execution_traces
            WHERE span_id = %s
            ORDER BY trace_timestamp DESC
            LIMIT 1
            """,
            (parent_span_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return row[0]

    def _project_event(self, conn, event: TelemetryEvent, ts: datetime, actor: dict) -> None:
        payload = dict(event.payload)
        event_type = event.event_type
        run_id = event.run_id or payload.get("run_id")

        if event_type == "plan_created" and run_id:
            behavior_ids = self._normalize_string_list(payload.get("behavior_ids"))
            baseline_tokens = self._coerce_int(payload.get("baseline_tokens"))
            template_id = payload.get("template_id")
            template_name = payload.get("template_name")

            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO fact_behavior_usage (
                        run_id,
                        template_id,
                        template_name,
                        behavior_ids,
                        behavior_count,
                        has_behaviors,
                        baseline_tokens,
                        actor_surface,
                        actor_role,
                        first_plan_timestamp
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE
                        SET template_id = COALESCE(EXCLUDED.template_id, fact_behavior_usage.template_id),
                            template_name = COALESCE(EXCLUDED.template_name, fact_behavior_usage.template_name),
                            behavior_ids = EXCLUDED.behavior_ids,
                            behavior_count = EXCLUDED.behavior_count,
                            has_behaviors = EXCLUDED.has_behaviors,
                            baseline_tokens = COALESCE(EXCLUDED.baseline_tokens, fact_behavior_usage.baseline_tokens),
                            actor_surface = COALESCE(EXCLUDED.actor_surface, fact_behavior_usage.actor_surface),
                            actor_role = COALESCE(EXCLUDED.actor_role, fact_behavior_usage.actor_role),
                            first_plan_timestamp = COALESCE(fact_behavior_usage.first_plan_timestamp, EXCLUDED.first_plan_timestamp)
                    """,
                    (
                        run_id,
                        template_id,
                        template_name,
                        self._json_wrapper(behavior_ids),
                        len(behavior_ids),
                        bool(behavior_ids),
                        baseline_tokens,
                        actor.get("surface"),
                        actor.get("role"),
                        ts,
                    ),
                )

        elif event_type == "execution_update" and run_id:
            template_id = payload.get("template_id")
            output_tokens = self._coerce_int(payload.get("output_tokens"))
            baseline_tokens = self._coerce_int(payload.get("baseline_tokens"))
            token_savings_pct = self._coerce_float(payload.get("token_savings_pct"))
            status = payload.get("status")
            actor_surface = actor.get("surface")
            actor_role = actor.get("role")

            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO fact_token_savings (
                        run_id,
                        template_id,
                        output_tokens,
                        baseline_tokens,
                        token_savings_pct
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE
                        SET template_id = COALESCE(EXCLUDED.template_id, fact_token_savings.template_id),
                            output_tokens = COALESCE(EXCLUDED.output_tokens, fact_token_savings.output_tokens),
                            baseline_tokens = COALESCE(EXCLUDED.baseline_tokens, fact_token_savings.baseline_tokens),
                            token_savings_pct = COALESCE(EXCLUDED.token_savings_pct, fact_token_savings.token_savings_pct)
                    """,
                    (
                        run_id,
                        template_id,
                        output_tokens,
                        baseline_tokens,
                        token_savings_pct,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO fact_execution_status (
                        run_id,
                        template_id,
                        status,
                        actor_surface,
                        actor_role,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE
                        SET template_id = COALESCE(EXCLUDED.template_id, fact_execution_status.template_id),
                            status = COALESCE(EXCLUDED.status, fact_execution_status.status),
                            actor_surface = COALESCE(EXCLUDED.actor_surface, fact_execution_status.actor_surface),
                            actor_role = COALESCE(EXCLUDED.actor_role, fact_execution_status.actor_role),
                            updated_at = EXCLUDED.updated_at
                    """,
                    (
                        run_id,
                        template_id,
                        status,
                        actor_surface,
                        actor_role,
                        ts,
                    ),
                )

        elif event_type == "compliance_step_recorded":
            checklist_id = payload.get("checklist_id")
            step_id = payload.get("step_id")
            status = payload.get("status")
            coverage_score = self._coerce_float(payload.get("coverage_score"))
            session_id = event.session_id or payload.get("session_id")
            behaviors = self._normalize_string_list(payload.get("behavior_ids"))

            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO fact_compliance_steps (
                        checklist_id,
                        step_id,
                        status,
                        coverage_score,
                        run_id,
                        session_id,
                        behavior_ids,
                        event_timestamp
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        checklist_id,
                        step_id,
                        status,
                        coverage_score,
                        run_id,
                        session_id,
                        self._json_wrapper(behaviors) if behaviors else None,
                        ts,
                    ),
                )

        elif event_type == "behavior_retrieved":
            behaviors = self._normalize_string_list(payload.get("behavior_ids"))
            session_id = event.session_id or payload.get("session_id")
            with self._cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO fact_compliance_steps (
                        checklist_id,
                        step_id,
                        status,
                        coverage_score,
                        run_id,
                        session_id,
                        behavior_ids,
                        event_timestamp
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        None,
                        None,
                        "BEHAVIOR_RETRIEVAL",
                        None,
                        run_id,
                        session_id,
                        self._json_wrapper(behaviors) if behaviors else None,
                        ts,
                    ),
                )


class PostgresTelemetrySink(TelemetrySink):
    """A :class:`TelemetrySink` implementation that writes to PostgreSQL.

    Supports both telemetry event ingestion and distributed execution tracing
    via the TimescaleDB-backed execution_traces hypertable.
    """

    def __init__(self, dsn: str, *, connect_timeout: int = 5) -> None:
        self._warehouse = PostgresTelemetryWarehouse(dsn, connect_timeout=connect_timeout)

    def write(self, event: TelemetryEvent) -> None:
        self._warehouse.write_event(event)

    def start_span(
        self,
        trace_id: str,
        span_id: str,
        operation_name: str,
        service_name: str = "guideai",
        *,
        parent_span_id: Optional[str] = None,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> ExecutionSpan:
        """Start a new execution trace span. See PostgresTelemetryWarehouse.start_span()."""
        return self._warehouse.start_span(
            trace_id=trace_id,
            span_id=span_id,
            operation_name=operation_name,
            service_name=service_name,
            parent_span_id=parent_span_id,
            run_id=run_id,
            action_id=action_id,
            attributes=attributes,
        )

    def end_span(
        self,
        span: ExecutionSpan,
        *,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
        token_count: Optional[int] = None,
        behavior_citations: Optional[List[str]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Complete an execution trace span. See PostgresTelemetryWarehouse.end_span()."""
        self._warehouse.end_span(
            span=span,
            status=status,
            error_message=error_message,
            token_count=token_count,
            behavior_citations=behavior_citations,
            events=events,
            links=links,
        )

    def refresh_metric_views(self) -> None:
        self._warehouse.refresh_metric_views()

    def close(self) -> None:
        self._warehouse.close()
