# PostgreSQL Migration Dry-Run Rehearsal

Generated: 2025-10-25T00:44:32.426152+00:00

## BehaviorService

### Schema Dry-Run
- Command: `/Users/nick/miniconda3/bin/python /Users/nick/guideai/scripts/run_postgres_behavior_migration.py --dsn postgresql://guideai_behavior:dev_behavior_pass@localhost:5433/behaviors --dry-run`
- Duration: 0.243s
- Exit code: 0

### Data Dry-Run
- Command: `/Users/nick/miniconda3/bin/python /Users/nick/guideai/scripts/migrate_behavior_sqlite_to_postgres.py --dsn postgresql://guideai_behavior:dev_behavior_pass@localhost:5433/behaviors --sqlite-path /Users/nick/.guideai/data/behaviors.db --dry-run`
- Duration: 2.069s
- Exit code: 0

## WorkflowService

### Schema Dry-Run
- Command: `/Users/nick/miniconda3/bin/python /Users/nick/guideai/scripts/run_postgres_workflow_migration.py --dsn postgresql://guideai_workflow:dev_workflow_pass@localhost:5434/workflows --dry-run`
- Duration: 0.304s
- Exit code: 0

### Data Dry-Run
- Command: `/Users/nick/miniconda3/bin/python /Users/nick/guideai/scripts/migrate_workflow_sqlite_to_postgres.py --dsn postgresql://guideai_workflow:dev_workflow_pass@localhost:5434/workflows --sqlite-path /Users/nick/.guideai/workflows.db --dry-run`
- Duration: 0.616s
- Exit code: 0
