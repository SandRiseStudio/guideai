"""
Dynamic Codebase Context Analyzer for AI Research Agent.

Provides two-tier indexing:
- Tier 1: Structural Index (cached 5min) - lightweight overview (~3-5K chars)
- Tier 2: Deep-Dive (on-demand) - full file contents when agent requests

Following behavior_use_raze_for_logging (Student): Using Raze for structured logging.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from raze import RazeLogger

logger = RazeLogger("guideai.research.codebase_analyzer")

# Token budget per section (in characters)
TOKEN_BUDGETS = {
    "services": 1500,
    "behaviors": 1500,
    "mcp_tools": 800,
    "db_tables": 500,
    "recent_commits": 500,
    "total": 5000,
}

# Security: files/patterns to never include
BLOCKED_PATTERNS = [
    r"\.env$",
    r"\.env\.",
    r"secrets?\.ya?ml$",
    r"credentials?\.json$",
    r"\.pem$",
    r"\.key$",
    r"client_secret.*\.json$",
    r"__pycache__",
    r"\.pyc$",
]


@dataclass
class CodebaseSnapshot:
    """Structural index of the codebase."""

    services: list[dict[str, Any]] = field(default_factory=list)
    behaviors: list[dict[str, str]] = field(default_factory=list)
    mcp_tools: list[dict[str, str]] = field(default_factory=list)
    db_tables: list[dict[str, str]] = field(default_factory=list)
    recent_commits: list[dict[str, str]] = field(default_factory=list)
    tree_hash: str = ""
    generated_at: float = 0.0

    def to_context_string(self) -> str:
        """Format snapshot as context string for LLM prompts."""
        sections = []

        # Services section
        if self.services:
            svc_lines = ["## Active Services"]
            for svc in self.services[: self._budget_limit("services", 80)]:
                svc_lines.append(f"- **{svc['name']}**: {svc.get('description', 'No description')}")
                if svc.get("methods"):
                    for m in svc["methods"][:5]:
                        svc_lines.append(f"  - `{m}`")
            sections.append("\n".join(svc_lines))

        # Behaviors section
        if self.behaviors:
            beh_lines = ["## Registered Behaviors"]
            for beh in self.behaviors[: self._budget_limit("behaviors", 60)]:
                beh_lines.append(f"- `{beh['name']}`: {beh.get('summary', '')[:100]}")
            sections.append("\n".join(beh_lines))

        # MCP Tools section
        if self.mcp_tools:
            mcp_lines = ["## MCP Tools"]
            for tool in self.mcp_tools[: self._budget_limit("mcp_tools", 50)]:
                mcp_lines.append(f"- `{tool['name']}`: {tool.get('description', '')[:80]}")
            sections.append("\n".join(mcp_lines))

        # DB Tables section
        if self.db_tables:
            db_lines = ["## Database Tables"]
            for tbl in self.db_tables[: self._budget_limit("db_tables", 30)]:
                db_lines.append(f"- `{tbl['name']}`: {tbl.get('columns', '')[:60]}")
            sections.append("\n".join(db_lines))

        # Recent commits section
        if self.recent_commits:
            commit_lines = ["## Recent Changes (last 7 days)"]
            for c in self.recent_commits[: self._budget_limit("recent_commits", 30)]:
                commit_lines.append(f"- {c.get('date', '')}: {c.get('message', '')[:80]}")
            sections.append("\n".join(commit_lines))

        result = "\n\n".join(sections)

        # Truncate to total budget if needed
        if len(result) > TOKEN_BUDGETS["total"]:
            result = result[: TOKEN_BUDGETS["total"] - 50] + "\n\n[... truncated for token budget]"

        return result

    def _budget_limit(self, section: str, avg_item_chars: int) -> int:
        """Calculate max items for a section based on budget."""
        budget = TOKEN_BUDGETS.get(section, 500)
        return max(3, budget // avg_item_chars)


class CodebaseAnalyzer:
    """
    Analyzes codebase structure for Research Agent context.

    Features:
    - Extracts service classes with public methods
    - Parses behaviors from AGENTS.md
    - Discovers MCP tool definitions
    - Finds database table schemas
    - Gets recent git commits (graceful fallback if not git repo)
    """

    def __init__(self, project_root: str | Path | None = None, cache_ttl: int = 300):
        """
        Initialize analyzer.

        Args:
            project_root: Root directory of the project. Defaults to guideai root.
            cache_ttl: Cache time-to-live in seconds. Default 5 minutes.
        """
        if project_root is None:
            # Default to guideai root (3 levels up from this file)
            self.project_root = Path(__file__).parent.parent.parent
        else:
            self.project_root = Path(project_root)

        self.cache_ttl = cache_ttl
        self._cache: CodebaseSnapshot | None = None
        self._is_git_repo: bool | None = None

        logger.debug(
            "CodebaseAnalyzer initialized",
            project_root=str(self.project_root),
            cache_ttl=cache_ttl,
        )

    def get_structural_index(self, force_refresh: bool = False) -> CodebaseSnapshot:
        """
        Get cached structural index or generate new one.

        Args:
            force_refresh: Force regeneration even if cache valid.

        Returns:
            CodebaseSnapshot with codebase structure.
        """
        if not force_refresh and self._is_cache_valid():
            logger.debug("Using cached structural index")
            return self._cache  # type: ignore

        logger.info("Generating structural index", project_root=str(self.project_root))
        start_time = time.time()

        snapshot = CodebaseSnapshot(
            services=self._extract_services(),
            behaviors=self._extract_behaviors(),
            mcp_tools=self._extract_mcp_tools(),
            db_tables=self._extract_db_tables(),
            recent_commits=self._get_recent_commits(),
            tree_hash=self._get_tree_hash(),
            generated_at=time.time(),
        )

        self._cache = snapshot

        logger.info(
            "Structural index generated",
            duration_ms=int((time.time() - start_time) * 1000),
            services_count=len(snapshot.services),
            behaviors_count=len(snapshot.behaviors),
            mcp_tools_count=len(snapshot.mcp_tools),
        )

        return snapshot

    def deep_dive(self, file_path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """
        Read specific file contents for detailed analysis.

        Args:
            file_path: Path relative to project root.
            start_line: Starting line (1-indexed).
            end_line: Ending line (inclusive). None for entire file.

        Returns:
            File contents or error message.
        """
        # Security check
        if self._is_blocked_file(file_path):
            logger.warning("Blocked file access attempt", file_path=file_path)
            return f"[BLOCKED: {file_path} contains sensitive data]"

        full_path = self.project_root / file_path

        if not full_path.exists():
            return f"[FILE NOT FOUND: {file_path}]"

        if not full_path.is_file():
            return f"[NOT A FILE: {file_path}]"

        try:
            lines = full_path.read_text(encoding="utf-8").splitlines()

            if end_line is None:
                end_line = len(lines)

            # Convert to 0-indexed
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)

            selected = lines[start_idx:end_idx]

            logger.debug(
                "Deep dive file read",
                file_path=file_path,
                lines_read=len(selected),
            )

            return "\n".join(selected)

        except Exception as e:
            logger.error("Deep dive read failed", file_path=file_path, error=str(e))
            return f"[READ ERROR: {e}]"

    def _is_cache_valid(self) -> bool:
        """Check if cached snapshot is still valid."""
        if self._cache is None:
            return False

        age = time.time() - self._cache.generated_at
        if age > self.cache_ttl:
            return False

        return True

    def _is_git_repo(self) -> bool:
        """Check if project is a git repository."""
        if self._is_git_repo is not None:
            return self._is_git_repo

        git_dir = self.project_root / ".git"
        self._is_git_repo = git_dir.exists() and git_dir.is_dir()
        return self._is_git_repo

    def _get_tree_hash(self) -> str:
        """Get git tree hash for change detection."""
        if not self._check_is_git_repo():
            return hashlib.md5(str(time.time()).encode()).hexdigest()[:12]

        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()[:12]
        except Exception:
            pass

        return hashlib.md5(str(time.time()).encode()).hexdigest()[:12]

    def _check_is_git_repo(self) -> bool:
        """Check if project is a git repository (cached)."""
        if self._is_git_repo is not None:
            return self._is_git_repo

        git_dir = self.project_root / ".git"
        self._is_git_repo = git_dir.exists() and git_dir.is_dir()
        return self._is_git_repo

    def _is_blocked_file(self, file_path: str) -> bool:
        """Check if file matches blocked patterns."""
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                return True
        return False

    def _extract_services(self) -> list[dict[str, Any]]:
        """Extract service classes from guideai package."""
        services = []
        guideai_dir = self.project_root / "guideai"

        if not guideai_dir.exists():
            return services

        # Find *_service.py and *Service classes
        service_files = list(guideai_dir.glob("*_service.py")) + list(guideai_dir.glob("**/*_service.py"))

        for svc_file in service_files[:20]:  # Limit to prevent over-scanning
            if self._is_blocked_file(str(svc_file)):
                continue

            try:
                content = svc_file.read_text(encoding="utf-8")
                rel_path = svc_file.relative_to(self.project_root)

                # Extract class definitions
                class_matches = re.findall(
                    r'^class\s+(\w+Service)\s*(?:\([^)]*\))?:\s*(?:"""([^"]*?)""")?',
                    content,
                    re.MULTILINE,
                )

                for class_name, docstring in class_matches:
                    # Extract public methods
                    methods = re.findall(
                        r"^\s{4}def\s+([a-z][a-z0-9_]*)\s*\(",
                        content,
                        re.MULTILINE,
                    )
                    public_methods = [m for m in methods if not m.startswith("_")][:10]

                    services.append(
                        {
                            "name": class_name,
                            "file": str(rel_path),
                            "description": (docstring or "").strip()[:150],
                            "methods": public_methods,
                        }
                    )

            except Exception as e:
                logger.debug("Failed to parse service file", file=str(svc_file), error=str(e))

        return services

    def _extract_behaviors(self) -> list[dict[str, str]]:
        """Extract behaviors from AGENTS.md."""
        behaviors = []
        agents_md = self.project_root / "AGENTS.md"

        if not agents_md.exists():
            return behaviors

        try:
            content = agents_md.read_text(encoding="utf-8")

            # Find behavior definitions: ### `behavior_xyz`
            behavior_blocks = re.findall(
                r"###\s+`(behavior_[a-z_]+)`\s*\n(.*?)(?=\n###|\n##|\Z)",
                content,
                re.DOTALL,
            )

            for name, block in behavior_blocks:
                # Extract "When" trigger
                when_match = re.search(r"-\s*\*\*When\*\*:\s*(.+?)(?:\n-|\Z)", block, re.DOTALL)
                when_trigger = when_match.group(1).strip()[:150] if when_match else ""

                behaviors.append(
                    {
                        "name": name,
                        "summary": when_trigger,
                    }
                )

        except Exception as e:
            logger.debug("Failed to parse AGENTS.md", error=str(e))

        return behaviors

    def _extract_mcp_tools(self) -> list[dict[str, str]]:
        """Extract MCP tool definitions."""
        tools = []
        mcp_design = self.project_root / "MCP_SERVER_DESIGN.md"

        if mcp_design.exists():
            try:
                content = mcp_design.read_text(encoding="utf-8")

                # Find tool definitions in markdown tables
                # Format: | Domain | `tool1`, `tool2`, `tool3` | Description |
                table_rows = re.findall(
                    r"\|\s*([^|]+)\s*\|\s*`([^`|]+(?:`,\s*`[^`|]+)*)`\s*\|\s*([^|]+)\s*\|",
                    content,
                )

                for domain, tools_str, desc in table_rows:
                    # Split comma-separated tools
                    tool_names = re.findall(r"`?([a-z]+\.[a-z_]+)`?", tools_str, re.IGNORECASE)
                    for name in tool_names:
                        if not any(t["name"] == name for t in tools):
                            tools.append(
                                {
                                    "name": name.strip(),
                                    "description": f"[{domain.strip()}] {desc.strip()[:80]}",
                                }
                            )

            except Exception as e:
                logger.debug("Failed to parse MCP_SERVER_DESIGN.md", error=str(e))

        # Also check mcp_server.py for tool registrations
        mcp_server = self.project_root / "guideai" / "mcp_server.py"
        if mcp_server.exists():
            try:
                content = mcp_server.read_text(encoding="utf-8")

                # Find @server.tool decorators
                tool_defs = re.findall(
                    r'@\w+\.tool\s*\(\s*["\']([^"\']+)["\']\s*\)\s*\n\s*(?:async\s+)?def\s+\w+[^:]*:\s*(?:"""([^"]*?)""")?',
                    content,
                    re.DOTALL,
                )

                for name, docstring in tool_defs:
                    if not any(t["name"] == name for t in tools):
                        tools.append(
                            {
                                "name": name,
                                "description": (docstring or "").strip()[:100],
                            }
                        )

            except Exception as e:
                logger.debug("Failed to parse mcp_server.py", error=str(e))

        # Check MCP handler files for *_HANDLERS dictionaries (primary source)
        mcp_handlers_dir = self.project_root / "guideai" / "mcp" / "handlers"
        if mcp_handlers_dir.exists():
            for handler_file in mcp_handlers_dir.glob("*_handlers.py"):
                try:
                    content = handler_file.read_text(encoding="utf-8")
                    handler_name = handler_file.stem.replace("_handlers", "")

                    # Find HANDLERS = { ... } dictionaries with tool names
                    # Pattern: "toolName.action": handler_function,
                    tool_matches = re.findall(
                        r'["\']([a-zA-Z]+\.[a-zA-Z_]+)["\']:\s*\w+',
                        content,
                    )

                    for name in tool_matches:
                        if not any(t["name"] == name for t in tools):
                            tools.append({
                                "name": name,
                                "description": f"[{handler_name}] MCP handler",
                            })

                except Exception as e:
                    logger.debug("Failed to parse handler file", file=str(handler_file), error=str(e))

        return tools

    def _extract_db_tables(self) -> list[dict[str, str]]:
        """Extract database table definitions from schema files and Alembic migrations."""
        tables = []

        # Check Alembic migrations (main database)
        migrations_dir = self.project_root / "migrations" / "versions"
        if migrations_dir.exists():
            for migration_file in sorted(migrations_dir.glob("*.py"))[-10:]:  # Recent 10
                try:
                    content = migration_file.read_text(encoding="utf-8")

                    # Find op.create_table calls
                    create_matches = re.findall(
                        r'op\.create_table\s*\(\s*["\'](\w+)["\']',
                        content,
                    )
                    for table_name in create_matches:
                        if not any(t["name"] == table_name for t in tables):
                            tables.append({
                                "name": table_name,
                                "columns": "(Alembic migration)",
                            })

                    # Find CREATE TABLE in raw SQL
                    sql_matches = re.findall(
                        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?(\w+)',
                        content,
                        re.IGNORECASE,
                    )
                    for table_name in sql_matches:
                        if not any(t["name"] == table_name for t in tables):
                            tables.append({
                                "name": table_name,
                                "columns": "(PostgreSQL)",
                            })

                except Exception:
                    pass

        # Check telemetry migrations
        telemetry_dir = self.project_root / "migrations_telemetry" / "versions"
        if telemetry_dir.exists():
            for migration_file in telemetry_dir.glob("*.py"):
                try:
                    content = migration_file.read_text(encoding="utf-8")
                    sql_matches = re.findall(
                        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?(\w+)',
                        content,
                        re.IGNORECASE,
                    )
                    for table_name in sql_matches:
                        if not any(t["name"] == table_name for t in tables):
                            tables.append({
                                "name": table_name,
                                "columns": "(Telemetry DB)",
                            })
                except Exception:
                    pass

        # Check Raze logging schema (packages/raze)
        raze_migrations = self.project_root / "packages" / "raze" / "alembic" / "versions"
        if raze_migrations.exists():
            for migration_file in raze_migrations.glob("*.py"):
                try:
                    content = migration_file.read_text(encoding="utf-8")
                    # Find sa.Column definitions in create_table
                    if "log_events" in content.lower():
                        tables.append({
                            "name": "log_events",
                            "columns": "(Raze TimescaleDB hypertable)",
                        })
                except Exception:
                    pass

        # Check contract docs for schema definitions
        contract_files = [
            "RESEARCH_SERVICE_CONTRACT.md",
            "BEHAVIOR_SERVICE_CONTRACT.md",
            "ACTION_SERVICE_CONTRACT.md",
            "AUDIT_LOG_STORAGE.md",
        ]
        for contract_name in contract_files:
            contract_path = self.project_root / contract_name
            if contract_path.exists():
                try:
                    content = contract_path.read_text(encoding="utf-8")
                    sql_matches = re.findall(
                        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\(',
                        content,
                        re.IGNORECASE,
                    )
                    for table_name in sql_matches:
                        if not any(t["name"] == table_name for t in tables):
                            tables.append({
                                "name": table_name,
                                "columns": f"({contract_name})",
                            })
                except Exception:
                    pass

        # Check SQLAlchemy models in guideai/
        for models_file in self.project_root.glob("guideai/**/models.py"):
            if ".venv" in str(models_file):
                continue
            try:
                content = models_file.read_text(encoding="utf-8")

                # Find __tablename__ definitions
                model_matches = re.findall(
                    r'class\s+(\w+)\s*\([^)]*\):\s*\n\s*__tablename__\s*=\s*["\'](\w+)["\']',
                    content,
                )

                for class_name, table_name in model_matches:
                    if not any(t["name"] == table_name for t in tables):
                        rel_path = models_file.relative_to(self.project_root)
                        tables.append({
                            "name": table_name,
                            "columns": f"(SQLAlchemy: {class_name} in {rel_path})",
                        })

            except Exception:
                pass

        return tables

    def _get_recent_commits(self) -> list[dict[str, str]]:
        """Get recent git commits (last 7 days)."""
        if not self._check_is_git_repo():
            return []

        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    "--since=7 days ago",
                    "--pretty=format:%h|%ad|%s",
                    "--date=short",
                    "-n",
                    "15",
                ],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return []

            commits = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|", 2)
                if len(parts) >= 3:
                    commits.append(
                        {
                            "hash": parts[0],
                            "date": parts[1],
                            "message": parts[2][:80],
                        }
                    )

            return commits

        except Exception as e:
            logger.debug("Failed to get git commits", error=str(e))
            return []


# Convenience function for quick context generation
def get_codebase_context(project_root: str | Path | None = None) -> str:
    """
    Get formatted codebase context string for LLM prompts.

    Args:
        project_root: Project root directory. Defaults to guideai root.

    Returns:
        Formatted context string within token budget.
    """
    analyzer = CodebaseAnalyzer(project_root)
    snapshot = analyzer.get_structural_index()
    return snapshot.to_context_string()
