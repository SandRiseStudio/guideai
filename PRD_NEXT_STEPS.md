# PRD Follow-Up Actions (from Agent Reviews)

> **Last Updated:** 2025-10-15
> **Milestone Status:** Milestone 0 Complete ✅ | Milestone 1 In Progress 🚧

## Function → Agent Mapping
| Function | Primary Agent | Playbook | Notes |
| --- | --- | --- | --- |
| Engineering | Agent Engineering | `AGENT_ENGINEERING.md` | Leads service/runtime implementation and telemetry contracts. |
| Developer Experience (DX) | Agent Developer Experience | `AGENT_DX.md` | Owns IDE workflows, onboarding assets, and parity evidence. |
| DevOps | Agent DevOps | `AGENT_DEVOPS.md` | Handles deploy pipelines, environment automation, and rollback readiness. |
| Product Management (PM) | Agent Product | `AGENT_PRODUCT.md` | Prioritizes roadmap, discovery, and launch gating. |
| Product (Analytics) | Agent Product | `AGENT_PRODUCT.md` | Drives analytics instrumentation and KPI dashboards. |
| Copywriting | Agent Copywriting | `AGENT_COPYWRITING.md` | Crafts release notes, in-product copy, and consent messaging. |
| Compliance | Agent Compliance | `AGENT_COMPLIANCE.md` | Ensures checklist automation, audit evidence, and policy adherence. |

> Use the CLI/API/MCP task actions (see "Task Assignment Actions" below) to query these mappings programmatically during execution planning.

## Completed (Milestone 0) ✅
All foundation deliverables successfully shipped and validated:

### Infrastructure & Services (Complete)
- ✅ Retrieval engine performance targets and scaling plan documented in `RETRIEVAL_ENGINE_PERFORMANCE.md`.
- ✅ Telemetry schema, storage, and retention policy captured in `TELEMETRY_SCHEMA.md`.
- ✅ Audit log storage approach defined in `AUDIT_LOG_STORAGE.md`.
- ✅ Secrets management approach for CLI/SDK recorded in `SECRETS_MANAGEMENT_PLAN.md`.
- ✅ Initial `ActionService` contract published in `ACTION_SERVICE_CONTRACT.md`.
- ✅ ActionService gRPC/REST handler stubs, adapters, and parity tests added (`guideai/action_service.py`, `guideai/adapters.py`, `tests/test_action_service_parity.py`).
- ✅ CLI/API parity for action capture and replay (`guideai record-action`, `guideai replay`, `/v1/actions/*`); comprehensive parity test coverage (`tests/test_cli_actions.py`).

### Security & Compliance (Complete)
- ✅ Agent Auth Phase A contract artifacts shipped (`proto/agentauth/v1/agent_auth.proto`, `schema/agentauth/v1/agent_auth.json`, `schema/agentauth/scope_catalog.yaml`, `policy/agentauth/bundle.yaml`, `mcp/tools/auth.*.json`, `guideai/agent_auth.py`, `tests/test_agent_auth_contracts.py`) — CMD-006.
- ✅ MFA enforcement defined for `high_risk` scopes (`actions.replay`, `agentauth.manage`) via scope catalog, policy bundle, and SDK updates.
- ✅ Operationalize automated secret scanning across CLI/UI/CI surfaces (`guideai scan-secrets`, pre-commit hooks, `.github/workflows/ci.yml`) and enforce remediation logging via ActionService.
- ✅ Compliance control mapping matrix covering SOC2/GDPR obligations (`docs/COMPLIANCE_CONTROL_MATRIX.md`).
- ✅ Policy deployment runbook with GitOps workflow and rollback tooling (`docs/POLICY_DEPLOYMENT_RUNBOOK.md`).

### Documentation & Governance (Complete)
- ✅ Capability matrix scaffold created in `docs/capability_matrix.md` and release checklist updated.
- ✅ Cross-team AgentAuth architecture review completed and logged in `PRD_AGENT_REVIEWS.md` (2025-10-15).
- ✅ SDK scope (supported languages, versioning, distribution) clarified and aligned with client integration plans (`docs/SDK_SCOPE.md`).
- ✅ Behavior versioning/migration strategy added to Data Model section (`docs/BEHAVIOR_VERSIONING.md`).
- ✅ Publish reproducible build runbook describing action capture/replay workflow (`docs/README.md`).
- ✅ Git governance playbook for branching, reviews, secret hygiene (`docs/GIT_STRATEGY.md`).
- ✅ Stand up CI/CD pipelines with guardrails and DevOps playbook (`.github/workflows/ci.yml`, `docs/AGENT_DEVOPS.md`).
- ✅ Plan guided onboarding assets for VS Code/CLI with telemetry checkpoints (`docs/ONBOARDING_QUICKSTARTS.md`).
- ✅ Document VS Code extension roadmap in `docs/capability_matrix.md` with parity evidence tracking.

