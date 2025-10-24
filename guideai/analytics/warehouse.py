"""DuckDB warehouse client for analytics queries."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore


class AnalyticsWarehouse:
    """Client for querying DuckDB analytics warehouse."""

    def __init__(self, db_path: Optional[str | Path] = None):
        """Initialize warehouse connection.

        Args:
            db_path: Path to DuckDB file (defaults to data/telemetry.duckdb)
        """
        if duckdb is None:
            raise RuntimeError("duckdb not installed. Run: pip install 'duckdb>=0.9,<1.0'")

        if db_path is None:
            # Default to repo root data directory
            repo_root = Path(__file__).parent.parent.parent
            db_path = repo_root / "data" / "telemetry.duckdb"

        self.db_path = str(db_path)
        self._conn: Optional[Any] = None

    @property
    def conn(self) -> Any:
        """Lazy connection to DuckDB."""
        if self._conn is None:
            self._conn = duckdb.connect(self.db_path, read_only=True)
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
        query = """
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
        FROM main.view_behavior_reuse_rate br
        CROSS JOIN main.view_token_savings_rate ts
        CROSS JOIN main.view_completion_rate cr
        CROSS JOIN main.view_compliance_coverage_rate cc
        """

        result = self.conn.execute(query).fetchall()
        columns = [desc[0] for desc in self.conn.description]

        return [dict(zip(columns, row)) for row in result]

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
        query = "SELECT * FROM main.fact_behavior_usage"
        conditions = []

        if start_date:
            conditions.append(f"first_plan_timestamp >= '{start_date}'")
        if end_date:
            conditions.append(f"first_plan_timestamp <= '{end_date}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += f" ORDER BY first_plan_timestamp DESC LIMIT {limit}"

        result = self.conn.execute(query).fetchall()
        columns = [desc[0] for desc in self.conn.description]

        return [dict(zip(columns, row)) for row in result]

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
        query = "SELECT * FROM main.fact_token_savings"
        conditions = []

        if start_date or end_date:
            # Join with fact_behavior_usage to get timestamp
            query = """
            SELECT ts.*, bu.first_plan_timestamp as recorded_at
            FROM main.fact_token_savings ts
            LEFT JOIN main.fact_behavior_usage bu ON ts.run_id = bu.run_id
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

        result = self.conn.execute(query).fetchall()
        columns = [desc[0] for desc in self.conn.description]

        return [dict(zip(columns, row)) for row in result]

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
        query = "SELECT * FROM main.fact_compliance_steps"
        conditions = []

        if start_date:
            conditions.append(f"timestamp >= '{start_date}'")
        if end_date:
            conditions.append(f"timestamp <= '{end_date}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += f" ORDER BY timestamp DESC LIMIT {limit}"

        result = self.conn.execute(query).fetchall()
        columns = [desc[0] for desc in self.conn.description]

        return [dict(zip(columns, row)) for row in result]
