# WORK_MANAGEMENT_GUIDE.md

This document defines how AI agents use the GuideAI platform to plan and manage the development of GuideAI itself.

> **Last validated**: 2026-02-09 against local GuideAI dev instance.

## 1. Purpose
- Make GuideAI platform development work tracking deterministic and replayable.
- Standardize backlog seeding and day-to-day execution for agents working on GuideAI.
- Ensure all non-trivial implementation work is visible in GuideAI's own project tracking.
- Dogfood the platform: GuideAI tracks its own development, exposing real bugs and UX gaps.

## 2. Required Rules
- Use only `epic`, `story`, and `task` item types.
- Do **not** use `feature` as a work item type.
- All implementation work must be tracked in GuideAI, except trivial fixes under 30 minutes.
- If a trivial fix exceeds 30 minutes, create a GuideAI item immediately.
- Platform bugs discovered during development must be tracked as items on the GuideAI Platform Issues board (see §3.1).
- Reference `AGENTS.md` behaviors in all work — cite `behavior_<name>` and your declared role.

## 3. Canonical Names for GuideAI Tracking

### 3.1 GuideAI Platform Development
- Project name: `GuideAI` / slug: `guideai`
- Project ID (current): `proj-b575d734aa37`
- Board name: `GuideAI Platform Issues`
- Board ID (current): `7342b025-404f-493f-a00c-d88e0859c3c2`
- Owner: `nick.sanders.a@gmail.com` (user ID `112316240869466547718`)

### 3.2 Relationship to WORK_STRUCTURE.md
`WORK_STRUCTURE.md` is the definitive epic/feature/task inventory for the GuideAI platform (14 epics, 150+ features). When creating work items in GuideAI, reference the corresponding epic/feature numbers from `WORK_STRUCTURE.md` in the `metadata.seed_key` field (e.g., `"seed_key": "E8"` for Epic 8: Infrastructure & Staging Readiness).

### 3.3 Relationship to BUILD_TIMELINE.md
`BUILD_TIMELINE.md` is the chronological audit log of completed work (170+ entries). After completing any work item, add an entry to `BUILD_TIMELINE.md` documenting what was done, files modified, and test results.

## 4. Surface Priority (Strict Order)

### 4.1 MCP-first (Preferred)
GuideAI MCP tools work natively in VS Code Copilot Chat. **Always prefer MCP tools when available.**

```
# List projects
mcp_guideai_projects_list

# Get behaviors for a task
mcp_guideai_behaviors_getfortask(task_description="...", role="Student")

# Create work items
mcp_guideai_workitems_create(item_type="task", project_id="proj-b575d734aa37", title="...")

# List work items
mcp_guideai_workitems_list(project_id="proj-b575d734aa37")
```

### 4.2 API (Fallback)
Use the REST API when MCP tools are unavailable or need fine-grained control.

### 4.3 CLI/Script (Fallback)
Use CLI or scripts when API calls need retry logic, state caching, or batch operations.

### 4.4 UI (Last Resort)
Use the web console UI only when all programmatic paths are blocked.

## 5. Infrastructure and Runtime Preflight

### 5.1 Container Runtime
GuideAI runs on **Podman** (not Docker). The Podman VM is named `guideai-dev`.

After a machine reboot, containers must be restarted manually:
```bash
# Start the Podman VM
podman machine start guideai-dev

# Start infrastructure containers first
podman start amp-037de200-8e29-478d-9531-9b08af7d0145-guideai-db \
             amp-037de200-8e29-478d-9531-9b08af7d0145-redis \
             amp-037de200-8e29-478d-9531-9b08af7d0145-zookeeper

# Wait 3s, then start Kafka
sleep 3
podman start amp-037de200-8e29-478d-9531-9b08af7d0145-kafka

# Wait 2s, then start application services
sleep 2
podman start amp-037de200-8e29-478d-9531-9b08af7d0145-guideai-api \
             amp-037de200-8e29-478d-9531-9b08af7d0145-gateway \
             amp-037de200-8e29-478d-9531-9b08af7d0145-execution-worker \
             amp-037de200-8e29-478d-9531-9b08af7d0145-web-console \
             amp-037de200-8e29-478d-9531-9b08af7d0145-telemetry-db \
             amp-037de200-8e29-478d-9531-9b08af7d0145-prometheus \
             amp-037de200-8e29-478d-9531-9b08af7d0145-grafana \
             amp-037de200-8e29-478d-9531-9b08af7d0145-podman-socket-proxy \
             amp-1ffce37b-30d0-4ce8-9ef2-1bdb1a046d32-execution-worker
```

