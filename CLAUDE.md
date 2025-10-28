# Claude Code Instructions for GuideAI

> **Platform Overview**: GuideAI is a metacognitive behavior handbook platform inspired by Meta AI's research showing 46% token reduction through procedural memory reuse. This document provides comprehensive context for Claude agents working on the platform.

---

## 🎯 Quick Start: Core Concepts

### **Product Vision**
GuideAI productizes the "behavior handbook" pattern—reusable reasoning procedures that reduce token usage, improve consistency, and maintain compliance across AI-assisted development workflows.

### **Success Metrics** (from `PRD.md`)
- **70% behavior reuse rate** across tasks
- **30% token savings** vs. full chain-of-thought
- **80% task completion rate** with behavior guidance
- **95% compliance coverage** via automated checklists

### **Current Phase** (October 2025)
- ✅ **Phase 1 Complete**: Service Parity (11/11 services with CLI/API/MCP coverage)
- 🚧 **Phase 3 Active**: PostgreSQL migration validation and infrastructure hardening
- ⏳ **Phase 4 Next**: Retrieval Engine (BGE-M3 + FAISS for behavior search)

---

## 📚 Architecture Overview

### **Core Services** (see `MCP_SERVER_DESIGN.md`)

| Service | Purpose | Storage | Status |
|---------|---------|---------|--------|
| **BehaviorService** | Behavior CRUD, versioning, handbook management | SQLite → PostgreSQL | ✅ Operational |
| **WorkflowService** | Template management, behavior-conditioned inference | SQLite → PostgreSQL | ✅ Operational |
| **ActionService** | Immutable action registry, replay capability | SQLite → PostgreSQL | ✅ Operational |
| **RunService** | Execution tracking, progress events, SSE streams | SQLite → PostgreSQL | ✅ Operational |
| **ComplianceService** | Checklist automation, coverage scoring | In-memory | ✅ Operational |
| **ReflectionService** | Behavior extraction from traces | Design phase | ⏳ Planned |
| **MetricsService** | Analytics dashboards, token accounting | Design phase | ⏳ Planned |
| **AgentOrchestratorService** | Runtime agent switching | SQLite | ✅ CLI complete |

### **Multi-Surface Parity Contract**
Every capability must work identically across:
- **CLI**: `guideai <command>` (Python Click, ~2500 lines in `guideai/cli.py`)
- **REST API**: FastAPI endpoints (design complete, wiring pending)
- **MCP Tools**: Model Context Protocol servers (`mcp/tools/*.json`)
- **VS Code Extension**: Tree views, webviews, commands (`extension/src/`)

**Validation**: 17 passing parity test suites in `tests/test_*_parity.py`

---

## 🤖 Agent Roles & Workflow

GuideAI uses a **Strategist → Teacher → Student** pipeline inspired by Meta's paper:

### **Strategist** (Planning Layer)
**Responsibilities:**
- Decompose user requests into actionable steps
- Scan `AGENTS.md` Quick Triggers table to identify applicable behaviors
- Propose plans citing specific behaviors (e.g., `behavior_align_storage_layers`)
- Update `AGENTS.md` when discovering new reusable patterns

**Before acting:**
- Review `PRD.md` for product vision and success metrics
- Check `MCP_SERVER_DESIGN.md` for service contracts
- Consult `AGENTS.md` for existing behaviors
- Map work to Strategist → Teacher → Student pipeline

### **Teacher** (Communication Layer)
**Responsibilities:**
- Explain Strategist's plan in clear, actionable terms
- Cite behaviors explicitly in responses (e.g., "Following `behavior_update_docs_after_changes`...")
- Surface validation steps and expected outcomes
- Map work to PRD success metrics

**Output format:**
- Actions taken (with behavior citations)
- Files changed
- Validation results
- Requirements coverage
- Next steps

### **Student** (Execution Layer)
**Responsibilities:**
- Execute approved plans precisely
- Run smallest relevant automated checks (pytest, linters, compile)
- Report commands executed, files modified, validation outcomes
- Reference behaviors followed
- Update `PROGRESS_TRACKER.md` and `BUILD_TIMELINE.md` with evidence

