#!/usr/bin/env python3
"""
Flink job wrapper for GuideAI Telemetry KPI Projector.

Deploys the TelemetryKPIProjector as a streaming Flink job that consumes
telemetry events from Kafka and produces fact tables for Snowflake warehouse.

Usage:
    python telemetry_kpi_job.py --kafka-servers localhost:9092 --topic telemetry.events
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Add guideai package to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from guideai.analytics.telemetry_kpi_projector import TelemetryKPIProjector

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class KafkaToWarehouseJob:
    """Flink job orchestrator for telemetry pipeline supporting multiple warehouse backends."""

    def __init__(
        self,
        kafka_servers: str,
        kafka_topic: str,
        warehouse_config: Dict[str, Any],
    ) -> None:
        self.kafka_servers = kafka_servers
        self.kafka_topic = kafka_topic
        self.warehouse_config = warehouse_config
        self.projector = TelemetryKPIProjector()

        # Determine warehouse backend
        self.warehouse_type = warehouse_config.get("type", "duckdb").lower()
        if self.warehouse_type not in ["duckdb", "postgresql", "snowflake"]:
            raise ValueError(f"Unsupported warehouse type: {self.warehouse_type}")

    def consume_and_project(self) -> None:
        """
        Consume events from Kafka, project to facts, and write to Snowflake.

        In production, this would use PyFlink streaming APIs. For MVP, we'll
        batch-process from Kafka in intervals.
        """
        try:
            from kafka import KafkaConsumer
            from kafka.errors import KafkaError
        except ImportError:
            logger.error("kafka-python not installed. Run: pip install kafka-python")
            sys.exit(1)

        logger.info(f"Starting Kafka consumer: {self.kafka_servers} topic={self.kafka_topic}")

        consumer = KafkaConsumer(
            self.kafka_topic,
            bootstrap_servers=self.kafka_servers.split(","),
            auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"),
            group_id=os.getenv("KAFKA_CONSUMER_GROUP", "telemetry-kpi-projector"),
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            consumer_timeout_ms=1000,  # Poll every 1 second to check flush interval
        )

        batch: List[Dict[str, Any]] = []
        batch_size = int(os.getenv("PROJECTION_BATCH_SIZE", "1000"))
        flush_interval = int(os.getenv("PROJECTION_FLUSH_INTERVAL_MS", "60000"))
        last_flush = datetime.now(timezone.utc)

        logger.info(f"Batch processing: size={batch_size}, flush_interval={flush_interval}ms")
        logger.info(f"Consumer starting to poll...")

        try:
            while True:
                # Poll for messages with timeout
                for message in consumer:
                    logger.debug(f"Received message: {message.offset}")
                    event = message.value
                    batch.append(event)

                    # Flush batch if size threshold or time threshold reached
                    now = datetime.now(timezone.utc)
                    elapsed_ms = (now - last_flush).total_seconds() * 1000

                    if len(batch) >= batch_size or elapsed_ms >= flush_interval:
                        self._process_batch(batch)
                        batch = []
                        last_flush = now

                # for loop exited (consumer timeout), check if we need to flush based on time
                now = datetime.now(timezone.utc)
                elapsed_ms = (now - last_flush).total_seconds() * 1000
                if batch and elapsed_ms >= flush_interval:
                    logger.info(f"Flushing batch due to timeout: {len(batch)} events")
                    self._process_batch(batch)
                    batch = []
                    last_flush = now

        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
            if batch:
                self._process_batch(batch)
        except KafkaError as e:
            logger.error(f"Kafka error: {e}")
            raise
        finally:
            consumer.close()

    def _process_batch(self, events: List[Dict[str, Any]]) -> None:
        """Project events to facts and write to warehouse."""
        if not events:
            return

        logger.info(f"Processing batch: {len(events)} events")

        # Project events to KPI facts
        projection = self.projector.project(events)

        # Write facts to warehouse
        self._write_to_warehouse(projection)

        logger.info(
            f"Batch complete: {len(projection.fact_behavior_usage)} behavior facts, "
            f"{len(projection.fact_execution_status)} execution facts, "
            f"{len(projection.fact_compliance_steps)} compliance facts"
        )

    def _write_to_warehouse(self, projection: Any) -> None:
        """Write projection facts to configured warehouse backend."""
        if self.warehouse_type == "duckdb":
            self._write_to_duckdb(projection)
        elif self.warehouse_type == "postgresql":
            self._write_to_postgresql(projection)
        elif self.warehouse_type == "snowflake":
            self._write_to_snowflake(projection)

    def _write_to_duckdb(self, projection: Any) -> None:
        """Write projection facts to DuckDB file."""
        try:
            import duckdb
        except ImportError:
            logger.warning("duckdb not installed, skipping warehouse write")
            return

        try:
            db_path = self.warehouse_config.get("db_path", "data/telemetry.duckdb")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

            conn = duckdb.connect(db_path)

            # Insert behavior usage facts
            if projection.fact_behavior_usage:
                self._insert_facts_duckdb(conn, "fact_behavior_usage", projection.fact_behavior_usage)

            # Insert token savings facts
            if projection.fact_token_savings:
                self._insert_facts_duckdb(conn, "fact_token_savings", projection.fact_token_savings)

            # Insert execution status facts
            if projection.fact_execution_status:
                self._insert_facts_duckdb(conn, "fact_execution_status", projection.fact_execution_status)

            # Insert compliance step facts
            if projection.fact_compliance_steps:
                self._insert_facts_duckdb(conn, "fact_compliance_steps", projection.fact_compliance_steps)

            conn.close()

        except Exception as e:
            logger.error(f"DuckDB write error: {e}")
            raise

    def _write_to_postgresql(self, projection: Any) -> None:
        """Write projection facts to PostgreSQL database."""
        try:
            import psycopg2
        except ImportError:
            logger.warning("psycopg2 not installed, skipping warehouse write")
            return

        try:
            conn = psycopg2.connect(
                host=self.warehouse_config.get("host", "localhost"),
                port=self.warehouse_config.get("port", 5432),
                database=self.warehouse_config.get("database", "guideai"),
                user=self.warehouse_config.get("user"),
                password=self.warehouse_config.get("password"),
            )

            cursor = conn.cursor()

            # Insert behavior usage facts
            if projection.fact_behavior_usage:
                self._insert_facts_pg(cursor, "fact_behavior_usage", projection.fact_behavior_usage)

            # Insert execution status facts
            if projection.fact_execution_status:
                self._insert_facts_pg(cursor, "fact_execution_status", projection.fact_execution_status)

            # Insert compliance step facts
            if projection.fact_compliance_steps:
                self._insert_facts_pg(cursor, "fact_compliance_steps", projection.fact_compliance_steps)

            conn.commit()
            cursor.close()
            conn.close()

        except Exception as e:
            logger.error(f"PostgreSQL write error: {e}")
            raise

    def _write_to_snowflake(self, projection: Any) -> None:
        """Write projection facts to Snowflake warehouse (legacy support)."""
        try:
            import snowflake.connector
        except ImportError:
            logger.warning("snowflake-connector-python not installed, skipping warehouse write")
            return

        try:
            conn = snowflake.connector.connect(
                account=self.warehouse_config["account"],
                user=self.warehouse_config["user"],
                password=self.warehouse_config["password"],
                database=self.warehouse_config.get("database", "GUIDEAI"),
                schema=self.warehouse_config.get("schema", "prd_metrics"),
                warehouse=self.warehouse_config.get("warehouse", "COMPUTE_WH"),
                role=self.warehouse_config.get("role", "ACCOUNTADMIN"),
            )

            cursor = conn.cursor()

            # Insert facts using Snowflake syntax
            if projection.behavior_facts:
                self._insert_facts_snowflake(cursor, "fact_behavior_usage", projection.behavior_facts)

            if projection.execution_facts:
                self._insert_facts_snowflake(cursor, "fact_execution_status", projection.execution_facts)

            if projection.compliance_facts:
                self._insert_facts_snowflake(cursor, "fact_compliance_steps", projection.compliance_facts)

            conn.commit()
            cursor.close()
            conn.close()

        except Exception as e:
            logger.error(f"Snowflake write error: {e}")
            raise

    def _insert_facts_duckdb(self, conn: Any, table: str, facts: List[Dict[str, Any]]) -> None:
        """Bulk insert facts into DuckDB table."""
        if not facts:
            return

        # Define schema columns for each fact table (aligned with TelemetryKPIProjector output)
        SCHEMA_COLUMNS = {
            "fact_behavior_usage": [
                "run_id", "template_id", "template_name", "behavior_ids",
                "behavior_count", "has_behaviors", "baseline_tokens",
                "actor_surface", "actor_role", "first_plan_timestamp"
            ],
            "fact_execution_status": [
                "run_id", "template_id", "status", "actor_surface", "actor_role"
            ],
            "fact_token_savings": [
                "run_id", "template_id", "output_tokens", "baseline_tokens", "token_savings_pct"
            ],
            "fact_compliance_steps": [
                "checklist_id", "step_id", "status", "coverage_score",
                "run_id", "session_id", "behavior_ids", "timestamp"
            ]
        }

        import pandas as pd
        df = pd.DataFrame(facts)

        # Filter DataFrame to only include schema-defined columns
        if table in SCHEMA_COLUMNS:
            missing_cols = [col for col in SCHEMA_COLUMNS[table] if col not in df.columns]
            if missing_cols:
                logger.error(f"Missing columns in {table}: {missing_cols}. Available: {list(df.columns)}")
                raise ValueError(f"Missing required columns: {missing_cols}")
            df = df[SCHEMA_COLUMNS[table]]

        conn.execute(f"INSERT INTO {table} SELECT * FROM df")
        logger.info(f"Inserted {len(facts)} rows into {table}")

    def _insert_facts_pg(self, cursor: Any, table: str, facts: List[Dict[str, Any]]) -> None:
        """Bulk insert facts into PostgreSQL table."""
        if not facts:
            return

        columns = list(facts[0].keys())
        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

        rows = [[fact[col] for col in columns] for fact in facts]
        cursor.executemany(sql, rows)
        logger.info(f"Inserted {len(rows)} rows into {table}")

    def _insert_facts_snowflake(self, cursor: Any, table: str, facts: List[Dict[str, Any]]) -> None:
        """Bulk insert facts into Snowflake table."""
        if not facts:
            return

        columns = list(facts[0].keys())
        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

        rows = [[fact[col] for col in columns] for fact in facts]
        cursor.executemany(sql, rows)
        logger.info(f"Inserted {len(rows)} rows into {table}")


def main() -> None:
    """Entry point for Flink job deployment."""
    parser = argparse.ArgumentParser(description="GuideAI Telemetry KPI Flink Job")
    parser.add_argument(
        "--kafka-servers",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        help="Kafka bootstrap servers",
    )
    parser.add_argument(
        "--kafka-topic",
        default=os.getenv("KAFKA_TOPIC_TELEMETRY_EVENTS", "telemetry.events"),
        help="Kafka topic for telemetry events",
    )
    args = parser.parse_args()

    # Load warehouse config from environment
    warehouse_type = os.getenv("WAREHOUSE_TYPE", "duckdb").lower()

    if warehouse_type == "duckdb":
        warehouse_config = {
            "type": "duckdb",
            "db_path": os.getenv("DUCKDB_PATH", "data/telemetry.duckdb"),
        }
    elif warehouse_type == "postgresql":
        warehouse_config = {
            "type": "postgresql",
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("POSTGRES_PORT", "5432")),
            "database": os.getenv("POSTGRES_DATABASE", "guideai"),
            "user": os.getenv("POSTGRES_USER"),
            "password": os.getenv("POSTGRES_PASSWORD"),
        }
        if not all([warehouse_config["user"], warehouse_config["password"]]):
            logger.error("Missing PostgreSQL credentials. Set POSTGRES_USER, POSTGRES_PASSWORD.")
            sys.exit(1)
    elif warehouse_type == "snowflake":
        warehouse_config = {
            "type": "snowflake",
            "account": os.getenv("SNOWFLAKE_ACCOUNT"),
            "user": os.getenv("SNOWFLAKE_USER"),
            "password": os.getenv("SNOWFLAKE_PASSWORD"),
            "database": os.getenv("SNOWFLAKE_DATABASE", "GUIDEAI_DEV"),
            "schema": os.getenv("SNOWFLAKE_SCHEMA", "prd_metrics"),
            "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
            "role": os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        }
        if not all([warehouse_config["account"], warehouse_config["user"], warehouse_config["password"]]):
            logger.error("Missing Snowflake credentials. Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD.")
            sys.exit(1)
    else:
        logger.error(f"Unsupported warehouse type: {warehouse_type}")
        sys.exit(1)

    logger.info("Starting GuideAI Telemetry KPI Projector Job")
    logger.info(f"Kafka: {args.kafka_servers} → {args.kafka_topic}")
    logger.info(f"Warehouse: {warehouse_type} ({warehouse_config})")

    job = KafkaToWarehouseJob(
        kafka_servers=args.kafka_servers,
        kafka_topic=args.kafka_topic,
        warehouse_config=warehouse_config,
    )

    job.consume_and_project()


if __name__ == "__main__":
    main()
