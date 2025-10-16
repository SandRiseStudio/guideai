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
| Secret scanning guardrails | Security + Engineering | ✅ Completed | `.pre-commit-config.yaml`, `scripts/scan_secrets.sh`, `scripts/install_hooks.sh`, `guideai/cli.py`, `mcp/tools/security.scanSecrets.json`, `.github/workflows/ci.yml`, `SECRETS_MANAGEMENT_PLAN.md`, `AGENTS.md` |
| Git governance playbook | DX + Engineering | ✅ Completed | `docs/GIT_STRATEGY.md`, `AGENTS.md`, `PRD_ALIGNMENT_LOG.md`, `BUILD_TIMELINE.md` |
| CI/CD guardrails & DevOps playbook | Engineering + DX | ✅ Completed | `.github/workflows/ci.yml`, `docs/AGENT_DEVOPS.md`, `AGENTS.md`, `docs/capability_matrix.md` |
| SDK scope & distribution plan | Engineering | ✅ Completed | `docs/SDK_SCOPE.md`, `PRD.md`, `docs/capability_matrix.md`, `PRD_NEXT_STEPS.md` |

## Milestone 1 – Internal Alpha (Planned)
| Work Item | Owner | Status | Notes |
| --- | --- | --- | --- |
| Onboarding quickstarts | DX + Engineering | ✅ Completed | `docs/ONBOARDING_QUICKSTARTS.md`, onboarding telemetry metrics, `docs/capability_matrix.md` row |
| Behavior versioning & migrations | Engineering | ✅ Completed | `docs/BEHAVIOR_VERSIONING.md`, `PRD.md` Data Model update, `docs/capability_matrix.md` evidence |
| Reproducible build runbook | Product + DX | ✅ Completed | `docs/README.md`, `BUILD_TIMELINE.md` entry #30, `PRD_ALIGNMENT_LOG.md` |
| Compliance control matrix | Compliance + Security | ✅ Completed | `docs/COMPLIANCE_CONTROL_MATRIX.md`, `PRD_ALIGNMENT_LOG.md`, `BUILD_TIMELINE.md` entry #31 |
| Onboarding telemetry ingestion | DX + Engineering | ✅ Completed | `docs/analytics/onboarding_adoption_snapshot.md`, `dashboard/src/hooks/useOnboardingTelemetry.ts`, `dashboard/src/components/OnboardingDashboard.tsx` |
| CLI/API action parity | Engineering + DX | ✅ Completed | `guideai/cli.py`, `guideai/adapters.py`, `tests/test_cli_actions.py` |
| Policy deployment runbook | Security + Product | ✅ Completed | `docs/POLICY_DEPLOYMENT_RUNBOOK.md`, `PRD_ALIGNMENT_LOG.md`, `BUILD_TIMELINE.md` entry #34 |
| VS Code extension preview | DX + Engineering | ⏳ Planned | Capability matrix row created; roadmap tasks in `PRD_NEXT_STEPS.md` |
| Checklist automation | Engineering | ✅ Completed | `COMPLIANCE_SERVICE_CONTRACT.md`, `guideai/compliance_service.py`, `guideai/adapters.py` (REST/CLI/MCP), `guideai/cli.py`, `tests/test_compliance_service_parity.py` (17 tests passed) — CMD-008 |
| Initial analytics dashboards | Product Analytics | ⏳ Planned | Requires telemetry pipeline deployment |
| Consent & MFA telemetry dashboards | DX + Analytics | ✅ Completed | `dashboard/src/app.tsx`, `dashboard/src/hooks/useConsentTelemetry.ts`, `docs/analytics/consent_mfa_snapshot.md` |
| MFA re-prompt validation dry-run | Security + Compliance + DX | ✅ Completed | `docs/analytics/mfa_usability_validation_plan.md` (Validation Execution – 2025-10-15) |
| Task assignment orchestration | Product + Engineering + DX | ✅ Completed | `guideai/task_assignments.py`, `ACTION_REGISTRY_SPEC.md`, `mcp/tools/tasks.listAssignments.json`, `PRD_NEXT_STEPS.md`, `docs/capability_matrix.md` |
| BehaviorService runtime & CLI parity | Engineering + Platform | 🚧 In Progress | SQLite-backed `guideai/behavior_service.py`, CLI adapters & commands in `guideai/cli.py` (`behaviors` group), regression coverage in `tests/test_cli_behaviors.py`, governance updates (`BUILD_TIMELINE.md` #39, `docs/capability_matrix.md`) |

## Action logging checklist
- [x] `guideai record-action --artifact PROGRESS_TRACKER.md --summary "Update capability matrix status" --behaviors behavior_update_docs_after_changes behavior_handbook_compliance_prompt` (CMD-001)
- [x] `guideai record-action --artifact PROGRESS_TRACKER.md --summary "Implement ActionService stubs and parity tests" --behaviors behavior_wire_cli_to_orchestrator behavior_instrument_metrics_pipeline` (CMD-002)
- [x] `guideai record-action --artifact dashboard --summary "Launch Milestone Zero dashboard" --behaviors behavior_wire_cli_to_orchestrator behavior_product_signal_alignment` (CMD-003)
- [x] `guideai record-action --artifact docs/AGENT_AUTH_ARCHITECTURE.md --summary "Publish Agent Auth architecture" --behaviors behavior_lock_down_security_surface behavior_update_docs_after_changes` (CMD-004)
- [x] `guideai agents review --artifact docs/AGENT_AUTH_ARCHITECTURE.md --scope engineering,dx,compliance,product --behaviors behavior_handbook_compliance_prompt behavior_update_docs_after_changes` (CMD-005)
- [x] `guideai record-action --artifact proto/agentauth/v1/agent_auth.proto --summary "Ship AgentAuth Phase A contract artifacts" --behaviors behavior_wire_cli_to_orchestrator behavior_update_docs_after_changes` (CMD-006)
- [x] `guideai record-action --artifact docs/CONSENT_UX_PROTOTYPE.md --summary "Draft consent UX prototypes and testing plan" --behaviors behavior_product_signal_alignment behavior_update_docs_after_changes behavior_prototype_consent_ux` (CMD-007)
- [x] `guideai record-action --artifact guideai/compliance_service.py --summary "Implement Checklist Automation Engine with cross-surface parity" --behaviors behavior_unify_execution_records behavior_wire_cli_to_orchestrator behavior_update_docs_after_changes` (CMD-008)
- [ ] `guideai record-action --artifact guideai/behavior_service.py --summary "Ship BehaviorService runtime + CLI parity" --behaviors behavior_wire_cli_to_orchestrator behavior_curate_behavior_handbook behavior_update_docs_after_changes`
- [ ] `guideai record-action --artifact guideai/cli.py --summary "Wire CLI action parity commands" --behaviors behavior_wire_cli_to_orchestrator behavior_update_docs_after_changes`
- [ ] `guideai record-action --artifact docs/analytics/mfa_usability_validation_plan.md --summary "Publish MFA re-prompt validation playbook" --behaviors behavior_prototype_consent_ux behavior_instrument_metrics_pipeline behavior_update_docs_after_changes`
- [ ] `guideai record-action --artifact docs/analytics/mfa_usability_validation_plan.md --summary "Run MFA validation dry-run" --behaviors behavior_prototype_consent_ux behavior_instrument_metrics_pipeline behavior_update_docs_after_changes`
- [ ] `guideai record-action --artifact guideai/task_assignments.py --summary "Publish task assignment registry" --behaviors behavior_wire_cli_to_orchestrator behavior_update_docs_after_changes behavior_curate_behavior_handbook`
- [ ] `guideai record-action --artifact docs/ONBOARDING_QUICKSTARTS.md --summary "Publish cross-surface onboarding quickstarts" --behaviors behavior_update_docs_after_changes behavior_wire_cli_to_orchestrator behavior_product_signal_alignment`
- [ ] `guideai record-action --artifact docs/BEHAVIOR_VERSIONING.md --summary "Document behavior versioning strategy" --behaviors behavior_curate_behavior_handbook behavior_update_docs_after_changes`
- [ ] `guideai record-action --artifact dashboard/src/app.tsx --summary "Wire consent/MFA dashboard to telemetry" --behaviors behavior_instrument_metrics_pipeline behavior_update_docs_after_changes`
- [ ] `guideai record-action --artifact .github/workflows/ci.yml --summary "Stand up CI/CD guardrails for pre-commit + tests" --behaviors behavior_orchestrate_cicd behavior_update_docs_after_changes`
- [ ] `guideai record-action --artifact docs/AGENT_DEVOPS.md --summary "Document DevOps agent responsibilities" --behaviors behavior_orchestrate_cicd behavior_update_docs_after_changes`
- [ ] `guideai scan-secrets --format json --fail-on-findings --output security/scan_reports/latest.json`
- [ ] `guideai record-action --artifact docs/POLICY_DEPLOYMENT_RUNBOOK.md --summary "Author policy deployment runbook" --behaviors behavior_orchestrate_cicd behavior_update_docs_after_changes behavior_lock_down_security_surface`

> Record each command above in the ActionService once the CLI is connected; include resulting `action_id` in the Evidence column when available.

_Last updated: 2025-10-15_
