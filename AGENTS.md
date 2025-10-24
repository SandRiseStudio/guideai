## Article that inspired GuideAI:

Home Tech News AI Paper Summary Meta AI Proposes ‘Metacognitive Reuse’: Turning LLM Chains-of-Thought into a Procedural Handbook...
Tech News AI Paper Summary Technology AI Shorts Artificial Intelligence Applications Editors Pick
Machine Learning Staff
Meta AI Proposes ‘Metacognitive Reuse’: Turning LLM Chains-of-Thought into a Procedural Handbook that Cuts Tokens by 46%
  
By Asif Razzaq - September 21, 2025
Meta researchers introduced a method that compresses repeated reasoning patterns into short,
named procedures—“behaviors”—and then conditions models to use them at inference or distills
them via fine-tuning. The result: up to 46% fewer reasoning tokens on MATH while matching or
improving accuracy, and up to 10% accuracy gains in a self-improvement setting on AIME, without
changing model weights. The work frames this as procedural memory for LLMs—how to reason, not
just what to recall—implemented with a curated, searchable “behavior handbook.”
https://arxiv.org/pdf/2509.13237
What problem does this solve?
Long chain-of-thought (CoT) traces repeatedly re-derive common sub-procedures (e.g., inclusion–
exclusion, base conversions, geometric angle sums). That redundancy burns tokens, adds latency,
and can crowd out exploration. Meta’s idea is to abstract recurring steps into concise, named
behaviors (name + one-line instruction) recovered from prior traces via an LLM-driven reflection
pipeline, then reuse them during future reasoning. On math benchmarks (MATH-500; AIME-24/25),
this reduces output length substantially while preserving or improving solution quality.
How does the pipeline work?
Three roles, one handbook:
Metacognitive Strategist (R1-Llama-70B):
solves a problem to produce a trace, 2) reflects on the trace to identify generalizable steps, 3)
emits behaviors as entries. These populate a
behavior handbook (procedural memory).
Teacher (LLM B): generates behavior-conditioned responses used to build training corpora.
Student (LLM C): consumes behaviors in-context (inference) or is fine-tuned on behavior-
conditioned data.
Retrieval is topic-based on MATH and embedding-based (BGE-M3 + FAISS) on AIME.
Prompts: The team provides explicit prompts for solution, reflection, behavior extraction, and
behavior-conditioned inference (BCI). In BCI, the model is instructed to reference behaviors explicitly
in its reasoning, encouraging consistently short, structured derivations.
[Recommended Read] NVIDIA AI Open-Sources ViPE (Video Pose Engine): A Powerful and
Versatile 3D Video Annotation Tool for Spatial AI
What are the evaluation modes?
1. Behavior-Conditioned Inference (BCI): Retrieve K relevant behaviors and prepend them to the
prompt.
2. Behavior-Guided Self-Improvement: Extract behaviors from a model’s own earlier attempts and
feed them back as hints for revision.
3. Behavior-Conditioned SFT (BC-SFT): Fine-tune students on teacher outputs that already follow
behavior-guided reasoning, so the behavior usage becomes parametric (no retrieval at test time).
Key results (MATH, AIME-24/25)
Token efficiency: On MATH-500, BCI reduces reasoning tokens by up to 46% versus the
same model without behaviors, while matching or improving accuracy. This holds for both R1-
Llama-70B and Qwen3-32B students across token budgets (2,048–16,384).
Self-improvement gains: On AIME-24, behavior-guided self-improvement beats a critique-
(behavior_name → instruction)
and-revise baseline at nearly every budget, with up to 10% higher accuracy as budgets
increase, indicating better test-time scaling of accuracy (not just shorter traces).
BC-SFT quality lift: Across Llama-3.1-8B-Instruct, Qwen2.5-14B-Base, Qwen2.5-32B-Instruct,
and Qwen3-14B, BC-SFT consistently outperforms (accuracy) standard SFT and the original
base across budgets, while remaining more token-efficient. Importantly, the advantage is not
explained by an easier training corpus: teacher correctness rates in the two training sets (original
vs. behavior-conditioned) are close, yet BC-SFT students generalize better on AIME-24/25.
Why does this work?
The handbook stores procedural knowledge (how-to strategies), distinct from classic RAG’s
declarative knowledge (facts). By converting verbose derivations into short, reusable steps, the
model skips re-derivation and reallocates compute to novel subproblems. Behavior prompts serve as
structured hints that bias the decoder toward efficient, correct trajectories; BC-SFT then
internalizes these trajectories so that behaviors are implicitly invoked without prompt overhead.
What’s inside a “behavior”?
Behaviors range from domain-general reasoning moves to precise mathematical tools, e.g.,
: avoid double counting by subtracting
intersections;
: formalize word problems systematically;
: apply |Ax+By+C|/√(A²+B²) for tangency checks.
During BCI, the student explicitly cites behaviors when they’re used, making traces auditable and
compact.
Retrieval and cost considerations
On MATH, behaviors are retrieved by topic; on AIME, top-K behaviors are selected via BGE-M3
embeddings and FAISS. While BCI introduces extra input tokens (the behaviors), input tokens are
pre-computable and non-autoregressive, and are often billed cheaper than output tokens on
commercial APIs. Since BCI shrinks output tokens, the overall cost can drop while latency
improves. BC-SFT eliminates retrieval at test time entirely.
behavior_inclusion_exclusion_principle
behavior_translate_verbal_to_equation behavior_distance_from_point_to_line
Image source: marktechpost.com
Summary
Meta’s behavior-handbook approach operationalizes procedural memory for LLMs: it abstracts
recurring reasoning steps into reusable “behaviors,” applies them via behavior-conditioned inference
or distills them with BC-SFT, and empirically delivers up to 46% fewer reasoning tokens with
accuracy that holds or improves (≈10% gains in self-correction regimes). The method is
straightforward to integrate—an index, a retriever, optional fine-tuning—and surfaces auditable
traces, though scaling beyond math and managing a growing behavior corpus remain open
engineering problems.

