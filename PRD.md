# Metacognitive Behavior Handbook Platform – Product Requirements Document

## Document Control
- **Status:** Milestone 0 Complete – Entering Internal Alpha
- **Date:** 2025-10-15
- **Last Updated:** 2025-10-15
- **Author(s):** Product & AI Enablement Team
- **Stakeholders:** Engineering, Developer Experience, Developer Productivity, Security & Compliance, Customer Success

## Background
The platform is inspired by Meta AI's "Metacognitive Reuse" work, which demonstrates how compressing repeated reasoning into reusable "behaviors" can cut reasoning token usage by up to 46% and raise accuracy in math benchmarks. Internally, we have begun dogfooding the approach through `AGENTS.md` and `agent-compliance-checklist.md`, but adoption remains inconsistent and manual. We need to productize the handbook concept so teams can reliably discover, apply, and evolve behaviors across tools (platform UI, CLI, VS Code) while preserving auditability.

## Current Status (2025-10-15)
**Milestone 0 – Foundations: COMPLETE** ✅

The platform has successfully completed its foundation phase with all 20+ planned deliverables shipped and validated:

### Core Infrastructure
- ✅ **ActionService & Adapters:** Full contract implementation with CLI/REST/MCP parity (`guideai/action_service.py`, `guideai/adapters.py`, `tests/test_action_service_parity.py`)
- ✅ **Agent Auth Phase A:** Complete contract artifacts including proto definitions, JSON schemas, scope catalog, policy bundles, MCP tool definitions, SDK stubs, and comprehensive test coverage
- ✅ **Telemetry Pipeline:** Cross-surface instrumentation for dashboard, ActionService, and AgentAuth with automated integration tests
- ✅ **Secret Scanning:** Pre-commit hooks, CI/CD integration, CLI commands, and MCP tools operational across all surfaces

### Documentation & Governance
- ✅ **13 Governance Playbooks:** Including Agent Auth Architecture, DevOps practices, Git strategy, behavior versioning, SDK scope, policy deployment, onboarding quickstarts, compliance control matrix, and consent UX prototypes
- ✅ **Capability Matrix:** Parity tracking across Web/API/CLI/MCP surfaces with release checklist hooks
- ✅ **Build Timeline:** 35 auditable actions with reproducible build documentation

### Security & Compliance
- ✅ **MFA Enforcement:** Policy-driven re-prompts for high-risk scopes (`actions.replay`, `agentauth.manage`)
- ✅ **Audit Infrastructure:** Immutable logging with evidence pipeline and compliance control matrix
- ✅ **Secrets Management:** Device flow, rotation policies, and leak prevention guardrails

### Analytics & Monitoring
- ✅ **Milestone Zero Dashboard:** Responsive Preact/Vite UI visualizing progress, timeline, and alignment
- ✅ **Consent/MFA Telemetry:** Event capture with dashboard integration and usability validation plan
- ✅ **Onboarding Metrics:** Time-to-first-behavior, checklist completion, and adoption tracking instrumented

### Testing & Quality
- ✅ **5 Test Suites:** Action service parity, agent auth contracts, CLI actions, secret scanning, telemetry integration
- ✅ **CI/CD Guardrails:** Automated pre-commit checks, secret scanning, tests, and builds across all PRs

**Next Focus (Milestone 1):** VS Code extension implementation, BehaviorService runtime deployment, checklist automation engine, and analytics dashboard deployment to production.

## Problem Statement
AI-assisted development teams repeatedly solve similar orchestration and remediation problems, causing long LLM traces, inconsistent outcomes, and weak institutional memory. Behavior handbooks exist but are siloed, hard to enforce, and unaudited. We need a product that operationalizes behavior discovery, retrieval, and compliance so that Strategist/Teacher/Student roles can collaborate efficiently and traceably.

## Vision
Deliver a connected platform that captures procedural knowledge, guides agents to reuse vetted behaviors, and makes compliance observable in every development surface (web, CLI, VS Code). The product should shorten reasoning traces, improve task success, and create a durable memory of high-quality workflows.

## Goals
1. **Increase behavior reuse:** 70% of assisted sessions reference at least one approved behavior by the end of public beta.
2. **Reduce token cost:** Average output tokens per complex remediation task drop by 30% compared to baseline traces.
3. **Improve success rate:** Completion rate for tracked engineering remediation tasks increases from 60% to 80%.
4. **Ensure auditability:** 95% of runs include compliance logs covering plan, execution, validation, and cited behaviors.

## Non-Goals
- Building proprietary LLMs; we rely on third-party APIs and prompt engineering.
- Replacing human review for production incidents; the platform augments but does not eliminate oversight.
- Managing declarative knowledge bases (classic RAG). Focus is procedural behaviors.

