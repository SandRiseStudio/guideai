-- ============================================================================
-- Migration 014: Upgrade Telemetry Warehouse to TimescaleDB
-- ============================================================================
-- Purpose: Convert telemetry_events to hypertable for time-series optimization,
--          add execution traces table, configure compression & retention policies
--
-- Target: postgres-telemetry (port 5432)
-- Database: telemetry
-- User: guideai_telemetry
-- TimescaleDB: 2.23.0+ required
--
-- Run: podman exec -i guideai-postgres-telemetry psql -U guideai_telemetry -d telemetry < schema/migrations/014_create_telemetry_warehouse_timescale.sql
--
-- PRD Alignment:
-- - TELEMETRY_SCHEMA.md: Time-series storage with 90-day hot retention
-- - Phase 5: Unified PostgreSQL persistence replacing DuckDB warehouse
-- - PRD metrics support: 70% behavior reuse, 30% token savings, 80% completion, 95% compliance
-- ============================================================================

BEGIN;

-- Enable TimescaleDB extension (creates hypertables with time-based partitioning)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- Step 1.0: Ensure base table exists (for fresh installs)
-- ============================================================================
CREATE TABLE IF NOT EXISTS telemetry_events (
    event_id UUID PRIMARY KEY,
    event_timestamp TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    actor_id TEXT,
    actor_role TEXT,
    actor_surface TEXT,
    run_id TEXT,
    action_id TEXT,
    session_id TEXT,
    payload JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Step 1.1: Add composite primary key for time-series partitioning
-- TimescaleDB requires timestamp column in primary key for hypertables

-- Drop existing primary key
ALTER TABLE telemetry_events DROP CONSTRAINT IF EXISTS telemetry_events_pkey;

-- Add new composite primary key (event_id + event_timestamp)
-- Note: event_timestamp used instead of inserted_at for partitioning on actual event time
ALTER TABLE telemetry_events
    ADD CONSTRAINT telemetry_events_pkey PRIMARY KEY (event_id, event_timestamp);

-- Step 1.2: Convert to hypertable with 7-day chunks
-- Chunk interval: 7 days balances query performance with chunk count
SELECT create_hypertable(
    'telemetry_events',
    'event_timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Step 1.3: Add hypertable-compatible indexes
-- Recreate dropped indexes with event_timestamp for partition pruning

-- Event type filtering (common query pattern)
CREATE INDEX IF NOT EXISTS idx_telemetry_events_type_time
    ON telemetry_events (event_type, event_timestamp DESC);

-- Run ID filtering (trace reconstruction)
CREATE INDEX IF NOT EXISTS idx_telemetry_events_run_time
    ON telemetry_events (run_id, event_timestamp DESC)
    WHERE run_id IS NOT NULL;

-- Actor filtering (user activity analysis)
CREATE INDEX IF NOT EXISTS idx_telemetry_events_actor_time
    ON telemetry_events (actor_id, event_timestamp DESC)
    WHERE actor_id IS NOT NULL;

-- Session filtering (session replay)
CREATE INDEX IF NOT EXISTS idx_telemetry_events_session_time
    ON telemetry_events (session_id, event_timestamp DESC)
    WHERE session_id IS NOT NULL;

-- Action ID filtering (action audit trail)
CREATE INDEX IF NOT EXISTS idx_telemetry_events_action_time
    ON telemetry_events (action_id, event_timestamp DESC)
    WHERE action_id IS NOT NULL;

-- GIN index for JSONB payload queries (search within event data)
CREATE INDEX IF NOT EXISTS idx_telemetry_events_payload_gin
    ON telemetry_events USING gin (payload jsonb_path_ops);

COMMENT ON INDEX idx_telemetry_events_type_time IS 'Partition-pruned queries by event type and time range';
COMMENT ON INDEX idx_telemetry_events_run_time IS 'Fast trace reconstruction for specific runs';
COMMENT ON INDEX idx_telemetry_events_actor_time IS 'User activity analysis and filtering';
COMMENT ON INDEX idx_telemetry_events_session_time IS 'Session replay and debugging';
COMMENT ON INDEX idx_telemetry_events_action_time IS 'Action audit trail and compliance';
COMMENT ON INDEX idx_telemetry_events_payload_gin IS 'Fast JSONB path queries within event payloads';

-- Purpose: Store execution traces separate from events for efficient span queries
-- Supports: Distributed tracing, performance analysis, error correlation

-- Drop legacy execution_traces tables that predate trace_timestamp column
DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'execution_traces'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'execution_traces'
          AND column_name = 'trace_timestamp'
    ) THEN
        RAISE NOTICE 'Dropping legacy execution_traces table lacking trace_timestamp column';
        EXECUTE 'DROP TABLE IF EXISTS execution_traces CASCADE';
    END IF;
END
$migration$;

CREATE TABLE IF NOT EXISTS execution_traces (
    trace_id UUID NOT NULL,
    span_id UUID NOT NULL,
    parent_span_id UUID,
    trace_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Execution context
    run_id TEXT,
    action_id TEXT,
    operation_name TEXT NOT NULL,
    service_name TEXT NOT NULL DEFAULT 'guideai',

    -- Timing metrics
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    duration_ms INTEGER GENERATED ALWAYS AS (
        CASE
            WHEN end_time IS NOT NULL
            THEN EXTRACT(MILLISECONDS FROM (end_time - start_time))::INTEGER
            ELSE NULL
        END
    ) STORED,

    -- Status tracking
    status TEXT NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'SUCCESS', 'ERROR', 'TIMEOUT', 'CANCELLED')),
    error_message TEXT,
    error_trace TEXT,

    -- Resource consumption
    token_count INTEGER,
    behavior_citations TEXT[],

    -- Additional context
    attributes JSONB NOT NULL DEFAULT '{}'::JSONB,
    events JSONB[], -- Span events (logs within span)
    links JSONB[], -- Links to other spans

    -- Metadata
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Composite primary key for hypertable partitioning
    PRIMARY KEY (span_id, trace_timestamp),

    -- Foreign key constraint to parent span (optional, can be in different chunk)
    -- Note: Not enforced across chunks for performance
    CONSTRAINT fk_parent_span
        FOREIGN KEY (parent_span_id, trace_timestamp)
        REFERENCES execution_traces(span_id, trace_timestamp)
        ON DELETE SET NULL
        NOT VALID -- Don't validate across chunks
);

