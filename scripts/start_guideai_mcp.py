#!/usr/bin/env python3
"""Portable launcher for the workspace-local GuideAI MCP server."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _venv_python(repo_root: Path) -> Path | None:
    """Return the preferred repo-local Python interpreter if it exists."""

    if os.name == "nt":
        candidate = repo_root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = repo_root / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    preferred_python = _venv_python(repo_root)
    current_python = Path(sys.executable).resolve()

    if (
        preferred_python is not None
        and current_python != preferred_python.resolve()
        and os.environ.get("GUIDEAI_MCP_REEXEC") != "1"
    ):
        env = dict(os.environ)
        env["GUIDEAI_MCP_REEXEC"] = "1"
        os.execve(
            str(preferred_python),
            [
                str(preferred_python),
                str(Path(__file__).resolve()),
                *sys.argv[1:],
            ],
            env,
        )

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from guideai.mcp_env import merge_mcp_runtime_env

    env = merge_mcp_runtime_env(repo_root, os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{repo_root}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(repo_root)
    )
    os.chdir(repo_root)
    os.execve(
        sys.executable,
        [sys.executable, "-m", "guideai.mcp_server", *sys.argv[1:]],
        env,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