**After execution:**
- ✅ List what passed
- 🚧 Flag blockers or partial completions
- 📋 Document next steps

---

## 📖 Behavior Handbook (from `AGENTS.md`)

### **Quick Triggers**
Scan this table before starting any task:

| Trigger keywords | Behavior(s) |
| --- | --- |
| execution record, SSE, progress, run status | `behavior_unify_execution_records` |
| storage adapter, audit log, timeline, run history | `behavior_align_storage_layers` |
| config path, env var, secrets manager, device flow | `behavior_externalize_configuration`, `behavior_rotate_leaked_credentials` |
| BehaviorService, behavior index, reflection prompt | `behavior_curate_behavior_handbook` |
| action registry, parity, `guideai record-action` | `behavior_sanitize_action_registry`, `behavior_wire_cli_to_orchestrator` |
| telemetry event, Kafka, metrics dashboard | `behavior_instrument_metrics_pipeline` |
| CORS, auth decorator, bearer token, cookie | `behavior_lock_down_security_surface` |
| PRD sync, alignment log, checklist, progress tracker | `behavior_update_docs_after_changes`, `behavior_handbook_compliance_prompt` |
| secret leak, token, credential, gitleaks | `behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials` |
| git workflow, branching, merge policy | `behavior_git_governance`, `behavior_prevent_secret_leaks` |
| ci pipeline, deployment, rollback | `behavior_orchestrate_cicd`, `behavior_prevent_secret_leaks` |
| PostgreSQL, migration, schema, data transfer | `behavior_align_storage_layers`, `behavior_unify_execution_records` |

### **Key Behaviors**

#### `behavior_unify_execution_records`
**When:** Work involves run persistence, SSE updates, CLI status, or execution records.

**Steps:**
1. Inventory all execution record definitions and storage adapters
2. Align fields with RunService contract (`MCP_SERVER_DESIGN.md`), ActionService payloads (`ACTION_SERVICE_CONTRACT.md`)
3. Route mutations through canonical RunService/ActionService APIs
4. Validate state transitions across Web/CLI/API/MCP surfaces
5. Add regression tests covering create/progress/complete/failure paths

#### `behavior_align_storage_layers`
**When:** Modifying `UnifiedStorage`, adapters, or Firestore data services.

**Steps:**
1. Check for duplicate methods or mismatched field names
2. Normalize method signatures, return types per `AUDIT_LOG_STORAGE.md`, `REPRODUCIBILITY_STRATEGY.md`
3. Update schema docs and indexes
4. Write tests across 2+ storage backends
5. Document migrations in `BUILD_TIMELINE.md`, `PRD_ALIGNMENT_LOG.md`

#### `behavior_externalize_configuration`
**When:** Encountering hardcoded paths, ports, configs, or API keys.

**Steps:**
1. Add typed config entries via `config/settings.py`
2. Load from environment variables or `.env` files
3. Update Docker Compose, deployment manifests, `.env.example`
4. Remove hardcoded values, fail fast with descriptive errors if config missing
5. Update setup docs per `behavior_update_docs_after_changes`

#### `behavior_prevent_secret_leaks`
**When:** Initializing repos, preparing commits, or wiring CI where tokens might leak.

**Steps:**
1. Confirm `.gitignore` excludes secrets directories/files
2. Ensure `pre-commit` is installed and active via `./scripts/install_hooks.sh`
3. Run `scripts/scan_secrets.sh` before opening PRs
4. Record `guideai scan-secrets` action with referenced behaviors
5. Escalate recurring findings to Compliance, update `SECRETS_MANAGEMENT_PLAN.md`

#### `behavior_update_docs_after_changes`
**When:** Any material change to setup, API contracts, or UX flows.

**Steps:**
1. Update `README.md`, `PRD.md`, `PRD_NEXT_STEPS.md`, `BUILD_TIMELINE.md`
2. Regenerate API reference if endpoints/schemas shift
3. Log change in `PRD_ALIGNMENT_LOG.md`
4. Mention updates in final summary

#### `behavior_instrument_metrics_pipeline`
**When:** Touching telemetry events, dashboards, or metrics contracts.

