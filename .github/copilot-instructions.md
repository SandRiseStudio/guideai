# Copilot Instructions

Reference `AGENTS.md` for the full behavior handbook. This file provides quick triggers for common patterns.

## Quick Triggers

| Keywords | Behavior |
|----------|----------|
| MCP tool, MCP server, IDE extension | `behavior_prefer_mcp_tools` |
| logging, structured logs, telemetry sink | `behavior_use_raze_for_logging` |
| environment, blueprint, podman, container | `behavior_use_amprealize_for_environments` |
| standalone package, reusable service, extract module | `behavior_extract_standalone_package` |
| secret, credential, leak, gitleaks | `behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials` |
| execution record, SSE, progress, run status | `behavior_unify_execution_records` |
| storage adapter, audit log, timeline | `behavior_align_storage_layers` |
| config path, env var, secrets manager | `behavior_externalize_configuration` |
| action registry, `guideai record-action` | `behavior_sanitize_action_registry` |
| telemetry event, Kafka, metrics dashboard | `behavior_instrument_metrics_pipeline` |
| CORS, auth decorator, bearer token | `behavior_lock_down_security_surface` |
| git workflow, branching, merge policy | `behavior_git_governance` |
| ci pipeline, deployment, rollback | `behavior_orchestrate_cicd` |

## Key Principles

- **Logging**: Use **Raze** for all structured logging (`packages/raze/`)
- **Environments**: Use **Amprealize** for container/resource management (`packages/amprealize/`)
- **MCP-first**: When MCP tools are available, prefer them over manual CLI/API calls—they provide consistent schemas and automatic telemetry
- **Standalone-first**: When adding significant functionality, consider creating a standalone package under `packages/`
- **Testing**: Run `pytest` or `npm run build` after changes; record outcomes
- **Secrets**: Never hardcode; run `pre-commit` before pushing
- **Docs**: Update `README.md`, `PRD.md`, `BUILD_TIMELINE.md` when APIs/workflows change

## Standalone Package Pattern

When creating reusable functionality, follow the Raze/Amprealize model:
1. Create under `packages/<name>/` with zero guideai core dependencies
2. Use hooks/callbacks for integration points
3. Define optional extras: `[cli]`, `[fastapi]`, `[dev]`
4. Add thin wrapper in `guideai/<name>/` for service integration

For detailed behavior steps and compliance checklist, see `AGENTS.md`.

_Last synced with AGENTS.md: 2025-11-24_