The API container reinstalls Python dependencies on startup. This can take 30–60 seconds. Poll the health endpoint before proceeding.

### 5.2 Health Checks
```bash
# Gateway (reverse proxy)
curl -sS -m 5 http://localhost:8080/health

# API (backend)
curl -sS -m 5 http://localhost:8000/health
```

Wait until both return HTTP 200 before making API calls. The gateway may return 502 while the API is still starting.

### 5.3 Database Access
Direct PostgreSQL access for debugging and workarounds:
```bash
podman exec amp-037de200-8e29-478d-9531-9b08af7d0145-guideai-db \
  psql -U guideai -d guideai -c "<SQL>"
```

- **User**: `guideai`
- **Password**: `guideai_dev`
- **Database**: `guideai`
- **Schemas**: `auth`, `board`, `execution`, `behavior`, `workflow`, `consent`, `audit`, `credentials`

Key tables:
- `auth.projects` — PK is `project_id` (varchar), has `owner_id` FK
- `auth.users` — PK is `id` (varchar)
- `board.boards` — PK is `id` (uuid), has `board_id` in API responses
- `board.work_items` — PK is `id` (uuid), has `item_id` in API responses, `parent_id` for hierarchy
- `behavior.behaviors` — PK is `id`, stores the behavior handbook entries
- `execution.runs` — PK is `run_id`, tracks agent execution runs
- `auth.device_sessions` — PK is `device_code`, stores OAuth device flow sessions

### 5.4 Alembic Migrations
GuideAI uses three isolated Alembic environments:

```bash
# Main guideai database
alembic upgrade head

# Workflow database
alembic -c alembic.workflow.ini upgrade head

# Telemetry database (TimescaleDB)
alembic -c alembic.telemetry.ini upgrade head
```

Verify migration state with:
```bash
alembic heads    # Must show exactly ONE head
alembic current  # Shows current revision
```

Refer to `docs/MIGRATION_GUIDE.md` and `behavior_migrate_postgres_schema` for migration procedures.

## 6. Authentication

### 6.1 Working Auth Method: Device Authorization Flow
This is the **only reliable auth method** in the current build. Service Principal tokens are broken (see §14).

Three-step flow:
```bash
# Step 1: Request device code
curl -X POST http://localhost:8080/api/v1/auth/device/authorize \
  -H "Content-Type: application/json" \
  -d '{"client_id": "guideai-agent-cli", "scopes": ["read", "write"]}'
# Returns: {"device_code": "...", "user_code": "XXXX-YYYY", ...}

# Step 2: Approve (self-approve for local dev)
curl -X POST http://localhost:8080/api/v1/auth/device/approve \
  -H "Content-Type: application/json" \
  -d '{"user_code": "XXXX-YYYY", "approver": "guideai-agent"}'

# Step 3: Exchange for access token
curl -X POST http://localhost:8080/api/v1/auth/device/token \
  -H "Content-Type: application/json" \
  -d '{"device_code": "...", "client_id": "guideai-agent-cli"}'
# Returns: {"access_token": "ga_...", "scope": "read write", ...}
```

Use the token in all subsequent requests:
```bash
curl -H "Authorization: Bearer ga_..." -H "Content-Type: application/json" \
  http://localhost:8080/api/v1/projects
```

Token TTL is approximately 1 hour. Scripts should re-authenticate each run.

### 6.2 MCP Device Authorization
MCP tools can also initiate device auth:
```
mcp_guideai_auth_deviceinit(client_id="guideai-agent-mcp", scopes=["read", "write"])
mcp_guideai_auth_devicepoll(device_code="...", client_id="guideai-agent-mcp")
```

### 6.3 Broken Auth Method: Service Principal (DO NOT USE)
`POST /api/v1/auth/sp/token` returns a valid-looking `ga_` token, but this token is rejected with 401 on all non-auth endpoints. This is a known platform bug tracked as GS2.1 on the GuideAI Platform Issues board.