**Steps:**
1. Map change against `TELEMETRY_SCHEMA.md`, `MCP_SERVER_DESIGN.md` MetricsService
2. Ensure events carry run IDs, behavior references, token accounting
3. Update Kafka topics, warehouse schemas, retention notes per `AUDIT_LOG_STORAGE.md`
4. Add automated checks validating event emission
5. Document dashboard/notebook updates in `PRD_ALIGNMENT_LOG.md`

#### `behavior_lock_down_security_surface`
**When:** Adjusting CORS, auth middleware, or handling secrets/API keys.

**Steps:**
1. Restrict CORS origins using configuration with safe dev defaults
2. Audit endpoints for auth decorators and consistent session/token validation
3. Remove inline secrets; load from secure config per `SECRETS_MANAGEMENT_PLAN.md`
4. Add or update security tests
5. Summarize security posture changes in `PRD_ALIGNMENT_LOG.md`

---

## 🛠️ Agent Etiquette

### **Testing & Validation**
- After every substantive change, run smallest relevant check:
  - Python: `pytest tests/test_<module>.py`
  - Frontend: `npm run build` in `extension/` or `dashboard/`
  - Linting: `python -m compileall <file>`, `npm run lint`
- Record command and outcome
- If no automated check exists, perform smoke test and log result

### **Environment Discipline**
- Never hardcode paths or secrets
- Prefer configuration via environment variables or `.env` files loaded through shared settings
- When a secret leaks, cite `behavior_rotate_leaked_credentials` and initiate rotation immediately

### **Service Calls**
- When backend code can call internal services directly, avoid loopback HTTP unless architecture explicitly separates them
- Make base URLs and credentials configurable
- Document service dependencies

### **Scope Control**
- Keep edits focused on active behaviors
- If uncovering additional debt, note under "next steps" instead of addressing silently

### **Documentation**
- Whenever APIs, env vars, or workflows change, update relevant docs
- Cite `behavior_update_docs_after_changes` in summary

### **Logging**
- Maintain structured logging with run IDs and timestamps for orchestration/services
- Improves observability and incident response

### **Metrics Discipline**
- When implementing flows affecting platform outcomes, confirm telemetry feeds PRD success targets
- Capture evidence in summary

### **Correctness-First Changes**
- Ensure every modification preserves correctness
- Keep diffs minimal
- Explicitly guard edge and corner cases

### **Root-Cause Focus**
- Avoid blanket fixes that hide failures
- Diagnose and remediate underlying issues

### **Conservative Normalization**
- Normalize inputs only when required
- Maintain API contracts, extensibility, and invariants

### **Accurate Messaging**
- Keep error/warning text, exceptions, and docs technically precise and actionable
- Update alongside behavior changes

### **Compatibility Discipline**
- Account for backwards/forwards compatibility
- Use feature detection or guards where possible

### **Data Integrity Safeguards**
- Never discard, mask, or mutate user data silently
- Make migrations invertible or document recovery paths

---

## 📋 Compliance Checklist

Use this checklist at task start and after major milestones:

1. **Scan triggers** – Review Quick Triggers table, list applicable behaviors
2. **Map roles** – Note Strategist/Teacher/Student responsibilities
3. **Plan with behaviors** – Present plan naming behaviors you'll follow
4. **Execute + log** – Track commands, files, validations, config changes
5. **Validate** – Run smallest relevant automated check
6. **Summarize with citations** – List completed work, outcomes, behaviors applied
7. **Update handbook if needed** – Add new behavior to `AGENTS.md` if discovering reusable workflow

---

## 🗂️ Key Documentation Paths

### **Strategic**
- `PRD.md` – Product vision, personas, success metrics
- `PRD_NEXT_STEPS.md` – Live follow-up items and roadmap
- `PRD_ALIGNMENT_LOG.md` – Cross-document sync history
- `PROGRESS_TRACKER.md` – Milestone tracker with evidence
- `BUILD_TIMELINE.md` – Chronological artifact log

