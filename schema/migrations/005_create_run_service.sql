-- Migration 005: RunService PostgreSQL schema
-- Implements run orchestration with step tracking for guideAI platform
-- Created: 2025-10-27
-- Purpose: Durable run state storage with SSE streaming support and step-level progress tracking

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Runs table: stores workflow/behavior execution runs with progress tracking
CREATE TABLE IF NOT EXISTS runs (
    run_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Actor details (embedded from Actor dataclass)
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    actor_surface TEXT NOT NULL CHECK (actor_surface IN ('cli', 'api', 'mcp', 'web')),

    -- Run status
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),

    -- Workflow/template linkage
    workflow_id TEXT,
    workflow_name TEXT,
    template_id TEXT,
    template_name TEXT,

    -- Behavior references (JSONB array for flexible querying)
    behavior_ids JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Progress tracking
    current_step TEXT,
    progress_pct REAL NOT NULL DEFAULT 0.0 CHECK (progress_pct >= 0.0 AND progress_pct <= 100.0),
    message TEXT,

    -- Completion details
    duration_ms INTEGER,
    outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Run steps table: tracks individual steps within a run
CREATE TABLE IF NOT EXISTS run_steps (
    step_id TEXT NOT NULL,
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,

    -- Step details
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'SKIPPED')),

    -- Timestamps
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Progress tracking
    progress_pct REAL DEFAULT 0.0 CHECK (progress_pct >= 0.0 AND progress_pct <= 100.0),

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Primary key and unique constraint for run_id + step_id combination
    PRIMARY KEY (run_id, step_id)
);

-- Standard indexes for common queries
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status);
CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs (workflow_id) WHERE workflow_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runs_template ON runs (template_id) WHERE template_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runs_actor_id ON runs (actor_id);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs (created_at);
CREATE INDEX IF NOT EXISTS idx_runs_updated_at ON runs (updated_at);

-- GIN index for behavior_ids JSONB array queries
CREATE INDEX IF NOT EXISTS idx_runs_behavior_ids ON runs USING GIN (behavior_ids);

-- Run steps indexes
CREATE INDEX IF NOT EXISTS idx_run_steps_run_id ON run_steps (run_id);
CREATE INDEX IF NOT EXISTS idx_run_steps_status ON run_steps (status);
CREATE INDEX IF NOT EXISTS idx_run_steps_created_at ON run_steps (created_at);

-- Trigger to update updated_at timestamps automatically
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_runs_updated_at ON runs;
CREATE TRIGGER update_runs_updated_at
    BEFORE UPDATE ON runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_run_steps_updated_at ON run_steps;
CREATE TRIGGER update_run_steps_updated_at
    BEFORE UPDATE ON run_steps
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comments for documentation
COMMENT ON TABLE runs IS 'Workflow and behavior execution runs with progress tracking and SSE support';
COMMENT ON TABLE run_steps IS 'Individual steps within a run with independent progress tracking';
COMMENT ON COLUMN runs.behavior_ids IS 'JSONB array of behavior IDs referenced during run execution';
COMMENT ON COLUMN runs.outputs IS 'JSONB object storing run outputs and results';
COMMENT ON COLUMN runs.metadata IS 'JSONB object for extensible run metadata (tags, labels, custom fields)';
COMMENT ON COLUMN run_steps.metadata IS 'JSONB object for extensible step metadata';
COMMENT ON COLUMN runs.progress_pct IS 'Overall run progress percentage (0.0-100.0)';
COMMENT ON COLUMN run_steps.progress_pct IS 'Individual step progress percentage (0.0-100.0)';