## 7. API Reference (Actual Behavior)

### 7.1 Important: Response Envelope Inconsistency
**Different endpoints use different response wrappers.** This is a known platform issue (GS3.2). Always handle both wrapped and unwrapped formats defensively.

| Endpoint | Create Response | List Response | ID Field |
|---|---|---|---|
| Projects | `{"id": "proj-..."}` (flat) | `{"items": [...]}` | `id` |
| Boards | `{"board": {"board_id": "..."}}` | `{"boards": [...]}` | `board_id` |
| Work Items | `{"item": {"item_id": "..."}}` | `{"items": [...]}` | `item_id` |

Defensive parsing pattern:
```python
# For boards
resp = api("POST", "/api/v1/boards", payload, headers)
board = resp.get("board", resp)
bid = board.get("board_id", board.get("id"))

# For work items
resp = api("POST", "/api/v1/work-items", payload, headers)
item = resp.get("item", resp)
iid = item.get("item_id", item.get("id"))
```

### 7.2 Endpoints

#### Projects
- `POST /api/v1/projects` — Create project
- `GET /api/v1/projects` — List projects (may not show projects from other auth sessions)
- `GET /api/v1/projects/<project_id>` — Get project by ID

#### Boards
- `POST /api/v1/boards` — Create board (set `create_default_columns: true` for default columns)
- `GET /api/v1/boards?project_id=<id>` — List boards for project
- `GET /api/v1/boards/<board_id>` — Get board by ID
- `PATCH /api/v1/boards/<board_id>` — Update board
- `DELETE /api/v1/boards/<board_id>` — Delete board

#### Work Items
- `POST /api/v1/work-items` — Create work item
- `GET /api/v1/work-items?board_id=<id>&limit=<n>` — List work items (supports filters: `project_id`, `board_id`, `item_type`, `parent_id`, `status`, `assignee_id`, `labels`, `limit`, `offset`)
- `GET /api/v1/work-items/<item_id>` — Get work item by ID
- `PATCH /api/v1/work-items/<item_id>` — Update work item
- `POST /api/v1/work-items/<item_id>/move` — Move work item to column
- `DELETE /api/v1/work-items/<item_id>` — Delete work item

#### Behaviors
- `GET /api/v1/behaviors` — List behaviors
- `POST /api/v1/behaviors` — Create behavior
- `POST /api/v1/behaviors:search` — Search behaviors
- `GET /api/v1/behaviors/<behavior_id>` — Get behavior by ID
- `POST /api/v1/behaviors/<behavior_id>:approve` — Approve behavior
- `POST /api/v1/behaviors/<behavior_id>:deprecate` — Deprecate behavior

#### Agents
- `GET /api/v1/agents` — List agents
- `POST /api/v1/agents` — Create agent
- `GET /api/v1/agents/<agent_id>` — Get agent by ID
- `POST /api/v1/agents/<agent_id>:publish` — Publish agent
- `POST /api/v1/agents/<agent_id>:deprecate` — Deprecate agent

#### Actions
- `POST /api/v1/actions` — Record action
- `GET /api/v1/actions` — List actions
- `GET /api/v1/actions/<action_id>` — Get action by ID
- `POST /api/v1/actions:replay` — Replay an action

### 7.3 Create Project
```json
{
  "name": "GuideAI",
  "slug": "guideai",
  "description": "GuideAI Metacognitive Behavior Handbook Platform",
  "visibility": "private"
}
```

### 7.4 Create Board
```json
{
  "project_id": "proj-b575d734aa37",
  "name": "GuideAI Platform Issues",
  "description": "Platform development and issue tracking",
  "create_default_columns": true
}
```

### 7.5 Create Work Items

`epic` (maps to WORK_STRUCTURE.md epics):
```json
{
  "item_type": "epic",
  "project_id": "proj-b575d734aa37",
  "board_id": "7342b025-404f-493f-a00c-d88e0859c3c2",
  "title": "Infrastructure & Staging Readiness",
  "description": "Complete infrastructure hardening for staging deployment",
  "priority": "high",
  "labels": ["guideai", "platform", "infrastructure"],
  "metadata": {
    "seed_source": "guideai-platform-v1",
    "seed_key": "E8",
    "seed_version": "2026-02-09",
    "work_structure_ref": "Epic 8"
  }
}
```