### **Architecture**
- `MCP_SERVER_DESIGN.md` – Control-plane architecture, service contracts
- `ACTION_SERVICE_CONTRACT.md` – ActionService API, schemas, RBAC
- `BEHAVIOR_SERVICE_CONTRACT.md` – BehaviorService lifecycle, versioning
- `WORKFLOW_SERVICE_CONTRACT.md` – WorkflowService templates, BCI algorithm
- `COMPLIANCE_SERVICE_CONTRACT.md` – ComplianceService checklists, scoring
- `AGENT_ORCHESTRATOR_SERVICE_CONTRACT.md` – Runtime agent switching

### **Data & Infrastructure**
- `RETRIEVAL_ENGINE_PERFORMANCE.md` – Retriever SLOs (latency, recall, precision)
- `TELEMETRY_SCHEMA.md` – Event model, pipeline, retention
- `AUDIT_LOG_STORAGE.md` – Immutable evidence, WORM requirements
- `REPRODUCIBILITY_STRATEGY.md` – Action replay, parity expectations
- `SECRETS_MANAGEMENT_PLAN.md` – Auth/rotation policies

### **Operations**
- `docs/POSTGRESQL_MIGRATION_PLAYBOOK.md` – 9-phase migration guide
- `docs/GIT_STRATEGY.md` – Branching, commit messaging, review guardrails
- `docs/AGENT_DEVOPS.md` – CI/CD patterns, deployment workflows
- `deployment/CONTAINER_RUNTIME_DECISION.md` – Podman standardization

### **Domain Agents**
- `AGENT_ENGINEERING.md` – Backend services, migrations, infrastructure
- `AGENT_DX.md` – Developer experience, CLI, VS Code extension
- `AGENT_COMPLIANCE.md` – Security, audit, policy enforcement
- `AGENT_PRODUCT.md` – Roadmap, metrics, user workflows
- `AGENT_FINANCE.md` – Budget, ROI, cost modeling
- `AGENT_GTM.md` – Launch planning, messaging, enablement
- `AGENT_ACCESSIBILITY.md` – WCAG compliance, a11y validation
- `AGENT_SECURITY.md` – Threat modeling, pen testing, SOC2
- `AGENT_AI_RESEARCH.md` – ML experiments, retrieval benchmarks
- `AGENT_DATA_SCIENCE.md` – Analytics pipelines, experimentation

---

## 🚀 Current Priorities (Phase 3 → Phase 4)

### **Phase 3 Closeout (Active – October 2025)**

#### **1. PostgreSQL Migration Validation** ✅ In Progress
- **Status**: Real infrastructure validated with Podman containers
- **Evidence**: `artifacts/migration/2025-10-24-real-infra/rehearsal.(json|md)`
- **Next**: Production cutover for BehaviorService + WorkflowService
- **Playbook**: `docs/POSTGRESQL_MIGRATION_PLAYBOOK.md` (9 phases documented)

#### **2. Extend to ActionService + ComplianceService Migrations**
- **Scope**: Create `004_create_action_service.sql`, `005_create_compliance_service.sql`
- **Pattern**: Follow BehaviorService/WorkflowService migration tooling
- **Timeline**: 3-5 days per service

#### **3. Agent Orchestration REST/MCP Parity**
- **Scope**: Wire `guideai agents assign/switch/status` to API + MCP tools
- **Contracts**: `AGENT_ORCHESTRATOR_SERVICE_CONTRACT.md`
- **Timeline**: 5-7 days

### **Phase 4 Kickoff (Next – November 2025)**

#### **1. Retrieval Engine (Priority 1)**
- **Tech**: BGE-M3 embeddings + FAISS index
- **Targets**: <100ms p95 latency, >0.85 recall@5, >0.90 precision@5
- **Blockers**: ✅ Unblocked (PostgreSQL behavior corpus ready)
- **Timeline**: 2-3 weeks

#### **2. ReflectionService (Priority 2)**
- **Scope**: Extract behaviors from Strategist traces, populate handbook
- **Dependencies**: Retrieval engine operational
- **Timeline**: 2-3 weeks

#### **3. MetricsService Analytics (Priority 3)**
- **Scope**: Dashboards for PRD success metrics across surfaces
- **Features**: Real-time metrics, CLI analytics, MCP tools, exportable reports
- **Timeline**: 2-3 weeks

---

## 🏗️ Project Structure