-- Convert execution_traces to hypertable
SELECT create_hypertable(
    'execution_traces',
    'trace_timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Indexes for execution_traces
CREATE INDEX IF NOT EXISTS idx_execution_traces_trace_id
    ON execution_traces (trace_id, trace_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_execution_traces_run_id
    ON execution_traces (run_id, trace_timestamp DESC)
    WHERE run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_execution_traces_action_id
    ON execution_traces (action_id, trace_timestamp DESC)
    WHERE action_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_execution_traces_operation
    ON execution_traces (operation_name, trace_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_execution_traces_status
    ON execution_traces (status, trace_timestamp DESC)
    WHERE status IN ('ERROR', 'TIMEOUT', 'CANCELLED');

CREATE INDEX IF NOT EXISTS idx_execution_traces_duration
    ON execution_traces (duration_ms DESC, trace_timestamp DESC)
    WHERE duration_ms IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_execution_traces_attributes_gin
    ON execution_traces USING gin (attributes jsonb_path_ops);

COMMENT ON TABLE execution_traces IS 'Distributed execution traces with span-level granularity for performance analysis';
COMMENT ON COLUMN execution_traces.trace_id IS 'Unique identifier for entire distributed trace (shared across spans)';
COMMENT ON COLUMN execution_traces.span_id IS 'Unique identifier for this specific span/operation';
COMMENT ON COLUMN execution_traces.parent_span_id IS 'Parent span creating causal relationship (NULL for root spans)';
COMMENT ON COLUMN execution_traces.duration_ms IS 'Computed span duration in milliseconds (NULL for in-progress spans)';
COMMENT ON COLUMN execution_traces.behavior_citations IS 'Behaviors referenced during this span execution';
COMMENT ON COLUMN execution_traces.attributes IS 'Arbitrary key-value span attributes (service-specific metadata)';
COMMENT ON COLUMN execution_traces.events IS 'Timestamped events within span (logs, state changes)';
COMMENT ON COLUMN execution_traces.links IS 'Links to causally related spans (cross-trace references)';

-- =========================================================================
-- Section 3: Configure Compression Policies (7-day threshold)
-- ============================================================================

-- Compress chunks older than 7 days for 3-5x storage reduction
-- Queries on compressed chunks remain fast with segment-level metadata

-- Step 3.1: Enable compression on hypertables
ALTER TABLE telemetry_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'event_type, actor_role',
    timescaledb.compress_orderby = 'event_timestamp DESC'
);

ALTER TABLE execution_traces SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'operation_name, status',
    timescaledb.compress_orderby = 'trace_timestamp DESC'
);

-- Step 3.2: Add compression policies (automatic background compression)
SELECT add_compression_policy(
    'telemetry_events',
    compress_after => INTERVAL '7 days',
    if_not_exists => TRUE
);

SELECT add_compression_policy(
    'execution_traces',
    compress_after => INTERVAL '7 days',
    if_not_exists => TRUE
);

COMMENT ON TABLE telemetry_events IS 'TimescaleDB hypertable: Event-based telemetry with 7-day compression threshold';
COMMENT ON TABLE execution_traces IS 'TimescaleDB hypertable: Distributed execution traces with 7-day compression threshold';

-- =========================================================================
-- Section 4: Configure Retention Policies (90-day hot, 1-year archive)
-- ============================================================================

-- Hot retention: 90 days (aligned with TELEMETRY_SCHEMA.md requirements)
-- After 90 days, data should be archived to cold storage or dropped

-- Retention for telemetry_events (90 days)
SELECT add_retention_policy(
    'telemetry_events',
    drop_after => INTERVAL '90 days',
    if_not_exists => TRUE
);

-- Retention for execution_traces (90 days)
SELECT add_retention_policy(
    'execution_traces',
    drop_after => INTERVAL '90 days',
    if_not_exists => TRUE
);

-- =========================================================================
-- Section 5: Create Continuous Aggregates for Dashboard Performance
-- ============================================================================

-- Continuous aggregate: Hourly event summary (pre-computed materialized view)
-- Refreshed automatically every 10 minutes, dramatically speeds up dashboard queries

DROP MATERIALIZED VIEW IF EXISTS telemetry_events_hourly;

CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_events_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', event_timestamp) AS bucket,
    event_type,
    actor_role,
    actor_surface,
    COUNT(*) AS event_count,
    COUNT(DISTINCT actor_id) AS unique_actors,
    COUNT(DISTINCT run_id) AS unique_runs,
    COUNT(DISTINCT session_id) AS unique_sessions
FROM telemetry_events
GROUP BY bucket, event_type, actor_role, actor_surface
WITH NO DATA;

-- Refresh policy: Update hourly aggregate every 10 minutes for near real-time dashboards
SELECT add_continuous_aggregate_policy(
    'telemetry_events_hourly',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '10 minutes',
    if_not_exists => TRUE
);

-- Continuous aggregate: Hourly trace performance (span-level metrics)
DROP MATERIALIZED VIEW IF EXISTS execution_traces_hourly;

CREATE MATERIALIZED VIEW IF NOT EXISTS execution_traces_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', trace_timestamp) AS bucket,
    operation_name,
    service_name,
    status,
    COUNT(*) AS span_count,
    AVG(duration_ms)::INTEGER AS avg_duration_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms)::INTEGER AS p50_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::INTEGER AS p95_duration_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms)::INTEGER AS p99_duration_ms,
    MAX(duration_ms) AS max_duration_ms,
    SUM(token_count) AS total_tokens