# Agent Handbook

This handbook captures the recurring procedures ("behaviors") we rely on while working inside the guideAI platform. Use it to keep responses consistent, avoid repeating mistakes, and preserve reasoning tokens for the unique parts of each task across the Strategist → Teacher → Student workflow described in `PRD.md` and `MCP_SERVER_DESIGN.md`.

## How to use this document
- **Before acting**, scan the trigger keywords below. If the request matches, reference the corresponding behavior in your plan (e.g., `behavior_unify_execution_records`).
- **If no behavior fits**, finish the task, then add a new entry describing any reusable pattern you discovered.
- **Keep roles in mind**:
  - **Strategist** – decomposes the request, maps applicable behaviors, and updates this handbook when new patterns emerge.
  - **Teacher** – explains the plan to the user, citing behaviors so intent stays clear.
  - **Student** – executes the plan, runs validations, and reports deltas with references to the behaviors followed.

## Quick triggers
| Trigger keywords | Behavior(s) |
| --- | --- |
| execution record, SSE, progress, run status | `behavior_unify_execution_records` |
| storage adapter, audit log, timeline, run history | `behavior_align_storage_layers` |
| config path, env var, secrets manager, device flow | `behavior_externalize_configuration`, `behavior_rotate_leaked_credentials` |
| BehaviorService, behavior index, reflection prompt | `behavior_curate_behavior_handbook` |
| action registry, parity, `guideai record-action` | `behavior_sanitize_action_registry`, `behavior_wire_cli_to_orchestrator` |
| telemetry event, Kafka, metrics dashboard | `behavior_instrument_metrics_pipeline` |
| data pipeline, experiment, drift, telemetry | `behavior_instrument_metrics_pipeline`, `behavior_align_storage_layers`, `behavior_update_docs_after_changes` |
| CORS, auth decorator, bearer token, cookie | `behavior_lock_down_security_surface` |
| PRD sync, alignment log, checklist, progress tracker | `behavior_update_docs_after_changes`, `behavior_handbook_compliance_prompt` |
| consent, JIT auth, scope catalog, prototype | `behavior_prototype_consent_ux`, `behavior_instrument_metrics_pipeline` |
| budget, ROI, forecast, payback | `behavior_validate_financial_impact`, `behavior_instrument_metrics_pipeline` |
| launch plan, messaging, funnel, adoption | `behavior_plan_go_to_market`, `behavior_instrument_metrics_pipeline` |
| threat model, vulnerability, pen test, SOC2 | `behavior_lock_down_security_surface`, `behavior_prevent_secret_leaks` |
| accessibility, WCAG, screen reader, keyboard nav | `behavior_validate_accessibility` |
| benchmark, research proposal, behavior extraction | `behavior_curate_behavior_handbook`, `behavior_instrument_metrics_pipeline`, `behavior_lock_down_security_surface` |
| secret leak, token, credential, gitleaks | `behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials` |
| git workflow, branching, merge policy | `behavior_git_governance`, `behavior_prevent_secret_leaks` |
| ci pipeline, deployment, rollback | `behavior_orchestrate_cicd`, `behavior_prevent_secret_leaks` |
| new reusable workflow discovered | Add a behavior entry |