```
guideai/
├── PRD.md, MCP_SERVER_DESIGN.md, AGENTS.md        # Strategic docs
├── guideai/                                         # Python package
│   ├── behavior_service.py                         # BehaviorService (720 lines)
│   ├── workflow_service.py                         # WorkflowService (600 lines)
│   ├── action_service.py                           # ActionService (500 lines)
│   ├── run_service.py                              # RunService (450 lines)
│   ├── compliance_service.py                       # ComplianceService (350 lines)
│   ├── agent_orchestrator_service.py               # AgentOrchestratorService (200 lines)
│   ├── cli.py                                      # CLI commands (~2500 lines)
│   ├── api.py                                      # FastAPI app (350 lines)
│   ├── mcp_server.py                               # MCP server (400 lines)
│   └── adapters.py                                 # CLI/REST/MCP adapters
├── mcp/                                            # MCP tool manifests
│   ├── tools/behaviors.*.json                      # BehaviorService MCP (9 tools)
│   ├── tools/workflow.*.json                       # WorkflowService MCP (5 tools)
│   ├── tools/actions.*.json                        # ActionService MCP (6 tools)
│   ├── tools/runs.*.json                           # RunService MCP (6 tools)
│   └── tools/compliance.*.json                     # ComplianceService MCP (5 tools)
├── extension/                                      # VS Code extension
│   ├── src/extension.ts                            # Entry point
│   ├── src/providers/                              # Tree views
│   ├── src/webviews/                               # Panels (behavior detail, plan composer)
│   └── src/client/GuideAIClient.ts                 # CLI bridge
├── schema/migrations/                              # PostgreSQL DDL
│   ├── 001_create_telemetry_warehouse.sql         # TelemetryService schema
│   ├── 002_create_behavior_service.sql            # BehaviorService schema
│   ├── 003_create_workflow_service.sql            # WorkflowService schema
│   └── 004_*, 005_* (planned)                     # ActionService, ComplianceService
├── scripts/                                        # Migration & automation
│   ├── run_postgres_behavior_migration.py         # BehaviorService schema runner
│   ├── migrate_behavior_sqlite_to_postgres.py     # BehaviorService data migrator
│   ├── run_postgres_workflow_migration.py         # WorkflowService schema runner
│   ├── migrate_workflow_sqlite_to_postgres.py     # WorkflowService data migrator
│   ├── run_postgres_migration_rehearsal.py        # Full dry-run orchestrator
│   └── scan_secrets.sh                            # Gitleaks wrapper
├── tests/                                          # Test suites
│   ├── test_behavior_parity.py                    # BehaviorService parity (25 tests)
│   ├── test_workflow_parity.py                    # WorkflowService parity (35 tests)
│   ├── test_action_service_parity.py              # ActionService parity (15 tests)
│   ├── test_run_parity.py                         # RunService parity (22 tests)
│   ├── test_compliance_service_parity.py          # ComplianceService parity (17 tests)
│   └── test_cli_agents.py                         # Agent orchestration (4 tests)
├── docs/                                           # Governance & playbooks
│   ├── POSTGRESQL_MIGRATION_PLAYBOOK.md           # Migration execution guide
│   ├── GIT_STRATEGY.md                            # Branching, commits, reviews
│   ├── AGENT_AUTH_ARCHITECTURE.md                 # JIT consent, policy engine
│   ├── AGENT_DEVOPS.md                            # CI/CD patterns
│   └── capability_matrix.md                       # Cross-surface parity tracker
├── docker-compose.postgres.yml                    # Podman PostgreSQL setup
├── .env.postgres                                  # DSN configuration
└── artifacts/migration/                           # Migration evidence
    └── 2025-10-24-real-infra/rehearsal.(json|md) # Latest rehearsal reports
```

---

## 🎓 Workflow Examples

### **Example 1: Adding a New Behavior**

