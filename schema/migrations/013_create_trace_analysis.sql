-- Migration 013: TraceAnalysisService PostgreSQL schema
-- Implements automated behavior extraction from execution traces (PRD Component B)
-- Created: 2025-10-30
-- Purpose: Pattern detection, reusability scoring, and extraction job tracking

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- Table 1: Trace Patterns
-- Purpose: Store recurring reasoning patterns detected across multiple runs
-- PRD Requirements: detect_patterns() output with frequency tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS trace_patterns (
    pattern_id UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,

    -- Pattern definition
    sequence JSONB NOT NULL, -- Array of normalized step texts
    sequence_length INTEGER GENERATED ALWAYS AS (jsonb_array_length(sequence)) STORED,

    -- Occurrence tracking
    frequency INTEGER NOT NULL DEFAULT 1 CHECK (frequency >= 1),
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Run references
    extracted_from_runs JSONB NOT NULL DEFAULT '[]'::jsonb, -- Array of run_id strings

    -- Computed metrics (updated on each occurrence)
    avg_tokens_per_step DECIMAL(10,2) DEFAULT 0.0,
    total_token_count INTEGER DEFAULT 0,

    -- Reusability scores (updated by score_reusability())
    frequency_score DECIMAL(5,3) DEFAULT NULL CHECK (frequency_score >= 0 AND frequency_score <= 1),
    token_savings_score DECIMAL(5,3) DEFAULT NULL CHECK (token_savings_score >= 0 AND token_savings_score <= 1),
    applicability_score DECIMAL(5,3) DEFAULT NULL CHECK (applicability_score >= 0 AND applicability_score <= 1),
    overall_score DECIMAL(5,3) DEFAULT NULL CHECK (overall_score >= 0 AND overall_score <= 1),
    last_scored_at TIMESTAMPTZ,

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb, -- task_types, domains, avg_completion_time

    -- Audit timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_trace_patterns_frequency ON trace_patterns (frequency DESC);
CREATE INDEX idx_trace_patterns_overall_score ON trace_patterns (overall_score DESC NULLS LAST);
CREATE INDEX idx_trace_patterns_last_seen ON trace_patterns (last_seen DESC);
CREATE INDEX idx_trace_patterns_sequence_length ON trace_patterns (sequence_length);

-- GIN index for JSONB sequence similarity queries
CREATE INDEX idx_trace_patterns_sequence ON trace_patterns USING GIN (sequence);
CREATE INDEX idx_trace_patterns_runs ON trace_patterns USING GIN (extracted_from_runs);

-- ============================================================================
-- Table 2: Pattern Occurrences
-- Purpose: Track each occurrence of a pattern in specific runs (evidence trail)
-- PRD Requirements: Link patterns to runs for token savings calculation
-- ============================================================================

CREATE TABLE IF NOT EXISTS pattern_occurrences (
    occurrence_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    occurrence_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Pattern linkage
    pattern_id UUID NOT NULL REFERENCES trace_patterns(pattern_id) ON DELETE CASCADE,

    -- Run linkage
    run_id UUID NOT NULL, -- Foreign key to run_service.runs (soft reference)

    -- Position in trace
    start_step_index INTEGER NOT NULL CHECK (start_step_index >= 0),
    end_step_index INTEGER NOT NULL CHECK (end_step_index >= start_step_index),
    step_span INTEGER GENERATED ALWAYS AS (end_step_index - start_step_index + 1) STORED,

    -- Context for disambiguation
    context_before JSONB DEFAULT '[]'::jsonb, -- Array of previous steps
    context_after JSONB DEFAULT '[]'::jsonb, -- Array of following steps

    -- Token accounting
    token_count INTEGER NOT NULL DEFAULT 0,

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb, -- task_type, domain, trace_format

    -- Composite primary key (partitioned by time for TimescaleDB compatibility)
    PRIMARY KEY (occurrence_id, occurrence_time)
);

-- Indexes for retrieval patterns
CREATE INDEX idx_occurrences_pattern_time ON pattern_occurrences (pattern_id, occurrence_time DESC);
CREATE INDEX idx_occurrences_run ON pattern_occurrences (run_id);
CREATE INDEX idx_occurrences_time ON pattern_occurrences (occurrence_time DESC);

-- GIN indexes for context searches
CREATE INDEX idx_occurrences_context_before ON pattern_occurrences USING GIN (context_before);
CREATE INDEX idx_occurrences_context_after ON pattern_occurrences USING GIN (context_after);

-- ============================================================================
-- Table 3: Extraction Jobs
-- Purpose: Track batch extraction jobs for nightly reflection and audit trail
-- PRD Requirements: Monitor extraction_rate (≥5 per 100 runs), job status
-- ============================================================================

CREATE TABLE IF NOT EXISTS extraction_jobs (
    job_id UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,

    -- Job lifecycle
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETE', 'FAILED')) DEFAULT 'PENDING',
    start_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_time TIMESTAMPTZ,
    duration_seconds DECIMAL(10,2) GENERATED ALWAYS AS (
        CASE
            WHEN end_time IS NOT NULL THEN EXTRACT(EPOCH FROM (end_time - start_time))
            ELSE NULL
        END
    ) STORED,

    -- Processing metrics
    runs_analyzed INTEGER NOT NULL DEFAULT 0,
    patterns_found INTEGER NOT NULL DEFAULT 0,
    candidates_generated INTEGER NOT NULL DEFAULT 0,

    -- PRD Success Metric: Extraction Rate (Target: 5 per 100 runs = 0.05)
    extraction_rate DECIMAL(5,4) GENERATED ALWAYS AS (
        CASE
            WHEN runs_analyzed > 0 THEN ROUND(candidates_generated::DECIMAL / runs_analyzed, 4)
            ELSE 0.0
        END
    ) STORED,

    -- Error handling
    error_message TEXT,
    error_trace TEXT,

    -- Job configuration
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb, -- date_range, filters, min_frequency, min_similarity

    -- Audit
    created_by TEXT, -- service account or user_id
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for job monitoring
CREATE INDEX idx_extraction_jobs_status ON extraction_jobs (status, start_time DESC);
CREATE INDEX idx_extraction_jobs_start_time ON extraction_jobs (start_time DESC);
CREATE INDEX idx_extraction_jobs_extraction_rate ON extraction_jobs (extraction_rate DESC);

-- ============================================================================
-- Table 4: Reflection Candidates (Links to Patterns)
-- Purpose: Track candidates generated from high-scoring patterns for approval workflow
-- PRD Requirements: 80% approval rate tracking, duplicate detection
-- ============================================================================

CREATE TABLE IF NOT EXISTS reflection_candidates (
    candidate_id UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,

    -- Pattern linkage
    pattern_id UUID NOT NULL REFERENCES trace_patterns(pattern_id) ON DELETE CASCADE,
    extraction_job_id UUID NOT NULL REFERENCES extraction_jobs(job_id) ON DELETE CASCADE,

    -- Candidate definition (aligned with ReflectionCandidate contract)
    slug TEXT NOT NULL,
    display_name TEXT NOT NULL,
    instruction TEXT NOT NULL,
    supporting_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Quality scores (inherited from pattern)
    overall_score DECIMAL(5,3) NOT NULL CHECK (overall_score >= 0 AND overall_score <= 1),
    confidence DECIMAL(5,3) NOT NULL DEFAULT 0.8,

    -- Approval workflow
    approval_status TEXT NOT NULL CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED', 'DUPLICATE')) DEFAULT 'PENDING',
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    rejection_reason TEXT,

    -- Duplicate detection
    duplicate_of_behavior_id UUID, -- Reference to existing behavior in behavior_service
    duplicate_of_behavior_name TEXT,

    -- Behavior creation (if approved)
    created_behavior_id UUID, -- Reference to behavior_service.behaviors

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for approval workflow
CREATE INDEX idx_candidates_approval_status ON reflection_candidates (approval_status, created_at DESC);
CREATE INDEX idx_candidates_pattern ON reflection_candidates (pattern_id);
CREATE INDEX idx_candidates_job ON reflection_candidates (extraction_job_id);
CREATE INDEX idx_candidates_overall_score ON reflection_candidates (overall_score DESC);
CREATE INDEX idx_candidates_slug ON reflection_candidates (slug);

-- GIN index for tag searches
CREATE INDEX idx_candidates_tags ON reflection_candidates USING GIN (tags);

-- ============================================================================
-- Functions and Triggers
-- ============================================================================

-- Trigger: Update trace_patterns.updated_at on modification
CREATE OR REPLACE FUNCTION update_trace_patterns_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trace_patterns_updated_at
    BEFORE UPDATE ON trace_patterns
    FOR EACH ROW
    EXECUTE FUNCTION update_trace_patterns_timestamp();

-- Trigger: Update reflection_candidates.updated_at on modification
CREATE OR REPLACE FUNCTION update_reflection_candidates_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER reflection_candidates_updated_at
    BEFORE UPDATE ON reflection_candidates
    FOR EACH ROW
    EXECUTE FUNCTION update_reflection_candidates_timestamp();

-- Function: Calculate pattern similarity (Jaccard index for sequence overlap)
CREATE OR REPLACE FUNCTION calculate_pattern_similarity(seq1 JSONB, seq2 JSONB)
RETURNS DECIMAL AS $$
DECLARE
    intersection_size INTEGER;
    union_size INTEGER;
BEGIN
    -- Convert JSONB arrays to sets and calculate Jaccard index
    WITH seq1_set AS (SELECT jsonb_array_elements_text(seq1) AS step),
         seq2_set AS (SELECT jsonb_array_elements_text(seq2) AS step),
         intersection AS (SELECT COUNT(*) AS cnt FROM seq1_set INTERSECT SELECT * FROM seq2_set),
         union_set AS (SELECT COUNT(*) AS cnt FROM seq1_set UNION SELECT * FROM seq2_set)
    SELECT
        COALESCE((SELECT cnt FROM intersection), 0) INTO intersection_size;
    SELECT
        COALESCE((SELECT cnt FROM union_set), 1) INTO union_size;

    RETURN ROUND(intersection_size::DECIMAL / NULLIF(union_size, 0), 3);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- Views for Common Queries
-- ============================================================================

-- View: High-Value Patterns (overall_score > 0.7, frequency ≥ 3)
CREATE OR REPLACE VIEW high_value_patterns AS
SELECT
    pattern_id,
    sequence,
    sequence_length,
    frequency,
    overall_score,
    frequency_score,
    token_savings_score,
    applicability_score,
    first_seen,
    last_seen,
    jsonb_array_length(extracted_from_runs) AS run_count,
    metadata
FROM trace_patterns
WHERE overall_score > 0.7
  AND frequency >= 3
ORDER BY overall_score DESC, frequency DESC;

-- View: Recent Extraction Jobs Summary
CREATE OR REPLACE VIEW extraction_jobs_summary AS
SELECT
    job_id,
    status,
    start_time,
    end_time,
    duration_seconds,
    runs_analyzed,
    patterns_found,
    candidates_generated,
    extraction_rate,
    CASE
        WHEN extraction_rate >= 0.05 THEN 'MEETS_TARGET'
        WHEN extraction_rate >= 0.03 THEN 'BELOW_TARGET'
        ELSE 'CRITICAL'
    END AS performance_rating,
    metadata->>'date_range' AS date_range
FROM extraction_jobs
ORDER BY start_time DESC;

-- View: Approval Funnel Metrics (for dashboard)
CREATE OR REPLACE VIEW approval_funnel AS
SELECT
    COUNT(*) FILTER (WHERE approval_status = 'PENDING') AS pending_count,
    COUNT(*) FILTER (WHERE approval_status = 'APPROVED') AS approved_count,
    COUNT(*) FILTER (WHERE approval_status = 'REJECTED') AS rejected_count,
    COUNT(*) FILTER (WHERE approval_status = 'DUPLICATE') AS duplicate_count,
    COUNT(*) AS total_candidates,
    ROUND(
        COUNT(*) FILTER (WHERE approval_status = 'APPROVED')::DECIMAL
        / NULLIF(COUNT(*) FILTER (WHERE approval_status IN ('APPROVED', 'REJECTED')), 0)
        * 100,
        2
    ) AS approval_rate_pct, -- PRD Target: 80%
    ROUND(
        COUNT(*) FILTER (WHERE approval_status = 'DUPLICATE')::DECIMAL
        / NULLIF(COUNT(*), 0)
        * 100,
        2
    ) AS duplicate_reduction_pct -- PRD Target: 50%
FROM reflection_candidates;

-- ============================================================================
-- Sample Data (for testing)
-- ============================================================================

-- Insert sample pattern for testing
DO $$
DECLARE
    v_pattern_id UUID;
BEGIN
    INSERT INTO trace_patterns (
        sequence,
        frequency,
        first_seen,
        last_seen,
        extracted_from_runs,
        avg_tokens_per_step,
        overall_score,
        frequency_score,
        token_savings_score,
        applicability_score,
        metadata
    ) VALUES (
        '["Identify key variables from problem statement", "Set up equations using standard formulas", "Solve system of equations step-by-step", "Verify solution against constraints"]'::jsonb,
        12,
        NOW() - INTERVAL '30 days',
        NOW() - INTERVAL '2 days',
        '["run-123", "run-456", "run-789"]'::jsonb,
        15.5,
        0.82,
        0.75,
        0.88,
        0.85,
        '{"task_types": ["math", "word_problems"], "domains": ["algebra"], "avg_completion_time": 45.3}'::jsonb
    ) RETURNING pattern_id INTO v_pattern_id;

    RAISE NOTICE 'Created sample pattern: %', v_pattern_id;
END $$;

-- Grant permissions (adjust for production deployment)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO guideai_service;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guideai_service;

-- ============================================================================
-- Migration Verification
-- ============================================================================

-- Verify tables created
SELECT 'trace_patterns' AS table_name, COUNT(*) AS row_count FROM trace_patterns
UNION ALL
SELECT 'pattern_occurrences', COUNT(*) FROM pattern_occurrences
UNION ALL
SELECT 'extraction_jobs', COUNT(*) FROM extraction_jobs
UNION ALL
SELECT 'reflection_candidates', COUNT(*) FROM reflection_candidates;

-- Verify views created
SELECT 'high_value_patterns' AS view_name, COUNT(*) AS row_count FROM high_value_patterns
UNION ALL
SELECT 'extraction_jobs_summary', COUNT(*) FROM extraction_jobs_summary
UNION ALL
SELECT 'approval_funnel', COUNT(*) FROM approval_funnel;