## Agent etiquette
- **Testing & validation**: After every substantive change, run the smallest relevant Python or frontend check—`python -m pytest`, targeted module scripts, or lint commands. Record the command and outcome. If no automated check exists, perform a smoke test and log the result.
- **Environment discipline**: Never hardcode paths or secrets. Prefer configuration via environment variables or `.env` files loaded through the shared settings module. When a secret leaks, cite `behavior_rotate_leaked_credentials` and initiate rotation steps immediately.
- **Service calls**: When backend code can call internal services directly, avoid loopback HTTP calls unless the architecture explicitly separates them. If you must call another service, make the base URL and credentials configurable and document them.
- **Scope control**: Keep edits focused on the active behaviors. If you uncover additional debt, note it under "next steps" instead of addressing it silently.
- **Documentation**: Whenever APIs, env vars, or workflows change, update `README.md`, `PRD.md`, `PRD_ALIGNMENT_LOG.md`, or other relevant docs and cite `behavior_update_docs_after_changes` in the summary.
- **Logging**: Maintain structured logging with run IDs and timestamps when touching orchestration or services. This improves observability and simplifies incident response.
- **Metrics discipline**: When implementing flows that influence platform outcomes, confirm telemetry feeds the success targets from `PRD.md` (behavior reuse, token savings, completion rate, compliance coverage) and capture evidence in the summary.
- **Correctness-first changes**: Ensure every code modification preserves correctness, keeps the diff minimal, and explicitly guards edge and corner cases—even inside inherited or deeply nested structures.
- **Root-cause focus**: Avoid blanket or quick fixes that merely hide failures; diagnose and remediate the underlying issue so symptoms do not reappear elsewhere.
- **Conservative normalization**: Normalize inputs only when required, maintaining API contracts, extensibility, and invariants across Python built-ins and supported library types.
- **Accurate messaging & docs**: Keep error and warning text, exceptions, and documentation technically precise, actionable, and updated alongside any behavior change.
- **Compatibility discipline**: Account for backwards and forwards compatibility by using feature detection or guards where possible so downstream environments continue to function.
- **Data integrity safeguards**: Never discard, mask, or mutate user data, hooks, plugin registrations, or extension points silently; when migrations are unavoidable, make them invertible or document recovery paths.

## Behaviors

### `behavior_unify_execution_records`
- **When**: Any work involves run persistence, SSE updates, CLI status, or multiple execution record models.
- **Steps**:
  1. Inventory all execution record definitions and storage adapters involved in the change.
  2. Align fields with the RunService contract in `MCP_SERVER_DESIGN.md`, the action payloads in `ACTION_SERVICE_CONTRACT.md`, and the evidence tracked in `PROGRESS_TRACKER.md`.
  3. Route all mutations through the canonical RunService or ActionService APIs; avoid ad-hoc database writes that bypass audit logging.
  4. Validate by triggering a behavior run and confirming the Web surface, CLI, API, and MCP surfaces observe consistent state transitions.
  5. Add or update regression tests covering create, progress updates, completion, and failure paths across telemetry and audit sinks.

