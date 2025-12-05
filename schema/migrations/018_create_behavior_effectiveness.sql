-- Migration: Create behavior effectiveness tracking tables
-- Version: 018
-- Description: Add tables for behavior feedback, benchmarks, and effectiveness metrics

-- Behavior feedback table for curator/user feedback
CREATE TABLE IF NOT EXISTS behavior_feedback (
    feedback_id UUID PRIMARY KEY,
    behavior_id UUID NOT NULL REFERENCES behaviors(behavior_id) ON DELETE CASCADE,
    relevance_score INTEGER NOT NULL CHECK (relevance_score >= 1 AND relevance_score <= 5),
    helpfulness_score INTEGER CHECK (helpfulness_score >= 1 AND helpfulness_score <= 5),
    token_reduction_observed FLOAT,
    comment TEXT,
    actor_id TEXT NOT NULL,
    context JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for feedback queries
CREATE INDEX IF NOT EXISTS idx_behavior_feedback_behavior_id
    ON behavior_feedback(behavior_id);
CREATE INDEX IF NOT EXISTS idx_behavior_feedback_actor_id
    ON behavior_feedback(actor_id);
CREATE INDEX IF NOT EXISTS idx_behavior_feedback_created_at
    ON behavior_feedback(created_at DESC);

-- Behavior benchmark results table
CREATE TABLE IF NOT EXISTS behavior_benchmarks (
    benchmark_id UUID PRIMARY KEY,
    run_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    corpus_size INTEGER NOT NULL DEFAULT 0,
    sample_size INTEGER NOT NULL DEFAULT 0,
    avg_retrieval_latency_ms FLOAT NOT NULL DEFAULT 0,
    p95_retrieval_latency_ms FLOAT NOT NULL DEFAULT 0,
    p99_retrieval_latency_ms FLOAT NOT NULL DEFAULT 0,
    accuracy_at_k JSONB DEFAULT '{}',  -- e.g., {"k1": 0.85, "k3": 0.92, "k5": 0.95}
    recall_at_k JSONB DEFAULT '{}',
    actor_id TEXT NOT NULL DEFAULT 'system',
    metadata JSONB DEFAULT '{}',
    status TEXT DEFAULT 'COMPLETED' CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED'))
);

-- Index for benchmark queries
CREATE INDEX IF NOT EXISTS idx_behavior_benchmarks_run_date
    ON behavior_benchmarks(run_date DESC);
CREATE INDEX IF NOT EXISTS idx_behavior_benchmarks_status
    ON behavior_benchmarks(status);

-- Behavior usage tracking (for counting retrieval usage)
CREATE TABLE IF NOT EXISTS behavior_usage (
    usage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    behavior_id UUID NOT NULL REFERENCES behaviors(behavior_id) ON DELETE CASCADE,
    run_id UUID,
    action_id UUID,
    query TEXT,
    rank_position INTEGER,  -- Position in retrieval results (1-indexed)
    was_selected BOOLEAN DEFAULT false,  -- Whether user selected/used this behavior
    token_count_before INTEGER,
    token_count_after INTEGER,
    actor_id TEXT NOT NULL,
    surface TEXT DEFAULT 'api',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for usage queries
CREATE INDEX IF NOT EXISTS idx_behavior_usage_behavior_id
    ON behavior_usage(behavior_id);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_created_at
    ON behavior_usage(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_run_id
    ON behavior_usage(run_id) WHERE run_id IS NOT NULL;

-- Aggregated metrics view for dashboard queries
CREATE OR REPLACE VIEW behavior_effectiveness_summary AS
SELECT
    b.behavior_id,
    b.name,
    b.status,
    b.updated_at,
    COALESCE(usage.total_usage, 0) as total_usage,
    COALESCE(usage.selection_rate, 0) as selection_rate,
    COALESCE(feedback.avg_relevance, 0) as avg_relevance,
    COALESCE(feedback.avg_helpfulness, 0) as avg_helpfulness,
    COALESCE(feedback.avg_token_reduction, 0) as avg_token_reduction,
    COALESCE(feedback.feedback_count, 0) as feedback_count
FROM behaviors b
LEFT JOIN (
    SELECT
        behavior_id,
        COUNT(*) as total_usage,
        AVG(CASE WHEN was_selected THEN 1.0 ELSE 0.0 END) as selection_rate
    FROM behavior_usage
    GROUP BY behavior_id
) usage ON b.behavior_id = usage.behavior_id
LEFT JOIN (
    SELECT
        behavior_id,
        AVG(relevance_score) as avg_relevance,
        AVG(helpfulness_score) as avg_helpfulness,
        AVG(token_reduction_observed) as avg_token_reduction,
        COUNT(*) as feedback_count
    FROM behavior_feedback
    GROUP BY behavior_id
) feedback ON b.behavior_id = feedback.behavior_id;

-- Comments for documentation
COMMENT ON TABLE behavior_feedback IS 'Curator and user feedback for behavior effectiveness';
COMMENT ON TABLE behavior_benchmarks IS 'Benchmark results for behavior retrieval performance';
COMMENT ON TABLE behavior_usage IS 'Tracking of behavior retrievals and selections';
COMMENT ON VIEW behavior_effectiveness_summary IS 'Aggregated view of behavior effectiveness metrics';