## Personas
1. **AI-Augmented Developer (Student role):** Executes tasks, needs actionable behavior prompts inside IDE/CLI.
2. **AI Strategist / Tech Lead:** Designs plans, curates behaviors, and monitors adoption.
3. **Teacher Agent / Prompt Author:** Crafts behavior-conditioned examples and ensures outputs cite behaviors.
4. **Compliance & Platform Admin:** Enforces standards, reviews new behaviors, audits logs.
5. **Knowledge Librarian (optional future role):** Manages large behavior corpora and taxonomy.

## User Stories
- As a developer, I retrieve relevant behaviors when drafting a remediation plan in VS Code and have the extension inject them into the prompt.
- As a strategist, I review traces post-task and convert novel steps into proposed behaviors through a reflection UI.
- As a compliance admin, I run a report showing which behaviors were cited over the last sprint and where the checklist was skipped.
- As a teacher agent, I author a prompt template that ensures every response references behavior IDs and validation steps.
- As a platform owner, I configure embeddings, storage backends, and token budgets for the behavior retriever.

## Scope
### In Scope (MVP + Beta)
- Unified behavior handbook service (CRUD, approval workflow, tagging, versioning).
- Retrieval service combining trigger keyword rules and embeddings (BGE-M3 + FAISS or equivalent).
- Strategist/Teacher/Student workflow tooling that references behaviors in plans, execution, and summaries.
- Compliance checklist enforcement and logging aligned with `agent-compliance-checklist.md`.
- Surfaced clients: minimal web console, CLI helper, VS Code extension.
- Analytics dashboards for adoption, token usage, and accuracy metrics.
- Behavior lifecycle management (draft → review → approved → deprecated).

### Out of Scope (for MVP)
- Native mobile apps.
- Automated fine-tuning pipeline (tracked as stretch goal).
- Marketplace for community behaviors (future consideration).

## Product Experience
### Core Platform (Web)
- **Behavior Library:** searchable list, filters (tags, roles, freshness), detail view with usage examples.
- **Reflection Inbox:** ingest traces, summarize, propose new behaviors with suggested names/instructions.
- **Compliance Dashboard:** displays checklist adherence, missing validations, and orphaned behaviors.
- **Run Explorer:** links strategist plans, student execution logs, and cited behaviors for each run.
- **Settings:** connectors for LLMs, embedding indices, storage backends, and auth.

### CLI Surface
- `guideai plan`: prompts Strategist to cite behaviors; fails checklist if empty.
- `guideai run`: executes tasks while logging validations and behavior usage.
- `guideai reflect`: summarizes traces, proposes behaviors, and submits to review queue.
- Configurable hooks for CI/CD to ensure every PR references compliance logs.

### VS Code Extension
- **Behavior Sidebar:** search, pin, and inject behaviors into prompts or plans.
- **Plan Composer:** scaffolds Strategist/Teacher/Student sections referencing selected behaviors.
- **Execution Tracker:** displays commands run, validations, and outstanding checklist items.
- **Post-Task Review:** allows quick reflection to suggest new behaviors without leaving the IDE.

## Workflows
1. **Task Kickoff:** Strategist scans triggers, selects behaviors, drafts plan citing IDs. Checklist auto-logs step completion.
2. **Execution:** Student follows plan within CLI/IDE, logs commands and validation outcomes. Behaviors are referenced inline in responses.
3. **Reflection:** Teacher/Strategist reviews trace, uses reflection tooling to extract potential behaviors, submits for review.
4. **Compliance Review:** Admin verifies checklist completion, behavior usage, and approval status.

## Architecture Overview
- **Behavior Service:** stores metadata, instructions, embeddings, usage stats. Backed by Postgres + vector index (FAISS/Qdrant) with performance targets defined in `RETRIEVAL_ENGINE_PERFORMANCE.md`.
- **Retriever Engine:** hybrid search (keyword triggers + embeddings) with ranking heuristics.
- **Workflow Engine:** enforces Strategist/Teacher/Student templates and checklist requirements.
- **Telemetry Pipeline:** captures task logs, commands, token counts, validation results following the schema in `TELEMETRY_SCHEMA.md`.
- **Audit Log Storage:** immutable evidence pipeline outlined in `AUDIT_LOG_STORAGE.md`.
- **Secrets Management:** device login + rotation policies documented in `SECRETS_MANAGEMENT_PLAN.md`.
- **Agent Auth Service:** centralized OAuth/OIDC broker with just-in-time consent, policy enforcement, and audit integration per `docs/AGENT_AUTH_ARCHITECTURE.md`.
- **Client Integrations:** web app (Next.js), CLI (Python Typer), VS Code extension (TypeScript). Shared SDK for authentication and API calls; see `docs/SDK_SCOPE.md` for supported languages, versioning, and distribution roadmap.
- **LLM Connectors:** plugable interface for OpenAI, Anthropic, local models; handles prompt templates for behavior-conditioned inference.