### `behavior_align_storage_layers`
- **When**: Modifying `UnifiedStorage`, JSON/SQLite/Firestore adapters, or Firestore data services.
- **Steps**:
  1. Check for duplicate methods or mismatched field names between adapters and services.
  2. Normalize method signatures, return types, and filters (e.g., prefer `agent_id`) in line with `AUDIT_LOG_STORAGE.md` and `REPRODUCIBILITY_STRATEGY.md`.
  3. Update schema docs and indexes, calling out retention or WORM requirements.
  4. Write tests that exercise the affected methods across at least two storage backends (e.g., local JSON + Postgres emulator).
  5. Document any migrations or manual steps in the summary, `BUILD_TIMELINE.md`, and `PRD_ALIGNMENT_LOG.md`.

### `behavior_externalize_configuration`
- **When**: Encountering hardcoded file paths, ports, Firebase configs, or API keys.
- **Steps**:
  1. Add typed configuration entries (e.g., via `config/settings.py`) for every constant discovered.
  2. Load defaults from environment variables or `.env` files with safe fallbacks for local development, matching the device-flow guidance in `SECRETS_MANAGEMENT_PLAN.md`.
  3. Update Docker Compose, deployment manifests, and `.env.example` to reflect the new variables.
  4. Remove the hardcoded values and ensure the app fails fast with descriptive errors if config is missing.
  5. Cite `behavior_update_docs_after_changes` and refresh setup docs and runbooks.

### `behavior_harden_service_boundaries`
- **When**: Code makes loopback HTTP calls, uses inline API keys, or crosses service boundaries inconsistently.
- **Steps**:
  1. Determine whether the call should remain in-process (monolith) or use an external client (microservice).
  2. For in-process orchestrations, replace HTTP fallbacks with direct service calls that honor the contracts in `ACTION_SERVICE_CONTRACT.md` and `MCP_SERVER_DESIGN.md`.
  3. For genuine cross-service calls, move base URLs and credentials into configuration, add authentication guards, and log failures clearly.
  4. Add integration tests for ActionService, BehaviorService, or RunService interactions touched by the change.
  5. Remove any hardcoded secrets and rotate if previously exposed (`behavior_rotate_leaked_credentials`).

### `behavior_curate_behavior_handbook`
- **When**: Updating behavior definitions, prompts, or retrieval metadata for guideAI.
- **Steps**:
  1. Review existing entries in `AGENTS.md`, `ACTION_REGISTRY_SPEC.md`, and `MCP_SERVER_DESIGN.md` to avoid duplicating behaviors.
  2. Ensure each new or revised behavior includes clear triggers, role expectations, and validation steps tied to Strategist → Teacher → Student responsibilities.
  3. Update the BehaviorService index and retrieval metadata to keep the handbook searchable across Web, CLI, API, and MCP surfaces.
  4. Add regression prompts or tests to confirm the new behavior is referenced during behavior-conditioned inference or reflection flows.
  5. Log the update in `PRD_ALIGNMENT_LOG.md` and, if it introduces reusable workflows, note the change in `PRD_NEXT_STEPS.md`.

### `behavior_sanitize_action_registry`
- **When**: Touching action registry schemas, defaults, or multi-tier storage.
- **Steps**:
  1. Keep registry modules inside the package tree and eliminate `sys.path` hacks or ad-hoc imports.
  2. Ensure default URLs and identifiers match the contract in `ACTION_REGISTRY_SPEC.md` and are configurable across environments.
  3. Provide graceful fallbacks when a registry tier is unavailable and document replay implications per `REPRODUCIBILITY_STRATEGY.md`.
  4. Add tests for registry resolution order, error handling, and CLI/API parity (`guideai record-action`, `guideai replay`).
  5. Reflect structural updates in packaging, docs, and samples referenced by `PRD.md`.

