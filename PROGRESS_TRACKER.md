# Project Progress Tracker

> Maintained alongside `PRD_NEXT_STEPS.md`. Update this table whenever actions are completed and log the change via `guideai record-action`.

## Milestone 0 – Foundations
| Work Item | Owner | Status | Evidence |
| --- | --- | --- | --- |
| Behavior retriever performance targets | Engineering | ✅ Completed | `RETRIEVAL_ENGINE_PERFORMANCE.md` |
| Telemetry schema & retention policy | Engineering + Compliance | ✅ Completed | `TELEMETRY_SCHEMA.md` |
| Audit log storage plan | Compliance + Platform | ✅ Completed | `AUDIT_LOG_STORAGE.md` |
| Secrets management approach for CLI/SDK | Engineering + Compliance | ✅ Completed | `SECRETS_MANAGEMENT_PLAN.md` |
| ActionService contract draft | Engineering | ✅ Completed | `ACTION_SERVICE_CONTRACT.md` |
| Capability matrix doc | Platform | ✅ Completed | `docs/capability_matrix.md` (see action log CMD-001) |
| Contract scaffolding & SDK stubs | Engineering | ✅ Completed | `guideai/action_service.py`, `guideai/adapters.py`, `tests/test_action_service_parity.py` (action log CMD-002) |
| Delightful progress dashboard | Product + DX | ✅ Completed | `dashboard/` (action log CMD-003) |
| Agent auth architecture | Security + Engineering | ✅ Completed | `docs/AGENT_AUTH_ARCHITECTURE.md` (action log CMD-004) |
| Agent auth cross-team review | Product + Security + DX | ✅ Completed | `PRD_AGENT_REVIEWS.md` (2025-10-15) (action log CMD-005) |
| Agent auth Phase A contracts | Security + Engineering | ✅ Completed | Artifacts + SDK stubs: `proto/agentauth/v1/agent_auth.proto`, `schema/agentauth/v1/agent_auth.json`, `schema/agentauth/scope_catalog.yaml`, `policy/agentauth/bundle.yaml`, `mcp/tools/auth.*.json`, `guideai/agent_auth.py`, `tests/test_agent_auth_contracts.py` (pytest 2025-10-15) — CMD-006 |
| Agent auth consent UX planning | DX + Product | ✅ Completed | Prototype, usability findings, telemetry wiring in `docs/CONSENT_UX_PROTOTYPE.md`; mockups in `designs/consent/mockups.md`; compliance policy logged — CMD-007 |
| Cross-surface telemetry instrumentation | Engineering + DX | ✅ Completed | `dashboard/src/telemetry.ts`, `guideai/action_service.py`, `guideai/agent_auth.py`, `tests/test_telemetry_integration.py` (pytest 2025-10-15) |
| High-risk scope MFA policy | Security + Compliance | ✅ Completed | `schema/agentauth/scope_catalog.yaml`, `policy/agentauth/bundle.yaml`, `docs/AGENT_AUTH_ARCHITECTURE.md`, `docs/CONSENT_UX_PROTOTYPE.md` |
| MFA re-prompt validation playbook | Security + Compliance + DX | ✅ Completed | `docs/analytics/mfa_usability_validation_plan.md` (playbook for Milestone 1 readiness) |
| Secret scanning guardrails | Security + Engineering | ✅ Completed | `.pre-commit-config.yaml`, `scripts/scan_secrets.sh`, `ACTION_REGISTRY_SPEC.md`, `SECRETS_MANAGEMENT_PLAN.md`, `AGENTS.md` |
| Git governance playbook | DX + Engineering | ✅ Completed | `docs/GIT_STRATEGY.md`, `AGENTS.md`, `PRD_ALIGNMENT_LOG.md`, `BUILD_TIMELINE.md` |

## Milestone 1 – Internal Alpha (Planned)
| Work Item | Owner | Status | Notes |
| --- | --- | --- | --- |
| VS Code extension preview | DX + Engineering | ⏳ Planned | Capability matrix row created; roadmap tasks in `PRD_NEXT_STEPS.md` |
| Checklist automation | Engineering | ⏳ Planned | |
| Initial analytics dashboards | Product Analytics | ⏳ Planned | Requires telemetry pipeline deployment |

## Action logging checklist
- [x] `guideai record-action --artifact PROGRESS_TRACKER.md --summary "Update capability matrix status" --behaviors behavior_update_docs_after_changes behavior_handbook_compliance_prompt` (CMD-001)
- [x] `guideai record-action --artifact PROGRESS_TRACKER.md --summary "Implement ActionService stubs and parity tests" --behaviors behavior_wire_cli_to_orchestrator behavior_instrument_metrics_pipeline` (CMD-002)
- [x] `guideai record-action --artifact dashboard --summary "Launch Milestone Zero dashboard" --behaviors behavior_wire_cli_to_orchestrator behavior_product_signal_alignment` (CMD-003)
- [x] `guideai record-action --artifact docs/AGENT_AUTH_ARCHITECTURE.md --summary "Publish Agent Auth architecture" --behaviors behavior_lock_down_security_surface behavior_update_docs_after_changes` (CMD-004)
- [x] `guideai agents review --artifact docs/AGENT_AUTH_ARCHITECTURE.md --scope engineering,dx,compliance,product --behaviors behavior_handbook_compliance_prompt behavior_update_docs_after_changes` (CMD-005)
- [x] `guideai record-action --artifact proto/agentauth/v1/agent_auth.proto --summary "Ship AgentAuth Phase A contract artifacts" --behaviors behavior_wire_cli_to_orchestrator behavior_update_docs_after_changes` (CMD-006)
- [x] `guideai record-action --artifact docs/CONSENT_UX_PROTOTYPE.md --summary "Draft consent UX prototypes and testing plan" --behaviors behavior_product_signal_alignment behavior_update_docs_after_changes behavior_prototype_consent_ux` (CMD-007)
- [ ] `guideai record-action --artifact docs/analytics/mfa_usability_validation_plan.md --summary "Publish MFA re-prompt validation playbook" --behaviors behavior_prototype_consent_ux behavior_instrument_metrics_pipeline behavior_update_docs_after_changes`
- [ ] `guideai scan-secrets --format json --fail-on-findings --output security/scan_reports/latest.json`

> Record each command above in the ActionService once the CLI is connected; include resulting `action_id` in the Evidence column when available.

_Last updated: 2025-10-15_
