# PRD Follow-Up Actions (from Agent Reviews)

## Completed (Milestone 0)
- Retrieval engine performance targets and scaling plan documented in `RETRIEVAL_ENGINE_PERFORMANCE.md`.
- Telemetry schema, storage, and retention policy captured in `TELEMETRY_SCHEMA.md`.
- Audit log storage approach defined in `AUDIT_LOG_STORAGE.md`.
- Secrets management approach for CLI/SDK recorded in `SECRETS_MANAGEMENT_PLAN.md`.
- Initial `ActionService` contract published in `ACTION_SERVICE_CONTRACT.md`.
- Capability matrix scaffold created in `docs/capability_matrix.md` and release checklist updated (`MCP_SERVER_DESIGN.md`).
- ActionService gRPC/REST handler stubs, adapters, and parity tests added (`guideai/action_service.py`, `guideai/adapters.py`, `tests/test_action_service_parity.py`).
- Milestone Zero progress dashboard shipped under `dashboard/` to visualize PRD metrics from source artifacts.
- Cross-team AgentAuth architecture review completed and logged in `PRD_AGENT_REVIEWS.md` (2025-10-15) with follow-up actions captured in `docs/AGENT_AUTH_ARCHITECTURE.md` §§16-19.
- Agent Auth Phase A contract artifacts shipped (`proto/agentauth/v1/agent_auth.proto`, `schema/agentauth/v1/agent_auth.json`, `schema/agentauth/scope_catalog.yaml`, `policy/agentauth/bundle.yaml`, `mcp/tools/auth.*.json`, `guideai/agent_auth.py`, `tests/test_agent_auth_contracts.py`) — CMD-006 (2025-10-15).
- Consent UX prototypes, usability study recap, and telemetry wiring plan published (`docs/CONSENT_UX_PROTOTYPE.md`, `designs/consent/mockups.md`) — CMD-007 (2025-10-15).
- Cross-surface telemetry instrumentation shipped for dashboard, ActionService, and AgentAuth with automated coverage (`dashboard/src/telemetry.ts`, `guideai/action_service.py`, `guideai/agent_auth.py`, `tests/test_telemetry_integration.py`) — 2025-10-15.
- MFA enforcement defined for `high_risk` scopes (`actions.replay`, `agentauth.manage`) via scope catalog, policy bundle, and SDK updates (`schema/agentauth/scope_catalog.yaml`, `policy/agentauth/bundle.yaml`, `guideai/agent_auth.py`) — 2025-10-15.

## Immediate (Milestone 0)
_All immediate Milestone 0 actions are now complete; upcoming work tracked in Short-Term._

## Short-Term (Before Milestone 1 Gate)
- Clarify SDK scope (supported languages, versioning, distribution) and align with client integration plans (Engineering).
- Add behavior versioning/migration strategy to Data Model section (Engineering).
- Instrument onboarding and adoption metrics (time-to-first-behavior, checklist completion, behavior search-to-insert conversion) and ensure analytics can report on the PRD targets (70% behavior reuse, 30% token reduction, 80% task completion, 95% compliance log coverage) (DX + Engineering).
- Plan guided onboarding assets for VS Code/CLI (tutorials, templates) and assign documentation ownership with release cadence (DX).
- Document VS Code extension roadmap in `docs/capability_matrix.md` and keep parity evidence up to date before extension preview (DX + Engineering).
- Produce compliance control mapping matrix covering SOC2/GDPR obligations (Compliance).
- Deliver CLI/API parity for action capture and replay (`guideai record-action`, `guideai replay`, `/v1/actions/*`); add parity tests covering all surfaces (Engineering + DX).
- Publish reproducible build runbook in docs/README describing how to capture/replay build timeline (Product + DX).
- Execute policy deployment runbook outlined in `docs/AGENT_AUTH_ARCHITECTURE.md` §17, including GitOps workflow and rollback tooling (Security + Product).
- Stand up consent/MFA analytics dashboards leveraging the new telemetry events (DX + Analytics).
- Validate MFA re-prompt UX across surfaces and document monitoring hooks post-instrumentation (Security + Compliance) — execution playbook in `docs/analytics/mfa_usability_validation_plan.md`.
- Operationalize automated secret scanning across CLI/UI/CI surfaces (`guideai scan-secrets`, pre-commit hooks) and enforce remediation logging via ActionService (Security + Engineering).

## Mid-Term (Milestone 2 Planning)
- Gather external customer research or pilot commitments; update PRD with discovery insights (Product Strategy).
- Outline pricing/packaging experiments and GA gating criteria (Product Strategy).
- Identify multi-tenant behavior sharing considerations and include in open questions if pursued (Product Strategy + Engineering).
- Stand up analytics dashboard tracking action replay usage, parity health, PRD success metrics (behavior reuse %, token savings, task completion rate, compliance coverage), and checklist adherence (Product Strategy + Platform).

## Tracking & Governance
- Log resolutions for each action in issue tracker linked to `PRD_AGENT_REVIEWS.md`.
- Update `PRD.md` once actions are addressed; capture change history in Document Control.
- Re-run agent reviews after updates to verify gaps closed and mark compliance checklist complete.
- Maintain `docs/capability_matrix.md` with entries for action capture/replay and enforce updates via PR checklist.
- Update `PROGRESS_TRACKER.md` alongside `guideai record-action --artifact PROGRESS_TRACKER.md ...` for each milestone change.