### `behavior_instrument_metrics_pipeline`
- **When**: Telemetry events, dashboards, or metrics contracts need updates.
- **Steps**:
  1. Map the change against `TELEMETRY_SCHEMA.md`, `RETRIEVAL_ENGINE_PERFORMANCE.md`, and the MetricsService responsibilities in `MCP_SERVER_DESIGN.md`.
  2. Ensure every event carries run IDs, behavior references, and token accounting required for PRD success metrics (70% behavior reuse, 30% token savings, 80% completion, 95% compliance coverage).
  3. Update Kafka topics, warehouse schemas, and WORM storage retention notes as needed; document deltas in `AUDIT_LOG_STORAGE.md` if evidence flows shift.
  4. Add automated checks or smoke scripts that validate event emission and replay, then capture results in the task summary.
  5. Coordinate dashboard or analytics notebook updates and log them in `PRD_ALIGNMENT_LOG.md` and `BUILD_TIMELINE.md`.

### `behavior_wire_cli_to_orchestrator`
- **When**: Implementing or modifying CLI commands that control runs.
- **Steps**:
  1. Map CLI subcommands to RunService, ActionService, and BehaviorService methods defined in `MCP_SERVER_DESIGN.md`.
  2. Support key operations (`guideai run`, `guideai status`, `guideai stop`, `guideai record-action`, `guideai replay`, `guideai backends`) with clear arguments and help text that align with `ACTION_REGISTRY_SPEC.md`.
  3. Add Click-based unit tests covering happy path and failure scenarios, including parity between CLI, API, and MCP flows.
  4. Ensure CLI output references run IDs that match the unified execution records and progress events surfaced in `PROGRESS_TRACKER.md`.
  5. Update CLI documentation, quickstart guides, and examples referenced in `PRD.md`.

### `behavior_lock_down_security_surface`
- **When**: Adjusting CORS, auth middleware, or handling secrets/API keys.
- **Steps**:
  1. Restrict CORS origins using configuration with safe dev defaults and documentable overrides per `MCP_SERVER_DESIGN.md`.
  2. Audit endpoints for auth decorators and consistent session/token validation, ensuring parity across Web, API, CLI, and MCP surfaces.
  3. Remove inline secrets; load from secure config and recommend rotation for any exposure following `SECRETS_MANAGEMENT_PLAN.md`.
  4. Add or update security tests (lint checks, automated scans, or targeted unit tests).
  5. Summarize security posture changes and next steps, noting any incident evidence in `PRD_ALIGNMENT_LOG.md`.

### `behavior_update_docs_after_changes`
- **When**: Any behavior materially changes developer setup, API contracts, or UX flows.
- **Steps**:
  1. Update `README.md`, `PRD.md`, `PRD_NEXT_STEPS.md`, `BUILD_TIMELINE.md`, and related docs with the latest instructions or references.
  2. Regenerate API reference material if endpoints or schemas shift, including ActionService or BehaviorService contracts.
  3. Log the documentation change in `PRD_ALIGNMENT_LOG.md` and mention updates in the final summary so maintainers know where to look.

### `behavior_prototype_consent_ux`
- **When**: Designing or updating consent experiences across Web, CLI, or IDE surfaces.
- **Steps**:
  1. Review requirements in `docs/AGENT_AUTH_ARCHITECTURE.md` §§18-19 and the detailed plan in `docs/CONSENT_UX_PROTOTYPE.md`.
  2. Ensure copy references scope catalog entries (`schema/agentauth/scope_catalog.yaml`) and clearly states purpose, expiry, and obligations.
  3. Define telemetry events for prompt impressions, approvals, denials, snoozes, and latency; coordinate with Analytics to validate dashboards.
  4. Capture accessibility acceptance criteria (keyboard navigation, screen-reader labels, contrast) and run WCAG AA checks.
  5. Log findings and next steps in `PRD_ALIGNMENT_LOG.md`, update trackers, and plan CMD-007 action logging once instrumentation lands.

