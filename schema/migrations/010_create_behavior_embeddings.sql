-- guideAI BehaviorRetriever pgvector integration
-- Creates behavior_embeddings table for semantic search with cosine similarity.
-- Enables multi-node consistency and transactional integrity for embeddings.
-- Part of Phase 4 Retrieval Engine pgvector migration (Phase 1: Preparation)

BEGIN;

-- Enable pgvector extension (provides vector data type and similarity operators)
CREATE EXTENSION IF NOT EXISTS vector;

-- Create behavior_embeddings table for semantic search
CREATE TABLE IF NOT EXISTS behavior_embeddings (
    behavior_id UUID NOT NULL,
    version TEXT NOT NULL,
    embedding vector(1024),  -- BGE-M3 dimension (1024-dim normalized vectors)

    -- Cached behavior metadata for retrieval efficiency
    name TEXT NOT NULL,
    instruction TEXT NOT NULL,
    description TEXT,
    role_focus TEXT NOT NULL,
    tags JSONB DEFAULT '[]'::jsonb,
    trigger_keywords JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    citation_label TEXT,

    -- Audit fields
    embedding_checksum TEXT,  -- Hash of embedding bytes for consistency validation
    model_name TEXT NOT NULL DEFAULT 'BAAI/bge-m3',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Primary key on (behavior_id, version) to support version history
    PRIMARY KEY (behavior_id, version),

    -- Foreign key to behavior_versions for referential integrity
    CONSTRAINT fk_behavior_version
        FOREIGN KEY (behavior_id, version)
        REFERENCES behavior_versions(behavior_id, version)
        ON DELETE CASCADE
);

-- IVFFlat index for fast cosine similarity search (approximate nearest neighbor)
-- Lists parameter: sqrt(num_rows) is recommended starting point
-- For 15K behaviors: sqrt(15000) ≈ 122, round to 100
-- Adjust lists parameter when corpus grows beyond 60K behaviors (per RETRIEVAL_ENGINE_PERFORMANCE.md)
CREATE INDEX IF NOT EXISTS idx_behavior_embeddings_vector_cosine
    ON behavior_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Additional indexes for metadata filtering and retrieval
CREATE INDEX IF NOT EXISTS idx_behavior_embeddings_role_focus
    ON behavior_embeddings (role_focus);

CREATE INDEX IF NOT EXISTS idx_behavior_embeddings_updated_at
    ON behavior_embeddings (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_behavior_embeddings_model_name
    ON behavior_embeddings (model_name);

-- GIN indexes for JSONB columns to support tag/keyword filtering
CREATE INDEX IF NOT EXISTS idx_behavior_embeddings_tags_gin
    ON behavior_embeddings
    USING GIN (tags jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_behavior_embeddings_trigger_keywords_gin
    ON behavior_embeddings
    USING GIN (trigger_keywords jsonb_path_ops);

-- Comments for documentation
COMMENT ON TABLE behavior_embeddings IS
'Stores BGE-M3 embeddings (1024-dim) for semantic behavior retrieval. Uses pgvector extension with IVFFlat index for approximate nearest neighbor search. Supports multi-node consistency and transactional updates. Part of Phase 4 Retrieval Engine optimization (VECTOR_STORE_PERSISTENCE.md).';

COMMENT ON COLUMN behavior_embeddings.embedding IS
'1024-dimensional L2-normalized embedding vector from BGE-M3 model. Indexed with IVFFlat for cosine similarity search (1 - cosine_distance = similarity).';

COMMENT ON COLUMN behavior_embeddings.embedding_checksum IS
'SHA-256 hash of embedding bytes for validating consistency between filesystem and database during dual-write migration.';

COMMIT;
