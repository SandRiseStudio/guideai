-- Migration 031: Unified Work Items Table
-- Consolidates epics, stories, and tasks into a single work_items table
-- with a discriminator column (item_type) and hierarchical parent_id
--
-- Hierarchy:
--   Epic (type='epic', parent_id=NULL)
--   └─ Story (type='story', parent_id=epic_id)
--      └─ Task (type='task', parent_id=story_id)
--
-- Created: 2025-12-09
-- Purpose: Simplify CRUD operations with unified model

-- =============================================================================
-- Add work_item_type ENUM
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_item_type') THEN
        CREATE TYPE work_item_type AS ENUM ('epic', 'story', 'task');
    END IF;
END$$;

-- =============================================================================
-- Unified Work Items Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS work_items (
    -- Primary key and type discriminator
    item_id TEXT PRIMARY KEY,                     -- epic-xxx, story-xxx, or task-xxx
    item_type work_item_type NOT NULL,            -- epic, story, or task

    -- Hierarchy and placement
    project_id TEXT NOT NULL,
    board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
    column_id TEXT REFERENCES board_columns(column_id) ON DELETE SET NULL,
    parent_id TEXT REFERENCES work_items(item_id) ON DELETE SET NULL, -- epic for stories, story for tasks

    -- Core fields (shared across all types)
    title TEXT NOT NULL,
    description TEXT,
    status work_item_status NOT NULL DEFAULT 'backlog',
    priority work_item_priority NOT NULL DEFAULT 'medium',
    position INTEGER NOT NULL DEFAULT 0,

    -- Estimation (optional based on type)
    story_points INTEGER,                         -- For epics/stories
    estimated_hours DECIMAL(5,2),                 -- For tasks
    actual_hours DECIMAL(5,2),                    -- For tasks

    -- Polymorphic assignment
    assignee_id TEXT,
    assignee_type assignee_type,
    assigned_at TIMESTAMPTZ,
    assigned_by TEXT,

    -- Dates
    start_date DATE,
    target_date DATE,
    due_date DATE,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Visual/organizational
    color TEXT,                                   -- Hex color for UI
    labels JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Rich content (JSONB for flexibility)
    acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
    checklist JSONB NOT NULL DEFAULT '[]'::jsonb,
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Agent integration (primarily for tasks)
    behavior_id TEXT,
    run_id TEXT,

    -- Metadata
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,

    -- Multi-tenant context
    org_id TEXT,

    -- Constraints
    CONSTRAINT valid_work_item_assignee CHECK (
        (assignee_id IS NULL AND assignee_type IS NULL) OR
        (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)
    ),
    -- Validate hierarchy: epics can't have parents
    CONSTRAINT valid_hierarchy CHECK (
        (item_type = 'epic' AND parent_id IS NULL) OR
        (item_type IN ('story', 'task'))
    )
);

