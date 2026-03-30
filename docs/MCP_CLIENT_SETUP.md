# GuideAI MCP Client Setup

Following `behavior_prefer_mcp_tools` (Student): this is the current, portable way to wire GuideAI MCP into local clients.

## Quick Start

From the repository root:

```bash
guideai mcp-server init
guideai mcp-server doctor
```

`guideai mcp-server init` writes project-local MCP configs for:
- `.vscode/mcp.json`
- `.claude/mcp.json`
- `.cursor/mcp.json`
- `.codex/config.toml` (project-scoped)

It also creates or updates:
- `~/.codex/config.toml` (global Codex config)

Each client uses a format tailored to its requirements (see Client-Specific Notes below).

## Monorepo clone vs pip-installed GuideAI

`guideai mcp-server init` picks a launch command based on what is in your **project workspace** (the directory where you run the command):

| Layout | MCP launch |
|--------|------------|
| **GuideAI git clone** (this repo) with `scripts/start_guideai_mcp.py` | Uses that script: it re-execs into `.venv`, merges MCP env from `.env` / `.env.local` / `.env.mcp`, sets `PYTHONPATH` to the repo root, then runs `python -m guideai.mcp_server`. |
| **Any other project** (only `pip install guideai` / `pipx install guideai`) | Uses `python -m guideai.mcp_server` (or your venv’s Python) with `cwd` set to the workspace. Tool JSON manifests ship inside the `guideai` wheel under `mcp_tool_manifests/`. |

After editing tools in a clone, run `python scripts/sync_mcp_tool_manifests.py` before releasing so bundled copies stay in sync (CI also checks this).

The launcher script (`scripts/start_guideai_mcp.py`), when present:
- resolves the repository root
- re-execs into `.venv` when present
- loads runtime env from `.env`, `.env.local`, and `.env.mcp` when present
- sets `PYTHONPATH` to the repo root
- starts `guideai.mcp_server`

`guideai mcp-server init` keeps generated client configs minimal. It does not snapshot local `GUIDEAI_*` DSNs or secrets into editor config files. Keep runtime settings in workspace env files instead:

- `.env` for standard local development
- `.env.local` for machine-specific overrides
- `.env.mcp` for MCP-only overrides

Existing process env still wins over file values. If you need a non-default env file set, point the launcher at it with `GUIDEAI_MCP_ENV_FILE` or `GUIDEAI_MCP_ENV_FILES`.

## Verification

Use the CLI smoke test after any client setup change:

```bash
guideai mcp-server doctor
```

This validates:
- MCP `initialize`
- MCP `tools/list`
- non-empty tool discovery

## Client-Specific Notes

### Cursor

Cursor's MCP config uses a different format from VS Code:
- **Requires** `"type": "stdio"` (VS Code infers it; Cursor does not)
- **Does not support** `cwd` -- use `${workspaceFolder}` interpolation instead
- **Supports** `envFile` to load `.env` files natively

Example `.cursor/mcp.json` for a **clone** (launcher script):
```json
{
  "mcpServers": {
    "guideai": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["${workspaceFolder}/scripts/start_guideai_mcp.py"],
      "env": { "PYTHONUNBUFFERED": "1" },
      "envFile": "${workspaceFolder}/.env"
    }
  }
}
```

For **pip-only** workspaces, `init` emits the same shape with `"args": ["-m", "guideai.mcp_server"]` and `command` pointing at your venv or system `python` / `python3` (Windows: `.venv/Scripts/python.exe` when present).

Debug MCP issues in Cursor: open the Output panel (Cmd+Shift+U) and select "MCP Logs".

### VS Code

Generated `.vscode/mcp.json`:
```json
{
  "servers": {
    "guideai": {
      "type": "stdio",
      "command": "python3",
      "args": ["scripts/start_guideai_mcp.py"],
      "cwd": "/path/to/repo",
      "env": { "PYTHONUNBUFFERED": "1" }
    }
  }
}
```

VS Code supports `cwd` and infers stdio transport.

### Codex (CLI and IDE Extension)

Codex reads `~/.codex/config.toml` globally and `.codex/config.toml` at the project level (trusted projects only). The CLI and the IDE extension share this configuration.

Generated config uses absolute paths since Codex does not support `${workspaceFolder}` interpolation:
```toml
[mcp_servers.guideai]
enabled = true
required = false
command = "/path/to/repo/.venv/bin/python"
args = ["/path/to/repo/scripts/start_guideai_mcp.py"]
cwd = "/path/to/repo"
startup_timeout_sec = 20
tool_timeout_sec = 120
env = { PYTHONUNBUFFERED = "1" }
```

### Claude Desktop

Generated `.claude/mcp.json`:
```json
{
  "mcpServers": {
    "guideai": {
      "command": "python3",
      "args": ["scripts/start_guideai_mcp.py"],
      "cwd": "/path/to/repo",
      "env": { "PYTHONUNBUFFERED": "1" }
    }
  }
}
```

## Generic MCP Clients

For clients beyond VS Code, Cursor, Claude, and Codex:

1. **Clone**: stdio config with `command` = Python, `args` = path to `scripts/start_guideai_mcp.py`, `cwd` = repo root.
2. **pip install**: `command` = Python, `args` = `["-m", "guideai.mcp_server"]`, `cwd` = project root (same directory as `.env` if you use one).
3. Run `guideai mcp-server doctor` before testing the client.

If the client does not support project-local config files, use its global MCP config and point it at either:

- the workspace launcher script with an absolute path (clone), or
- `python -m guideai.mcp_server` with appropriate `cwd`, or
- an installed CLI entrypoint:

```json
{
  "command": "guideai",
  "args": ["mcp-server"]
}
```

## After Configuration Changes

All MCP hosts require a fresh session after configuration changes. MCP tool mounts happen at session start and are not hot-reloaded.

- **Cursor**: Fully quit (Cmd+Q) and relaunch, or use Cmd+Shift+P > "Developer: Reload Window"
- **VS Code**: Reload window (Cmd+Shift+P > "Developer: Reload Window")
- **Codex CLI**: Start a new `codex` session
- **Codex IDE extension**: Reload the window or restart the IDE

## Notes

- GuideAI MCP is tool-first. Clients may expose `mcp_guideai_*` tools even if they do not surface MCP resources.
- If MCP is unavailable in a given host, `guideai behaviors get-for-task "<task>"` is the CLI fallback for handbook retrieval before work starts.
  It now falls back to the nearest local `AGENTS.md` when the behavior Postgres backend is not configured or is unreachable.
- If a client can start the server but no tools appear, verify that it supports MCP tools, not just resources.
- If startup fails, run `guideai mcp-server doctor` first, then inspect the client-specific MCP logs.