```bash
# 1. Strategist identifies pattern
# "I noticed we repeatedly normalize timestamps in migrations. Let's add a behavior."

# 2. Teacher plans addition
# - Create behavior entry in AGENTS.md Quick Triggers
# - Add behavior_normalize_timestamps to Behaviors section
# - Document when/steps/validation

# 3. Student executes
# - Edit AGENTS.md with new behavior
# - Update Quick Triggers table
# - Add example usage from migration scripts
# - Run: guideai record-action behavior-added name=normalize_timestamps
# - Update PROGRESS_TRACKER.md with action ID
# - Commit with behavior citation in message

# 4. Validation
pytest tests/test_behavior_service.py  # Ensure no regressions
python -m compileall AGENTS.md         # Syntax check
git diff AGENTS.md                      # Review changes
```

### **Example 2: Running PostgreSQL Migration Rehearsal**

```bash
# 1. Strategist reviews playbook
# - Check docs/POSTGRESQL_MIGRATION_PLAYBOOK.md for prerequisites
# - Identify behaviors: behavior_align_storage_layers, behavior_externalize_configuration

# 2. Teacher prepares environment
# - Start Podman containers: podman-compose -f docker-compose.postgres.yml up -d
# - Load DSNs: source .env.postgres
# - Verify connectivity: podman exec guideai-postgres-behavior psql -U guideai_behavior -c "SELECT 1;"

# 3. Student executes rehearsal
python scripts/run_postgres_migration_rehearsal.py \
  --format both \
  --output-json artifacts/migration/$(date +%Y-%m-%d)/rehearsal.json \
  --output-markdown artifacts/migration/$(date +%Y-%m-%d)/rehearsal.md

# 4. Record action
guideai record-action migration-rehearsal \
  service=behavior,workflow \
  status=pass \
  duration=$(cat artifacts/migration/$(date +%Y-%m-%d)/rehearsal.json | jq .duration)

# 5. Update docs
# - Add entry to BUILD_TIMELINE.md
# - Update PROGRESS_TRACKER.md with evidence path
# - Log in PRD_ALIGNMENT_LOG.md

# 6. Validation
cat artifacts/migration/$(date +%Y-%m-%d)/rehearsal.json | jq '.services.behavior.schema_step.returncode'
# Should output: 0
```

### **Example 3: Implementing New MCP Tool**

```bash
# 1. Strategist defines tool contract
# - Review MCP_SERVER_DESIGN.md for existing patterns
# - Check ACTION_SERVICE_CONTRACT.md for schemas
# - Behaviors: behavior_wire_cli_to_orchestrator, behavior_lock_down_security_surface

# 2. Teacher plans implementation
# - Create MCP tool manifest in mcp/tools/<service>.<operation>.json
# - Update guideai/mcp_server.py with tool handler
# - Add corresponding CLI command in guideai/cli.py
# - Write parity test in tests/test_<service>_parity.py

# 3. Student implements
# mcp/tools/behaviors.search.json (manifest)
{
  "name": "behaviors.search",
  "description": "Search behavior handbook by keywords",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "role_focus": {"type": "string", "enum": ["strategist", "teacher", "student"]}
    },
    "required": ["query"]
  }
}

# guideai/mcp_server.py (handler)
@server.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    if name == "behaviors.search":
        result = behavior_service.search(
            query=arguments["query"],
            role_focus=arguments.get("role_focus")
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

# 4. Test parity
pytest tests/test_behavior_parity.py::test_search_parity -v

# 5. Record and document
guideai record-action mcp-tool-added tool=behaviors.search
# Update docs/capability_matrix.md with new row
# Add entry to BUILD_TIMELINE.md
```

---

## 🔍 Debugging Tips

### **Storage Layer Issues**
- Check `guideai/unified_storage.py` for adapter consistency
- Verify SQLite files exist: `ls -lh ~/.guideai/data/`
- Inspect PostgreSQL connections: `podman exec guideai-postgres-<service> psql -U <user> -d <db> -c "\dt"`
- Review migration logs: `cat artifacts/migration/*/rehearsal.md`

### **Parity Test Failures**
- Run single test: `pytest tests/test_<service>_parity.py::test_<operation>_parity -v`
- Compare CLI vs. API output: `guideai <command> --format json` vs. `curl localhost:8000/v1/<endpoint>`
- Check MCP tool manifest: `cat mcp/tools/<service>.<operation>.json`
- Verify adapter wiring: `grep -A 10 "def <operation>" guideai/adapters.py`

