# MCP Server Design – Metacognitive Behavior Handbook Platform

## 1. Overview
The Metacognitive Control Plane (MCP) server provides a contract-first integration point that keeps the platform UI, public API, CLI, and agent tooling in lockstep. It exposes behavior-handbook operations, run orchestration, compliance auditing, and reflection workflows through a consistent schema so every surface delivers the same capabilities and guardrails.

## 2. Objectives
- **Parity:** Ensure any capability offered in the platform UI or CLI is available through MCP tools and the public API by default.
- **Observability:** Capture structured telemetry for every command (request metadata, behaviors used, checklist status).
- **Extensibility:** Support partner agents and IDE extensions through well-typed schemas (JSON Schema + OpenAPI) and capability negotiation.
- **Security & Compliance:** Enforce auth, RBAC, and audit logging aligned with compliance requirements.

## 3. Core Capabilities
| Domain | MCP Tool / Endpoint | Description |
| --- | --- | --- |
| Behavior Management | `behaviors.search`, `behaviors.get`, `behaviors.createDraft`, `behaviors.update`, `behaviors.approve` | Discover, retrieve, submit, and govern handbook entries. |
| Run Orchestration | `runs.create`, `runs.updateStatus`, `runs.list`, `runs.fetchLogs` | Manage Strategist/Student/Teacher runs, progress updates, and telemetry. |
| Compliance | `compliance.checklistStatus`, `compliance.recordStep`, `compliance.auditTrail` | Enforce checklist adherence and expose immutable evidence. |
| Reflection & Suggestions | `reflections.submitTrace`, `reflections.suggestBehaviors` | Upload traces, trigger summarization, and propose new behaviors. |
| Analytics | `analytics.metrics`, `analytics.tokenSavings`, `analytics.behaviorUsage` | Surface adoption and efficiency metrics (behavior reuse %, token reduction, task completion, compliance coverage) used by dashboards. |
| Configuration | `config.get`, `config.update`, `config.listLLMConnectors` | Manage model connectors, embedding indices, and token budgets (admin-scoped). |
| Action Registry | `actions.create`, `actions.list`, `actions.replay`, `actions.get` | Record, inspect, and replay build actions to ensure reproducibility and parity. |
| Agent Reviews | `reviews.run`, `reviews.list`, `reviews.get` | Trigger cross-functional agent reviewers (Engineering, DX, Compliance, Product) and retrieve synthesized feedback for artifacts. |
| Agent Authentication | `auth.ensureGrant`, `auth.listGrants`, `auth.revoke`, `auth.status` | Broker OAuth/OIDC flows, enforce policy decisions, and expose grant state for agents and tools. |

## 4. Integration Surfaces
- **Platform UI (Web):** Uses REST/GraphQL façade deployed alongside MCP; feature flags ensure UI only exposes capabilities registered in MCP.
- **Public API:** Thin wrapper around MCP gRPC/HTTP endpoints with identical schemas; versioned routes (e.g., `/v1/behaviors`).
- **CLI:** Consumes the MCP SDK; commands (`guideai plan`, `guideai run`, `guideai reflect`, `guideai agents review`) call the same tools.
- **VS Code & MCP Tools:** IDE extension communicates via MCP protocol to retrieve behaviors, submit runs, and validate checklists without bespoke APIs.

## 5. Architecture
- **Transport:** Primary gRPC (for IDEs/CLI) with HTTP/JSON gateway; follows MCP capability negotiation (handshake with `listTools`).
- **Authentication & Authorization:** Central AgentAuthService handles OAuth/OIDC exchanges (auth code, device, OBO, client credentials), JIT consent, and RBAC/ABAC policy evaluation. Legacy PAT/device flows remain for backward compatibility.
- **Schema Management:** Source-of-truth OpenAPI + JSON Schema stored in `schema/` directory. MCP tool definitions generated from schemas; SDKs auto-generated (TypeScript, Python, Go).
- **Service Components:**
  - `BehaviorService` (Postgres + Vector index; performance targets and scaling plan in `RETRIEVAL_ENGINE_PERFORMANCE.md`).
  - `RunService` (Event-driven, persisting to unified run store).
  - `ComplianceService` (append-only audit log, WORM storage per `AUDIT_LOG_STORAGE.md`).
  - `ReflectionService` (queues traces to LLM reflection workers).
  - `MetricsService` (streams telemetry to warehouse and caches recent metrics).
  - `ActionService` (captures reproducible actions, links to artifacts, exposes replay state).
  - `AgentReviewService` (coordinates cross-functional agent runs, stores feedback summaries, records linked actions).
  - `AgentAuthService` (token broker, policy engine, consent orchestration, telemetry + audit integration per `docs/AGENT_AUTH_ARCHITECTURE.md`).
