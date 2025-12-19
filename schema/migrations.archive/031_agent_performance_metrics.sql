-- Migration 031: Agent Performance Metrics
-- Implements event-driven performance tracking with daily rollups
-- Created: 2025-12-10
-- Purpose: Feature 13.4.6 - Agent performance metrics for task completion, token efficiency, behavior reuse

-- =============================================================================
-- Cleanup (for idempotent re-runs)
-- =============================================================================
-- Drop objects in reverse dependency order to handle partial migrations

-- Remove retention/refresh policies first (ignore errors if objects don't exist)
DO $$
BEGIN
    PERFORM remove_retention_policy('agent_performance_snapshots', if_exists => TRUE);
EXCEPTION WHEN undefined_table OR undefined_object THEN
    NULL;  -- Ignore - table doesn't exist
END $$;

DO $$
BEGIN
    PERFORM remove_continuous_aggregate_policy('agent_performance_hourly', if_not_exists => TRUE);
EXCEPTION WHEN undefined_table OR undefined_object THEN
    NULL;  -- Ignore - view doesn't exist
END $$;

-- Drop continuous aggregates and materialized views (or any object with that name)
-- Each wrapped in DO block because IF EXISTS doesn't properly handle type mismatches
DO $$
BEGIN
    EXECUTE 'DROP MATERIALIZED VIEW agent_performance_hourly CASCADE';
EXCEPTION WHEN undefined_table THEN
    NULL;  -- Object doesn't exist
WHEN wrong_object_type THEN
    NULL;  -- Not a materialized view, try other types
WHEN OTHERS THEN
    NULL;  -- Ignore any other errors
END $$;

DO $$
BEGIN
    EXECUTE 'DROP VIEW agent_performance_hourly CASCADE';
EXCEPTION WHEN undefined_table THEN
    NULL;
WHEN wrong_object_type THEN
    NULL;
WHEN OTHERS THEN
    NULL;
END $$;

DO $$
BEGIN
    EXECUTE 'DROP TABLE agent_performance_hourly CASCADE';
EXCEPTION WHEN undefined_table THEN
    NULL;
WHEN wrong_object_type THEN
    NULL;
WHEN OTHERS THEN
    NULL;
END $$;

-- Drop tables
DROP TABLE IF EXISTS agent_performance_alerts CASCADE;
DROP TABLE IF EXISTS agent_performance_daily CASCADE;
DROP TABLE IF EXISTS agent_performance_thresholds CASCADE;
DROP TABLE IF EXISTS agent_performance_snapshots CASCADE;

-- Drop types (if exist)
DROP TYPE IF EXISTS performance_alert_severity CASCADE;
DROP TYPE IF EXISTS performance_metric_type CASCADE;

-- =============================================================================
-- ENUM Types
-- =============================================================================

-- Alert severity levels
CREATE TYPE performance_alert_severity AS ENUM (
    'info',
    'warning',
    'critical'
);

-- Alert metric types
CREATE TYPE performance_metric_type AS ENUM (
    'success_rate',
    'token_efficiency',
    'behavior_reuse',
    'compliance_coverage',
    'avg_task_duration',
    'utilization'
);

-- =============================================================================
-- Agent Performance Snapshots (Event-Driven - TimescaleDB Hypertable)
-- =============================================================================
-- Records individual task completion events for granular analysis
-- Retention: 90 days detailed

CREATE TABLE IF NOT EXISTS agent_performance_snapshots (
    snapshot_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    snapshot_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_id TEXT NOT NULL,
    org_id TEXT,

    -- Task context
    run_id TEXT,
    task_id TEXT,
    project_id TEXT,

    -- Task metrics (event-driven)
    task_completed BOOLEAN NOT NULL DEFAULT FALSE,
    task_success BOOLEAN NOT NULL DEFAULT FALSE,
    task_duration_ms BIGINT,

    -- Token metrics
    tokens_used BIGINT NOT NULL DEFAULT 0,
    baseline_tokens BIGINT NOT NULL DEFAULT 0,
    token_savings_pct DECIMAL(5,2),

    -- Behavior metrics
    behaviors_cited INTEGER NOT NULL DEFAULT 0,
    unique_behaviors TEXT[] DEFAULT '{}',

    -- Compliance metrics
    compliance_checks_passed INTEGER NOT NULL DEFAULT 0,
    compliance_checks_total INTEGER NOT NULL DEFAULT 0,

    -- Status transition tracking
    status_from TEXT,
    status_to TEXT,
    time_in_status_ms BIGINT,

    -- Metadata
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    PRIMARY KEY (snapshot_id, snapshot_time)
);

-- Convert to TimescaleDB hypertable
SELECT create_hypertable('agent_performance_snapshots', 'snapshot_time',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_perf_snap_agent_id ON agent_performance_snapshots (agent_id, snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_perf_snap_org_id ON agent_performance_snapshots (org_id, snapshot_time DESC) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_perf_snap_run_id ON agent_performance_snapshots (run_id) WHERE run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_perf_snap_project_id ON agent_performance_snapshots (project_id, snapshot_time DESC) WHERE project_id IS NOT NULL;

-- =============================================================================
-- Agent Performance Daily Rollups (Aggregated)
-- =============================================================================
-- Pre-computed daily aggregates for dashboard queries
-- Retention: 1 year aggregated

CREATE TABLE IF NOT EXISTS agent_performance_daily (
    rollup_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    rollup_date DATE NOT NULL,
    agent_id TEXT NOT NULL,
    org_id TEXT,
    project_id TEXT,

    -- Task metrics (aggregated)
    tasks_completed INTEGER NOT NULL DEFAULT 0,
    tasks_failed INTEGER NOT NULL DEFAULT 0,
    tasks_total INTEGER NOT NULL DEFAULT 0,
    success_rate_pct DECIMAL(5,2),

    -- Time metrics (aggregated)
    avg_task_duration_ms BIGINT,
    min_task_duration_ms BIGINT,
    max_task_duration_ms BIGINT,
    total_execution_time_ms BIGINT NOT NULL DEFAULT 0,

    -- Token metrics (aggregated)
    total_tokens_used BIGINT NOT NULL DEFAULT 0,
    total_baseline_tokens BIGINT NOT NULL DEFAULT 0,
    avg_token_savings_pct DECIMAL(5,2),

    -- Behavior metrics (aggregated)
    total_behaviors_cited INTEGER NOT NULL DEFAULT 0,
    unique_behaviors_count INTEGER NOT NULL DEFAULT 0,
    behavior_reuse_rate_pct DECIMAL(5,2),

    -- Compliance metrics (aggregated)
    compliance_checks_passed INTEGER NOT NULL DEFAULT 0,
    compliance_checks_total INTEGER NOT NULL DEFAULT 0,
    compliance_coverage_pct DECIMAL(5,2),

    -- Utilization metrics
    time_busy_ms BIGINT NOT NULL DEFAULT 0,
    time_idle_ms BIGINT NOT NULL DEFAULT 0,
    time_paused_ms BIGINT NOT NULL DEFAULT 0,
    utilization_pct DECIMAL(5,2),

    -- Assignment metrics
    switch_count INTEGER NOT NULL DEFAULT 0,
    assignments_count INTEGER NOT NULL DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (rollup_date, agent_id)
);

-- Indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_perf_daily_agent_date ON agent_performance_daily (agent_id, rollup_date DESC);
CREATE INDEX IF NOT EXISTS idx_perf_daily_org_date ON agent_performance_daily (org_id, rollup_date DESC) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_perf_daily_project_date ON agent_performance_daily (project_id, rollup_date DESC) WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_perf_daily_success_rate ON agent_performance_daily (success_rate_pct DESC) WHERE success_rate_pct IS NOT NULL;

-- =============================================================================
-- Agent Performance Alerts
-- =============================================================================
-- Tracks when agents cross performance thresholds

CREATE TABLE IF NOT EXISTS agent_performance_alerts (
    alert_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_id TEXT NOT NULL,
    org_id TEXT,

    -- Alert details
    metric_type performance_metric_type NOT NULL,
    severity performance_alert_severity NOT NULL,
    current_value DECIMAL(10,2) NOT NULL,
    threshold_value DECIMAL(10,2) NOT NULL,
    threshold_direction TEXT NOT NULL,  -- 'below' or 'above'

    -- Context
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,

    -- Resolution
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,

    -- Metadata
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    PRIMARY KEY (alert_id)
);

CREATE INDEX IF NOT EXISTS idx_perf_alerts_agent ON agent_performance_alerts (agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_perf_alerts_unresolved ON agent_performance_alerts (agent_id, severity) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_perf_alerts_org ON agent_performance_alerts (org_id, created_at DESC) WHERE org_id IS NOT NULL;

-- =============================================================================
-- Performance Thresholds Configuration
-- =============================================================================
-- Configurable thresholds per org/agent (defaults + overrides)

CREATE TABLE IF NOT EXISTS agent_performance_thresholds (
    threshold_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    org_id TEXT,                        -- NULL = global default
    agent_id TEXT,                      -- NULL = org-wide default

    -- Threshold values (PRD-aligned defaults)
    success_rate_warning DECIMAL(5,2) NOT NULL DEFAULT 70.00,
    success_rate_critical DECIMAL(5,2) NOT NULL DEFAULT 60.00,

    token_savings_warning DECIMAL(5,2) NOT NULL DEFAULT 20.00,
    token_savings_critical DECIMAL(5,2) NOT NULL DEFAULT 10.00,

    behavior_reuse_warning DECIMAL(5,2) NOT NULL DEFAULT 60.00,
    behavior_reuse_critical DECIMAL(5,2) NOT NULL DEFAULT 40.00,

    compliance_coverage_warning DECIMAL(5,2) NOT NULL DEFAULT 90.00,
    compliance_coverage_critical DECIMAL(5,2) NOT NULL DEFAULT 80.00,

    avg_duration_warning_ms BIGINT NOT NULL DEFAULT 300000,     -- 5 min
    avg_duration_critical_ms BIGINT NOT NULL DEFAULT 600000,    -- 10 min

    utilization_low_warning DECIMAL(5,2) NOT NULL DEFAULT 20.00,
    utilization_high_warning DECIMAL(5,2) NOT NULL DEFAULT 90.00,

    -- Evaluation settings
    evaluation_window_hours INTEGER NOT NULL DEFAULT 24,
    min_sample_size INTEGER NOT NULL DEFAULT 5,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT,

    PRIMARY KEY (threshold_id),
    UNIQUE (org_id, agent_id)
);

-- Default global thresholds (insert if not exists)
INSERT INTO agent_performance_thresholds (org_id, agent_id, created_by)
VALUES (NULL, NULL, 'system')
ON CONFLICT (org_id, agent_id) DO NOTHING;

-- =============================================================================
-- Continuous Aggregates for TimescaleDB (Hourly Rollups)
-- =============================================================================

-- Hourly aggregates for real-time dashboards
CREATE MATERIALIZED VIEW IF NOT EXISTS agent_performance_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', snapshot_time) AS bucket,
    agent_id,
    org_id,
    project_id,
    COUNT(*) FILTER (WHERE task_completed = TRUE) AS tasks_completed,
    COUNT(*) FILTER (WHERE task_completed = TRUE AND task_success = FALSE) AS tasks_failed,
    COUNT(*) FILTER (WHERE task_completed = TRUE AND task_success = TRUE) AS tasks_succeeded,
    AVG(task_duration_ms) FILTER (WHERE task_duration_ms IS NOT NULL) AS avg_duration_ms,
    SUM(tokens_used) AS total_tokens,
    SUM(baseline_tokens) AS total_baseline_tokens,
    SUM(behaviors_cited) AS total_behaviors_cited,
    SUM(compliance_checks_passed) AS compliance_passed,
    SUM(compliance_checks_total) AS compliance_total,
    SUM(time_in_status_ms) FILTER (WHERE status_to = 'BUSY') AS time_busy_ms,
    SUM(time_in_status_ms) FILTER (WHERE status_to = 'IDLE') AS time_idle_ms
FROM agent_performance_snapshots
GROUP BY bucket, agent_id, org_id, project_id
WITH NO DATA;

-- Refresh policy for continuous aggregate (every 5 minutes)
SELECT add_continuous_aggregate_policy('agent_performance_hourly',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);

-- =============================================================================
-- Retention Policies
-- =============================================================================

-- 90 days retention for detailed snapshots
SELECT add_retention_policy('agent_performance_snapshots', INTERVAL '90 days', if_not_exists => TRUE);

-- 1 year retention for daily rollups (handled by application, not hypertable)
-- Daily rollups are regular table, cleanup via scheduled job

-- =============================================================================
-- Helper Functions
-- =============================================================================

-- Function to calculate success rate
CREATE OR REPLACE FUNCTION calc_success_rate(succeeded INTEGER, total INTEGER)
RETURNS DECIMAL(5,2) AS $$
BEGIN
    IF total = 0 THEN
        RETURN NULL;
    END IF;
    RETURN ROUND((succeeded::DECIMAL / total::DECIMAL) * 100, 2);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to calculate token savings percentage
CREATE OR REPLACE FUNCTION calc_token_savings(actual BIGINT, baseline BIGINT)
RETURNS DECIMAL(5,2) AS $$
BEGIN
    IF baseline = 0 THEN
        RETURN NULL;
    END IF;
    RETURN ROUND(((baseline - actual)::DECIMAL / baseline::DECIMAL) * 100, 2);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to get effective thresholds for an agent
CREATE OR REPLACE FUNCTION get_agent_thresholds(p_org_id TEXT, p_agent_id TEXT)
RETURNS agent_performance_thresholds AS $$
DECLARE
    result agent_performance_thresholds;
BEGIN
    -- Priority: agent-specific > org-wide > global default
    SELECT * INTO result
    FROM agent_performance_thresholds
    WHERE (org_id = p_org_id AND agent_id = p_agent_id)
       OR (org_id = p_org_id AND agent_id IS NULL)
       OR (org_id IS NULL AND agent_id IS NULL)
    ORDER BY
        CASE WHEN agent_id IS NOT NULL THEN 0 ELSE 1 END,
        CASE WHEN org_id IS NOT NULL THEN 0 ELSE 1 END
    LIMIT 1;

    RETURN result;
END;
$$ LANGUAGE plpgsql STABLE;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE agent_performance_snapshots IS 'Event-driven agent performance tracking (90-day retention)';
COMMENT ON TABLE agent_performance_daily IS 'Pre-computed daily aggregates for dashboard queries (1-year retention)';
COMMENT ON TABLE agent_performance_alerts IS 'Performance threshold alerts for agents';
COMMENT ON TABLE agent_performance_thresholds IS 'Configurable thresholds per org/agent';
-- Note: TimescaleDB continuous aggregates use COMMENT ON VIEW, not MATERIALIZED VIEW
COMMENT ON VIEW agent_performance_hourly IS 'Continuous aggregate for real-time hourly metrics';
