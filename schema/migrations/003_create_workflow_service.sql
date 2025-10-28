-- guideAI WorkflowService PostgreSQL schema
-- Aligns with the SQLite workflow runtime defined in `guideai/workflow_service.py`.

BEGIN;

CREATE TABLE IF NOT EXISTS workflow_templates (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    role_focus TEXT NOT NULL,
    version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    created_by_id TEXT NOT NULL,
    created_by_role TEXT NOT NULL,
    created_by_surface TEXT NOT NULL,
    template_data JSONB NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL REFERENCES workflow_templates(template_id) ON DELETE CASCADE,
    template_name TEXT NOT NULL,
    role_focus TEXT NOT NULL,
    status TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    actor_surface TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    total_tokens INTEGER DEFAULT 0,
    run_data JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_templates_role_focus ON workflow_templates (role_focus);
CREATE INDEX IF NOT EXISTS idx_workflow_templates_created_at ON workflow_templates (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_templates_tags_gin ON workflow_templates USING GIN (tags jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_template_id ON workflow_runs (template_id);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs (status);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_started_at ON workflow_runs (started_at DESC);

COMMIT;
