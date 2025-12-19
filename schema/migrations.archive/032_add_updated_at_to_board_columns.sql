-- Migration 032: Add updated_at to board_columns
-- Created: 2025-12-11
-- Purpose: Align board_columns schema with BoardService expectations (updated_at support)

ALTER TABLE board_columns
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Backfill for existing rows (if any). If the column already existed, this is a no-op.
UPDATE board_columns
SET updated_at = COALESCE(updated_at, created_at, NOW());