### Analytics & Monitoring (Complete)
- ✅ Milestone Zero progress dashboard shipped under `dashboard/` to visualize PRD metrics from source artifacts — CMD-003.
- ✅ Cross-surface telemetry instrumentation shipped for dashboard, ActionService, and AgentAuth with automated coverage (`dashboard/src/telemetry.ts`, `guideai/action_service.py`, `guideai/agent_auth.py`, `tests/test_telemetry_integration.py`).
- ✅ Consent UX prototypes, usability study recap, and telemetry wiring plan published (`docs/CONSENT_UX_PROTOTYPE.md`, `designs/consent/mockups.md`) — CMD-007.
- ✅ Stand up consent/MFA analytics dashboards leveraging the new telemetry events (`dashboard/src/app.tsx`, `dashboard/src/hooks/useConsentTelemetry.ts`, `docs/analytics/consent_mfa_snapshot.md`).
- ✅ Validate MFA re-prompt UX across surfaces and document monitoring hooks (`docs/analytics/mfa_usability_validation_plan.md`).
- ✅ Instrument onboarding and adoption metrics (time-to-first-behavior, checklist completion, behavior search-to-insert conversion) aligned with PRD targets (`docs/analytics/onboarding_adoption_snapshot.md`, `dashboard/src/hooks/useOnboardingTelemetry.ts`, `dashboard/src/components/OnboardingDashboard.tsx`).

## Immediate (Milestone 0)
_All Milestone 0 actions complete; work shifts to Milestone 1 deliverables._

## Short-Term (Milestone 1 Gate – Target: 6 weeks) 🚧

### Primary Deliverables
- **VS Code Extension Preview** (DX + Engineering): Implement Behavior Sidebar, Plan Composer, Execution Tracker, and Post-Task Review features leveraging the completed SDK and telemetry infrastructure.
  - **Primary Function → Agent:** Developer Experience → `AGENT_DX.md`
  - **Supporting Functions → Agents:** Engineering → `AGENT_ENGINEERING.md`; Copywriting → `AGENT_COPYWRITING.md` (release notes & UX copy); Product Management → `AGENT_PRODUCT.md` (preview gating)
  - **Dependencies:** SDK authentication flows, behavior retrieval API, ActionService integration
  - **Evidence Target:** Extension bundle, integration tests, capability matrix update

- ✅ **Checklist Automation Engine** (Engineering): ✅ **COMPLETE** – Implemented ComplianceService with full CLI/REST/MCP parity for create/record/list/get/validate operations, coverage scoring algorithm, and telemetry integration.
  - **Primary Function → Agent:** Engineering → `AGENT_ENGINEERING.md`
  - **Supporting Functions → Agents:** Compliance → `AGENT_COMPLIANCE.md`; DevOps → `AGENT_DEVOPS.md` (pipeline hooks); Product Management → `AGENT_PRODUCT.md`
  - **Delivered:** `COMPLIANCE_SERVICE_CONTRACT.md` (contract with schemas, endpoints, RBAC scopes, validation rules), `guideai/compliance_service.py` (~350 lines service implementation), REST/CLI/MCP adapters in `guideai/adapters.py`, 5 CLI commands (`guideai compliance create-checklist/record-step/list/get/validate`), `tests/test_compliance_service_parity.py` (17 passing parity tests) — CMD-008
  - **Note:** Current implementation is in-memory stub suitable for Milestone 1 alpha; persistent backend (PostgreSQL/SQLite) planned for Milestone 2 deployment.

- **BehaviorService Runtime Deployment** (Engineering + Platform): Deploy BehaviorService with CRUD operations, approval workflow, embedding index (FAISS/Qdrant), and retrieval API. Integrate persistent storage backend for both behavior data and compliance checklists.
  - **Primary Function → Agent:** Engineering → `AGENT_ENGINEERING.md`
  - **Supporting Functions → Agents:** DevOps → `AGENT_DEVOPS.md` (environment/bootstrap); Product Management → `AGENT_PRODUCT.md`; Compliance → `AGENT_COMPLIANCE.md` (approval workflow evidence)
  - **Dependencies:** Postgres backend, vector DB, embedding model integration, persistent storage for ComplianceService
  - **Evidence Target:** Service endpoints, retrieval benchmarks matching `RETRIEVAL_ENGINE_PERFORMANCE.md` targets, database migrations for checklist + behavior storage
  - **Status Update (2025-10-15):** SQLite-backed runtime and CLI parity shipped (`guideai/behavior_service.py`, `guideai/cli.py` behaviors subcommands, `tests/test_cli_behaviors.py`); next step is to migrate to Postgres/vector index and expose REST/MCP endpoints per contract.