`story` (with parent):
```json
{
  "item_type": "story",
  "project_id": "proj-b575d734aa37",
  "board_id": "7342b025-404f-493f-a00c-d88e0859c3c2",
  "parent_id": "<epic_item_id>",
  "title": "Fix Service Principal token validation",
  "description": "SP tokens from POST /api/v1/auth/sp/token are rejected with 401 on non-auth endpoints",
  "priority": "high",
  "labels": ["guideai", "platform", "auth", "bug"],
  "metadata": {
    "seed_source": "guideai-platform-v1",
    "seed_key": "GS2.1",
    "seed_version": "2026-02-09",
    "bug_id": "GS2.1"
  }
}
```

`task` (with parent):
```json
{
  "item_type": "task",
  "project_id": "proj-b575d734aa37",
  "board_id": "7342b025-404f-493f-a00c-d88e0859c3c2",
  "parent_id": "<story_item_id>",
  "title": "Debug SP token middleware in api.py to find 401 root cause",
  "description": "Trace the token validation path for SP tokens and fix the rejection logic",
  "priority": "medium",
  "labels": ["guideai", "platform", "auth"],
  "metadata": {
    "seed_source": "guideai-platform-v1",
    "seed_key": "GS2.1-T1",
    "seed_version": "2026-02-09"
  }
}
```

## 8. MCP Tools for Self-Management

GuideAI MCP tools are available directly in VS Code Copilot Chat. Key tools for platform self-management:

### 8.1 Work Item Management
| Tool | Purpose |
|------|---------|
| `mcp_guideai_workitems_create` | Create epics, stories, tasks |
| `mcp_guideai_workitems_list` | List and filter work items |
| `mcp_guideai_workitems_execute` | Execute a work item via GEP |
| `mcp_guideai_workitem_executewithtracking` | Execute with progress tracking |

### 8.2 Behavior Management
| Tool | Purpose |
|------|---------|
| `mcp_guideai_behaviors_getfortask` | Retrieve behaviors before starting any task |
| `mcp_guideai_behaviors_list` | List all behaviors in the handbook |
| `mcp_guideai_behaviors_create` | Create a new behavior draft |
| `mcp_guideai_behavior_analyzeandretrieve` | Analyze task and retrieve behaviors + recommendations |

### 8.3 Project & Compliance
| Tool | Purpose |
|------|---------|
| `mcp_guideai_context_getcontext` | Get current tenant context and auth state |
| `mcp_guideai_compliance_fullvalidation` | Validate compliance policies and audit trail |
| `mcp_guideai_project_setupcomplete` | Set up a complete project with board |

## 9. Idempotent Seeding Rules
- Resolve project and board by name/slug before create.
- Use `metadata.seed_key` + `metadata.seed_version` to detect duplicate seeds.
- Re-runs must update or skip existing items; never create duplicate hierarchy.
- Use a local state cache file (e.g., `.guideai_seed_state.json`) to track created IDs across runs, since device auth sessions may not share project list visibility.

## 10. Ongoing Agent Workflow

### 10.1 Before Starting Any Task
1. Retrieve behaviors: `mcp_guideai_behaviors_getfortask(task_description="...", role="Student")`
2. Declare your role per `AGENTS.md` Role Declaration Protocol.
3. Select or create a GuideAI work item for the task.

### 10.2 During Execution
1. Set item to `in_progress` at start.
2. Keep item notes current with implementation evidence.
3. Cite behaviors and role in all work output: `Following behavior_xyz (Student): ...`
4. Run the smallest relevant automated check after each change (`pytest`, `npm run build`, lint).
5. Record command and outcome.

### 10.3 Completing Work
1. Move item to `in_review` when tests and docs are ready.
2. Move to `done` only when code, tests, docs, and acceptance checks are complete.
3. Add entry to `BUILD_TIMELINE.md` documenting the work.
4. Update `WORK_STRUCTURE.md` if epic/feature status changed.
5. If pattern repeated 3+ times, escalate to Strategist for behavior proposal.

### 10.4 Testing & Validation
```bash
# Run unit tests (no infrastructure required)
pytest -q tests/unit

# Run full test suite (requires Podman containers)
./scripts/run_tests.sh

# Run with Amprealize-managed environment
./scripts/run_tests.sh --amprealize

# Compile VS Code extension
cd extension && npm run compile

# Run pre-commit hooks
pre-commit run --all-files
```

