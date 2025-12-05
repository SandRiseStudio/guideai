"""Analytics warehouse client with DuckDB + Timescale/Postgres backends."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from guideai.utils.dsn import apply_host_overrides

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - optional dependency
    psycopg2 = None  # type: ignore


class AnalyticsWarehouse:
    """Client for querying analytics warehouse (DuckDB or Timescale/Postgres)."""

    def __init__(
        self,
        *,
        db_path: Optional[str | Path] = None,
        dsn: Optional[str] = None,
    ):
        """Initialize warehouse connection.

        Args:
            db_path: Optional DuckDB file path override.
            dsn: Optional Postgres/TimescaleDSN. When provided (or available via
                environment), the warehouse uses psycopg2 instead of DuckDB.
        """

        # Explicit db_path always forces DuckDB usage (even if DSN env vars exist)
        if db_path is not None:
            if duckdb is None:
                raise RuntimeError(
                    "duckdb not installed. Run: pip install 'duckdb>=0.9,<1.0'"
                )
            self._backend = "duckdb"
            self.db_path = str(db_path)
            self._dsn: Optional[str] = None
        else:
            # Postgres DSN (Timescale) can be passed directly or via env vars
            env_dsn_raw = dsn or os.environ.get("GUIDEAI_ANALYTICS_PG_DSN") or os.environ.get(
                "GUIDEAI_TELEMETRY_PG_DSN"
            )
            env_dsn = apply_host_overrides(env_dsn_raw, "ANALYTICS")

            if env_dsn:
                if psycopg2 is None:
                    raise RuntimeError(
                        "psycopg2 not installed. Run: pip install 'psycopg2-binary>=2.9,<3.0'"
                    )
                self._backend = "postgres"
                self._dsn = env_dsn
                self.db_path = None
            else:
                if duckdb is None:
                    raise RuntimeError(
                        "duckdb not installed. Run: pip install 'duckdb>=0.9,<1.0'"
                    )
                repo_root = Path(__file__).parent.parent.parent
                default_path = os.environ.get("GUIDEAI_ANALYTICS_DUCKDB_PATH")
                if default_path is None:
                    default_path = repo_root / "data" / "telemetry.duckdb"
                self._backend = "duckdb"
                self.db_path = str(default_path)
                self._dsn = None

        self._conn: Optional[Any] = None

    @property
    def backend(self) -> str:
        """Return active backend name (duckdb or postgres)."""
        return self._backend

    @property
    def conn(self) -> Any:
        """Lazy database connection (backend aware)."""
        if self._conn is None:
            if self.backend == "duckdb":
                assert self.db_path is not None  # mypy hint
                assert duckdb is not None  # nosec - checked during init
                self._conn = duckdb.connect(self.db_path, read_only=True)
            else:
                assert self._dsn is not None
                assert psycopg2 is not None  # nosec - checked during init
                self._conn = psycopg2.connect(self._dsn)
                self._conn.autocommit = True
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> AnalyticsWarehouse:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def get_kpi_summary(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query KPI summary - aggregates metrics from fact tables.

        Args:
            start_date: ISO format date string (e.g., '2025-10-01')
            end_date: ISO format date string

        Returns:
            List of KPI summary records with PRD metrics
        """
        # Build aggregation query combining the rate views
        query = f"""
        SELECT
            CURRENT_TIMESTAMP AS snapshot_time,
            br.reuse_rate_pct AS behavior_reuse_pct,
            br.total_runs AS total_runs,
            br.runs_with_behaviors,
            ts.avg_savings_rate_pct AS average_token_savings_pct,
            ts.total_baseline_tokens,
            ts.total_output_tokens,
            cr.completion_rate_pct AS task_completion_rate_pct,
            cr.completed_runs,
            cr.failed_runs,
            cc.avg_coverage_rate_pct AS average_compliance_coverage_pct,
            cc.total_compliance_events
        FROM {self._view('behavior_reuse')} br
        CROSS JOIN {self._view('token_savings')} ts
        CROSS JOIN {self._view('completion')} cr
        CROSS JOIN {self._view('compliance_coverage')} cc
        """

        return self._fetch(query)

    def get_behavior_usage(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query behavior usage facts.

        Args:
            start_date: ISO format date string
            end_date: ISO format date string
            limit: Maximum number of records to return

        Returns:
            List of behavior usage records
        """
        query = f"SELECT * FROM {self._table('fact_behavior_usage')}"
        conditions = []

        if start_date:
            conditions.append(f"first_plan_timestamp >= '{start_date}'")
        if end_date:
            conditions.append(f"first_plan_timestamp <= '{end_date}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += f" ORDER BY first_plan_timestamp DESC LIMIT {limit}"

        return self._fetch(query)

    def get_token_savings(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query token savings facts.

        Args:
            start_date: ISO format date string
            end_date: ISO format date string
            limit: Maximum number of records to return

        Returns:
            List of token savings records
        """
        query = f"SELECT * FROM {self._table('fact_token_savings')}"

        if start_date or end_date:
            # Join with fact_behavior_usage to get timestamp
            query = f"""
            SELECT ts.*, bu.first_plan_timestamp as recorded_at
            FROM {self._table('fact_token_savings')} ts
            LEFT JOIN {self._table('fact_behavior_usage')} bu ON ts.run_id = bu.run_id
            """
            where_conditions = []
            if start_date:
                where_conditions.append(f"bu.first_plan_timestamp >= '{start_date}'")
            if end_date:
                where_conditions.append(f"bu.first_plan_timestamp <= '{end_date}'")
            if where_conditions:
                query += " WHERE " + " AND ".join(where_conditions)
            query += f" ORDER BY bu.first_plan_timestamp DESC LIMIT {limit}"
        else:
            query += f" LIMIT {limit}"

        return self._fetch(query)

    def get_compliance_coverage(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query compliance steps facts.

        Args:
            start_date: ISO format date string
            end_date: ISO format date string
            limit: Maximum number of records to return

        Returns:
            List of compliance step records
        """
        query = f"SELECT * FROM {self._table('fact_compliance_steps')}"
        conditions = []

        if start_date:
            conditions.append(f"{self._compliance_timestamp_column()} >= '{start_date}'")
        if end_date:
            conditions.append(f"{self._compliance_timestamp_column()} <= '{end_date}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += f" ORDER BY {self._compliance_timestamp_column()} DESC LIMIT {limit}"

        return self._fetch(query)

    # ------------------------------------------------------------------
    # Cost Optimization Queries (Epic 8.12)
    # ------------------------------------------------------------------

    def get_cost_by_service(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        service_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query cost allocation by service.

        Args:
            start_date: ISO format date string (e.g., '2025-10-01')
            end_date: ISO format date string
            service_name: Optional filter for specific service

        Returns:
            List of cost-by-service records with totals and operation counts
        """
        query = f"SELECT * FROM {self._view('cost_by_service')}"
        conditions = []

        if service_name:
            conditions.append(f"service_name = '{service_name}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY total_cost_usd DESC"

        return self._fetch(query)

    def get_cost_per_run(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        template_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query cost allocation per run.

        Args:
            start_date: ISO format date string
            end_date: ISO format date string
            template_id: Optional filter for specific workflow template
            limit: Maximum number of records to return

        Returns:
            List of cost-per-run records with savings calculations
        """
        query = f"SELECT * FROM {self._view('cost_per_run')}"
        conditions = []

        if start_date:
            conditions.append(f"timestamp >= '{start_date}'")
        if end_date:
            conditions.append(f"timestamp <= '{end_date}'")
        if template_id:
            conditions.append(f"template_id = '{template_id}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += f" ORDER BY timestamp DESC LIMIT {limit}"

        return self._fetch(query)

    def get_roi_summary(self) -> Dict[str, Any]:
        """Query ROI analysis summary.

        Returns:
            Single ROI summary record with total savings, costs, and ratio
        """
        query = f"SELECT * FROM {self._view('roi_analysis')}"
        results = self._fetch(query)
        if results:
            return results[0]
        return {
            "total_savings_usd": 0.0,
            "total_runs": 0,
            "total_infrastructure_cost_usd": 0.0,
            "roi_ratio": None,
        }

    def get_daily_cost_summary(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """Query daily cost summary for budget tracking.

        Args:
            start_date: ISO format date string
            end_date: ISO format date string
            limit: Maximum number of days to return (default 30)

        Returns:
            List of daily cost summaries
        """
        query = f"SELECT * FROM {self._view('daily_cost_summary')}"
        conditions = []

        if start_date:
            conditions.append(f"date >= '{start_date}'")
        if end_date:
            conditions.append(f"date <= '{end_date}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += f" ORDER BY date DESC LIMIT {limit}"

        return self._fetch(query)

    def get_top_expensive_workflows(
        self,
        *,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Query top expensive workflows by cumulative cost.

        Args:
            limit: Maximum number of workflows to return (default 10)

        Returns:
            List of workflow cost summaries ordered by total cost
        """
        query = f"SELECT * FROM {self._view('top_expensive_workflows')} LIMIT {limit}"
        return self._fetch(query)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _table(self, name: str) -> str:
        """Return fully-qualified table name for current backend."""
        if self.backend == "duckdb":
            return f"main.{name}"
        return name

    def _view(self, metric: str) -> str:
        """Return correct KPI view name per backend."""
        mapping = {
            "behavior_reuse": "view_behavior_reuse_rate"
            if self.backend == "duckdb"
            else "mv_behavior_reuse_rate",
            "token_savings": "view_token_savings_rate"
            if self.backend == "duckdb"
            else "mv_token_savings_rate",
            "completion": "view_completion_rate"
            if self.backend == "duckdb"
            else "mv_completion_rate",
            "compliance_coverage": "view_compliance_coverage_rate"
            if self.backend == "duckdb"
            else "mv_compliance_coverage_rate",
            # Cost optimization views (Epic 8.12)
            "cost_by_service": "view_cost_by_service"
            if self.backend == "duckdb"
            else "mv_cost_by_service",
            "cost_per_run": "view_cost_per_run"
            if self.backend == "duckdb"
            else "mv_cost_per_run",
            "roi_analysis": "view_roi_analysis"
            if self.backend == "duckdb"
            else "mv_roi_analysis",
            "daily_cost_summary": "view_daily_cost_summary"
            if self.backend == "duckdb"
            else "mv_daily_cost_summary",
            "top_expensive_workflows": "view_top_expensive_workflows"
            if self.backend == "duckdb"
            else "mv_top_expensive_workflows",
        }
        identifier = mapping[metric]
        return identifier if self.backend == "postgres" else f"main.{identifier}"

    def _compliance_timestamp_column(self) -> str:
        return "timestamp" if self.backend == "duckdb" else "event_timestamp"

    def _fetch(self, query: str) -> List[Dict[str, Any]]:
        """Execute a query and return list of dict rows."""
        if self.backend == "duckdb":
            cursor = self.conn.execute(query)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]

        assert psycopg2 is not None  # nosec - ensured during initialization
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cursor.execute(query)
            rows = cursor.fetchall()
            # RealDictRow is already dict-like but convert for clarity
            return [dict(row) for row in rows]
        finally:
            cursor.close()