## Data Model
- **Behavior:** id, name, trigger keywords, instruction, role focus, status, version, embedding vector, usage stats. `version` follows semantic versioning with lifecycle rules defined in `docs/BEHAVIOR_VERSIONING.md`; every run stores `(behavior_id, version)` for reproducibility.
- **Run:** id, task metadata, behaviors cited, plan, execution log, validation results, checklist flags.
- **Trace:** raw LLM output, associated run, tokens used, derived candidate behaviors.
- **Compliance Record:** checklist step, status, reviewer, timestamp, notes.

## Dependencies & Integrations
- Embedding model (BGE-M3 or alternative) with vector DB support.
- LLM APIs supporting long context (≥ 16k tokens) and tool-use metadata.
- Authentication (OAuth/SAML + AgentAuthService) for web; device/OBO/client-credential flows for CLI, IDE, and service agents.
- Telemetry sink (Snowflake/BigQuery) for analytics.

## Success Metrics
- Behavior reuse rate per run.
- Token savings vs baseline (tracked automatically).
- Checklist adherence percentage.
- Task completion time and success rate.
- Number of new behaviors proposed, approved, deprecated.

## Release Plan
1. **Milestone 0 – Foundations (4 weeks):** ✅ **COMPLETE** – Stand up behavior service, manual retriever, basic CLI to log behaviors, publish Agent Auth architecture and scope catalog.
   - **Delivered:** ActionService contracts & stubs, Agent Auth Phase A (proto/schema/policy artifacts), secret scanning guardrails, CI/CD pipelines, telemetry instrumentation, compliance control matrix, SDK scope definition, behavior versioning strategy, Git/DevOps governance playbooks, policy deployment runbook, onboarding quickstarts, consent/MFA UX prototypes with validation plan, reproducible build documentation.
   - **Evidence:** 20+ completed work items tracked in `PROGRESS_TRACKER.md`, 35 timeline entries in `BUILD_TIMELINE.md`, full test coverage in `tests/`, contract artifacts in `proto/`, `schema/`, `policy/`, `mcp/tools/`.

2. **Milestone 1 – Internal Alpha (6 weeks):** 🚧 **IN PROGRESS** – VS Code extension preview, checklist automation, BehaviorService runtime, initial analytics, AgentAuthService contracts (published proto + JSON schemas, scope catalog, MCP tool definitions) and consent UX prototypes.
   - **Status:** Checklist automation engine complete with full CLI/REST/MCP parity; BehaviorService runtime with SQLite backend and CLI parity shipped. VS Code extension and analytics dashboards remain as primary deliverables.
   - **Delivered:**
     - **ComplianceService** (`COMPLIANCE_SERVICE_CONTRACT.md`, `guideai/compliance_service.py`, `guideai/adapters.py`, 17 passing parity tests) – In-memory service with create/record/list/get/validate operations, coverage scoring algorithm, telemetry integration, REST/CLI/MCP adapters, 5 CLI commands.
     - **BehaviorService Runtime** (`guideai/behavior_service.py`, `guideai/adapters.py`, `guideai/cli.py`, `tests/test_cli_behaviors.py`) – SQLite-backed runtime with full lifecycle support (create/list/search/get/update/submit/approve/deprecate/delete-draft), telemetry instrumentation, CLI adapters and 9 behaviors subcommands, regression coverage with 2 passing test suites.
   - **Next:** VS Code extension implementation, BehaviorService backend migration to PostgreSQL with vector index (FAISS/Qdrant), REST/MCP endpoint exposure, analytics dashboard deployment to production.

3. **Milestone 2 – External Beta (8 weeks):** Web console v1, embedding retriever, compliance dashboards, AgentAuthService in production with just-in-time consent for core tools.

4. **Milestone 3 – GA (6 weeks):** Scaling improvements, behavior lifecycle automation, SDK release, documentation, expanded provider connectors and advanced policy tooling.

## Risks & Mitigations
- **Behavior sprawl:** implement review workflow, tagging, and decay policies.
- **Compliance fatigue:** automate checklists, provide quick inline actions.
- **LLM hallucination:** enforce behavior citation format, add evaluation harness.
- **Security:** ensure secrets never logged; integrate with secret scanners.
- **Vendor lock-in:** design abstraction layer for embeddings/LLMs.

## Open Questions
- Should we support multi-tenant behavior handbooks with shared/global behaviors?
- How to price token savings; do we surface cost analytics to customers?
- What is the minimum viable reflection quality to auto-suggest behaviors?
- Do we offer on-prem deployments for regulated environments?

## Appendix
- **Reference Docs:** `AGENTS.md`, `agent-compliance-checklist.md`, `Metacognitive_reuse.txt`, `RETRIEVAL_ENGINE_PERFORMANCE.md`, `TELEMETRY_SCHEMA.md`, `AUDIT_LOG_STORAGE.md`, `SECRETS_MANAGEMENT_PLAN.md`, `ACTION_SERVICE_CONTRACT.md`
- **Terminology:** Strategist = plan author, Teacher = reflection coach, Student = executor.
- **Future Enhancements:** Behavior-conditioned fine-tuning service, marketplace, incident retrospectives integration.
