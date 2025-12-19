-- Migration 030: Agile Board PostgreSQL schema
-- Implements Boards, Epics, Stories, Tasks with polymorphic assignment support
-- Created: 2025-12-09
-- Purpose: Enable project management with agent/user task assignment

-- Feature: 13.4.5 (Agent assignment to tasks) + 13.5.1-13.5.3 (Agile Board System)

-- =============================================================================
-- RLS Helper Functions (for multi-tenant isolation)
-- =============================================================================

-- Get current org context
CREATE OR REPLACE FUNCTION current_org_id() RETURNS TEXT AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_org_id', true), '');
END;
$$ LANGUAGE plpgsql STABLE;

-- Set current org context (2-param version for postgres_pool compatibility)
CREATE OR REPLACE FUNCTION set_current_org(p_org_id TEXT, p_user_id TEXT) RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_org_id', COALESCE(p_org_id, ''), false);
    PERFORM set_config('app.current_user_id', COALESCE(p_user_id, ''), false);
END;
$$ LANGUAGE plpgsql;

-- Clear org context
CREATE OR REPLACE FUNCTION clear_current_org() RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_org_id', '', false);
    PERFORM set_config('app.current_user_id', '', false);
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- ENUM Types
-- =============================================================================

-- Assignee type for polymorphic assignment (user OR agent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'assignee_type') THEN
        CREATE TYPE assignee_type AS ENUM ('user', 'agent');
    END IF;
END$$;

-- Work item status (generic for epic/story/task)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_item_status') THEN
        CREATE TYPE work_item_status AS ENUM (
            'backlog',
            'todo',
            'in_progress',
            'in_review',
            'done',
            'cancelled'
        );
    END IF;
END$$;

-- Epic status (higher-level milestones)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'epic_status') THEN
        CREATE TYPE epic_status AS ENUM (
            'draft',
            'active',
            'completed',
            'cancelled'
        );
    END IF;
END$$;

-- Work item priority
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_item_priority') THEN
        CREATE TYPE work_item_priority AS ENUM (
            'critical',
            'high',
            'medium',
            'low'
        );
    END IF;
END$$;

-- Work item type for tasks
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_type') THEN
        CREATE TYPE task_type AS ENUM (
            'feature',
            'bug',
            'chore',
            'spike',
            'documentation'
        );
    END IF;
END$$;

-- =============================================================================
-- Boards Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS boards (
    board_id TEXT PRIMARY KEY,                -- brd-<12-hex> format
    project_id TEXT NOT NULL,                 -- Links to projects table
    name TEXT NOT NULL,
    description TEXT,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,                 -- User ID who created
    is_default BOOLEAN NOT NULL DEFAULT FALSE,

    -- Multi-tenant context (inherited from project)
    org_id TEXT                               -- NULL for user-owned projects
);

