# PostgreSQL Migration Dry-Run Rehearsal

Generated: 2025-10-24T22:14:25.605543+00:00

## BehaviorService

### Schema Dry-Run
- Command: `/Users/nick/miniconda3/bin/python /Users/nick/guideai/scripts/run_postgres_behavior_migration.py --dsn postgresql://localhost:5432/guideai_behavior_dev --dry-run`
- Duration: 0.04s
- Exit code: 0

### Data Dry-Run
- Command: `/Users/nick/miniconda3/bin/python /Users/nick/guideai/scripts/migrate_behavior_sqlite_to_postgres.py --dsn postgresql://localhost:5432/guideai_behavior_dev --sqlite-path /Users/nick/.guideai/data/behaviors.db --dry-run`
- Duration: 0.146s
- Exit code: 0

## WorkflowService

### Schema Dry-Run
- Command: `/Users/nick/miniconda3/bin/python /Users/nick/guideai/scripts/run_postgres_workflow_migration.py --dsn postgresql://localhost:5432/guideai_workflow_dev --dry-run`
- Duration: 0.025s
- Exit code: 0

### Data Dry-Run
- Command: `/Users/nick/miniconda3/bin/python /Users/nick/guideai/scripts/migrate_workflow_sqlite_to_postgres.py --dsn postgresql://localhost:5432/guideai_workflow_dev --sqlite-path /Users/nick/.guideai/workflows.db --dry-run`
- Duration: 0.049s
- Exit code: 0
