-- GuideAI PRD Metrics Schema - DuckDB Edition
-- Purpose: Fact tables for measuring PRD success metrics (behavior reuse, token savings, completion rate, compliance coverage)
-- Backend: DuckDB (embedded, zero-cost analytics engine)
-- Phase: Phase 1 Local Development
-- Note: Schema aligned with TelemetryKPIProjector run-level aggregates

-- Fact: Behavior Usage (Run-Level Aggregate)
-- Tracks behavior usage per workflow run
-- Supports: 70% behavior reuse target, behavior retrieval effectiveness
CREATE TABLE IF NOT EXISTS fact_behavior_usage (
    run_id VARCHAR PRIMARY KEY,
    template_id VARCHAR,
    template_name VARCHAR,
    behavior_ids VARCHAR,  -- JSON array of behavior IDs used in run
    behavior_count INTEGER NOT NULL DEFAULT 0,
    has_behaviors BOOLEAN NOT NULL DEFAULT FALSE,
    baseline_tokens INTEGER,
    actor_surface VARCHAR,  -- CLI | WEB | API | MCP
    actor_role VARCHAR,  -- STRATEGIST | TEACHER | STUDENT
    first_plan_timestamp TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_template_id ON fact_behavior_usage(template_id);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_actor_role ON fact_behavior_usage(actor_role);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_first_plan_timestamp ON fact_behavior_usage(first_plan_timestamp);

-- Fact: Execution Status (Run-Level Aggregate)
-- Tracks final execution outcome per workflow run
-- Supports: 80% completion rate target, execution time metrics
CREATE TABLE IF NOT EXISTS fact_execution_status (
    run_id VARCHAR PRIMARY KEY,
    template_id VARCHAR,
    status VARCHAR,  -- COMPLETED | FAILED | CANCELLED | IN_PROGRESS
    actor_surface VARCHAR,
    actor_role VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_execution_status_template_id ON fact_execution_status(template_id);
CREATE INDEX IF NOT EXISTS idx_execution_status_status ON fact_execution_status(status);
CREATE INDEX IF NOT EXISTS idx_execution_status_actor_role ON fact_execution_status(actor_role);

-- Fact: Token Savings (Run-Level Aggregate)
-- Tracks token consumption and savings per workflow run
-- Supports: 30% token savings target
CREATE TABLE IF NOT EXISTS fact_token_savings (
    run_id VARCHAR PRIMARY KEY,
    template_id VARCHAR,
    output_tokens INTEGER,
    baseline_tokens INTEGER,
    token_savings_pct DOUBLE
);
CREATE INDEX IF NOT EXISTS idx_token_savings_template_id ON fact_token_savings(template_id);
CREATE INDEX IF NOT EXISTS idx_token_savings_token_savings_pct ON fact_token_savings(token_savings_pct);

-- Fact: Compliance Steps (Event-Level)
-- Tracks compliance checklist step execution across Web/API/CLI/MCP surfaces
-- Supports: 95% compliance coverage target, audit trail
CREATE TABLE IF NOT EXISTS fact_compliance_steps (
    checklist_id VARCHAR,
    step_id VARCHAR,
    status VARCHAR,
    coverage_score DOUBLE,
    run_id VARCHAR,
    session_id VARCHAR,
    behavior_ids VARCHAR,  -- JSON array of behavior IDs
    timestamp TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_compliance_steps_run_id ON fact_compliance_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_compliance_steps_status ON fact_compliance_steps(status);
CREATE INDEX IF NOT EXISTS idx_compliance_steps_timestamp ON fact_compliance_steps(timestamp);

-- View: Behavior Reuse Rate
-- Calculates percentage of runs that reference at least one behavior
CREATE VIEW IF NOT EXISTS view_behavior_reuse_rate AS
SELECT
    COUNT(DISTINCT CASE WHEN has_behaviors = TRUE THEN run_id END) * 100.0 / NULLIF(COUNT(DISTINCT run_id), 0) AS reuse_rate_pct,
    COUNT(DISTINCT run_id) AS total_runs,
    COUNT(DISTINCT CASE WHEN has_behaviors = TRUE THEN run_id END) AS runs_with_behaviors
FROM fact_behavior_usage;

-- View: Token Savings Rate
-- Calculates average percentage reduction in reasoning tokens when using behaviors
CREATE VIEW IF NOT EXISTS view_token_savings_rate AS
SELECT
    AVG(token_savings_pct) AS avg_savings_rate_pct,
    COUNT(*) AS total_runs,
    SUM(baseline_tokens) AS total_baseline_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(baseline_tokens - output_tokens) AS total_tokens_saved
FROM fact_token_savings
WHERE token_savings_pct IS NOT NULL;

-- View: Completion Rate
-- Calculates percentage of runs that reach 'COMPLETED' status
CREATE VIEW IF NOT EXISTS view_completion_rate AS
SELECT
    COUNT(DISTINCT CASE WHEN status = 'COMPLETED' THEN run_id END) * 100.0 / NULLIF(COUNT(DISTINCT run_id), 0) AS completion_rate_pct,
    COUNT(DISTINCT run_id) AS total_runs,
    COUNT(DISTINCT CASE WHEN status = 'COMPLETED' THEN run_id END) AS completed_runs,
    COUNT(DISTINCT CASE WHEN status = 'FAILED' THEN run_id END) AS failed_runs,
    COUNT(DISTINCT CASE WHEN status = 'CANCELLED' THEN run_id END) AS cancelled_runs
FROM fact_execution_status;

-- View: Compliance Coverage Rate
-- Calculates average compliance coverage score across runs
CREATE VIEW IF NOT EXISTS view_compliance_coverage_rate AS
SELECT
    AVG(coverage_score) * 100 AS avg_coverage_rate_pct,
    COUNT(DISTINCT run_id) AS total_runs,
    COUNT(*) AS total_compliance_events,
    COUNT(CASE WHEN coverage_score >= 0.95 THEN 1 END) AS runs_above_95pct
FROM fact_compliance_steps
WHERE coverage_score IS NOT NULL;

-- DuckDB-specific optimizations:
-- 1. Indexes created separately (DuckDB doesn't support inline INDEX)
-- 2. VARCHAR used instead of STRING (DuckDB prefers VARCHAR)
-- 3. TIMESTAMP without timezone (DuckDB default)
-- 4. NULLIF guards against division by zero
-- 5. Views use IF NOT EXISTS for idempotency
-- 6. Schema aligned with TelemetryKPIProjector run-level aggregates
