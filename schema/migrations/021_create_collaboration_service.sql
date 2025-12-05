-- Migration 021: Create CollaborationService schema
-- Supports shared workspaces and real-time co-editing
-- behavior_migrate_postgres_schema

-- ============================================================================
-- Collaboration Workspaces Table
-- Shared workspaces for multi-agent collaboration
-- ============================================================================
CREATE TABLE IF NOT EXISTS collaboration_workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    owner_id TEXT NOT NULL,
    workspace_type TEXT NOT NULL DEFAULT 'shared',  -- shared, private, team
    settings JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collaboration_workspaces_owner ON collaboration_workspaces(owner_id);
CREATE INDEX IF NOT EXISTS idx_collaboration_workspaces_type ON collaboration_workspaces(workspace_type);
CREATE INDEX IF NOT EXISTS idx_collaboration_workspaces_active ON collaboration_workspaces(is_active) WHERE is_active = true;

-- ============================================================================
-- Workspace Members Table
-- Tracks membership and permissions
-- ============================================================================
CREATE TABLE IF NOT EXISTS workspace_members (
    member_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES collaboration_workspaces(workspace_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'editor',  -- owner, admin, editor, viewer
    permissions JSONB NOT NULL DEFAULT '{}',
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_active_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace ON workspace_members(workspace_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON workspace_members(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_members_unique ON workspace_members(workspace_id, user_id);

-- ============================================================================
-- Collaboration Documents Table
-- Documents within workspaces
-- ============================================================================
CREATE TABLE IF NOT EXISTS collaboration_documents (
    document_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES collaboration_workspaces(workspace_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT 'text',  -- text, markdown, code, json
    version INTEGER NOT NULL DEFAULT 1,
    locked_by TEXT,  -- user_id of lock holder
    locked_at TIMESTAMP WITH TIME ZONE,
    lock_expires_at TIMESTAMP WITH TIME ZONE,
    created_by TEXT NOT NULL,
    last_edited_by TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collaboration_documents_workspace ON collaboration_documents(workspace_id);
CREATE INDEX IF NOT EXISTS idx_collaboration_documents_type ON collaboration_documents(document_type);
CREATE INDEX IF NOT EXISTS idx_collaboration_documents_created_by ON collaboration_documents(created_by);
CREATE INDEX IF NOT EXISTS idx_collaboration_documents_locked ON collaboration_documents(locked_by) WHERE locked_by IS NOT NULL;

-- ============================================================================
-- Document Versions Table
-- Version history for conflict resolution
-- ============================================================================
CREATE TABLE IF NOT EXISTS document_versions (
    version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES collaboration_documents(document_id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    edited_by TEXT NOT NULL,
    edit_summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_versions_document ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_document_versions_number ON document_versions(document_id, version_number DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_document_versions_unique ON document_versions(document_id, version_number);

-- ============================================================================
-- Active Cursors Table
-- Real-time cursor positions for presence awareness
-- ============================================================================
CREATE TABLE IF NOT EXISTS active_cursors (
    cursor_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES collaboration_documents(document_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    position_line INTEGER NOT NULL DEFAULT 0,
    position_column INTEGER NOT NULL DEFAULT 0,
    selection_start_line INTEGER,
    selection_start_column INTEGER,
    selection_end_line INTEGER,
    selection_end_column INTEGER,
    color TEXT,  -- For visual distinction
    last_updated TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_active_cursors_document ON active_cursors(document_id);
CREATE INDEX IF NOT EXISTS idx_active_cursors_user ON active_cursors(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_cursors_unique ON active_cursors(document_id, user_id);

-- Cleanup stale cursors (older than 5 minutes)
-- This would be run periodically by a cleanup job
-- DELETE FROM active_cursors WHERE last_updated < NOW() - INTERVAL '5 minutes';

-- ============================================================================
-- Pending Edits Table
-- Queued edits for conflict resolution
-- ============================================================================
CREATE TABLE IF NOT EXISTS pending_edits (
    edit_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES collaboration_documents(document_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    operation TEXT NOT NULL,  -- insert, delete, replace
    position_start INTEGER NOT NULL,
    position_end INTEGER,
    content TEXT,
    base_version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, applied, rejected, conflict
    conflict_resolution TEXT,  -- How conflict was resolved
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    applied_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_pending_edits_document ON pending_edits(document_id);
CREATE INDEX IF NOT EXISTS idx_pending_edits_status ON pending_edits(status);
CREATE INDEX IF NOT EXISTS idx_pending_edits_created ON pending_edits(created_at);

-- ============================================================================
-- Collaboration Events Table
-- Activity stream for workspace
-- ============================================================================
CREATE TABLE IF NOT EXISTS collaboration_events (
    event_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES collaboration_workspaces(workspace_id) ON DELETE CASCADE,
    document_id TEXT REFERENCES collaboration_documents(document_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- join, leave, edit, lock, unlock, comment, mention
    event_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collaboration_events_workspace ON collaboration_events(workspace_id);
CREATE INDEX IF NOT EXISTS idx_collaboration_events_document ON collaboration_events(document_id);
CREATE INDEX IF NOT EXISTS idx_collaboration_events_user ON collaboration_events(user_id);
CREATE INDEX IF NOT EXISTS idx_collaboration_events_type ON collaboration_events(event_type);
CREATE INDEX IF NOT EXISTS idx_collaboration_events_created ON collaboration_events(created_at DESC);

-- ============================================================================
-- Comments for documentation
-- ============================================================================
COMMENT ON TABLE collaboration_workspaces IS 'Shared workspaces for multi-agent/user collaboration';
COMMENT ON TABLE workspace_members IS 'Workspace membership with role-based permissions';
COMMENT ON TABLE collaboration_documents IS 'Documents within workspaces with locking support';
COMMENT ON TABLE document_versions IS 'Version history for conflict resolution and rollback';
COMMENT ON TABLE active_cursors IS 'Real-time cursor positions for presence awareness';
COMMENT ON TABLE pending_edits IS 'Queued edits for OT-style conflict resolution';
COMMENT ON TABLE collaboration_events IS 'Activity stream for workspace notifications';

COMMENT ON COLUMN collaboration_documents.locked_by IS 'Pessimistic locking for exclusive editing';
COMMENT ON COLUMN pending_edits.base_version IS 'Document version this edit was based on';
