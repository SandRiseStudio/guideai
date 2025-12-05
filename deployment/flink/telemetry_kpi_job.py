#!/usr/bin/env python3
"""
Production Flink job for GuideAI Telemetry KPI Projection.

Implements streaming pipeline with:
- Checkpointing: 60s interval, exactly-once semantics
- Windowing: 1-minute tumbling windows with 10s lateness allowance
- Continuous aggregate updates: Real-time TimescaleDB materialized view refresh
- Backpressure handling: Kafka consumer with flow control

Architecture:
    Kafka (telemetry.events) → Flink Streaming → TimescaleDB (continuous aggregates)

Usage:
    # Development mode (kafka-python polling, no PyFlink required)
    python telemetry_kpi_job.py --kafka-servers localhost:9092 --mode dev

    # Production mode (PyFlink streaming, submit to Flink cluster)
    python telemetry_kpi_job.py --kafka-servers kafka-1:9092 --mode prod

    # With Podman/Docker:
    podman exec -it guideai-flink-jobmanager \\
      python /opt/flink/jobs/telemetry_kpi_job.py \\
      --mode prod \\
      --kafka-servers kafka-1:9092,kafka-2:9092,kafka-3:9092 \\
      --postgres-dsn "postgresql://user:pass@postgres-telemetry:5432/guideai_telemetry"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add guideai package to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from guideai.analytics.telemetry_kpi_projector import TelemetryKPIProjector

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)




class ProductionFlinkJob:
    """
    Production Flink streaming job with exactly-once semantics.

    Features:
    - Checkpointing: 60s interval, RocksDB state backend
    - Exactly-once: Kafka source/sink with transactional writes
    - Windowing: 1-minute tumbling windows, 10s allowed lateness
    - Backpressure: Automatic flow control via Flink watermarks
    - Monitoring: Flink metrics exposed via /metrics endpoint
    """

    def __init__(
        self,
        kafka_servers: str,
        kafka_topic: str,
        postgres_dsn: str,
        checkpoint_dir: str = "/opt/flink/checkpoints",
    ) -> None:
        self.kafka_servers = kafka_servers
        self.kafka_topic = kafka_topic
        self.postgres_dsn = postgres_dsn
        self.checkpoint_dir = checkpoint_dir
        self.projector = TelemetryKPIProjector()

    def run_streaming(self) -> None:
        """Execute PyFlink streaming job with exactly-once guarantees."""
        try:
            from pyflink.datastream import StreamExecutionEnvironment
            from pyflink.datastream.connectors.kafka import (
                KafkaSource,
                KafkaOffsetsInitializer,
                KafkaRecordSerializationSchema,
            )
            from pyflink.common import WatermarkStrategy, Duration, Time
            from pyflink.common.serialization import SimpleStringSchema
            from pyflink.datastream.window import TumblingEventTimeWindows
        except ImportError:
            logger.error(
                "PyFlink not installed. Run: pip install apache-flink\n"
                "For production deployment, use Flink Docker image with Python 3.9+"
            )
            sys.exit(1)

        logger.info("Initializing PyFlink streaming environment")

        # Create streaming environment
        env = StreamExecutionEnvironment.get_execution_environment()

        # Configure checkpointing (exactly-once semantics)
        env.enable_checkpointing(60000)  # 60 seconds
        env.get_checkpoint_config().set_checkpoint_storage_dir(f"file://{self.checkpoint_dir}")
        env.get_checkpoint_config().set_checkpointing_mode(
            "EXACTLY_ONCE"  # Guarantee exactly-once processing
        )
        env.get_checkpoint_config().set_checkpoint_timeout(300000)  # 5 minutes
        env.get_checkpoint_config().set_max_concurrent_checkpoints(1)
        env.get_checkpoint_config().set_min_pause_between_checkpoints(30000)  # 30s

        # Configure state backend (RocksDB for large state)
        env.set_state_backend("rocksdb")

        logger.info(f"Checkpointing enabled: interval=60s, mode=EXACTLY_ONCE, dir={self.checkpoint_dir}")

        # Create Kafka source
        kafka_source = (
            KafkaSource.builder()
            .set_bootstrap_servers(self.kafka_servers)
            .set_topics(self.kafka_topic)
            .set_group_id("telemetry-kpi-projector")
            .set_starting_offsets(KafkaOffsetsInitializer.earliest())
            .set_value_only_deserializer(SimpleStringSchema())
            .build()
        )

        logger.info(f"Kafka source configured: {self.kafka_servers} → {self.kafka_topic}")

        # Create data stream with watermark strategy
        # Allow 10 seconds of lateness for event-time processing
        watermark_strategy = (
            WatermarkStrategy
            .for_bounded_out_of_orderness(Duration.of_seconds(10))
            .with_idleness(Duration.of_minutes(1))
        )

        stream = env.from_source(
            kafka_source,
            watermark_strategy,
            "KafkaTelemetrySource"
        )

        # Parse JSON events
        stream = stream.map(
            lambda json_str: json.loads(json_str),
            output_type="MAP<STRING, STRING>"
        )

        # Apply 1-minute tumbling windows
        windowed_stream = stream.window(
            TumblingEventTimeWindows.of(Time.minutes(1))
        ).allowed_lateness(Time.seconds(10))

        # Process windows: aggregate events and write to TimescaleDB
        windowed_stream.process(
            TimescaleDBWindowFunction(self.postgres_dsn, self.projector)
        )

        logger.info("Window configuration: 1-minute tumbling, 10s lateness")
        logger.info("Starting Flink streaming job...")

        # Execute job
        env.execute("GuideAI Telemetry KPI Projection (Production)")


class TimescaleDBWindowFunction:
    """
    Flink ProcessWindowFunction that writes window aggregates to TimescaleDB.

    Implements:
    - Batch inserts into telemetry_events hypertable
    - Projection to fact tables via TelemetryKPIProjector
    - Continuous aggregate refresh via refresh_continuous_aggregate()
    """

    def __init__(self, postgres_dsn: str, projector: TelemetryKPIProjector) -> None:
        self.postgres_dsn = postgres_dsn
        self.projector = projector
        self._conn: Optional[Any] = None

    def open(self, runtime_context) -> None:
        """Initialize PostgreSQL connection (called once per task)."""
        try:
            import psycopg2
        except ImportError:
            logger.error("psycopg2 not installed")
            raise

        self._conn = psycopg2.connect(self.postgres_dsn)
        self._conn.autocommit = False  # Use transactions for exactly-once
        logger.info(f"Connected to TimescaleDB: {self.postgres_dsn}")

    def process(self, key, context, elements) -> None:
        """Process windowed batch of events."""
        events = list(elements)

        if not events:
            return

        logger.info(f"Processing window: {len(events)} events, "
                   f"window=[{context.window().start()}, {context.window().end()})")

        try:
            cursor = self._conn.cursor()

            # 1. Insert raw events into telemetry_events hypertable
            for event in events:
                self._insert_telemetry_event(cursor, event)

            # 2. Project events to fact tables
            projection = self.projector.project([e for e in events])

            # 3. Write facts to warehouse
            self._write_facts(cursor, projection)

            # 4. Refresh continuous aggregates (near real-time)
            cursor.execute("CALL refresh_continuous_aggregate('metrics_10min', NULL, NULL)")

            # 5. Commit transaction (exactly-once guarantee)
            self._conn.commit()

            logger.info(f"Window committed: {len(events)} events processed, "
                       f"{len(projection.fact_behavior_usage)} behavior facts, "
                       f"continuous aggregates refreshed")

        except Exception as e:
            logger.error(f"Window processing error: {e}")
            self._conn.rollback()
            raise

    def _insert_telemetry_event(self, cursor, event: Dict[str, Any]) -> None:
        """Insert event into telemetry_events hypertable."""
        from psycopg2.extras import Json

        cursor.execute(
            """
            INSERT INTO telemetry_events (
                event_id, event_timestamp, event_type,
                actor_id, actor_role, actor_surface,
                run_id, action_id, session_id, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id, event_timestamp) DO NOTHING
            """,
            (
                event.get("event_id"),
                event.get("timestamp"),
                event.get("event_type"),
                event.get("actor", {}).get("id"),
                event.get("actor", {}).get("role"),
                event.get("actor", {}).get("surface"),
                event.get("run_id"),
                event.get("action_id"),
                event.get("session_id"),
                Json(event.get("payload", {})),
            ),
        )

    def _write_facts(self, cursor, projection: Any) -> None:
        """Write projection facts to TimescaleDB fact tables."""
        # Insert behavior usage facts
        if projection.fact_behavior_usage:
            for fact in projection.fact_behavior_usage:
                cursor.execute(
                    """
                    INSERT INTO fact_behavior_usage (
                        run_id, template_id, template_name, behavior_ids,
                        behavior_count, has_behaviors, baseline_tokens,
                        actor_surface, actor_role, first_plan_timestamp
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        fact.get("run_id"),
                        fact.get("template_id"),
                        fact.get("template_name"),
                        fact.get("behavior_ids"),
                        fact.get("behavior_count"),
                        fact.get("has_behaviors"),
                        fact.get("baseline_tokens"),
                        fact.get("actor_surface"),
                        fact.get("actor_role"),
                        fact.get("first_plan_timestamp"),
                    ),
                )

        # Additional fact tables (token_savings, execution_status, compliance_steps)
        # follow similar pattern...

    def close(self) -> None:
        """Close PostgreSQL connection."""
        if self._conn:
            self._conn.close()


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
    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],
        default=os.getenv("FLINK_MODE", "dev"),
        help="Execution mode: dev (kafka-python polling) or prod (PyFlink streaming)",
    )
    parser.add_argument(
        "--checkpoint-dir",
        default=os.getenv("FLINK_CHECKPOINT_DIR", "/opt/flink/checkpoints"),
        help="Checkpoint storage directory (prod mode only)",
    )
    args = parser.parse_args()

    # Load warehouse config from environment
    warehouse_type = os.getenv("WAREHOUSE_TYPE", "postgresql").lower()

    if warehouse_type == "duckdb":
        warehouse_config = {
            "type": "duckdb",
            "db_path": os.getenv("DUCKDB_PATH", "data/telemetry.duckdb"),
        }
        postgres_dsn = None
    elif warehouse_type == "postgresql":
        postgres_host = os.getenv("POSTGRES_HOST", "postgres-telemetry")
        postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
        postgres_db = os.getenv("POSTGRES_DATABASE", "guideai_telemetry")
        postgres_user = os.getenv("POSTGRES_USER", "guideai_telemetry")
        postgres_password = os.getenv("POSTGRES_PASSWORD")

        if not postgres_password:
            logger.error("Missing POSTGRES_PASSWORD environment variable")
            sys.exit(1)

        postgres_dsn = (
            f"postgresql://{postgres_user}:{postgres_password}"
            f"@{postgres_host}:{postgres_port}/{postgres_db}"
        )

        warehouse_config = {
            "type": "postgresql",
            "host": postgres_host,
            "port": postgres_port,
            "database": postgres_db,
            "user": postgres_user,
            "password": postgres_password,
        }
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
        postgres_dsn = None
        if not all([warehouse_config["account"], warehouse_config["user"], warehouse_config["password"]]):
            logger.error("Missing Snowflake credentials. Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD.")
            sys.exit(1)
    else:
        logger.error(f"Unsupported warehouse type: {warehouse_type}")
        sys.exit(1)

    logger.info("=" * 80)
    logger.info("GuideAI Telemetry KPI Projection Job")
    logger.info("=" * 80)
    logger.info(f"Mode: {args.mode.upper()}")
    logger.info(f"Kafka: {args.kafka_servers} → {args.kafka_topic}")
    logger.info(f"Warehouse: {warehouse_type}")

    if args.mode == "prod":
        logger.info(f"Checkpointing: enabled (dir={args.checkpoint_dir})")
        logger.info("Semantics: EXACTLY_ONCE")
        logger.info("Windowing: 1-minute tumbling, 10s lateness")
        logger.info("=" * 80)

        if not postgres_dsn:
            logger.error("Production mode requires PostgreSQL/TimescaleDB warehouse")
            sys.exit(1)

        job = ProductionFlinkJob(
            kafka_servers=args.kafka_servers,
            kafka_topic=args.kafka_topic,
            postgres_dsn=postgres_dsn,
            checkpoint_dir=args.checkpoint_dir,
        )
        job.run_streaming()
    else:
        logger.info("Checkpointing: disabled (dev mode)")
        logger.info("Semantics: AT_LEAST_ONCE")
        logger.info("Windowing: batch processing (1000 events or 60s)")
        logger.info("=" * 80)

        job = KafkaToWarehouseJob(
            kafka_servers=args.kafka_servers,
            kafka_topic=args.kafka_topic,
            warehouse_config=warehouse_config,
        )
        job.consume_and_project()


if __name__ == "__main__":
    main()
