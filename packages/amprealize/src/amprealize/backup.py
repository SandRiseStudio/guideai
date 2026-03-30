"""Database backup and restore for Amprealize-managed PostgreSQL containers.

Uses pg_dump/pg_restore (logical backups) executed inside running containers
via `podman exec`. Designed for local development — portable, version-tolerant,
and survives Podman machine rebuilds.

Backup location: ~/.guideai/backups/<timestamp>/
"""

import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKUP_ROOT = Path.home() / ".guideai" / "backups"
MAX_AUTO_BACKUPS = 5

# Container name patterns → (db_name, pg_user) for pg_dump
DEFAULT_DB_CONTAINERS: List[Dict[str, str]] = [
    {
        "container_pattern": "guideai-db",
        "db_name": "guideai",
        "pg_user": "guideai",
        "label": "guideai-db (main)",
    },
    {
        "container_pattern": "telemetry-db",
        "db_name": "telemetry",
        "pg_user": "telemetry",
        "label": "telemetry-db (TimescaleDB)",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_running_container(pattern: str) -> Optional[str]:
    """Find a running container whose name contains *pattern*."""
    try:
        result = subprocess.run(
            ["podman", "ps", "--format", "{{.Names}}", "--filter", f"name={pattern}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for name in result.stdout.strip().splitlines():
            name = name.strip()
            if name:
                return name
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _ensure_backup_dir(tag: str = "auto") -> Path:
    """Create and return a timestamped backup directory.

    Returns e.g. ``~/.guideai/backups/2025-07-15T10-30-00_auto/``
    """
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    backup_dir = BACKUP_ROOT / f"{ts}_{tag}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


# ---------------------------------------------------------------------------
# Core: backup / restore / list / rotate
# ---------------------------------------------------------------------------

def backup_databases(
    tag: str = "auto",
    containers: Optional[List[Dict[str, str]]] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Dump every reachable database to ``~/.guideai/backups/<ts>_<tag>/``.

    Returns a dict with ``path``, ``databases`` (list of what was backed up),
    and ``errors`` (list of failures).
    """
    targets = containers or DEFAULT_DB_CONTAINERS
    backup_dir = _ensure_backup_dir(tag)

    result: Dict[str, Any] = {
        "path": str(backup_dir),
        "databases": [],
        "errors": [],
        "skipped": [],
    }

    for target in targets:
        container = _find_running_container(target["container_pattern"])
        if not container:
            result["skipped"].append(
                f"{target['label']}: container not running"
            )
            continue

        dump_file = backup_dir / f"{target['db_name']}.sql.gz"
        try:
            # pg_dump → gzip inside the container, stream to host file
            proc = subprocess.run(
                [
                    "podman", "exec", container,
                    "bash", "-c",
                    f"pg_dump -U {target['pg_user']} -d {target['db_name']}"
                    f" --no-owner --no-acl --clean --if-exists | gzip",
                ],
                capture_output=True,
                timeout=300,  # 5 min ceiling
            )
            if proc.returncode != 0:
                stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                result["errors"].append(f"{target['label']}: {stderr}")
                continue

            dump_file.write_bytes(proc.stdout)
            size_kb = dump_file.stat().st_size / 1024
            result["databases"].append(
                f"{target['label']} → {dump_file.name} ({size_kb:.1f} KB)"
            )
        except subprocess.TimeoutExpired:
            result["errors"].append(f"{target['label']}: pg_dump timed out")
        except OSError as exc:
            result["errors"].append(f"{target['label']}: {exc}")

    return result


def restore_databases(
    backup_path: Path,
    containers: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Restore databases from a backup directory.

    Each ``<db_name>.sql.gz`` in *backup_path* is gunzipped and piped into
    ``psql`` inside the matching container.
    """
    targets = containers or DEFAULT_DB_CONTAINERS

    result: Dict[str, Any] = {
        "path": str(backup_path),
        "restored": [],
        "errors": [],
        "skipped": [],
    }

    if not backup_path.is_dir():
        result["errors"].append(f"Backup directory not found: {backup_path}")
        return result

    for target in targets:
        dump_file = backup_path / f"{target['db_name']}.sql.gz"
        if not dump_file.exists():
            result["skipped"].append(
                f"{target['label']}: no dump file ({dump_file.name})"
            )
            continue

        container = _find_running_container(target["container_pattern"])
        if not container:
            result["errors"].append(
                f"{target['label']}: container not running"
            )
            continue

        try:
            dump_bytes = dump_file.read_bytes()
            proc = subprocess.run(
                [
                    "podman", "exec", "-i", container,
                    "bash", "-c",
                    f"gunzip | psql -U {target['pg_user']} -d {target['db_name']}"
                    " --set ON_ERROR_STOP=on",
                ],
                input=dump_bytes,
                capture_output=True,
                timeout=300,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                # psql prints notices on --clean drops; only treat as error
                # if it actually failed hard
                if "ERROR" in stderr:
                    result["errors"].append(f"{target['label']}: {stderr[:300]}")
                    continue

            result["restored"].append(target["label"])
        except subprocess.TimeoutExpired:
            result["errors"].append(f"{target['label']}: restore timed out")
        except OSError as exc:
            result["errors"].append(f"{target['label']}: {exc}")

    return result


def list_backups() -> List[Dict[str, Any]]:
    """Return metadata for each backup directory, newest first."""
    if not BACKUP_ROOT.exists():
        return []

    backups = []
    for entry in sorted(BACKUP_ROOT.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        dumps = list(entry.glob("*.sql.gz"))
        total_size = sum(f.stat().st_size for f in dumps)
        backups.append({
            "name": entry.name,
            "path": str(entry),
            "databases": [f.stem.replace(".sql", "") for f in dumps],
            "size_kb": round(total_size / 1024, 1),
            "created": entry.name.split("_")[0] if "_" in entry.name else entry.name,
            "tag": entry.name.split("_", 1)[1] if "_" in entry.name else "",
        })
    return backups


def rotate_backups(tag: str = "auto", keep: int = MAX_AUTO_BACKUPS) -> List[str]:
    """Remove oldest auto-backups beyond *keep* count.

    Only removes directories whose name ends with ``_<tag>``.
    Returns list of removed directory names.
    """
    if not BACKUP_ROOT.exists():
        return []

    matching = sorted(
        [d for d in BACKUP_ROOT.iterdir() if d.is_dir() and d.name.endswith(f"_{tag}")],
        reverse=True,  # newest first
    )

    removed = []
    for old in matching[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old.name)
    return removed