## 11. CLI/Script Fallback
When MCP and API paths are blocked, use CLI commands:

```bash
# Behavior retrieval
guideai behaviors get-for-task "describe your task" --role Student

# List behaviors
guideai behaviors list

# Create a behavior draft
guideai behaviors create --name behavior_xyz --description "..." --instruction "..."
```

## 12. UI Fallback
Use Web Console UI only when API, MCP, and CLI paths are blocked.

UI paths (default: `http://localhost:5173`):
- `/projects/new` for project creation
- Project page for board creation
- Board page for epic/story/task creation

After UI fallback:
- Run the same verification checks (counts, hierarchy, status).
- Backfill seed metadata where supported.

## 13. Handling Platform Bugs Discovered During Development
Since GuideAI tracks its own development, platform bugs are first-class work items:

1. Check if bug already exists on the GuideAI Platform Issues board (`board_id: 7342b025-404f-493f-a00c-d88e0859c3c2`).
2. If not, create a story with `labels: ["guideai", "platform", "bug"]` and a `metadata.bug_id` field (e.g., `GS4.1`).
3. Include repro steps, expected behavior, observed behavior, and workaround status in the description.
4. If the bug blocks current work, add the workaround to §14 of this document.
5. When the bug is fixed, update the work item to `done` and note in §14 that the workaround is no longer needed.

If GuideAI cannot self-track (e.g., API is completely down):
- Document blockers in this file as temporary fallback.
- Backfill GuideAI items after platform recovery.

## 14. Known Platform Bugs and Workarounds (as of 2026-02-09)
These are tracked on the GuideAI Platform Issues board. Agents **must** apply these workarounds until the bugs are fixed.

### 14.1 Project Creation Does Not Persist to `auth.projects` (GS1.1)
**Bug**: `POST /api/v1/projects` returns 201 but does not write to `auth.projects` in PostgreSQL. Boards and work items that FK-reference the project will fail.

**Workaround**: After creating a project via API, insert the row directly:
```bash
podman exec amp-037de200-8e29-478d-9531-9b08af7d0145-guideai-db \
  psql -U guideai -d guideai -c \
  "INSERT INTO auth.projects (project_id, name, slug, description, visibility, created_by, owner_id)
   VALUES ('<project_id>', '<name>', '<slug>', '<desc>', 'private', '<user_id>', '<user_id>')
   ON CONFLICT (project_id) DO NOTHING;"
```
Note: `auth.projects` has a check constraint requiring either `org_id` or `owner_id` to be non-null.

### 14.2 Missing `parent_id` Column on `board.work_items` (GS1.2)
**Bug**: The API accepts `parent_id` in work item payloads but the DB migration did not create the column.

**Workaround**: Add the column manually (only needed once):
```bash
podman exec amp-037de200-8e29-478d-9531-9b08af7d0145-guideai-db \
  psql -U guideai -d guideai -c \
  "ALTER TABLE board.work_items ADD COLUMN IF NOT EXISTS parent_id uuid
   REFERENCES board.work_items(id) ON DELETE SET NULL;"
```

### 14.3 Missing Default Users in `auth.users` (GS1.3)
**Bug**: Board creation sets `created_by = 'anonymous'` but no such user exists, causing FK violations.

**Workaround**: Insert default users (only needed once):
```bash
podman exec amp-037de200-8e29-478d-9531-9b08af7d0145-guideai-db \
  psql -U guideai -d guideai -c \
  "INSERT INTO auth.users (id, email, display_name, auth_provider)
   VALUES ('anonymous', 'anonymous@system', 'Anonymous', 'system'),
          ('guideai-agent', 'guideai-agent@system', 'GuideAI Agent', 'system')
   ON CONFLICT (id) DO NOTHING;"
```

### 14.4 Service Principal Tokens Rejected on Non-Auth Endpoints (GS2.1)
**Bug**: Tokens from `POST /api/v1/auth/sp/token` return 401 on projects, boards, and work-items endpoints.

**Workaround**: Use the device authorization flow exclusively (see §6.1).

