-- Migration 012: MetricsService PostgreSQL/TimescaleDB schema
-- Implements time-series storage for PRD success metrics tracking
-- Created: 2025-10-29
-- Purpose: Real-time metrics aggregation with historical trend analysis for PRD KPIs

-- Enable TimescaleDB extension (creates hypertables with time-based partitioning)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- Table 1: Metrics Snapshots (Hypertable)
-- Purpose: Store point-in-time KPI summaries for dashboard consumption
-- PRD Targets: 70% behavior reuse, 30% token savings, 80% completion, 95% compliance
-- ============================================================================

CREATE TABLE IF NOT EXISTS metrics_snapshots (
    snapshot_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    snapshot_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- PRD Success Metric 1: Behavior Reuse Rate (Target: 70%)
    behavior_reuse_pct DECIMAL(5,2) NOT NULL DEFAULT 0.0 CHECK (behavior_reuse_pct >= 0 AND behavior_reuse_pct <= 100),
    total_runs INTEGER NOT NULL DEFAULT 0,
    runs_with_behaviors INTEGER NOT NULL DEFAULT 0,

    -- PRD Success Metric 2: Token Savings (Target: 30%)
    average_token_savings_pct DECIMAL(5,2) NOT NULL DEFAULT 0.0,
    total_baseline_tokens BIGINT NOT NULL DEFAULT 0,
    total_output_tokens BIGINT NOT NULL DEFAULT 0,

    -- PRD Success Metric 3: Task Completion Rate (Target: 80%)
    task_completion_rate_pct DECIMAL(5,2) NOT NULL DEFAULT 0.0 CHECK (task_completion_rate_pct >= 0 AND task_completion_rate_pct <= 100),
    completed_runs INTEGER NOT NULL DEFAULT 0,
    failed_runs INTEGER NOT NULL DEFAULT 0,

    -- PRD Success Metric 4: Compliance Coverage (Target: 95%)
    average_compliance_coverage_pct DECIMAL(5,2) NOT NULL DEFAULT 0.0 CHECK (average_compliance_coverage_pct >= 0 AND average_compliance_coverage_pct <= 100),
    total_compliance_events INTEGER NOT NULL DEFAULT 0,

    -- Aggregation window metadata
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    aggregation_type TEXT CHECK (aggregation_type IN ('realtime', 'hourly', 'daily', 'weekly', 'monthly')),

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Composite primary key including partitioning column (required by TimescaleDB)
    PRIMARY KEY (snapshot_id, snapshot_time)
);

-- Convert to hypertable (time-series partitioning on snapshot_time)
SELECT create_hypertable('metrics_snapshots', 'snapshot_time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Compression policy: compress chunks older than 7 days (reduce storage by ~80%)
ALTER TABLE metrics_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'aggregation_type',
    timescaledb.compress_orderby = 'snapshot_time DESC'
);

