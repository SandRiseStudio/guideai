# GuideAI Capability Matrix

## Mission
Maintain a single source of truth for feature parity across all GuideAI surfaces (Web, REST API, CLI, MCP tools, and SDKs). This matrix ensures every shipped capability satisfies the MCP parity strategy in `MCP_SERVER_DESIGN.md`, the reproducibility promises in `REPRODUCIBILITY_STRATEGY.md`, and the release governance rules in `PRD_NEXT_STEPS.md`.

## How to use this document
1. **Before implementation** – Add or update the relevant row(s) to describe the new capability, noting target surfaces and required telemetry hooks.
2. **During review** – Link the corresponding parity tests, action records, and audit evidence to prove the capability works across every surface.
3. **Before merge/release** – Confirm the release checklist items reference this matrix and mark the capability status. Record action evidence via `guideai record-action` when updating the matrix.
4. **After release** – Update `PROGRESS_TRACKER.md`, `PRD_ALIGNMENT_LOG.md`, and `BUILD_TIMELINE.md` with the final status and cross-link to the matrix row.

## Capability overview
| Capability | Description | Web / UI | REST API | CLI | MCP Tool | SDK / Automation | Parity Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Behavior handbook management | Create, approve, and retrieve handbook behaviors. | Behavior admin console | `POST /v1/behaviors`, `GET /v1/behaviors/:id` | `guideai behaviors {search,get,approve}` | `behaviors.search`, `behaviors.get`, `behaviors.approve` | Handbook SDK (`guideai.behaviors`) | Regression prompts + contract tests; audit entries per `AUDIT_LOG_STORAGE.md` |
| Run orchestration | Launch and monitor Strategist/Teacher/Student runs. | Run timeline view | `POST /v1/runs`, `PATCH /v1/runs/:id/status` | `guideai run`, `guideai status` | `runs.create`, `runs.updateStatus`, `runs.list` | Runs SDK (`guideai.runs`) | Unified execution record validation + telemetry (`run.statusChanged`) |
| Compliance checklist | Enforce agent compliance workflow and evidence capture. | Compliance dashboard | `POST /v1/compliance/steps` | `guideai compliance record-step` | `compliance.recordStep` | Compliance SDK (`guideai.compliance`) | WORM audit log linkage + checklist automation tests |
| Action capture & replay | Record build actions and replay reproducible steps. | Action timeline | `POST /v1/actions`, `POST /v1/actions:replay` | `guideai record-action`, `guideai replay` | `actions.create`, `actions.replay`, `actions.replayStatus` | Action SDK (`guideai.actions`) | Contract parity tests, checksum verification scripts, telemetry instrumentation (`guideai/action_service.py`, `tests/test_telemetry_integration.py`) |
| VS Code extension parity | Provide IDE sidebar, plan composer, and execution tracker that mirror platform/CLI flows. | Extension webviews | `GET /v1/behaviors`, `POST /v1/ide/events` | `guideai ide sync` (planned) | MCP tools consumed via IDE adapters (`actions.*`, `runs.*`, `behaviors.*`) | IDE SDK (`guideai.ide`) | Extension smoke tests, MCP contract fixtures, checklist automation in IDE |
| Metrics & analytics | Track adoption and efficiency KPIs. | Milestone Zero dashboard (`dashboard/`) | `GET /v1/analytics/*` | `guideai analytics metrics` | `analytics.metrics`, `analytics.behaviorUsage`, `analytics.tokenSavings` | Analytics SDK (`guideai.analytics`) | Warehouse assertions + dashboard smoke tests + Vite build artifact |
| Agent authentication & authorization | Centralize OAuth/OIDC flows, JIT consent, MFA, and policy enforcement for agents. | Agent auth console (planned) | `/v1/auth/*`, `/v1/auth/grants` | `guideai auth login/status/revoke`, tool pre-checks | `auth.ensureGrant`, `auth.revoke`, `auth.listGrants`, `auth.policy.preview` | Auth SDK (`guideai.auth`) | `proto/agentauth/v1/agent_auth.proto`, `schema/agentauth/v1/agent_auth.json`, `schema/agentauth/scope_catalog.yaml`, `policy/agentauth/bundle.yaml`, `mcp/tools/auth.*.json`, `guideai/agent_auth.py`, `tests/test_agent_auth_contracts.py`, `tests/test_telemetry_integration.py`, `docs/AGENT_AUTH_ARCHITECTURE.md` §§12,16-19 (CMD-006 + MFA update) |
| Consent UX & telemetry | Deliver consistent consent experiences with instrumentation across surfaces. | Dashboard modal | `/v1/auth/consent` (planned) | `guideai auth consent` device flow | `auth.ensureGrant` (CONSENT_REQUIRED flow) | Auth SDK (`guideai.auth`), VS Code extension | `docs/CONSENT_UX_PROTOTYPE.md`, `designs/consent/mockups.md`, `docs/AGENT_AUTH_ARCHITECTURE.md` §§18-19, `dashboard/src/telemetry.ts`, telemetry events snapshot, CMD-007 complete |
| Agent review automation | Schedule cross-functional agent feedback loops for artifacts (Engineering, DX, Compliance, Product). | Review scheduler modal (planned) | `/v1/reviews/*` | `guideai agents review` | `reviews.run`, `reviews.list`, `reviews.get` | Review SDK (`guideai.reviews`) | `PRD_AGENT_REVIEWS.md` (2025-10-15), planned action logs CMD-005, parity tests TBD |

> **Note:** Add additional rows as new capabilities are introduced. Keep descriptions concise but auditable, and reference concrete endpoints/commands.

## Release checklist hook
- Every release PR must include a checkbox referencing the relevant capability matrix rows (e.g., "☑ Capability matrix updated for `<feature>`").
- Reviewers must confirm:
  - The matrix row lists all surfaces with implemented status.
  - Linked parity evidence (contract tests, audit log IDs, action records) is accessible.
  - Telemetry fields required by `TELEMETRY_SCHEMA.md` are documented.

## Change log template
When updating this file, copy the snippet below into the PR description and action log:
```
Capability Matrix Update
- Capability: <name>
- Surfaces touched: <Web/API/CLI/MCP/SDK>
- Evidence: <tests executed, audit log IDs, action IDs>
- guideai record-action --artifact docs/capability_matrix.md --summary "Update capability matrix for <feature>" --behaviors <ids>
```

## Governance reminders
- Changes to this matrix must be accompanied by an action record (`guideai record-action`) and logged in `PRD_ALIGNMENT_LOG.md`.
- If the update introduces a new capability, add follow-up tasks to `PRD_NEXT_STEPS.md` and `PROGRESS_TRACKER.md` as needed.
- Verify that capability telemetry is covered by the metrics pipeline targets (70% behavior reuse, 30% token savings, 80% completion, 95% compliance coverage).