### `behavior_rotate_leaked_credentials`
- **When**: Secrets, keys, or credentials appear in code, logs, or chat.
- **Steps**:
  1. Remove the leaked artifact from the repo and ensure `.gitignore` blocks future commits.
  2. Instruct the user to rotate every affected credential and provide context-specific guidance per `SECRETS_MANAGEMENT_PLAN.md`.
  3. If the secret reached git history, document scrub steps (`git filter-repo`, etc.).
  4. Replace production secrets with placeholders in `.env.example` or config docs.
  5. Note the incident in the summary with remediation status and capture evidence in `PROGRESS_TRACKER.md` if the rotation ties to a milestone.

### `behavior_handbook_compliance_prompt`
- **When**: Starting a task, resuming after a long pause, or when the user requests assurance of handbook adherence.
- **Steps**:
  1. Walk through `agents-compliance-checklist.md` before executing work.
  2. Explicitly reference the behaviors you will follow in your plan.
  3. Reconfirm checklist compliance after major milestones (plan, implementation, validation).
  4. If new reusable patterns emerge, add behaviors and update the checklist promptly.

### `behavior_prevent_secret_leaks`
- **When**: Initializing repositories, preparing commits/pushes, or wiring CI pipelines where sensitive tokens might leak.
- **Steps**:
  1. Confirm `.gitignore` excludes secrets directories/files and extend if new providers are introduced.
  2. Ensure `pre-commit` is installed and the repo hook (`.pre-commit-config.yaml`) is active via `pre-commit install`.
  3. Run `scripts/scan_secrets.sh` (or `pre-commit run gitleaks --all-files`) before opening PRs; remediate any findings immediately.
  4. Record a `guideai scan-secrets` action with referenced behaviors (`behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials`) and attach sanitized reports.
  5. Escalate recurring findings to Compliance and update `SECRETS_MANAGEMENT_PLAN.md` with new suppression rules or rotation steps.

### `behavior_git_governance`
- **When**: Creating branches, preparing merges/rebases, coordinating cross-surface reviews, or mirroring repos across hosts (GitHub/GitLab/Bitbucket/self-hosted).
- **Steps**:
  1. Review `docs/GIT_STRATEGY.md` for branching, commit messaging, and review guardrails relevant to the task.
  2. Create feature branches using `role/short-slug`, run `pre-commit run` (including gitleaks), and ensure `scripts/scan_secrets.sh` passes before pushing.
  3. Include ActionService action IDs and cited behaviors in commit/PR descriptions; ensure `guideai record-action` logs reference the branch work.
  4. Require cross-role review prior to merge and confirm CI executed `guideai scan-secrets`, tests, and lint/build jobs successfully.
  5. Update `PROGRESS_TRACKER.md`, tag releases as needed, and document outcomes in `PRD_ALIGNMENT_LOG.md` when branches merge or repositories mirror.

### `behavior_orchestrate_cicd`
- **When**: Designing or updating CI/CD pipelines, deployment workflows, or environment automation across GitHub/GitLab/Bitbucket/self-hosted runners.
- **Steps**:
  1. Reference `docs/AGENT_DEVOPS.md`, `docs/GIT_STRATEGY.md`, and `.github/workflows/ci.yml` (or equivalent) to ensure parity with local guardrails.
  2. Configure pipelines to run `pre-commit run --all-files`, `pytest`, `npm run build`, and secret scanning (`guideai scan-secrets` when available) before merge/deploy.
  3. Capture deployment telemetry and link runs to ActionService entries, including rollback metadata and environment identifiers.
  4. Coordinate with Security/Compliance to manage secrets via `SECRETS_MANAGEMENT_PLAN.md`; document changes in `PRD_ALIGNMENT_LOG.md` and update runbooks.
  5. Validate pipelines via dry run or staging deploy, then update `PROGRESS_TRACKER.md`, `BUILD_TIMELINE.md`, and incident playbooks as needed.