FROM execution_traces
WHERE duration_ms IS NOT NULL
GROUP BY bucket, operation_name, service_name, status
WITH NO DATA;

-- Refresh policy: Update hourly trace aggregate every 10 minutes
SELECT add_continuous_aggregate_policy(
    'execution_traces_hourly',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '10 minutes',
    if_not_exists => TRUE
);

-- Continuous aggregate: Daily summary for long-term trend analysis
DROP MATERIALIZED VIEW IF EXISTS telemetry_events_daily;

CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_events_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', event_timestamp) AS bucket,
    event_type,
    COUNT(*) AS event_count,
    COUNT(DISTINCT actor_id) AS unique_actors,
    COUNT(DISTINCT run_id) AS unique_runs
FROM telemetry_events
GROUP BY bucket, event_type
WITH NO DATA;

-- Refresh policy: Update daily aggregate every hour
SELECT add_continuous_aggregate_policy(
    'telemetry_events_daily',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- =========================================================================
-- Section 6: Create Helper Views for Common Dashboard Queries
-- ============================================================================

-- View: Recent events (last 7 days, uncompressed chunks only)
CREATE OR REPLACE VIEW recent_telemetry_events AS
SELECT
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
FROM telemetry_events
WHERE event_timestamp >= now() - INTERVAL '7 days'
ORDER BY event_timestamp DESC;

-- View: Error traces for incident response
CREATE OR REPLACE VIEW error_traces AS
SELECT
    trace_id,
    span_id,
    parent_span_id,
    trace_timestamp,
    run_id,
    action_id,
    operation_name,
    service_name,
    start_time,
    end_time,
    duration_ms,
    error_message,
    error_trace,
    attributes
FROM execution_traces
WHERE status IN ('ERROR', 'TIMEOUT', 'CANCELLED')
    AND trace_timestamp >= now() - INTERVAL '7 days'
ORDER BY trace_timestamp DESC;

-- View: Slow traces (P99+ latency)
CREATE OR REPLACE VIEW slow_traces AS
SELECT
    trace_id,
    span_id,
    operation_name,
    service_name,
    start_time,
    end_time,
    duration_ms,
    status,
    token_count,
    behavior_citations,
    attributes
FROM execution_traces
WHERE duration_ms >= (
    SELECT PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms)
    FROM execution_traces
    WHERE trace_timestamp >= now() - INTERVAL '1 day'
        AND duration_ms IS NOT NULL
)
AND trace_timestamp >= now() - INTERVAL '7 days'
ORDER BY duration_ms DESC;

