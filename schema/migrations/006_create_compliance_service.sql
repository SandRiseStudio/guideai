-- Migration 006: ComplianceService PostgreSQL schema
-- Implements compliance checklist tracking with step-level evidence and validation
-- Created: 2025-10-27
-- Purpose: Durable compliance checklist storage for audit trails and policy validation

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Checklists table: stores compliance checklists with coverage tracking
CREATE TABLE IF NOT EXISTS checklists (
    checklist_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Metadata
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    template_id TEXT,
    milestone TEXT,
    compliance_category JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Status tracking
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    coverage_score REAL NOT NULL DEFAULT 0.0 CHECK (coverage_score >= 0.0 AND coverage_score <= 1.0),

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Checklist steps table: tracks individual compliance steps with evidence
CREATE TABLE IF NOT EXISTS checklist_steps (
    step_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    checklist_id UUID NOT NULL REFERENCES checklists(checklist_id) ON DELETE CASCADE,

    -- Step details
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'SKIPPED')),

    -- Actor (embedded from Actor dataclass)
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    actor_surface TEXT NOT NULL CHECK (actor_surface IN ('cli', 'api', 'mcp', 'web')),

    -- Evidence and linkage
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    behaviors_cited JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_run_id TEXT,
    audit_log_event_id TEXT,

    -- Validation
    validation_result JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Prevent duplicate steps with same title in a checklist
    UNIQUE (checklist_id, title)
);

-- Standard indexes for common queries
CREATE INDEX IF NOT EXISTS idx_checklists_milestone ON checklists (milestone) WHERE milestone IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_checklists_template ON checklists (template_id) WHERE template_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_checklists_completed ON checklists (completed_at) WHERE completed_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_checklists_created_at ON checklists (created_at);

-- JSONB GIN indexes for flexible querying
CREATE INDEX IF NOT EXISTS idx_checklists_compliance_category ON checklists USING GIN (compliance_category);
CREATE INDEX IF NOT EXISTS idx_checklist_steps_evidence ON checklist_steps USING GIN (evidence);
CREATE INDEX IF NOT EXISTS idx_checklist_steps_behaviors ON checklist_steps USING GIN (behaviors_cited);
CREATE INDEX IF NOT EXISTS idx_checklist_steps_validation ON checklist_steps USING GIN (validation_result);

-- Step indexes
CREATE INDEX IF NOT EXISTS idx_checklist_steps_checklist_id ON checklist_steps (checklist_id);
CREATE INDEX IF NOT EXISTS idx_checklist_steps_status ON checklist_steps (status);
CREATE INDEX IF NOT EXISTS idx_checklist_steps_actor_id ON checklist_steps (actor_id);
CREATE INDEX IF NOT EXISTS idx_checklist_steps_created_at ON checklist_steps (created_at);
CREATE INDEX IF NOT EXISTS idx_checklist_steps_related_run ON checklist_steps (related_run_id) WHERE related_run_id IS NOT NULL;

-- Trigger to update checklists.updated_at automatically
CREATE OR REPLACE FUNCTION update_checklists_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_checklists_updated_at ON checklists;
CREATE TRIGGER trigger_checklists_updated_at
    BEFORE UPDATE ON checklists
    FOR EACH ROW
    EXECUTE FUNCTION update_checklists_updated_at();

-- Trigger to update checklist_steps.updated_at automatically
CREATE OR REPLACE FUNCTION update_checklist_steps_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_checklist_steps_updated_at ON checklist_steps;
CREATE TRIGGER trigger_checklist_steps_updated_at
    BEFORE UPDATE ON checklist_steps
    FOR EACH ROW
    EXECUTE FUNCTION update_checklist_steps_updated_at();

-- Add updated_at column to checklists if it doesn't exist (for completeness)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'checklists' AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE checklists ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
    END IF;
END $$;
