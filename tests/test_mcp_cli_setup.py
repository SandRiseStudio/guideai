"""Tests for MCP client setup helpers in the CLI."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from guideai.cli import (
    _build_ide_mcp_configs,
    _frame_mcp_message,
    _run_mcp_smoke_test,
    _upsert_codex_mcp_server_config,
)

pytestmark = pytest.mark.unit


class _FakeProcess:
    def __init__(self, responses: list[dict]):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(
            b"".join(_frame_mcp_message(response) for response in responses)
        )
        self.stderr = io.BytesIO()

    def terminate(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        return None


def test_build_ide_mcp_configs_uses_shared_launcher(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GUIDEAI_MCP_ENV_FILE", raising=False)
    monkeypatch.delenv("GUIDEAI_MCP_ENV_FILES", raising=False)

    configs = dict(_build_ide_mcp_configs(tmp_path, "python-test"))

    vscode = configs[".vscode/mcp.json"]["servers"]["guideai"]
    claude = configs[".claude/mcp.json"]["mcpServers"]["guideai"]
    cursor = configs[".cursor/mcp.json"]["mcpServers"]["guideai"]

    for config in (vscode, claude, cursor):
        assert config["command"] == "python-test"
        assert config["args"] == ["scripts/start_guideai_mcp.py"]
        assert config["cwd"] == str(tmp_path.resolve())
        assert config["env"]["PYTHONUNBUFFERED"] == "1"
        assert sorted(config["env"].keys()) == ["PYTHONUNBUFFERED"]

    assert vscode["type"] == "stdio"


def test_upsert_codex_mcp_server_config_updates_existing_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '\n'.join(
            [
                'model = "gpt-5.4"',
                "",
                "[mcp_servers.guideai]",
                'command = "python3"',
                'args = ["old.py"]',
                "",
                '[plugins."github@openai-curated"]',
                "enabled = true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    status = _upsert_codex_mcp_server_config(
        config_path,
        workspace_root=tmp_path,
        python_path="python-test",
    )

    updated = config_path.read_text(encoding="utf-8")
    assert status == "updated"
    assert '[mcp_servers.guideai]' in updated
    assert 'command = "python-test"' in updated
    assert 'args = ["scripts/start_guideai_mcp.py"]' in updated
    assert 'PYTHONUNBUFFERED = "1"' in updated
    assert "GUIDEAI_DEFAULT_APPROVER" not in updated
    assert '[plugins."github@openai-curated"]' in updated
    assert 'args = ["old.py"]' not in updated


def test_run_mcp_smoke_test_reports_tool_summary(monkeypatch) -> None:
    responses = [
        {
            "jsonrpc": "2.0",
            "id": "init",
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "guideai"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "tools",
            "result": {
                "tools": [
                    {"name": "auth_authstatus"},
                    {"name": "projects_list"},
                ]
            },
        },
    ]
    fake_proc = _FakeProcess(responses)

    def _fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd == [sys.executable, str(Path.cwd() / "scripts" / "start_guideai_mcp.py")]
        assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"
        assert kwargs["cwd"] == str(Path.cwd())
        return fake_proc

    monkeypatch.setattr("guideai.cli.subprocess.Popen", _fake_popen)

    summary = _run_mcp_smoke_test(timeout=1.0)

    assert summary == {
        "protocol_version": "2024-11-05",
        "server_name": "guideai",
        "tool_count": 2,
        "sample_tools": ["auth_authstatus", "projects_list"],
    }
