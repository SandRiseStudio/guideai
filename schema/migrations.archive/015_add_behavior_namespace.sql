-- Add namespace column to behaviors table
-- Default to 'core' for existing behaviors to maintain backward compatibility

ALTER TABLE behaviors ADD COLUMN IF NOT EXISTS namespace TEXT NOT NULL DEFAULT 'core';

-- Create index for faster filtering by namespace
CREATE INDEX IF NOT EXISTS idx_behaviors_namespace ON behaviors(namespace);

-- Comment on column
COMMENT ON COLUMN behaviors.namespace IS 'Logical grouping for behaviors (e.g., core, project-x, team-y)';