SELECT add_compression_policy('metrics_snapshots', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention policy: drop chunks older than 1 year (configurable for compliance)
SELECT add_retention_policy('metrics_snapshots', INTERVAL '1 year', if_not_exists => TRUE);

-- ============================================================================
-- Table 2: Behavior Usage Events (Hypertable)
-- Purpose: Track per-run behavior citations for reuse rate calculation
-- ============================================================================

CREATE TABLE IF NOT EXISTS behavior_usage_events (
    event_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Run linkage
    run_id TEXT NOT NULL,

    -- Behavior citation details
    behavior_id TEXT NOT NULL,
    behavior_version TEXT,
    citation_count INTEGER NOT NULL DEFAULT 1,

    -- Context
    actor_id TEXT,
    actor_role TEXT,
    surface TEXT CHECK (surface IN ('cli', 'api', 'mcp', 'web')),

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Composite primary key including partitioning column
    PRIMARY KEY (event_id, event_time)
);

SELECT create_hypertable('behavior_usage_events', 'event_time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

ALTER TABLE behavior_usage_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'run_id, behavior_id',
    timescaledb.compress_orderby = 'event_time DESC'
);

SELECT add_compression_policy('behavior_usage_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('behavior_usage_events', INTERVAL '1 year', if_not_exists => TRUE);

-- ============================================================================
-- Table 3: Token Usage Events (Hypertable)
-- Purpose: Track baseline vs actual token consumption for savings calculation
-- ============================================================================

CREATE TABLE IF NOT EXISTS token_usage_events (
    event_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Run linkage
    run_id TEXT NOT NULL,

    -- Token measurements
    baseline_tokens INTEGER NOT NULL CHECK (baseline_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    token_savings_pct DECIMAL(5,2) NOT NULL DEFAULT 0.0,

    -- BCI metadata
    bci_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    behavior_count INTEGER NOT NULL DEFAULT 0,

    -- Context
    actor_id TEXT,
    surface TEXT CHECK (surface IN ('cli', 'api', 'mcp', 'web')),

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Composite primary key including partitioning column
    PRIMARY KEY (event_id, event_time)
);

SELECT create_hypertable('token_usage_events', 'event_time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

ALTER TABLE token_usage_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'run_id',
    timescaledb.compress_orderby = 'event_time DESC'
);

SELECT add_compression_policy('token_usage_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('token_usage_events', INTERVAL '1 year', if_not_exists => TRUE);

-- ============================================================================
-- Table 4: Completion Events (Hypertable)
-- Purpose: Track run completion status for success rate calculation
-- ============================================================================

CREATE TABLE IF NOT EXISTS completion_events (
    event_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Run linkage
    run_id TEXT NOT NULL,

    -- Completion status
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FAILED', 'CANCELLED', 'TIMEOUT')),
    duration_seconds INTEGER CHECK (duration_seconds >= 0),

    -- Context
    actor_id TEXT,
    surface TEXT CHECK (surface IN ('cli', 'api', 'mcp', 'web')),

    -- Failure details (if applicable)
    error_type TEXT,
    error_message TEXT,

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Composite primary key including partitioning column
    PRIMARY KEY (event_id, event_time)
);

SELECT create_hypertable('completion_events', 'event_time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

ALTER TABLE completion_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'run_id, status',
    timescaledb.compress_orderby = 'event_time DESC'
);

SELECT add_compression_policy('completion_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('completion_events', INTERVAL '1 year', if_not_exists => TRUE);

-- ============================================================================
-- Table 5: Compliance Events (Hypertable)
-- Purpose: Track checklist coverage for compliance metric calculation
-- ============================================================================

CREATE TABLE IF NOT EXISTS compliance_events (
    event_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Run/checklist linkage
    run_id TEXT NOT NULL,
    checklist_id TEXT NOT NULL,

    -- Coverage measurement
    coverage_score DECIMAL(5,2) NOT NULL CHECK (coverage_score >= 0 AND coverage_score <= 100),
    total_steps INTEGER NOT NULL CHECK (total_steps > 0),
    completed_steps INTEGER NOT NULL CHECK (completed_steps >= 0),

    -- Context
    actor_id TEXT,
    surface TEXT CHECK (surface IN ('cli', 'api', 'mcp', 'web')),

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Composite primary key including partitioning column
    PRIMARY KEY (event_id, event_time)
);

SELECT create_hypertable('compliance_events', 'event_time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

ALTER TABLE compliance_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'run_id, checklist_id',
    timescaledb.compress_orderby = 'event_time DESC'
);

SELECT add_compression_policy('compliance_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('compliance_events', INTERVAL '1 year', if_not_exists => TRUE);

-- ============================================================================
-- Indexes for common query patterns
-- ============================================================================

-- Metrics snapshots: query by time window and aggregation type
CREATE INDEX IF NOT EXISTS idx_metrics_snapshots_time_agg ON metrics_snapshots (snapshot_time DESC, aggregation_type);
CREATE INDEX IF NOT EXISTS idx_metrics_snapshots_window ON metrics_snapshots (window_start, window_end);

-- Behavior usage: query by run_id, behavior_id, time range
CREATE INDEX IF NOT EXISTS idx_behavior_usage_run_id ON behavior_usage_events (run_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_behavior_id ON behavior_usage_events (behavior_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_surface ON behavior_usage_events (surface, event_time DESC);

-- Token usage: query by run_id, bci_enabled, time range
CREATE INDEX IF NOT EXISTS idx_token_usage_run_id ON token_usage_events (run_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_bci ON token_usage_events (bci_enabled, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_surface ON token_usage_events (surface, event_time DESC);

-- Completion: query by status, time range
CREATE INDEX IF NOT EXISTS idx_completion_status ON completion_events (status, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_completion_run_id ON completion_events (run_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_completion_surface ON completion_events (surface, event_time DESC);

-- Compliance: query by run_id, checklist_id, time range
CREATE INDEX IF NOT EXISTS idx_compliance_run_id ON compliance_events (run_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_compliance_checklist ON compliance_events (checklist_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_compliance_surface ON compliance_events (surface, event_time DESC);

-- ============================================================================
-- Continuous Aggregates (Materialized Views for Dashboard Performance)
-- ============================================================================

-- Hourly KPI rollup for dashboard queries (pre-compute expensive aggregations)
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', snapshot_time) AS bucket_time,
    aggregation_type,
    AVG(behavior_reuse_pct) AS avg_behavior_reuse_pct,
    AVG(average_token_savings_pct) AS avg_token_savings_pct,
    AVG(task_completion_rate_pct) AS avg_completion_rate_pct,
    AVG(average_compliance_coverage_pct) AS avg_compliance_coverage_pct,
    SUM(total_runs) AS total_runs,
    SUM(runs_with_behaviors) AS total_runs_with_behaviors,
    SUM(total_baseline_tokens) AS total_baseline_tokens,
    SUM(total_output_tokens) AS total_output_tokens,
    SUM(completed_runs) AS total_completed_runs,
    SUM(failed_runs) AS total_failed_runs,
    SUM(total_compliance_events) AS total_compliance_events
FROM metrics_snapshots
GROUP BY bucket_time, aggregation_type
WITH NO DATA;

-- Refresh policy: update hourly view every 10 minutes
SELECT add_continuous_aggregate_policy('metrics_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '10 minutes',
    if_not_exists => TRUE
);

-- Daily KPI rollup for historical trend analysis
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', snapshot_time) AS bucket_time,
    aggregation_type,
    AVG(behavior_reuse_pct) AS avg_behavior_reuse_pct,
    AVG(average_token_savings_pct) AS avg_token_savings_pct,
    AVG(task_completion_rate_pct) AS avg_completion_rate_pct,
    AVG(average_compliance_coverage_pct) AS avg_compliance_coverage_pct,
    SUM(total_runs) AS total_runs,
    SUM(runs_with_behaviors) AS total_runs_with_behaviors,
    SUM(total_baseline_tokens) AS total_baseline_tokens,
    SUM(total_output_tokens) AS total_output_tokens,
    SUM(completed_runs) AS total_completed_runs,
    SUM(failed_runs) AS total_failed_runs,
    SUM(total_compliance_events) AS total_compliance_events
FROM metrics_snapshots
GROUP BY bucket_time, aggregation_type
WITH NO DATA;

-- Refresh policy: update daily view every hour
SELECT add_continuous_aggregate_policy('metrics_daily',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- ============================================================================
-- Column comments for documentation
-- ============================================================================

COMMENT ON TABLE metrics_snapshots IS 'Time-series KPI snapshots for PRD success metrics (70% behavior reuse, 30% token savings, 80% completion, 95% compliance)';
COMMENT ON TABLE behavior_usage_events IS 'Per-run behavior citations for reuse rate calculation';
COMMENT ON TABLE token_usage_events IS 'Baseline vs actual token consumption for savings calculation';
COMMENT ON TABLE completion_events IS 'Run completion status for success rate calculation';
COMMENT ON TABLE compliance_events IS 'Checklist coverage for compliance metric calculation';

COMMENT ON COLUMN metrics_snapshots.behavior_reuse_pct IS 'Percentage of runs citing ≥1 behavior (PRD target: 70%)';
COMMENT ON COLUMN metrics_snapshots.average_token_savings_pct IS 'Average token reduction via BCI (PRD target: 30%)';
COMMENT ON COLUMN metrics_snapshots.task_completion_rate_pct IS 'Percentage of runs completed successfully (PRD target: 80%)';
COMMENT ON COLUMN metrics_snapshots.average_compliance_coverage_pct IS 'Average checklist coverage (PRD target: 95%)';

COMMENT ON COLUMN behavior_usage_events.citation_count IS 'Number of times behavior was referenced in run output';
COMMENT ON COLUMN token_usage_events.baseline_tokens IS 'Token count without BCI (unconditioned prompt)';
COMMENT ON COLUMN token_usage_events.output_tokens IS 'Actual token count with BCI applied';
COMMENT ON COLUMN token_usage_events.token_savings_pct IS 'Percentage reduction: (baseline - output) / baseline × 100';

COMMENT ON COLUMN completion_events.duration_seconds IS 'Run duration from creation to completion/failure';
COMMENT ON COLUMN compliance_events.coverage_score IS 'Percentage of checklist steps completed (0-100)';
