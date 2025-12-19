-- guideAI Telemetry Warehouse (PostgreSQL)
-- Implements append-only telemetry event storage, fact tables used by the
-- PRD metrics dashboards, and helper functions for refreshing materialized
-- views that expose the four headline KPIs.

-- 1. Base event log -------------------------------------------------------
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

CREATE INDEX IF NOT EXISTS idx_telemetry_events_event_type
    ON telemetry_events (event_type);
CREATE INDEX IF NOT EXISTS idx_telemetry_events_run_id
    ON telemetry_events (run_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_events_inserted_at
    ON telemetry_events (inserted_at DESC);

-- 2. Fact tables ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_behavior_usage (
    run_id TEXT PRIMARY KEY,
    template_id TEXT,
    template_name TEXT,
    behavior_ids JSONB,
    behavior_count INTEGER NOT NULL DEFAULT 0,
    has_behaviors BOOLEAN NOT NULL DEFAULT FALSE,
    baseline_tokens INTEGER,
    actor_surface TEXT,
    actor_role TEXT,
    first_plan_timestamp TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_fact_behavior_usage_template_id
    ON fact_behavior_usage (template_id);
CREATE INDEX IF NOT EXISTS idx_fact_behavior_usage_actor_role
    ON fact_behavior_usage (actor_role);
CREATE INDEX IF NOT EXISTS idx_fact_behavior_usage_first_plan_timestamp
    ON fact_behavior_usage (first_plan_timestamp DESC);

CREATE TABLE IF NOT EXISTS fact_execution_status (
    run_id TEXT PRIMARY KEY,
    template_id TEXT,
    status TEXT,
    actor_surface TEXT,
    actor_role TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fact_execution_status_template_id
    ON fact_execution_status (template_id);
CREATE INDEX IF NOT EXISTS idx_fact_execution_status_status
    ON fact_execution_status (status);
CREATE INDEX IF NOT EXISTS idx_fact_execution_status_actor_role
    ON fact_execution_status (actor_role);

CREATE TABLE IF NOT EXISTS fact_token_savings (
    run_id TEXT PRIMARY KEY,
    template_id TEXT,
    output_tokens INTEGER,
    baseline_tokens INTEGER,
    token_savings_pct DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_fact_token_savings_template_id
    ON fact_token_savings (template_id);
CREATE INDEX IF NOT EXISTS idx_fact_token_savings_pct
    ON fact_token_savings (token_savings_pct);

CREATE TABLE IF NOT EXISTS fact_compliance_steps (
    id BIGSERIAL PRIMARY KEY,
    checklist_id TEXT,
    step_id TEXT,
    status TEXT,
    coverage_score DOUBLE PRECISION,
    run_id TEXT,
    session_id TEXT,
    behavior_ids JSONB,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fact_compliance_steps_run_id
    ON fact_compliance_steps (run_id);
CREATE INDEX IF NOT EXISTS idx_fact_compliance_steps_status
    ON fact_compliance_steps (status);
CREATE INDEX IF NOT EXISTS idx_fact_compliance_steps_timestamp
    ON fact_compliance_steps (event_timestamp DESC);

-- 3. Materialized views for PRD metrics ----------------------------------
DROP MATERIALIZED VIEW IF EXISTS mv_behavior_reuse_rate;
CREATE MATERIALIZED VIEW mv_behavior_reuse_rate AS
SELECT
    COALESCE(
        (COUNT(DISTINCT CASE WHEN has_behaviors THEN run_id END)::DOUBLE PRECISION * 100.0)
        / NULLIF(COUNT(DISTINCT run_id), 0),
        0.0
    ) AS reuse_rate_pct,
    COUNT(DISTINCT run_id) AS total_runs,
    COUNT(DISTINCT CASE WHEN has_behaviors THEN run_id END) AS runs_with_behaviors
FROM fact_behavior_usage;

DROP MATERIALIZED VIEW IF EXISTS mv_token_savings_rate;
CREATE MATERIALIZED VIEW mv_token_savings_rate AS
SELECT
    AVG(token_savings_pct) AS avg_savings_rate_pct,
    COUNT(*) AS total_runs,
    SUM(baseline_tokens) AS total_baseline_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(baseline_tokens - output_tokens) AS total_tokens_saved
FROM fact_token_savings
WHERE token_savings_pct IS NOT NULL;

DROP MATERIALIZED VIEW IF EXISTS mv_completion_rate;
CREATE MATERIALIZED VIEW mv_completion_rate AS
SELECT
    COALESCE(
        (COUNT(DISTINCT CASE WHEN status = 'COMPLETED' THEN run_id END)::DOUBLE PRECISION * 100.0)
        / NULLIF(COUNT(DISTINCT run_id), 0),
        0.0
    ) AS completion_rate_pct,
    COUNT(DISTINCT run_id) AS total_runs,
    COUNT(DISTINCT CASE WHEN status = 'COMPLETED' THEN run_id END) AS completed_runs,
    COUNT(DISTINCT CASE WHEN status = 'FAILED' THEN run_id END) AS failed_runs,
    COUNT(DISTINCT CASE WHEN status = 'CANCELLED' THEN run_id END) AS cancelled_runs
FROM fact_execution_status;

DROP MATERIALIZED VIEW IF EXISTS mv_compliance_coverage_rate;
CREATE MATERIALIZED VIEW mv_compliance_coverage_rate AS
SELECT
    AVG(coverage_score) * 100 AS avg_coverage_rate_pct,
    COUNT(DISTINCT run_id) AS total_runs,
    COUNT(*) AS total_compliance_events,
    COUNT(CASE WHEN coverage_score >= 0.95 THEN 1 END) AS runs_above_95pct
FROM fact_compliance_steps
WHERE coverage_score IS NOT NULL;

-- 4. Helper function for refreshing metric views -------------------------
CREATE OR REPLACE FUNCTION refresh_prd_metric_views()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW mv_behavior_reuse_rate;
    REFRESH MATERIALIZED VIEW mv_token_savings_rate;
    REFRESH MATERIALIZED VIEW mv_completion_rate;
    REFRESH MATERIALIZED VIEW mv_compliance_coverage_rate;
END;
$$;