### **Secret Leaks**
- Run scan: `scripts/scan_secrets.sh`
- Check `.gitignore`: `cat .gitignore | grep -i secret`
- Review recent commits: `git log --all --full-history --source -- '*secret*' '*token*' '*password*'`
- If leaked, follow `behavior_rotate_leaked_credentials` immediately

### **Agent Orchestration**
- List available agents: `guideai agents status`
- Check assignment history: `cat ~/.guideai/agent_context.json`
- View subagent definitions: `ls -l .rulesync/subagents/` (if implemented)
- Test MCP tools: `guideai mcp-test agents.assign --agent strategist`

---

## 📞 Escalation Paths

### **Engineering Issues**
- **Storage/Migration**: Consult `docs/POSTGRESQL_MIGRATION_PLAYBOOK.md` Appendix A (Troubleshooting)
- **Service Contracts**: Review `*_SERVICE_CONTRACT.md` files
- **Parity Failures**: Check `docs/capability_matrix.md` for known gaps

### **Compliance Issues**
- **Security**: Review `SECRETS_MANAGEMENT_PLAN.md`, run `scripts/scan_secrets.sh`
- **Audit**: Check `AUDIT_LOG_STORAGE.md` for retention requirements
- **Policy**: Consult `docs/AGENT_AUTH_ARCHITECTURE.md` for scope enforcement

### **Documentation Issues**
- **Sync**: Log in `PRD_ALIGNMENT_LOG.md`, update `PRD_NEXT_STEPS.md`
- **Gaps**: Add to domain agent playbooks (`AGENT_*.md`)
- **Evidence**: Record in `BUILD_TIMELINE.md` with action ID

---

## ✅ Pre-Commit Checklist

Before committing code:

1. **Run tests**: `pytest tests/test_<affected_module>.py`
2. **Scan secrets**: `scripts/scan_secrets.sh`
3. **Lint code**: `python -m compileall <files>`, `npm run lint` (if frontend)
4. **Update docs**: Check `behavior_update_docs_after_changes` requirements
5. **Record action**: `guideai record-action <type> <metadata>`
6. **Cite behaviors**: Include in commit message (e.g., `behavior_align_storage_layers`)
7. **Update trackers**: Add entry to `BUILD_TIMELINE.md`, update `PROGRESS_TRACKER.md` if milestone-related

---

## 🎉 Success Indicators

You're following guideAI patterns correctly when:

- ✅ Every task starts by scanning `AGENTS.md` Quick Triggers
- ✅ Plans explicitly cite 2-3 applicable behaviors
- ✅ Automated tests run after every change
- ✅ Documentation updates accompany code changes
- ✅ Actions are recorded via `guideai record-action`
- ✅ Parity maintained across CLI/API/MCP surfaces
- ✅ Secrets never appear in code or commits
- ✅ Evidence captured in `BUILD_TIMELINE.md` and `PROGRESS_TRACKER.md`
- ✅ Behaviors referenced in commit messages and summaries

---

## 📚 Further Reading

- **Meta AI Paper**: `Metacognitive_reuse.txt` – Original research inspiration
- **Agent Reviews**: `PRD_AGENT_REVIEWS.md` – Cross-functional feedback examples
- **Milestone Dashboard**: `dashboard/index.html` – Visual progress tracker
- **Consent UX**: `docs/CONSENT_UX_PROTOTYPE.md` – JIT auth patterns
- **Agentic Postgres**: `PRD.md` §Future Enhancements – MCP-native DB playbooks

---

**Last Updated**: 2025-10-27
**Document Owner**: Platform Team
**Feedback**: Update `PRD_ALIGNMENT_LOG.md` with suggestions or gaps
## Additional Instructions

- Prioritize updating existing documentation files instead of creating new summary documents after every update (languages: TypeScript, JavaScript, Python)
- Always run pre-commit hooks before pushing code (languages: JavaScript, Python, TypeScript)
- Use descriptive variable names that explain purpose and intent (languages: JavaScript, TypeScript, Python)
- Document all public API endpoints with OpenAPI specs (languages: JavaScript, TypeScript, Python)