-- Standard indexes
CREATE INDEX IF NOT EXISTS idx_boards_project_id ON boards (project_id);
CREATE INDEX IF NOT EXISTS idx_boards_org_id ON boards (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_boards_is_default ON boards (project_id, is_default) WHERE is_default = TRUE;

-- =============================================================================
-- Board Columns Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS board_columns (
    column_id TEXT PRIMARY KEY,               -- col-<12-hex> format
    board_id TEXT NOT NULL REFERENCES boards(board_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,      -- Order within board
    status_mapping work_item_status NOT NULL, -- Maps to work item status
    wip_limit INTEGER,                        -- Work in progress limit (NULL = no limit)
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (board_id, position)
);

CREATE INDEX IF NOT EXISTS idx_board_columns_board_id ON board_columns (board_id);

-- =============================================================================
-- Epics Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS epics (
    epic_id TEXT PRIMARY KEY,                 -- epic-<12-hex> format
    project_id TEXT NOT NULL,
    board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT,
    status epic_status NOT NULL DEFAULT 'draft',
    priority work_item_priority NOT NULL DEFAULT 'medium',
    color TEXT,                               -- Hex color for UI
    start_date DATE,
    target_date DATE,
    completed_at TIMESTAMPTZ,
    labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,

    -- Multi-tenant context
    org_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_epics_project_id ON epics (project_id);
CREATE INDEX IF NOT EXISTS idx_epics_board_id ON epics (board_id);
CREATE INDEX IF NOT EXISTS idx_epics_status ON epics (status);
CREATE INDEX IF NOT EXISTS idx_epics_org_id ON epics (org_id) WHERE org_id IS NOT NULL;

-- =============================================================================
-- Stories Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS stories (
    story_id TEXT PRIMARY KEY,                -- story-<12-hex> format
    project_id TEXT NOT NULL,
    board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
    epic_id TEXT REFERENCES epics(epic_id) ON DELETE SET NULL,
    column_id TEXT REFERENCES board_columns(column_id) ON DELETE SET NULL,

    title TEXT NOT NULL,
    description TEXT,
    status work_item_status NOT NULL DEFAULT 'backlog',
    priority work_item_priority NOT NULL DEFAULT 'medium',
    story_points INTEGER,                     -- Estimation
    position INTEGER NOT NULL DEFAULT 0,      -- Order within column

    -- Polymorphic single assignee (user OR agent)
    assignee_id TEXT,                         -- user_id or agent_id
    assignee_type assignee_type,              -- 'user' or 'agent'
    assigned_at TIMESTAMPTZ,
    assigned_by TEXT,

    -- Timestamps
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    due_date DATE,

    -- Metadata
    labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,

    -- Multi-tenant context
    org_id TEXT,

    -- Ensure assignee_id and assignee_type are both set or both null
    CONSTRAINT valid_assignee CHECK (
        (assignee_id IS NULL AND assignee_type IS NULL) OR
        (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_stories_project_id ON stories (project_id);
CREATE INDEX IF NOT EXISTS idx_stories_board_id ON stories (board_id);
CREATE INDEX IF NOT EXISTS idx_stories_epic_id ON stories (epic_id);
CREATE INDEX IF NOT EXISTS idx_stories_column_id ON stories (column_id);
CREATE INDEX IF NOT EXISTS idx_stories_status ON stories (status);
CREATE INDEX IF NOT EXISTS idx_stories_assignee ON stories (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stories_org_id ON stories (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stories_position ON stories (column_id, position);

-- =============================================================================
-- Tasks Table (subtasks of stories)
-- =============================================================================

CREATE TABLE IF NOT EXISTS board_tasks (
    task_id TEXT PRIMARY KEY,                 -- task-<12-hex> format
    project_id TEXT NOT NULL,
    story_id TEXT REFERENCES stories(story_id) ON DELETE CASCADE,
    board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
    column_id TEXT REFERENCES board_columns(column_id) ON DELETE SET NULL,

    title TEXT NOT NULL,
    description TEXT,
    task_type task_type NOT NULL DEFAULT 'feature',
    status work_item_status NOT NULL DEFAULT 'todo',
    priority work_item_priority NOT NULL DEFAULT 'medium',
    estimated_hours DECIMAL(5,2),
    actual_hours DECIMAL(5,2),
    position INTEGER NOT NULL DEFAULT 0,

    -- Polymorphic single assignee (user OR agent)
    assignee_id TEXT,
    assignee_type assignee_type,
    assigned_at TIMESTAMPTZ,
    assigned_by TEXT,

    -- Timestamps
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    due_date DATE,

    -- Behavior/Run linking (for agent tasks)
    behavior_id TEXT,                         -- behavior_* reference
    run_id TEXT,                              -- Execution run reference

    -- Metadata
    labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    checklist JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,

    -- Multi-tenant context
    org_id TEXT,

    CONSTRAINT valid_task_assignee CHECK (
        (assignee_id IS NULL AND assignee_type IS NULL) OR
        (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_board_tasks_project_id ON board_tasks (project_id);
CREATE INDEX IF NOT EXISTS idx_board_tasks_story_id ON board_tasks (story_id);
CREATE INDEX IF NOT EXISTS idx_board_tasks_board_id ON board_tasks (board_id);
CREATE INDEX IF NOT EXISTS idx_board_tasks_column_id ON board_tasks (column_id);
CREATE INDEX IF NOT EXISTS idx_board_tasks_status ON board_tasks (status);
CREATE INDEX IF NOT EXISTS idx_board_tasks_assignee ON board_tasks (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_board_tasks_behavior_id ON board_tasks (behavior_id) WHERE behavior_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_board_tasks_run_id ON board_tasks (run_id) WHERE run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_board_tasks_org_id ON board_tasks (org_id) WHERE org_id IS NOT NULL;

-- =============================================================================
-- Assignment History Table (audit trail for assignments)
-- =============================================================================

CREATE TABLE IF NOT EXISTS assignment_history (
    history_id TEXT PRIMARY KEY,              -- ahist-<12-hex> format

    -- Polymorphic reference to assignable (story or task)
    assignable_id TEXT NOT NULL,              -- story_id or task_id
    assignable_type TEXT NOT NULL,            -- 'story' or 'task'

    -- Assignment details
    assignee_id TEXT,                         -- NULL for unassignment
    assignee_type assignee_type,

    -- Action metadata
    action TEXT NOT NULL,                     -- 'assigned', 'unassigned', 'reassigned'
    performed_by TEXT NOT NULL,               -- User who made the change
    performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Previous assignee (for reassignment tracking)
    previous_assignee_id TEXT,
    previous_assignee_type assignee_type,

    reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Multi-tenant context
    org_id TEXT,

    CONSTRAINT valid_assignable_type CHECK (assignable_type IN ('story', 'task'))
);

CREATE INDEX IF NOT EXISTS idx_assignment_history_assignable ON assignment_history (assignable_id, assignable_type);
CREATE INDEX IF NOT EXISTS idx_assignment_history_assignee ON assignment_history (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_assignment_history_performed_at ON assignment_history (performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_assignment_history_org_id ON assignment_history (org_id) WHERE org_id IS NOT NULL;

-- =============================================================================
-- Sprints Table (for sprint-based work)
-- =============================================================================

CREATE TABLE IF NOT EXISTS sprints (
    sprint_id TEXT PRIMARY KEY,               -- sprint-<12-hex> format
    project_id TEXT NOT NULL,
    board_id TEXT REFERENCES boards(board_id) ON DELETE CASCADE,

    name TEXT NOT NULL,
    goal TEXT,
    status TEXT NOT NULL DEFAULT 'planning' CHECK (status IN ('planning', 'active', 'completed', 'cancelled')),

    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    velocity_planned INTEGER,                 -- Planned story points
    velocity_completed INTEGER,               -- Actual completed points

    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,

    -- Multi-tenant context
    org_id TEXT,

    CONSTRAINT valid_sprint_dates CHECK (end_date > start_date)
);

CREATE INDEX IF NOT EXISTS idx_sprints_board_id ON sprints (board_id);
CREATE INDEX IF NOT EXISTS idx_sprints_project_id ON sprints (project_id);
CREATE INDEX IF NOT EXISTS idx_sprints_status ON sprints (status);
CREATE INDEX IF NOT EXISTS idx_sprints_org_id ON sprints (org_id) WHERE org_id IS NOT NULL;

-- Sprint-Story relationship (many-to-many)
CREATE TABLE IF NOT EXISTS sprint_stories (
    sprint_id TEXT NOT NULL REFERENCES sprints(sprint_id) ON DELETE CASCADE,
    story_id TEXT NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by TEXT NOT NULL,

    PRIMARY KEY (sprint_id, story_id)
);

-- =============================================================================
-- Row-Level Security Policies
-- =============================================================================

ALTER TABLE boards ENABLE ROW LEVEL SECURITY;
ALTER TABLE board_columns ENABLE ROW LEVEL SECURITY;
ALTER TABLE epics ENABLE ROW LEVEL SECURITY;
ALTER TABLE stories ENABLE ROW LEVEL SECURITY;
ALTER TABLE board_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignment_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE sprints ENABLE ROW LEVEL SECURITY;
ALTER TABLE sprint_stories ENABLE ROW LEVEL SECURITY;

-- Boards RLS: Access if in org or project owner
CREATE POLICY boards_org_policy ON boards
    FOR ALL
    USING (
        org_id IS NULL OR
        org_id = current_setting('app.current_org_id', TRUE)
    );

-- Similar policies for other tables
CREATE POLICY epics_org_policy ON epics
    FOR ALL
    USING (
        org_id IS NULL OR
        org_id = current_setting('app.current_org_id', TRUE)
    );

CREATE POLICY stories_org_policy ON stories
    FOR ALL
    USING (
        org_id IS NULL OR
        org_id = current_setting('app.current_org_id', TRUE)
    );

CREATE POLICY board_tasks_org_policy ON board_tasks
    FOR ALL
    USING (
        org_id IS NULL OR
        org_id = current_setting('app.current_org_id', TRUE)
    );

CREATE POLICY assignment_history_org_policy ON assignment_history
    FOR ALL
    USING (
        org_id IS NULL OR
        org_id = current_setting('app.current_org_id', TRUE)
    );

CREATE POLICY sprints_org_policy ON sprints
    FOR ALL
    USING (
        org_id IS NULL OR
        org_id = current_setting('app.current_org_id', TRUE)
    );

-- Board columns follow board access
CREATE POLICY board_columns_access_policy ON board_columns
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM boards b
            WHERE b.board_id = board_columns.board_id
        )
    );

-- Sprint stories follow sprint access
CREATE POLICY sprint_stories_access_policy ON sprint_stories
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM sprints s
            WHERE s.sprint_id = sprint_stories.sprint_id
        )
    );

-- =============================================================================
-- Trigger Functions
-- =============================================================================

-- Update timestamps on modification
CREATE OR REPLACE FUNCTION update_board_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER boards_updated_at
    BEFORE UPDATE ON boards
    FOR EACH ROW
    EXECUTE FUNCTION update_board_updated_at();

CREATE TRIGGER epics_updated_at
    BEFORE UPDATE ON epics
    FOR EACH ROW
    EXECUTE FUNCTION update_board_updated_at();

CREATE TRIGGER stories_updated_at
    BEFORE UPDATE ON stories
    FOR EACH ROW
    EXECUTE FUNCTION update_board_updated_at();

CREATE TRIGGER board_tasks_updated_at
    BEFORE UPDATE ON board_tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_board_updated_at();

CREATE TRIGGER sprints_updated_at
    BEFORE UPDATE ON sprints
    FOR EACH ROW
    EXECUTE FUNCTION update_board_updated_at();

-- =============================================================================
-- Views for Common Queries
-- =============================================================================

-- Agent workload view: count of assigned stories/tasks per agent
CREATE OR REPLACE VIEW agent_workload AS
SELECT
    assignee_id,
    assignee_type,
    org_id,
    COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
    COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
    SUM(CASE WHEN story_points IS NOT NULL THEN story_points ELSE 0 END) AS total_story_points
FROM stories
WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
GROUP BY assignee_id, assignee_type, org_id

UNION ALL

SELECT
    assignee_id,
    assignee_type,
    org_id,
    COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
    COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
    SUM(COALESCE(estimated_hours, 0)) AS total_story_points  -- Use hours for tasks
FROM board_tasks
WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
GROUP BY assignee_id, assignee_type, org_id;

-- Comment for documentation
COMMENT ON TABLE boards IS 'Kanban/Scrum boards for project management';
COMMENT ON TABLE stories IS 'DEPRECATED - Use work_items table instead. User stories with polymorphic assignee (user or agent)';
COMMENT ON TABLE board_tasks IS 'DEPRECATED - Use work_items table instead. Tasks/subtasks of stories with polymorphic assignee';
COMMENT ON TABLE epics IS 'DEPRECATED - Use work_items with item_type=epic instead';
COMMENT ON TABLE sprint_stories IS 'DEPRECATED - Use work_items with sprint_id field instead';
COMMENT ON TABLE assignment_history IS 'Audit trail for all assignment changes';
COMMENT ON VIEW agent_workload IS 'Aggregated workload per agent for capacity planning';

-- =============================================================================
-- UNIFIED WORK ITEMS TABLE (replaces epics, stories, board_tasks)
-- =============================================================================
-- This unified table consolidates all work item types into a single
-- table with a type discriminator. Use this for all new work items.

-- Work item type ENUM
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_item_type') THEN
        CREATE TYPE work_item_type AS ENUM ('epic', 'story', 'task');
    END IF;
END$$;

-- Add 'draft' to work_item_status if not already present
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumlabel = 'draft'
        AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'work_item_status')
    ) THEN
        ALTER TYPE work_item_status ADD VALUE 'draft' BEFORE 'backlog';
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS work_items (
    -- Primary key and type discriminator
    item_id TEXT PRIMARY KEY,
    item_type work_item_type NOT NULL,

    -- Hierarchy and placement
    project_id TEXT NOT NULL,
    board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
    column_id TEXT REFERENCES board_columns(column_id) ON DELETE SET NULL,
    parent_id TEXT REFERENCES work_items(item_id) ON DELETE SET NULL,
    sprint_id TEXT REFERENCES sprints(sprint_id) ON DELETE SET NULL,

    -- Core fields
    title TEXT NOT NULL,
    description TEXT,
    status work_item_status NOT NULL DEFAULT 'backlog',
    priority work_item_priority NOT NULL DEFAULT 'medium',
    position INTEGER NOT NULL DEFAULT 0,

    -- Estimation
    story_points INTEGER,
    estimated_hours DECIMAL(5,2),
    actual_hours DECIMAL(5,2),

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
    color TEXT,
    labels JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Rich content
    acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
    checklist JSONB NOT NULL DEFAULT '[]'::jsonb,
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Agent integration
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
    CONSTRAINT valid_hierarchy CHECK (
        (item_type = 'epic' AND parent_id IS NULL) OR
        (item_type IN ('story', 'task'))
    )
);

-- Work items indexes
CREATE INDEX IF NOT EXISTS idx_work_items_item_type ON work_items (item_type);
CREATE INDEX IF NOT EXISTS idx_work_items_project_id ON work_items (project_id);
CREATE INDEX IF NOT EXISTS idx_work_items_board_id ON work_items (board_id);
CREATE INDEX IF NOT EXISTS idx_work_items_column_id ON work_items (column_id);
CREATE INDEX IF NOT EXISTS idx_work_items_parent_id ON work_items (parent_id);
CREATE INDEX IF NOT EXISTS idx_work_items_sprint_id ON work_items (sprint_id);
CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items (status);
CREATE INDEX IF NOT EXISTS idx_work_items_priority ON work_items (priority);
CREATE INDEX IF NOT EXISTS idx_work_items_assignee ON work_items (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_work_items_behavior_id ON work_items (behavior_id) WHERE behavior_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_work_items_run_id ON work_items (run_id) WHERE run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_work_items_org_id ON work_items (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_work_items_position ON work_items (column_id, position);
CREATE INDEX IF NOT EXISTS idx_work_items_created_at ON work_items (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_items_hierarchy ON work_items (project_id, item_type, parent_id);

-- RLS for work_items
ALTER TABLE work_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY work_items_org_policy ON work_items
    FOR ALL
    USING (
        org_id IS NULL OR
        org_id = current_setting('app.current_org_id', TRUE)
    );

-- Updated_at trigger for work_items
CREATE TRIGGER work_items_updated_at
    BEFORE UPDATE ON work_items
    FOR EACH ROW
    EXECUTE FUNCTION update_board_updated_at();

COMMENT ON TABLE work_items IS 'Unified work items table (replaces epics, stories, board_tasks). Use item_type to distinguish between epic/story/task.';

-- =============================================================================
-- Updated agent_workload view (includes work_items table)
-- =============================================================================
DROP VIEW IF EXISTS agent_workload;

CREATE OR REPLACE VIEW agent_workload AS
-- New unified work_items
SELECT
    assignee_id,
    assignee_type,
    org_id,
    COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
    COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
    SUM(COALESCE(story_points, 0)) AS total_story_points
FROM work_items
WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
GROUP BY assignee_id, assignee_type, org_id

UNION ALL

-- Legacy stories (for backwards compatibility during migration)
SELECT
    assignee_id,
    assignee_type,
    org_id,
    COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
    COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
    SUM(CASE WHEN story_points IS NOT NULL THEN story_points ELSE 0 END) AS total_story_points
FROM stories
WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
GROUP BY assignee_id, assignee_type, org_id

UNION ALL

-- Legacy board_tasks (for backwards compatibility during migration)
SELECT
    assignee_id,
    assignee_type,
    org_id,
    COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress', 'in_review')) AS active_items,
    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
    COUNT(*) FILTER (WHERE status = 'done') AS completed_count,
    SUM(COALESCE(estimated_hours, 0)) AS total_story_points
FROM board_tasks
WHERE assignee_id IS NOT NULL AND assignee_type = 'agent'
GROUP BY assignee_id, assignee_type, org_id;