-- =========================================================================
-- Section 7: Grant Permissions (conditional - only if role exists)
-- ============================================================================

-- Grant permissions only if guideai_telemetry role exists (production)
-- In test environments, the connecting user already owns the tables
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'guideai_telemetry') THEN
        -- Grant SELECT on all tables/views to telemetry user
        GRANT SELECT ON telemetry_events TO guideai_telemetry;
        GRANT SELECT ON execution_traces TO guideai_telemetry;
        GRANT SELECT ON telemetry_events_hourly TO guideai_telemetry;
        GRANT SELECT ON execution_traces_hourly TO guideai_telemetry;
        GRANT SELECT ON telemetry_events_daily TO guideai_telemetry;
        GRANT SELECT ON recent_telemetry_events TO guideai_telemetry;
        GRANT SELECT ON error_traces TO guideai_telemetry;
        GRANT SELECT ON slow_traces TO guideai_telemetry;

        -- Grant INSERT for data ingestion
        GRANT INSERT ON telemetry_events TO guideai_telemetry;
        GRANT INSERT ON execution_traces TO guideai_telemetry;

        -- Grant UPDATE for span completion (end_time updates)
        GRANT UPDATE ON execution_traces TO guideai_telemetry;

        RAISE NOTICE 'Permissions granted to guideai_telemetry role';
    ELSE
        RAISE NOTICE 'Role guideai_telemetry does not exist - skipping GRANT statements (test environment)';
    END IF;
END
$$;

-- =========================================================================
-- Section 8: Validation Queries
-- ============================================================================

-- Verify hypertables created
SELECT
    hypertable_name,
    num_chunks,
    compression_enabled
FROM timescaledb_information.hypertables
WHERE hypertable_name IN ('telemetry_events', 'execution_traces');

-- Verify compression policies exist
SELECT
    application_name,
    job_id,
    config
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_compression';

-- Verify retention policies exist
SELECT
    application_name,
    job_id,
    config
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_retention';

-- Verify continuous aggregates exist
SELECT
    view_name,
    materialized_only
FROM timescaledb_information.continuous_aggregates;

-- Verify indexes
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN ('telemetry_events', 'execution_traces')
ORDER BY tablename, indexname;

COMMIT;

-- =========================================================================
-- Migration Complete
-- =========================================================================
-- Next Steps:
-- 1. Update guideai/telemetry_postgres.py to use execution_traces table
-- 2. Configure Metabase dashboards to query continuous aggregates
-- 3. Migrate historical DuckDB data via scripts/migrate_telemetry_duckdb_to_postgres.py
-- 4. Update TELEMETRY_SCHEMA.md with TimescaleDB architecture details
-- ============================================================================
