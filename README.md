# GuideAI — The Behavior Engine for AI Agents

[![CI](https://img.shields.io/github/actions/workflow/status/SandRiseStudio/guideai/ci.yml?branch=main&label=CI)](https://github.com/SandRiseStudio/guideai/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/guideai)](https://pypi.org/project/guideai/)
[![Python 3.10+](https://img.shields.io/pypi/pyversions/guideai)](https://pypi.org/project/guideai/)
[![License](https://img.shields.io/github/license/SandRiseStudio/guideai)](LICENSE)
[![Homebrew](https://img.shields.io/badge/brew-sandrisestudio%2Fguideai-orange)](https://github.com/SandRiseStudio/homebrew-guideai)

**Turn your LLM chains-of-thought into a reusable procedural handbook — cut reasoning tokens by up to 46% while maintaining or improving quality.**

GuideAI captures recurring AI reasoning patterns as named **behaviors** and conditions agents to reuse them, inspired by [Meta AI's Metacognitive Reuse research](https://arxiv.org/pdf/2509.13237).

---

## Get Started in 30 Seconds

**Cloud** — zero install:
```
→ https://amprealize.ai (sign up and go)
```

**CLI** — for developers:
```bash
pipx install guideai
guideai init
```

**Desktop app:** not shipped from this repository yet; use the **cloud** console, **CLI**, **VS Code extension**, or **MCP** today. Watch [GitHub Releases](https://github.com/SandRiseStudio/guideai/releases) for future desktop builds.

---

## What Is GuideAI?

GuideAI is a **behavior-driven AI workflow platform** that extracts, stores, and retrieves procedural knowledge — reusable how-to strategies — from successful AI reasoning traces. Instead of re-deriving common patterns on every prompt, agents consult a behavior handbook and allocate their compute budget to novel subproblems.

The platform serves three roles:
- **Student** — consumes behaviors in-context for efficient task execution
- **Teacher** — validates behaviors, creates examples, and reviews quality
- **Metacognitive Strategist** — discovers patterns, proposes new behaviors, and curates the handbook

GuideAI works across multiple surfaces: **Web Console**, **CLI**, **VS Code Extension**, and **MCP Server** — with consistent behavior retrieval and execution tracking everywhere.

---

## Features

- **Behavior Engine** — extract, version, retrieve, and apply reusable reasoning patterns
- **MCP Server** — 220+ tools for behaviors, runs, compliance, actions, metrics, and more
- **Multi-Surface Parity** — CLI, REST API, MCP, Web UI, and VS Code extension share the same backend
- **Agent Orchestration** — run agents with behavior-conditioned inference (BCI) for token-efficient execution
- **Compliance & Audit** — full action logging, hash-chained audit trails, and policy enforcement
- **Structured Logging (Raze)** — centralized, queryable, context-enriched telemetry
- **Environment Management (Amprealize)** — blueprint-driven container orchestration with compliance hooks
- **Multi-Tenant** — org-scoped or personal projects with role-based access control
- **OAuth & Device Flow Auth** — GitHub, Google, Microsoft providers with token vault
- **Billing Tiers** — OSS → Starter → Pro → Team → Enterprise

---

## Architecture

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Web Console │  │  VS Code    │  │    CLI      │
│  (React)     │  │  Extension  │  │  (Click)    │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └─────────────────┴────────┬────────┘
                                  │
                         ┌────────▼────────┐
                         │   FastAPI + MCP  │
                         │   Server         │
                         └────────┬────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         │                        │                        │
  ┌──────▼──────┐  ┌──────────────▼──────────────┐  ┌─────▼──────┐
  │  Behavior   │  │  RunService / ActionService  │  │  Raze      │
  │  Service    │  │  ComplianceService           │  │  Telemetry │
  └─────────────┘  └─────────────────────────────┘  └────────────┘
```

---

## Gateway (Nginx :8080)

All client traffic (Web Console, CLI, VS Code, MCP) enters through **nginx on port 8080**, which acts as the single edge gateway:

| Concern | Implementation |
|---------|---------------|
| **TLS termination** | `NGINX_SSL_CERT` / `NGINX_SSL_KEY` env vars (optional; plain HTTP in dev) |
| **Header stripping** | `X-Tenant-Id` and `X-User-Id` are stripped at all proxy locations to prevent spoofing |
| **Rate limiting** | 100 req/s for API, 10 req/s for WebSocket |
| **Auth middleware** | `AuthMiddleware` → `TenantMiddleware` stack on the FastAPI app; toggle with `GUIDEAI_AUTH_ENABLED` |
| **CORS** | Driven by `GUIDEAI_CORS_ORIGINS` env var |
| **Web Console proxy** | Static files served directly by nginx |

See [docs/GATEWAY_ARCHITECTURE.md](docs/GATEWAY_ARCHITECTURE.md) for the full gateway design.

---

## Project Structure

```
guideai/
├── guideai/              # Core Python package
│   ├── mcp_tool_manifests/  # Bundled MCP tool JSON (sync from mcp/tools for releases)
│   ├── behaviors/        # Behavior engine
│   ├── mcp/              # MCP server (220+ tools)
│   ├── services/         # Run, Action, Compliance services
│   ├── auth/             # OAuth, device flow, token vault
│   ├── cli/              # CLI commands (Click)
│   ├── config/           # Configuration loader
│   └── storage/          # Storage adapters (SQLite, Postgres)
├── packages/
│   ├── raze/             # Structured logging (standalone)
│   ├── amprealize/       # Environment orchestration (standalone)
│   ├── midnighter/       # Background task scheduler
│   ├── notify/           # Notification service
│   ├── observability/    # Metrics pipeline
│   └── billing/          # Billing & tier management
├── web-console/          # React web UI
├── extension/            # VS Code extension
├── dashboard/            # Grafana metrics dashboard
├── docs/
│   ├── contracts/        # Service contract specs
│   ├── agents/           # Agent role documentation
│   └── research/         # Research papers & references
├── infra/                # Docker, deployment, CI/CD configs
├── tests/                # Test suite
├── scripts/              # Dev & CI scripts
├── mcp/                  # MCP tool JSON schemas
├── migrations/           # Alembic database migrations
└── schema/               # Database schema definitions
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [AGENTS.md](AGENTS.md) | Behavior handbook — roles, behaviors, triggers, checklists |
| [MCP Client Setup](docs/MCP_CLIENT_SETUP.md) | Portable GuideAI MCP setup for VS Code, Cursor, Claude, and other clients |
| [Installation Plan](docs/INSTALLATION_AND_REPO_OPTIMIZATION_PLAN.md) | v3.1 plan with 6 tracks, 39 stories |
| [MCP Server Design](docs/contracts/MCP_SERVER_DESIGN.md) | MCP tool catalog and service contracts |
| [API Contracts](docs/contracts/) | ActionService, RunService, BehaviorService contracts |
| [Audit Log Storage](docs/contracts/AUDIT_LOG_STORAGE.md) | Hash-chained audit trail design |
| [Build Timeline](BUILD_TIMELINE.md) | Chronological build log |

---

## OSS install profiles

| Profile | What you need | Notes |
|--------|----------------|-------|
| **Minimal (solo / local)** | Python 3.10+, `pip install guideai` or `pipx install guideai`, optional `.env` | Use SQLite via `guideai init` and `guideai db migrate`. MCP tools ship in the wheel (`guideai mcp-server doctor` to verify). |
| **Full stack (Postgres, telemetry, etc.)** | Docker or Podman, Postgres, Redis, and the variables in [`.env.example`](.env.example) | See [infra/docker-compose.postgres.yml](infra/docker-compose.postgres.yml) for reference service layout. Heavy dependencies (e.g. Podman, DB clients) are installed with the default package; trim via optional extras only where the project already exposes them. |
| **Contributors (this monorepo)** | Git clone + editable install (below) | Canonical MCP tool JSON lives in `mcp/tools/`; run `python scripts/sync_mcp_tool_manifests.py` after changing manifests so `guideai/mcp_tool_manifests/` stays aligned (CI enforces this). |

## Development

```bash
# Clone and set up
git clone https://github.com/SandRiseStudio/guideai.git
cd guideai
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Install pre-commit hooks
./scripts/install_hooks.sh

# Run tests
pytest

# Generate local MCP configs for VS Code/Cursor/Claude/Codex and smoke-test them
guideai mcp-server init
guideai mcp-server doctor

# Keep GUIDEAI_* runtime settings in .env / .env.local / .env.mcp
# instead of embedding DSNs into editor MCP configs

# Start the server
uvicorn guideai.api:app --reload

# Run secret scan
bash scripts/scan_secrets.sh
```

---

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for development setup, PR process, commit conventions, and the behavior handbook reference.

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before contributing.

---

## Security

To report security vulnerabilities, please see [SECURITY.md](SECURITY.md). **Do NOT use GitHub Issues for security reports.**

---

## Canonical GitHub repository

Public source of truth: **[github.com/SandRiseStudio/guideai](https://github.com/SandRiseStudio/guideai)**.

**Maintainers (after org or repo moves):** point PyPI [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) at `SandRiseStudio/guideai`, confirm GitHub Actions secrets and environments still apply to this repository, and re-check branch protection and Dependabot on the default branch.

---

## License

[Apache License 2.0](LICENSE)

Copyright 2026 GuideAI Team