### `behavior_validate_financial_impact`
- **When**: Evaluating budget requests, ROI analyses, pricing impacts, or telemetry-driven savings claims.
- **Steps**:
  1. Collect latest cost forecasts, vendor quotes, and telemetry baselines tied to the initiative.
  2. Model best/base/worst-case scenarios, documenting assumptions and sensitivity to adoption metrics.
  3. Validate ROI/payback targets against Finance guardrails; highlight gaps or overages explicitly.
  4. Ensure financial telemetry (token savings %, cost per task) is instrumented and reviewed with `behavior_instrument_metrics_pipeline`.
  5. Record outcomes, approvals, and outstanding actions in `PRD_ALIGNMENT_LOG.md` and `PROGRESS_TRACKER.md`.

### `behavior_plan_go_to_market`
- **When**: Crafting or reviewing launch plans, messaging frameworks, enablement kits, or adoption campaigns.
- **Steps**:
  1. Map target segments, personas, and JTBD to concrete value propositions using current telemetry evidence.
  2. Align messaging, pricing, and packaging across Web, API, CLI, and MCP surfaces for parity.
  3. Inventory launch assets (announcements, demos, sales enablement) and assign owners with delivery dates.
  4. Define adoption KPIs, feedback loops, and telemetry dashboards in coordination with `behavior_instrument_metrics_pipeline`.
  5. Capture launch readiness status, risks, and mitigations in `PRD_NEXT_STEPS.md` and `BUILD_TIMELINE.md`.

### `behavior_validate_accessibility`
- **When**: Designing, implementing, or auditing user-facing workflows for accessibility compliance.
- **Steps**:
  1. Run automated scans (axe, Lighthouse, PA11y) across responsive breakpoints and document findings.
  2. Perform manual keyboard and screen reader walkthroughs, validating focus order, announcements, and shortcuts.
  3. Review copy, error messaging, and documentation for clarity, localization, and consistent tone.
  4. Verify components expose semantic markup and ARIA metadata; escalate gaps to shared component owners.
  5. Track remediation commitments, retest results, and evidence links in `PRD_ALIGNMENT_LOG.md` and accessibility dashboards.

  ### `behavior_prevent_secret_leaks`
  - **When**: Initializing repositories, preparing commits/pushes, or wiring CI pipelines where sensitive tokens might leak.
  - **Steps**:
    1. Confirm `.gitignore` excludes secrets directories/files and extend if new providers are introduced.
  2. Ensure `pre-commit` is installed and enable the repo hooks by running `./scripts/install_hooks.sh` (wraps `pre-commit install`).
    3. Run `scripts/scan_secrets.sh` (or `pre-commit run gitleaks --all-files`) before opening PRs; remediate any findings immediately.
    4. Record a `guideai scan-secrets` action with referenced behaviors (`behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials`) and attach sanitized reports.
    5. Escalate recurring findings to Compliance and update `SECRETS_MANAGEMENT_PLAN.md` with new suppression rules or rotation steps.

_Last updated: 2025-10-17_

# Agent Compliance Checklist

Use this checklist at the start of every task and after major milestones to stay aligned with `AGENTS.md` and keep work auditable.

1. **Scan triggers** – Review the Quick Triggers table in `AGENTS.md` and list which behaviors apply to the request (e.g., `behavior_unify_execution_records`, `behavior_externalize_configuration`).
2. **Map roles** – Note the Strategist, Teacher, and Student responsibilities for the task so each role’s duties are covered.
3. **Plan with behaviors** – Present your plan to the user, naming the behaviors you’ll follow and explaining how they guide the work.
4. **Execute + log** – While implementing, track commands, files touched, validations, and any config changes so the Student report is precise.
5. **Validate** – Run the smallest relevant automated check (tests, linters, smoke scripts). If a check is skipped or unavailable, document why and the next best alternative.
6. **Summarize with citations** – In the final response, list completed work, validation outcomes, and cite the behaviors applied. Call out any follow-up tasks or risks.
7. **Update the handbook if needed** – When you uncover a reusable workflow that isn’t documented, add a new behavior to `AGENTS.md` and extend this checklist if required.

Following these steps satisfies `behavior_handbook_compliance_prompt` and keeps the remediation workflow transparent.
