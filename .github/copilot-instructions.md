# Copilot Instructions for guideai

## Understand the blueprint first
- Start with `PRD.md` to grasp the product vision, personas (Strategist/Teacher/Student/Admin), and success metrics (70% behavior reuse, 30% token savings, 80% completion, 95% compliance coverage).
- Read `MCP_SERVER_DESIGN.md` for the control-plane architecture (BehaviorService, ActionService, RunService, ComplianceService, ReflectionService, MetricsService) and parity expectations across Web, API, CLI, and MCP tools.
- Consult `ACTION_REGISTRY_SPEC.md` and `REPRODUCIBILITY_STRATEGY.md` to see how every platform action must be recorded and replayable via API/CLI/MCP.
- Review supporting specs: `RETRIEVAL_ENGINE_PERFORMANCE.md` (retriever SLOs), `TELEMETRY_SCHEMA.md` (event model), `AUDIT_LOG_STORAGE.md` (immutable evidence), `SECRETS_MANAGEMENT_PLAN.md` (auth/rotation), and `ACTION_SERVICE_CONTRACT.md` (parity contract).

## Behaviors & agent workflow
- Treat `AGENTS.md` as the procedural memory handbook. Reuse existing behaviors before inventing new flows; document any additions there.
- When updating workflows, ensure they map to the Strategist → Student → Teacher pipeline and cite behaviors (see build examples in `PRD_AGENT_REVIEWS.md`).

## Keep documents in sync
- `PRD_NEXT_STEPS.md` lists live follow-up items; update it when plans change.
- Log cross-document updates in `PRD_ALIGNMENT_LOG.md` so the PRD remains the single source of truth.
- Maintain `BUILD_TIMELINE.md` whenever new artifacts are created and sync status in `PROGRESS_TRACKER.md` (log updates via `guideai record-action`).

## Conventions for new work
- New specs or playbooks should mirror the structure of existing files (mission, checklists, rubrics, escalation rules).
- Any feature or workflow must include parity notes (Web/API/CLI/MCP) and instrumentation hooks for the PRD metrics.
- If you touch execution flows, reference the compliance checklist (`agent-compliance-checklist.md`) and note evidence requirements.

## Pending implementation cues
- CLI command names and parameters must align with `ACTION_REGISTRY_SPEC.md` (`guideai record-action`, `guideai replay`, etc.).
- Analytics outputs should ladder up to the metrics called out in the PRD and MCP design (`analytics.metrics`, `analytics.tokenSavings`, `analytics.behaviorUsage`).

## Collaboration reminders
- Before finalizing, run the relevant agent playbooks (`AGENT_ENGINEERING.md`, `AGENT_DX.md`, `AGENT_COMPLIANCE.md`, `AGENT_PRODUCT.md`, `AGENT_COPYWRITING.md`) to capture feedback.
- Note any new reusable workflow in `AGENTS.md` and update the capability matrix (once introduced) to keep parity enforced.
## Additional Instructions

- Prioritize updating existing documentation files instead of creating new summary documents after every update (languages: TypeScript, JavaScript, Python)
- Always run pre-commit hooks before pushing code (languages: JavaScript, Python, TypeScript)
- Use descriptive variable names that explain purpose and intent (languages: JavaScript, TypeScript, Python)
- Document all public API endpoints with OpenAPI specs (languages: JavaScript, TypeScript, Python)
