-- Migration 011: AgentOrchestratorService PostgreSQL schema
-- Implements multi-tenant agent assignment and runtime switching for guideAI platform
-- Created: 2025-10-29
-- Purpose: Durable agent orchestration state with assignment history and persona management

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Agent personas table: stores available agent definitions
CREATE TABLE IF NOT EXISTS agent_personas (
    agent_id TEXT PRIMARY KEY,

    -- Display information
    display_name TEXT NOT NULL,
    role_alignment TEXT NOT NULL CHECK (role_alignment IN ('STRATEGIST', 'TEACHER', 'STUDENT', 'MULTI_ROLE')),

    -- Behavior configuration (JSONB arrays for flexibility)
    default_behaviors JSONB NOT NULL DEFAULT '[]'::jsonb,
    playbook_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Audit trail
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Agent assignments table: stores current and historical agent assignments per run
CREATE TABLE IF NOT EXISTS agent_assignments (
    assignment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Run linkage (NULL allows global assignments)
    run_id TEXT,

    -- Current active agent
    active_agent_id TEXT NOT NULL REFERENCES agent_personas(agent_id),

    -- Stage/context
    stage TEXT NOT NULL,

    -- Heuristics applied during assignment
    heuristics_applied JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Actor who requested assignment
    requested_by_id TEXT NOT NULL,
    requested_by_role TEXT NOT NULL,
    requested_by_surface TEXT NOT NULL CHECK (requested_by_surface IN ('cli', 'api', 'mcp', 'web')),

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Extensibility (context metadata)
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Unique constraint: one active assignment per run
    UNIQUE (run_id)
);

-- Agent switch events table: tracks agent switching history
CREATE TABLE IF NOT EXISTS agent_switch_events (
    event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Assignment linkage
    assignment_id UUID NOT NULL REFERENCES agent_assignments(assignment_id) ON DELETE CASCADE,

    -- Switch details
    from_agent_id TEXT NOT NULL REFERENCES agent_personas(agent_id),
    to_agent_id TEXT NOT NULL REFERENCES agent_personas(agent_id),
    stage TEXT NOT NULL,

    -- Trigger information
    trigger TEXT NOT NULL CHECK (trigger IN ('MANUAL', 'HEURISTIC', 'POLICY', 'ESCALATION')),
    trigger_details JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Actor who issued switch
    issued_by_id TEXT,
    issued_by_role TEXT,
    issued_by_surface TEXT CHECK (issued_by_surface IN ('cli', 'api', 'mcp', 'web')),

    -- Timestamp
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Standard indexes for common queries
CREATE INDEX IF NOT EXISTS idx_agent_personas_role_alignment ON agent_personas (role_alignment);
CREATE INDEX IF NOT EXISTS idx_agent_personas_capabilities ON agent_personas USING GIN (capabilities);

CREATE INDEX IF NOT EXISTS idx_agent_assignments_run_id ON agent_assignments (run_id) WHERE run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_assignments_active_agent ON agent_assignments (active_agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_assignments_stage ON agent_assignments (stage);
CREATE INDEX IF NOT EXISTS idx_agent_assignments_created_at ON agent_assignments (created_at);
CREATE INDEX IF NOT EXISTS idx_agent_assignments_requested_by ON agent_assignments (requested_by_id, requested_by_role);

CREATE INDEX IF NOT EXISTS idx_agent_switch_events_assignment ON agent_switch_events (assignment_id);
CREATE INDEX IF NOT EXISTS idx_agent_switch_events_from_agent ON agent_switch_events (from_agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_switch_events_to_agent ON agent_switch_events (to_agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_switch_events_trigger ON agent_switch_events (trigger);
CREATE INDEX IF NOT EXISTS idx_agent_switch_events_created_at ON agent_switch_events (created_at);

-- Column comments for documentation
COMMENT ON TABLE agent_personas IS 'Available agent definitions with role alignments and capabilities';
COMMENT ON TABLE agent_assignments IS 'Current agent assignments per run with heuristics and context';
COMMENT ON TABLE agent_switch_events IS 'Historical agent switching events with trigger reasons';

COMMENT ON COLUMN agent_personas.role_alignment IS 'Default guideAI role (STRATEGIST/TEACHER/STUDENT/MULTI_ROLE)';
COMMENT ON COLUMN agent_personas.default_behaviors IS 'JSONB array of behavior IDs recommended for this agent';
COMMENT ON COLUMN agent_personas.playbook_refs IS 'JSONB array of playbook markdown file references';
COMMENT ON COLUMN agent_personas.capabilities IS 'JSONB array of agent capability tags';

COMMENT ON COLUMN agent_assignments.run_id IS 'Run identifier (NULL for global assignments)';
COMMENT ON COLUMN agent_assignments.heuristics_applied IS 'JSONB object with assignment heuristics (task_type, severity, etc.)';
COMMENT ON COLUMN agent_assignments.metadata IS 'JSONB object with context data used for assignment';

COMMENT ON COLUMN agent_switch_events.trigger IS 'Switch trigger type (MANUAL/HEURISTIC/POLICY/ESCALATION)';
COMMENT ON COLUMN agent_switch_events.trigger_details IS 'JSONB object with reason and allow_downgrade flags';
