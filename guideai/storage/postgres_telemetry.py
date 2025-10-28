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
from datetime import datetime, timezone
from typing import Iterable, List, MutableSequence, Optional, Sequence

from guideai.telemetry import TelemetryEvent, TelemetrySink

__all__ = [
    "PostgresTelemetrySink",
    "PostgresTelemetryWarehouse",
]


class PostgresTelemetryWarehouse:
    """Helper responsible for writing telemetry data into PostgreSQL.

    Parameters
    ----------
    dsn:
        Connection string in the form
        ``postgresql://user:password@host:port/database``.
    connect_timeout:
        Optional connection timeout passed to psycopg2.  Defaults to 5 seconds.
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
        self._connection = psycopg2.connect(self._dsn, connect_timeout=self._connect_timeout)
        self._connection.autocommit = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def write_event(self, event: TelemetryEvent) -> None:
        """Persist a telemetry event and update fact tables as needed."""

        conn = self._ensure_connection()
        ts = self._parse_timestamp(event.timestamp)
        actor = event.actor or {}

        event_id = self._coerce_uuid(event.event_id)
        payload_json = self._json_wrapper(event.payload)

        with conn.cursor() as cur:
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
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    str(event_id),
                    ts,
                    event.event_type,
                    actor.get("id"),
                    actor.get("role"),
                    actor.get("surface"),
                    event.run_id,
                    event.action_id,
                    event.session_id,
                    payload_json,
                ),
            )

        self._project_event(conn, event, ts, actor)

    def write_events(self, events: Iterable[TelemetryEvent]) -> None:
        """Convenience helper for batch ingestion."""

        for event in events:
            self.write_event(event)

    def refresh_metric_views(self) -> None:
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT refresh_prd_metric_views();")

    def close(self) -> None:
        if getattr(self, "_connection", None) is not None and self._connection.closed == 0:
            self._connection.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_connection(self):
        if getattr(self, "_connection", None) is None or self._connection.closed != 0:
            self._connect()
        return self._connection

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

    def _project_event(self, conn, event: TelemetryEvent, ts: datetime, actor: dict) -> None:
        payload = dict(event.payload)
        event_type = event.event_type
        run_id = event.run_id or payload.get("run_id")

        if event_type == "plan_created" and run_id:
            behavior_ids = self._normalize_string_list(payload.get("behavior_ids"))
            baseline_tokens = self._coerce_int(payload.get("baseline_tokens"))
            template_id = payload.get("template_id")
            template_name = payload.get("template_name")

            with conn.cursor() as cur:
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

            with conn.cursor() as cur:
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

            with conn.cursor() as cur:
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
            with conn.cursor() as cur:
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
    """A :class:`TelemetrySink` implementation that writes to PostgreSQL."""

    def __init__(self, dsn: str, *, connect_timeout: int = 5) -> None:
        self._warehouse = PostgresTelemetryWarehouse(dsn, connect_timeout=connect_timeout)

    def write(self, event: TelemetryEvent) -> None:
        self._warehouse.write_event(event)

    def refresh_metric_views(self) -> None:
        self._warehouse.refresh_metric_views()

    def close(self) -> None:
        self._warehouse.close()