- **Telemetry Pipeline:** Ingestion + warehouse path defined in `TELEMETRY_SCHEMA.md` (supports PRD metrics dashboards).
- **Secrets Management:** Client auth flows and SDK usage follow `SECRETS_MANAGEMENT_PLAN.md` (device flow, OS keychain storage, rotation).
- **Event Bus:** NATS or Kafka to emit `behavior.updated`, `run.statusChanged`, `compliance.stepRecorded`, enabling real-time UI updates and webhook integrations.

## 6. Parity Strategy
1. **Capability Matrix:** Maintain `docs/capability_matrix.md` mapping each feature to API route, MCP tool, CLI command, and UI surface. Update via PR for any new capability.
2. **Spec-First Development:** Define/modify schemas before implementation. Use contract tests across SDKs and UI clients.
3. **Shared SDKs:** Generate language SDKs from the same proto/OpenAPI definitions; CLI and web clients depend on these packages to prevent drift.
4. **Release Checklist:** New features require:
  - Capability matrix row in `docs/capability_matrix.md` updated with surfaces, parity status, and evidence links.
  - Schema update merged and versioned.
  - CLI command and UI components gated behind feature toggles until parity verified.
  - Automated parity test (CLI vs MCP vs REST) passing in CI.
5. **Observability Dashboards:** Monitor feature usage across surfaces; alert if any surface lags adoption (indicating parity issues).
6. **Versioning & Deprecation:** Semantic versioning for MCP APIs; backward-compatible changes only in minor versions. CLI and UI pinned to matching SDK versions.

## 7. Security & Compliance Considerations
- Enforce least-privilege scopes (e.g., `behavior.write`, `run.execute`, `compliance.review`).
- Tokenized audit entries with cryptographic signatures to ensure tamper evidence.
- Secrets never transmitted in clear text; configuration updates require dual control for production environments.
- Require every tool execution to pass through `auth.ensureGrant` decisioning, emitting telemetry for grants, denials, and JIT consent prompts.
- Rate limiting and anomaly detection to prevent abuse by automated agents.

## 8. Implementation Phases
1. **Phase 0 – Contracts (2 weeks):** Draft schemas, capability matrix, scaffold gRPC/HTTP services, generate SDKs.
2. **Phase 1 – Behavior, Run & Action Tools (4 weeks):** Implement behavior/run domains, stand up `ActionService`, and integrate CLI + UI read/write parity for action capture.
3. **Phase 2 – Compliance & Reflection (4 weeks):** Add checklist enforcement, trace submission, and ensure actions reference compliance evidence.
4. **Phase 3 – Analytics & Admin (3 weeks):** Deliver metrics endpoints, configuration management, parity tests, and action replay reporting.
5. **Phase 4 – Harden & Scale (3 weeks):** Load testing, security review, release workflow, documentation.

## 9. Open Questions
- Do we provide tenant-level isolation per MCP server instance or enforce isolation within a multi-tenant deployment?
- Should reflection suggestions trigger automatic behavior drafts, or stay manual for initial release?
- What is the minimum offline support required for CLI usage (queued operations when disconnected)?
- How do we expose parity compliance reports to customers (self-serve vs internal only)?

## 10. Next Steps
- Create capability matrix doc and integrate into `PRD_NEXT_STEPS.md` tracking.
- Align with infrastructure team on event bus selection and audit log storage.
- Kick off Phase 0 contract work, ensuring agent playbooks reference MCP parity requirements when reviewing future changes.
- Define `ActionService` schemas (action record, replay job) and publish draft CLI/API specs for review.