- **Initial Analytics Dashboards** (Product Analytics): Deploy production analytics tracking behavior reuse, token savings, task completion, and compliance coverage aligned with PRD success metrics.
  - **Primary Function → Agent:** Product (Analytics) → `AGENT_PRODUCT.md`
  - **Supporting Functions → Agents:** Engineering → `AGENT_ENGINEERING.md` (data pipes); DX → `AGENT_DX.md` (dashboard UX); Copywriting → `AGENT_COPYWRITING.md` (metric definitions)
  - **Dependencies:** Telemetry pipeline deployment, data warehouse schema
  - **Evidence Target:** Live dashboards showing PRD KPIs (70% reuse, 30% token savings, 80% completion, 95% compliance)

### Supporting Work
- **AgentAuthService Runtime** (Security + Engineering): Deploy authentication service with device flow, consent management, and policy enforcement.
  - **Primary Function → Agent:** Engineering → `AGENT_ENGINEERING.md`
  - **Supporting Functions → Agents:** Compliance → `AGENT_COMPLIANCE.md`; Product Management → `AGENT_PRODUCT.md`; DevOps → `AGENT_DEVOPS.md`
- **Workflow Engine Foundation** (Engineering): Implement Strategist/Teacher/Student template system and behavior-conditioned inference support.
  - **Primary Function → Agent:** Engineering → `AGENT_ENGINEERING.md`
  - **Supporting Functions → Agents:** DX → `AGENT_DX.md`; Compliance → `AGENT_COMPLIANCE.md`
- **Embedding Model Integration** (Engineering): Integrate BGE-M3 or alternative embedding model with vector index for semantic behavior retrieval.
  - **Primary Function → Agent:** Engineering → `AGENT_ENGINEERING.md`
  - **Supporting Functions → Agents:** Product Management → `AGENT_PRODUCT.md`; DevOps → `AGENT_DEVOPS.md`

## Mid-Term (Milestone 2 Planning)
- Gather external customer research or pilot commitments; update PRD with discovery insights (Product Strategy).
  - **Primary Function → Agent:** Product Management → `AGENT_PRODUCT.md`
  - **Supporting Functions → Agents:** Copywriting → `AGENT_COPYWRITING.md` (survey scripts); Compliance → `AGENT_COMPLIANCE.md`
- Outline pricing/packaging experiments and GA gating criteria (Product Strategy).
  - **Primary Function → Agent:** Product Management → `AGENT_PRODUCT.md`
  - **Supporting Functions → Agents:** Engineering → `AGENT_ENGINEERING.md`; DevOps → `AGENT_DEVOPS.md` (cost telemetry); Product (Analytics) → `AGENT_PRODUCT.md`
- Identify multi-tenant behavior sharing considerations and include in open questions if pursued (Product Strategy + Engineering).
  - **Primary Function → Agent:** Engineering → `AGENT_ENGINEERING.md`
  - **Supporting Functions → Agents:** Product Management → `AGENT_PRODUCT.md`; Compliance → `AGENT_COMPLIANCE.md`
- Stand up analytics dashboard tracking action replay usage, parity health, PRD success metrics (behavior reuse %, token savings, task completion rate, compliance coverage), and checklist adherence (Product Strategy + Platform).
  - **Primary Function → Agent:** Product (Analytics) → `AGENT_PRODUCT.md`
  - **Supporting Functions → Agents:** Engineering → `AGENT_ENGINEERING.md`; DX → `AGENT_DX.md`; Compliance → `AGENT_COMPLIANCE.md`

## Task Assignment Actions
- `guideai tasks --function <function>` – Retrieve outstanding tasks for a given function (Developer Experience, Engineering, DevOps, Product Management, Product, Copywriting, Compliance).
- REST: `POST /v1/tasks:listAssignments` – Mirrors CLI response payload schema for platform/API clients.
- MCP Tool: `tasks.listAssignments` – Exposes the same schema for IDE/MCP surfaces.

> Each response includes `function`, `primary_agent`, `supporting_agents`, and `milestone` fields for downstream planning. See `guideai/task_assignments.py` for the canonical registry.

## Tracking & Governance
- Log resolutions for each action in issue tracker linked to `PRD_AGENT_REVIEWS.md`.
- Update `PRD.md` once actions are addressed; capture change history in Document Control.
- Re-run agent reviews after updates to verify gaps closed and mark compliance checklist complete.
- Maintain `docs/capability_matrix.md` with entries for action capture/replay and enforce updates via PR checklist.
- Update `PROGRESS_TRACKER.md` alongside `guideai record-action --artifact PROGRESS_TRACKER.md ...` for each milestone change.