-- =============================================================================
-- Indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_work_items_item_type ON work_items (item_type);
CREATE INDEX IF NOT EXISTS idx_work_items_project_id ON work_items (project_id);
CREATE INDEX IF NOT EXISTS idx_work_items_board_id ON work_items (board_id);
CREATE INDEX IF NOT EXISTS idx_work_items_column_id ON work_items (column_id);
CREATE INDEX IF NOT EXISTS idx_work_items_parent_id ON work_items (parent_id);
CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items (status);
CREATE INDEX IF NOT EXISTS idx_work_items_priority ON work_items (priority);
CREATE INDEX IF NOT EXISTS idx_work_items_assignee ON work_items (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_work_items_behavior_id ON work_items (behavior_id) WHERE behavior_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_work_items_run_id ON work_items (run_id) WHERE run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_work_items_org_id ON work_items (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_work_items_position ON work_items (column_id, position);
CREATE INDEX IF NOT EXISTS idx_work_items_created_at ON work_items (created_at DESC);

-- Composite index for efficient hierarchy queries
CREATE INDEX IF NOT EXISTS idx_work_items_hierarchy ON work_items (project_id, item_type, parent_id);

-- =============================================================================
-- Views for backward compatibility (optional - queries can use work_items directly)
-- =============================================================================

-- Epics view
CREATE OR REPLACE VIEW epics_view AS
SELECT
    item_id AS epic_id,
    project_id,
    board_id,
    title AS name,
    description,
    status,
    priority,
    color,
    start_date,
    target_date,
    completed_at,
    labels,
    metadata,
    created_at,
    updated_at,
    created_by,
    org_id,
    story_points
FROM work_items
WHERE item_type = 'epic';

-- Stories view
CREATE OR REPLACE VIEW stories_view AS
SELECT
    item_id AS story_id,
    project_id,
    board_id,
    parent_id AS epic_id,
    column_id,
    title,
    description,
    status,
    priority,
    story_points,
    position,
    assignee_id,
    assignee_type,
    assigned_at,
    assigned_by,
    started_at,
    completed_at,
    due_date,
    labels,
    acceptance_criteria,
    metadata,
    created_at,
    updated_at,
    created_by,
    org_id
FROM work_items
WHERE item_type = 'story';

-- Tasks view
CREATE OR REPLACE VIEW tasks_view AS
SELECT
    item_id AS task_id,
    project_id,
    parent_id AS story_id,
    board_id,
    column_id,
    title,
    description,
    status,
    priority,
    estimated_hours,
    actual_hours,
    position,
    assignee_id,
    assignee_type,
    assigned_at,
    assigned_by,
    started_at,
    completed_at,
    due_date,
    behavior_id,
    run_id,
    labels,
    checklist,
    metadata,
    created_at,
    updated_at,
    created_by,
    org_id
FROM work_items
WHERE item_type = 'task';

-- =============================================================================
-- Row Level Security (consistent with other tables)
-- =============================================================================

ALTER TABLE work_items ENABLE ROW LEVEL SECURITY;

-- Org isolation policy (when org_id is set)
DROP POLICY IF EXISTS work_items_org_isolation ON work_items;
CREATE POLICY work_items_org_isolation ON work_items
    FOR ALL
    USING (
        org_id IS NULL
        OR org_id = current_setting('app.current_org_id', true)
        OR current_setting('app.current_org_id', true) = ''
    );

-- =============================================================================
-- Updated Assignment History (reference unified work_items)
-- =============================================================================

-- Update constraint to allow 'epic' as assignable_type
ALTER TABLE assignment_history DROP CONSTRAINT IF EXISTS valid_assignable_type;
ALTER TABLE assignment_history ADD CONSTRAINT valid_assignable_type CHECK (
    assignable_type IN ('story', 'task', 'epic', 'work_item')
);

-- =============================================================================
-- Trigger to update updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION update_work_items_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS work_items_updated_at_trigger ON work_items;
CREATE TRIGGER work_items_updated_at_trigger
    BEFORE UPDATE ON work_items
    FOR EACH ROW
    EXECUTE FUNCTION update_work_items_updated_at();

-- =============================================================================
-- Migration helper: Migrate existing data (if needed)
-- =============================================================================

-- Uncomment and run this block to migrate existing data:
/*
-- Migrate epics
INSERT INTO work_items (
    item_id, item_type, project_id, board_id, column_id, parent_id,
    title, description, status, priority, position,
    story_points, color, start_date, target_date, completed_at,
    labels, metadata, created_at, updated_at, created_by, org_id
)
SELECT
    epic_id, 'epic'::work_item_type, project_id, board_id, NULL, NULL,
    name, description,
    CASE status
        WHEN 'draft' THEN 'backlog'::work_item_status
        WHEN 'active' THEN 'in_progress'::work_item_status
        WHEN 'completed' THEN 'done'::work_item_status
        WHEN 'cancelled' THEN 'cancelled'::work_item_status
    END,
    priority, 0,
    NULL, color, start_date, target_date, completed_at,
    labels, metadata, created_at, updated_at, created_by, org_id
FROM epics
ON CONFLICT (item_id) DO NOTHING;

-- Migrate stories
INSERT INTO work_items (
    item_id, item_type, project_id, board_id, column_id, parent_id,
    title, description, status, priority, position,
    story_points, assignee_id, assignee_type, assigned_at, assigned_by,
    due_date, started_at, completed_at,
    labels, acceptance_criteria, metadata, created_at, updated_at, created_by, org_id
)
SELECT
    story_id, 'story'::work_item_type, project_id, board_id, column_id, epic_id,
    title, description, status, priority, position,
    story_points, assignee_id, assignee_type, assigned_at, assigned_by,
    due_date, started_at, completed_at,
    labels, acceptance_criteria, metadata, created_at, updated_at, created_by, org_id
FROM stories
ON CONFLICT (item_id) DO NOTHING;

-- Migrate tasks
INSERT INTO work_items (
    item_id, item_type, project_id, board_id, column_id, parent_id,
    title, description, status, priority, position,
    estimated_hours, actual_hours,
    assignee_id, assignee_type, assigned_at, assigned_by,
    due_date, started_at, completed_at,
    behavior_id, run_id,
    labels, checklist, metadata, created_at, updated_at, created_by, org_id
)
SELECT
    task_id, 'task'::work_item_type, project_id, board_id, column_id, story_id,
    title, description, status, priority, position,
    estimated_hours, actual_hours,
    assignee_id, assignee_type, assigned_at, assigned_by,
    due_date, started_at, completed_at,
    behavior_id, run_id,
    labels, checklist, metadata, created_at, updated_at, created_by, org_id
FROM board_tasks
ON CONFLICT (item_id) DO NOTHING;
*/
