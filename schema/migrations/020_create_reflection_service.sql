-- Migration 020: Create ReflectionService schema
-- Supports PRD Component B: Reflection and behavior candidate extraction
-- behavior_migrate_postgres_schema

-- ============================================================================
-- Reflection Patterns Table
-- Stores extracted patterns from trace analysis
-- ============================================================================
CREATE TABLE IF NOT EXISTS reflection_patterns (
    pattern_id TEXT PRIMARY KEY,
    run_id TEXT,
    trace_id TEXT,
    pattern_type TEXT NOT NULL,  -- 'procedural', 'structural', 'error_recovery'
    description TEXT NOT NULL,
    frequency INTEGER NOT NULL DEFAULT 1,
    confidence FLOAT NOT NULL DEFAULT 0.5,
    context JSONB,  -- Source context where pattern was observed
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reflection_patterns_run_id ON reflection_patterns(run_id);
CREATE INDEX IF NOT EXISTS idx_reflection_patterns_trace_id ON reflection_patterns(trace_id);
CREATE INDEX IF NOT EXISTS idx_reflection_patterns_type ON reflection_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_reflection_patterns_confidence ON reflection_patterns(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_reflection_patterns_created_at ON reflection_patterns(created_at DESC);

-- ============================================================================
-- Behavior Candidates Table
-- Proposed behaviors extracted from reflection analysis
-- ============================================================================
CREATE TABLE IF NOT EXISTS behavior_candidates (
    candidate_id TEXT PRIMARY KEY,
    pattern_id TEXT REFERENCES reflection_patterns(pattern_id) ON DELETE SET NULL,
    name TEXT NOT NULL,  -- behavior_<verb>_<noun> format
    summary TEXT NOT NULL,
    triggers TEXT[] NOT NULL DEFAULT '{}',  -- When conditions
    steps TEXT[] NOT NULL DEFAULT '{}',  -- Procedure steps
    confidence FLOAT NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'proposed',  -- proposed, approved, rejected, merged
    role TEXT NOT NULL DEFAULT 'student',  -- student, teacher, strategist
    keywords TEXT[] NOT NULL DEFAULT '{}',  -- For retrieval
    historical_validation JSONB,  -- Cases where this would have helped
    reviewed_by TEXT,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    merged_behavior_id TEXT,  -- If approved and merged into handbook
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_behavior_candidates_pattern_id ON behavior_candidates(pattern_id);
CREATE INDEX IF NOT EXISTS idx_behavior_candidates_status ON behavior_candidates(status);
CREATE INDEX IF NOT EXISTS idx_behavior_candidates_confidence ON behavior_candidates(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_behavior_candidates_name ON behavior_candidates(name);
CREATE INDEX IF NOT EXISTS idx_behavior_candidates_created_at ON behavior_candidates(created_at DESC);

-- GIN index for keyword search
CREATE INDEX IF NOT EXISTS idx_behavior_candidates_keywords ON behavior_candidates USING GIN(keywords);

-- ============================================================================
-- Reflection Sessions Table
-- Tracks reflection analysis sessions
-- ============================================================================
CREATE TABLE IF NOT EXISTS reflection_sessions (
    session_id TEXT PRIMARY KEY,
    run_id TEXT,
    trace_id TEXT,
    session_type TEXT NOT NULL DEFAULT 'automatic',  -- automatic, manual, scheduled
    patterns_extracted INTEGER NOT NULL DEFAULT 0,
    candidates_generated INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reflection_sessions_run_id ON reflection_sessions(run_id);
CREATE INDEX IF NOT EXISTS idx_reflection_sessions_status ON reflection_sessions(status);
CREATE INDEX IF NOT EXISTS idx_reflection_sessions_created_at ON reflection_sessions(created_at DESC);

-- ============================================================================
-- Pattern Observations Table
-- Tracks occurrences of patterns across runs (for 3+ threshold)
-- ============================================================================
CREATE TABLE IF NOT EXISTS pattern_observations (
    observation_id TEXT PRIMARY KEY,
    pattern_hash TEXT NOT NULL,  -- Hash of pattern signature for deduplication
    pattern_type TEXT NOT NULL,
    description TEXT NOT NULL,
    run_id TEXT NOT NULL,
    trace_id TEXT,
    file_path TEXT,
    line_range TEXT,  -- e.g., "10-25"
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_pattern_observations_hash ON pattern_observations(pattern_hash);
CREATE INDEX IF NOT EXISTS idx_pattern_observations_run_id ON pattern_observations(run_id);
CREATE INDEX IF NOT EXISTS idx_pattern_observations_type ON pattern_observations(pattern_type);
CREATE INDEX IF NOT EXISTS idx_pattern_observations_observed_at ON pattern_observations(observed_at DESC);

-- Unique constraint to prevent duplicate observations in same run
CREATE UNIQUE INDEX IF NOT EXISTS idx_pattern_observations_unique
    ON pattern_observations(pattern_hash, run_id);

-- ============================================================================
-- Comments for documentation
-- ============================================================================
COMMENT ON TABLE reflection_patterns IS 'Extracted patterns from trace analysis for behavior mining';
COMMENT ON TABLE behavior_candidates IS 'Proposed behaviors awaiting approval per AGENTS.md lifecycle';
COMMENT ON TABLE reflection_sessions IS 'Reflection analysis session tracking';
COMMENT ON TABLE pattern_observations IS 'Pattern occurrence tracking for 3+ threshold escalation';

COMMENT ON COLUMN behavior_candidates.confidence IS '0.0-1.0 score; >=0.8 eligible for auto-approval';
COMMENT ON COLUMN behavior_candidates.role IS 'Proposed execution role: student, teacher, or strategist';
COMMENT ON COLUMN behavior_candidates.status IS 'Lifecycle state: proposed -> approved/rejected -> merged';