### 14.5 Board Service Returns 503 on FK Failures (GS3.1)
**Bug**: When a board creation fails due to FK constraint violation, the service returns HTTP 503 with no error body.

**Workaround**: Ensure the project row exists in `auth.projects` (§14.1) and default users exist (§14.3) before creating boards.

### 14.6 Inconsistent Response Envelopes (GS3.2)
**Bug**: Projects return flat `{"id": ...}`, boards wrap in `{"board": {"board_id": ...}}`, work items wrap in `{"item": {"item_id": ...}}`.

**Workaround**: Use defensive parsing that handles both wrapped and unwrapped formats (see §7.1).

## 15. Verification
After any seed run or batch of work item operations, verify counts directly in the database:
```bash
podman exec amp-037de200-8e29-478d-9531-9b08af7d0145-guideai-db \
  psql -U guideai -d guideai -c \
  "SELECT item_type, count(*) FROM board.work_items
   WHERE metadata->>'seed_source' = 'guideai-platform-v1'
   GROUP BY item_type ORDER BY item_type;"
```

For verifying work item hierarchy:
```bash
podman exec amp-037de200-8e29-478d-9531-9b08af7d0145-guideai-db \
  psql -U guideai -d guideai -c \
  "SELECT wi.item_type, wi.title, wi.status, p.title AS parent_title
   FROM board.work_items wi
   LEFT JOIN board.work_items p ON wi.parent_id = p.id
   WHERE wi.metadata->>'seed_source' = 'guideai-platform-v1'
   ORDER BY wi.item_type, wi.title;"
```

## 16. Key Source Files

### Platform Core
| File | Purpose |
|------|---------|
| `guideai/api.py` | FastAPI application with all REST endpoints |
| `guideai/mcp_server.py` | MCP server (220 tools) |
| `guideai/services/board_api_v2.py` | Board and work item REST routes |
| `guideai/projects_api.py` | Project REST routes |
| `guideai/behavior_service.py` | Behavior CRUD and lifecycle |
| `guideai/bci_service.py` | Behavior-Conditioned Inference |
| `guideai/run_service.py` | Run orchestration |
| `guideai/task_cycle_service.py` | GEP 8-phase execution |
| `guideai/work_item_execution_service.py` | Work item execution wiring |

### Auth
| File | Purpose |
|------|---------|
| `guideai/auth/` | Auth services directory |
| `guideai/auth/postgres_device_flow.py` | PostgreSQL-backed device flow |
| `guideai/auth/consent_service.py` | JIT consent service |
| `guideai/auth/user_service_postgres.py` | User management |

### Infrastructure
| File | Purpose |
|------|---------|
| `environments.yaml` | Amprealize environment configuration |
| `alembic.ini` | Main database migration config |
| `migrations/versions/` | Alembic migration scripts |
| `packages/amprealize/` | Container orchestration package |
| `packages/raze/` | Structured logging package |

### Extension
| File | Purpose |
|------|---------|
| `extension/src/extension.ts` | VS Code extension entry point |
| `extension/src/client/McpClient.ts` | MCP client for extension |
| `extension/src/client/RazeClient.ts` | Raze logging client |

### Documentation
| File | Purpose |
|------|---------|
| `AGENTS.md` | Agent behavior handbook (33 behaviors) |
| `WORK_STRUCTURE.md` | Full epic/feature/task inventory |
| `BUILD_TIMELINE.md` | Chronological audit log |
| `PRD.md` | Product requirements document |
| `MCP_SERVER_DESIGN.md` | MCP server architecture |
| `docs/MIGRATION_GUIDE.md` | Database migration procedures |
| `docs/TESTING_GUIDE.md` | Testing strategy and procedures |

## 17. Source Documents
- `AGENTS.md` — Behavior handbook and agent roles
- `WORK_STRUCTURE.md` — Full platform work inventory (14 epics)
- `BUILD_TIMELINE.md` — Chronological build audit log
- `PRD.md` — Product requirements
- `MCP_SERVER_DESIGN.md` — MCP server architecture (220 tools)
- `environments.yaml` — Amprealize environment configuration
- `docs/MIGRATION_GUIDE.md` — Database migration procedures
- `docs/TESTING_GUIDE.md` — Testing strategy
- `.github/copilot-instructions.md` — Copilot quick triggers
