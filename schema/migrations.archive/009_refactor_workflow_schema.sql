-- Migration 009: Refactor WorkflowService to Normalized Schema
-- Purpose: Add workflow_template_versions table and normalize workflow_templates
-- Following BehaviorService pattern for version history and audit compliance
-- Date: 2025-10-28
-- Context: Priority 1.3.4.B - Architecture Standardization

BEGIN;

-- Step 1: Create workflow_template_versions table (matching BehaviorService pattern)
CREATE TABLE IF NOT EXISTS workflow_template_versions (
    template_id TEXT NOT NULL REFERENCES workflow_templates(template_id) ON DELETE CASCADE,
    version TEXT NOT NULL,

    -- Template content (from template_data JSONB)
    steps JSONB NOT NULL,  -- Array of TemplateStep objects

    -- Metadata
    status TEXT NOT NULL CHECK (status IN ('DRAFT', 'APPROVED', 'DEPRECATED')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Version lifecycle
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,  -- NULL for current version

    -- Audit trail
    created_by_id TEXT NOT NULL,
    created_by_role TEXT NOT NULL,
    created_by_surface TEXT NOT NULL,
    approval_action_id TEXT,  -- Link to ActionService for approval audit

    PRIMARY KEY (template_id, version)
);

-- Step 2: Add status and latest_version columns to workflow_templates header table
ALTER TABLE workflow_templates ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'DRAFT';
ALTER TABLE workflow_templates ADD COLUMN IF NOT EXISTS latest_version TEXT NOT NULL DEFAULT '1.0.0';
ALTER TABLE workflow_templates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- Step 3: Add CHECK constraint for status
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'workflow_templates_status_check'
    ) THEN
        ALTER TABLE workflow_templates
        ADD CONSTRAINT workflow_templates_status_check
        CHECK (status IN ('DRAFT', 'APPROVED', 'DEPRECATED'));
    END IF;
END $$;

-- Step 4: Migrate existing data from template_data JSONB to normalized structure
-- Extract version data into workflow_template_versions table
INSERT INTO workflow_template_versions (
    template_id,
    version,
    steps,
    status,
    metadata,
    effective_from,
    effective_to,
    created_by_id,
    created_by_role,
    created_by_surface,
    approval_action_id
)
SELECT
    template_id,
    COALESCE(template_data->>'version', version, '1.0.0') as version,
    COALESCE(template_data->'steps', '[]'::jsonb) as steps,
    'APPROVED' as status,  -- Existing templates treated as approved
    COALESCE(template_data->'metadata', '{}'::jsonb) as metadata,
    created_at as effective_from,
    NULL as effective_to,  -- Current version
    created_by_id,
    created_by_role,
    created_by_surface,
    NULL as approval_action_id
FROM workflow_templates
WHERE NOT EXISTS (
    SELECT 1 FROM workflow_template_versions wtv
    WHERE wtv.template_id = workflow_templates.template_id
)
ON CONFLICT (template_id, version) DO NOTHING;

-- Step 5: Update workflow_templates header with status and updated_at
UPDATE workflow_templates
SET
    status = 'APPROVED',
    updated_at = created_at
WHERE status IS NULL OR updated_at IS NULL;

-- Step 6: Create composite indexes matching BehaviorService optimization pattern
-- These enable efficient JOIN queries and version lookups
CREATE INDEX IF NOT EXISTS idx_workflow_template_versions_lookup
    ON workflow_template_versions(template_id, status, effective_to)
    WHERE status = 'APPROVED' AND effective_to IS NULL;

CREATE INDEX IF NOT EXISTS idx_workflow_template_versions_status
    ON workflow_template_versions(status);

CREATE INDEX IF NOT EXISTS idx_workflow_template_versions_effective_from
    ON workflow_template_versions(effective_from);

CREATE INDEX IF NOT EXISTS idx_workflow_templates_status
    ON workflow_templates(status);

CREATE INDEX IF NOT EXISTS idx_workflow_templates_updated_at
    ON workflow_templates(updated_at DESC);

-- Step 7: GIN index on steps JSONB for searching step names/descriptions
CREATE INDEX IF NOT EXISTS idx_workflow_template_versions_steps_gin
    ON workflow_template_versions USING GIN (steps jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_workflow_template_versions_metadata_gin
    ON workflow_template_versions USING GIN (metadata jsonb_path_ops);

-- Step 8: Add comments for documentation
COMMENT ON TABLE workflow_template_versions IS 'Version history for workflow templates with immutable audit trail';
COMMENT ON COLUMN workflow_template_versions.steps IS 'Array of TemplateStep objects defining workflow execution sequence';
COMMENT ON COLUMN workflow_template_versions.status IS 'Version status: DRAFT (under development), APPROVED (production), DEPRECATED (archived)';
COMMENT ON COLUMN workflow_template_versions.effective_from IS 'Timestamp when this version became active';
COMMENT ON COLUMN workflow_template_versions.effective_to IS 'Timestamp when this version was superseded (NULL for current version)';
COMMENT ON COLUMN workflow_template_versions.approval_action_id IS 'Reference to ActionService audit log for approval event';

COMMENT ON COLUMN workflow_templates.status IS 'Current template status (aggregated from latest version)';
COMMENT ON COLUMN workflow_templates.latest_version IS 'Semver string of most recent version';
COMMENT ON COLUMN workflow_templates.updated_at IS 'Last modification timestamp (updated on version changes)';

-- Step 9: Template data column can be dropped in future migration once service is fully refactored
-- For now, keeping it for rollback safety
-- ALTER TABLE workflow_templates DROP COLUMN IF EXISTS template_data;

COMMIT;

-- Migration notes:
-- - Follows BehaviorService normalized pattern (header + versions tables)
-- - Preserves all existing data with backward compatibility
-- - Composite indexes enable efficient JOIN queries for optimization (Priority 1.3.4.C)
-- - Status tracking supports approve/deprecate workflows
-- - Audit trail via approval_action_id links to ActionService
-- - template_data column retained for rollback safety, can be dropped after service refactor validation
