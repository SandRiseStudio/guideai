"""Podman executor implementation.

This module provides the PodmanExecutor class, which implements the Executor
protocol using Podman as the container runtime.
"""

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    CleanupResult,
    ContainerInfo,
    ContainerRunConfig,
    ExecutorError,
    MachineCapableExecutor,
    MachineInfo,
    ResourceCapableExecutor,
    ResourceHealthResult,
    ResourceInfo,
    ResourceUsage,
)


class PodmanExecutor(ResourceCapableExecutor):
    """Executor implementation using Podman.

    This executor runs containers via the `podman` CLI and supports
    machine management for Podman on macOS/Windows, including resource
    monitoring for both host and VM environments.

    Example:
        executor = PodmanExecutor()

        # Check machine status
        machines = executor.list_machines()
        if machines and not machines[0].running:
            executor.start_machine(machines[0].name)

        # Check resources before deploying
        resources = executor.get_all_resources()
        for r in resources:
            if not r.healthy:
                print(f"Warning: {r.source} has issues: {r.warnings}")

        # Run a container
        config = ContainerRunConfig(
            image="postgres:16-alpine",
            name="my-postgres",
            ports=["5432:5432"],
            environment={"POSTGRES_PASSWORD": "secret"}
        )
        container_id = executor.run_container(config)

    Attributes:
        connection: Optional Podman connection name for remote/machine access
    """

    def __init__(self, connection: Optional[str] = None):
        """Initialize the Podman executor.

        Args:
            connection: Podman connection name (for --connection flag).
                        If None, uses the default connection.
        """
        self.connection = connection

    def _run_podman(
        self,
        args: List[str],
        check: bool = True,
        capture_output: bool = True
    ) -> subprocess.CompletedProcess:
        """Execute a podman command.

        Args:
            args: Command arguments (without 'podman' prefix)
            check: Whether to raise on non-zero exit
            capture_output: Whether to capture stdout/stderr

        Returns:
            Completed process result

        Raises:
            ExecutorError: If check=True and command fails
        """
        cmd = ["podman"]
        if self.connection:
            cmd.extend(["--connection", self.connection])
        cmd.extend(args)

        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True
        )

        if check and result.returncode != 0:
            raise ExecutorError(
                message=f"Podman command failed",
                command=cmd,
                stderr=result.stderr.strip() if result.stderr else None,
                returncode=result.returncode
            )

        return result

    # -------------------------------------------------------------------------
    # Container Operations
    # -------------------------------------------------------------------------

    def find_container_by_port(self, host_port: int) -> Optional[ContainerInfo]:
        """Find a container using a specific host port.

        Args:
            host_port: The host port to search for

        Returns:
            Container info if found, None otherwise
        """
        containers = self.list_containers(all_containers=True)
        for container in containers:
            # Also check via inspect for more detailed port info
            try:
                detailed = self.inspect_container(container.name or container.container_id)
                for port_binding in detailed.ports.values():
                    try:
                        if int(port_binding) == host_port:
                            return container
                    except (ValueError, TypeError):
                        continue
            except ExecutorError:
                continue
        return None

    def cleanup_port_conflict(self, host_port: int) -> bool:
        """Stop and remove any container using the specified host port.

        Args:
            host_port: The host port to free up

        Returns:
            True if a container was cleaned up, False otherwise
        """
        container = self.find_container_by_port(host_port)
        if container:
            self.stop_container(container.name or container.container_id)
            self.remove_container(container.name or container.container_id, force=True)
            return True
        return False

    def find_native_process_on_port(self, port: int) -> Optional[Dict[str, Any]]:
        """Find a native (non-container) process listening on a port.

        Uses lsof to find processes. Only works on Unix-like systems.

        Args:
            port: The port to check

        Returns:
            Dict with process info (pid, command, user) or None if no process found
        """
        import shutil

        lsof_path = shutil.which("lsof")
        if not lsof_path:
            return None

        try:
            result = subprocess.run(
                ["lsof", "-i", f":{port}", "-t", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None

            pid = int(result.stdout.strip().split()[0])

            # Get more process info
            ps_result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "pid,user,comm"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if ps_result.returncode == 0 and ps_result.stdout.strip():
                lines = ps_result.stdout.strip().split("\n")
                if len(lines) > 1:
                    parts = lines[1].split()
                    return {
                        "pid": pid,
                        "user": parts[1] if len(parts) > 1 else "unknown",
                        "command": parts[2] if len(parts) > 2 else "unknown"
                    }
            return {"pid": pid, "user": "unknown", "command": "unknown"}
        except (subprocess.TimeoutExpired, ValueError, IndexError):
            return None

    def cleanup_native_process_on_port(
        self,
        port: int,
        safe_commands: Optional[List[str]] = None,
        force: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Kill a native process listening on a port.

        By default, only kills processes that match 'safe_commands' to avoid
        killing unrelated services. Use force=True to kill any process.

        Args:
            port: The port to free up
            safe_commands: List of command names safe to kill (default: guideai-related)
            force: If True, kill any process; if False, only kill safe ones

        Returns:
            Dict with killed process info, or None if no process killed
        """
        import os
        import signal

        if safe_commands is None:
            # Default: only kill guideai-related processes
            safe_commands = ["python", "python3", "uvicorn", "gunicorn", "guideai"]

        process = self.find_native_process_on_port(port)
        if not process:
            return None

        pid = process["pid"]
        command = process.get("command", "")

        # Safety check: only kill if command matches safe list or force=True
        is_safe = force or any(safe_cmd in command.lower() for safe_cmd in safe_commands)
        if not is_safe:
            return None  # Don't kill unknown processes

        try:
            os.kill(pid, signal.SIGTERM)
            # Give it a moment to terminate gracefully
            import time
            for _ in range(10):  # Wait up to 1 second
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)  # Check if still alive
                except OSError:
                    break  # Process is gone
            else:
                # Still alive after SIGTERM, use SIGKILL
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

            process["killed"] = True
            return process
        except OSError:
            return None  # Process already gone or permission denied

    def resolve_native_port_conflicts(
        self,
        ports: List[int],
        cleanup: bool = True,
        force: bool = False
    ) -> Dict[int, Optional[Dict[str, Any]]]:
        """Check for and optionally resolve native process port conflicts.

        This handles non-container processes (like stale API servers) that may
        be blocking ports needed for testing.

        Args:
            ports: List of host ports that need to be available
            cleanup: Whether to kill conflicting processes
            force: If True, kill any process; if False, only kill safe ones

        Returns:
            Dict mapping port to process info (None if port is free)
        """
        conflicts: Dict[int, Optional[Dict[str, Any]]] = {}

        for port in ports:
            process = self.find_native_process_on_port(port)
            conflicts[port] = process

            if process and cleanup:
                killed = self.cleanup_native_process_on_port(port, force=force)
                if killed:
                    conflicts[port] = None  # Port is now free

        return conflicts

    def run_container(self, config: ContainerRunConfig) -> str:
        """Create and start a container using Podman.

        Handles conflicts gracefully:
        - If a container with the same name exists, it will be stopped and removed
        - If a port is in use by another container, that container will be stopped

        Args:
            config: Container configuration

        Returns:
            Container ID
        """
        # Clean up any existing container with the same name
        try:
            self.stop_container(config.name)
            self.remove_container(config.name, force=True)
        except ExecutorError:
            pass  # Container doesn't exist, that's fine

        # Clean up port conflicts before attempting to run
        for port_mapping in config.ports:
            # Parse port mapping (e.g., "6433:5432" or "0.0.0.0:6433:5432")
            parts = port_mapping.split(":")
            if len(parts) >= 2:
                # Host port is second-to-last (or first if only two parts)
                try:
                    host_port = int(parts[-2] if len(parts) > 2 else parts[0])
                    self.cleanup_port_conflict(host_port)
                except (ValueError, IndexError):
                    pass

        args = ["run"]

        if config.detach:
            args.append("-d")

        args.extend(["--name", config.name])

        # Network
        if config.network:
            args.extend(["--network", config.network])
            # Add network aliases
            for alias in config.network_aliases:
                args.extend(["--network-alias", alias])

        # Ports
        for port in config.ports:
            args.extend(["-p", port])

        # Environment
        for key, value in config.environment.items():
            args.extend(["-e", f"{key}={value}"])

        # Volumes
        for vol in config.volumes:
            args.extend(["-v", vol])

        # Image
        args.append(config.image)

        # Command
        if config.command:
            args.extend(config.command)

        try:
            result = self._run_podman(args)
            return result.stdout.strip()
        except ExecutorError as e:
            # If container name already exists (race condition), try to clean up and retry once
            if "already in use" in (e.stderr or "").lower() or "already exists" in (e.stderr or "").lower():
                self.stop_container(config.name)
                self.remove_container(config.name, force=True)
                result = self._run_podman(args)
                return result.stdout.strip()
            raise

    def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop a running container.

        Silently handles cases where:
        - Container doesn't exist
        - Container is already stopped
        """
        try:
            self._run_podman(["stop", "-t", str(timeout), container_id])
        except ExecutorError as e:
            stderr = (e.stderr or "").lower()
            # Ignore if container doesn't exist or is already stopped
            if "no such container" in stderr or "not running" in stderr:
                pass
            else:
                raise

    def remove_container(self, container_id: str, force: bool = False) -> None:
        """Remove a container.

        Silently handles cases where container doesn't exist.
        """
        args = ["rm"]
        if force:
            args.append("-f")
        args.append(container_id)

        try:
            self._run_podman(args)
        except ExecutorError as e:
            stderr = (e.stderr or "").lower()
            # Ignore if container doesn't exist
            if "no such container" in stderr or "no such object" in stderr:
                pass
            else:
                raise

    def inspect_container(self, container_id: str) -> ContainerInfo:
        """Get container information."""
        result = self._run_podman(["inspect", container_id, "--format", "json"])

        try:
            raw_data = json.loads(result.stdout)
            if isinstance(raw_data, list) and raw_data:
                data: Dict[str, Any] = raw_data[0]
            elif isinstance(raw_data, dict):
                data = raw_data
            else:
                data = {}
        except json.JSONDecodeError as e:
            raise ExecutorError(
                message="Failed to parse container inspection result",
                stderr=str(e)
            )

        state: Dict[str, Any] = data.get("State", {})
        config: Dict[str, Any] = data.get("Config", {})

        return ContainerInfo(
            container_id=data.get("Id", container_id)[:12],
            name=data.get("Name", "").lstrip("/"),
            status=state.get("Status", "unknown"),
            image=config.get("Image", ""),
            created=data.get("Created"),
            ports=self._parse_port_bindings(data.get("NetworkSettings", {}).get("Ports", {}))
        )

    def _parse_port_bindings(self, ports: Dict[str, Any]) -> Dict[str, str]:
        """Parse port bindings from inspect output."""
        result = {}
        for container_port, bindings in ports.items():
            if bindings:
                for binding in bindings:
                    host_port = binding.get("HostPort", "")
                    if host_port:
                        result[container_port] = host_port
        return result

    def exec_in_container(
        self,
        container_id: str,
        command: List[str],
        workdir: Optional[str] = None
    ) -> str:
        """Execute a command in a running container."""
        args = ["exec"]
        if workdir:
            args.extend(["-w", workdir])
        args.append(container_id)
        args.extend(command)

        result = self._run_podman(args)
        return result.stdout

    def get_logs(
        self,
        container_id: str,
        tail: Optional[int] = None,
        since: Optional[str] = None
    ) -> str:
        """Get container logs."""
        args = ["logs"]
        if tail is not None:
            args.extend(["--tail", str(tail)])
        if since:
            args.extend(["--since", since])
        args.append(container_id)

        result = self._run_podman(args)
        return result.stdout

    def get_container_status(self, container_id: str) -> str:
        """Get the status of a container."""
        result = self._run_podman(
            ["inspect", container_id, "--format", "{{.State.Status}}"],
            check=False
        )

        if result.returncode != 0:
            return "unknown"

        return result.stdout.strip()

    # -------------------------------------------------------------------------
    # Machine Operations (for Podman on macOS/Windows)
    # -------------------------------------------------------------------------

    def list_machines(self) -> List[MachineInfo]:
        """List all Podman machines."""
        result = self._run_podman(["machine", "list", "--format", "json"], check=False)

        if result.returncode != 0:
            return []

        try:
            machines = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return []

        return [
            MachineInfo(
                name=m.get("Name", ""),
                running=m.get("Running", False),
                cpus=m.get("CPUs"),
                memory_mb=int(m.get("Memory", 0)) // (1024 * 1024) if m.get("Memory") else None,
                disk_gb=int(m.get("DiskSize", 0)) // (1024 * 1024 * 1024) if m.get("DiskSize") else None
            )
            for m in machines
        ]

    def get_machine(self, name: str) -> Optional[MachineInfo]:
        """Get information about a specific machine."""
        machines = self.list_machines()
        for machine in machines:
            if machine.name == name:
                return machine
        return None

    def start_machine(self, name: str) -> None:
        """Start a Podman machine.

        Silently handles cases where the machine is already running.
        """
        try:
            self._run_podman(["machine", "start", name])
        except ExecutorError as e:
            stderr = (e.stderr or "").lower()
            # Ignore if machine is already running
            if "already running" in stderr or "is already running" in stderr:
                pass
            else:
                raise

    def stop_machine(self, name: str) -> None:
        """Stop a Podman machine.

        Silently handles cases where the machine is already stopped.
        """
        try:
            self._run_podman(["machine", "stop", name])
        except ExecutorError as e:
            stderr = (e.stderr or "").lower()
            # Ignore if machine is already stopped
            if "not running" in stderr or "is not running" in stderr:
                pass
            else:
                raise

    def init_machine(
        self,
        name: str,
        cpus: Optional[int] = None,
        memory_mb: Optional[int] = None,
        disk_gb: Optional[int] = None
    ) -> None:
        """Initialize a new Podman machine."""
        args = ["machine", "init"]

        if cpus is not None:
            args.extend(["--cpus", str(cpus)])
        if memory_mb is not None:
            args.extend(["--memory", str(memory_mb)])
        if disk_gb is not None:
            args.extend(["--disk-size", str(disk_gb)])

        args.append(name)
        self._run_podman(args)

    def inspect_machine(self, name: str) -> Dict[str, Any]:
        """Get detailed machine configuration."""
        result = self._run_podman(["machine", "inspect", name])

        try:
            raw_data = json.loads(result.stdout or "[]")
            if isinstance(raw_data, list) and raw_data:
                return dict(raw_data[0]) if isinstance(raw_data[0], dict) else {}
            elif isinstance(raw_data, dict):
                return raw_data
            return {}
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def is_podman_available(self) -> bool:
        """Check if Podman CLI is available."""
        try:
            result = subprocess.run(
                ["podman", "--version"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def get_podman_version(self) -> Optional[str]:
        """Get the Podman version string."""
        try:
            result = subprocess.run(
                ["podman", "--version"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                # Parse "podman version X.Y.Z"
                return result.stdout.strip().split()[-1]
        except FileNotFoundError:
            pass
        return None

    def pull_image(self, image: str) -> None:
        """Pull a container image."""
        self._run_podman(["pull", image])

    def image_exists(self, image: str) -> bool:
        """Check if an image exists locally."""
        result = self._run_podman(
            ["image", "exists", image],
            check=False
        )
        return result.returncode == 0

    def list_containers(
        self,
        all_containers: bool = False,
        filters: Optional[Dict[str, str]] = None
    ) -> List[ContainerInfo]:
        """List containers.

        Args:
            all_containers: Include stopped containers
            filters: Filter criteria (e.g., {"name": "myapp"})

        Returns:
            List of container information
        """
        args = ["ps", "--format", "json"]
        if all_containers:
            args.append("-a")

        if filters:
            for key, value in filters.items():
                args.extend(["--filter", f"{key}={value}"])

        result = self._run_podman(args, check=False)

        if result.returncode != 0:
            return []

        try:
            containers = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return []

        return [
            ContainerInfo(
                container_id=c.get("Id", "")[:12],
                name=c.get("Names", [""])[0] if isinstance(c.get("Names"), list) else c.get("Names", ""),
                status=c.get("State", "unknown"),
                image=c.get("Image", ""),
                created=c.get("Created"),
            )
            for c in containers
        ]

    # =========================================================================
    # Network Management
    # =========================================================================

    def create_network(self, name: str, ignore_exists: bool = True) -> bool:
        """Create a Podman network.

        Args:
            name: Network name
            ignore_exists: If True, don't raise error if network already exists

        Returns:
            True if network was created or already exists

        Raises:
            ExecutorError: If creation fails (and ignore_exists is False)
        """
        result = self._run_podman(["network", "create", name], check=False)

        if result.returncode == 0:
            return True

        stderr = (result.stderr or "").lower()
        if ignore_exists and ("already exists" in stderr or "network already exists" in stderr):
            return True

        raise ExecutorError(
            message=f"Failed to create network '{name}'",
            stderr=result.stderr
        )

    def network_exists(self, name: str) -> bool:
        """Check if a network exists.

        Args:
            name: Network name

        Returns:
            True if network exists
        """
        result = self._run_podman(["network", "exists", name], check=False)
        return result.returncode == 0

    def remove_network(self, name: str, force: bool = False) -> None:
        """Remove a network.

        Args:
            name: Network name
            force: Force removal even if in use
        """
        args = ["network", "rm"]
        if force:
            args.append("-f")
        args.append(name)

        try:
            self._run_podman(args)
        except ExecutorError as e:
            stderr = (e.stderr or "").lower()
            # Ignore if network doesn't exist
            if "no such network" in stderr or "network not found" in stderr:
                pass
            else:
                raise

    def get_network_stats(self, container_id: str) -> Dict[str, Any]:
        """Get network statistics for a container.

        Returns dict with rx_bytes, tx_bytes, etc.
        """
        result = self._run_podman(
            ["stats", container_id, "--no-stream", "--format", "json"],
            check=False
        )

        if result.returncode != 0:
            return {}

        try:
            raw_stats = json.loads(result.stdout or "[]")
            if isinstance(raw_stats, list) and raw_stats:
                first = raw_stats[0]
                if isinstance(first, dict):
                    return first.get("NetIO", {})
                return {}
            elif isinstance(raw_stats, dict):
                return raw_stats.get("NetIO", {})
            return {}
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------------------------------
    # Conflict Resolution & Cleanup
    # -------------------------------------------------------------------------

    # Stale container statuses that indicate containers need cleanup
    STALE_STATUSES = frozenset({"exited", "dead", "created", "removing", "paused"})

    def find_stale_containers(
        self,
        include_all: bool = False,
        max_age_hours: Optional[float] = None,
    ) -> List[ContainerInfo]:
        """Find stale containers that are not running and may need cleanup.

        Stale containers include:
        - Exited containers (finished or crashed)
        - Dead containers (failed to start)
        - Created but never started containers
        - Paused containers (if include_all=True)
        - Containers older than max_age_hours (if specified)

        Args:
            include_all: Include all non-running containers, not just stale statuses
            max_age_hours: Only include containers older than this (None = any age)

        Returns:
            List of stale containers sorted by age (oldest first)
        """
        import time
        from datetime import datetime

        all_containers = self.list_containers(all_containers=True)
        stale = []

        for container in all_containers:
            status = (container.status or "").lower()

            # Check if container is stale
            is_stale = False
            if include_all and status != "running":
                is_stale = True
            elif status in self.STALE_STATUSES:
                is_stale = True

            if not is_stale:
                continue

            # Check age if max_age_hours is specified
            if max_age_hours is not None and container.created:
                try:
                    # Parse ISO format created timestamp
                    created_time = datetime.fromisoformat(
                        container.created.replace("Z", "+00:00")
                    )
                    age_hours = (datetime.now(created_time.tzinfo) - created_time).total_seconds() / 3600
                    if age_hours < max_age_hours:
                        continue  # Too young, skip
                except (ValueError, TypeError):
                    pass  # Can't parse, include it

            stale.append(container)

        # Sort by created time (oldest first) for consistent cleanup order
        def get_created_time(c: ContainerInfo) -> str:
            return c.created or "9999"  # Put unknown dates last

        return sorted(stale, key=get_created_time)

    def cleanup_stale_containers(
        self,
        include_all: bool = False,
        max_age_hours: Optional[float] = None,
        force: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Clean up stale containers.

        Args:
            include_all: Include all non-running containers
            max_age_hours: Only clean containers older than this
            force: Force remove even if stop fails
            dry_run: If True, only report what would be cleaned

        Returns:
            Dict with cleanup results:
                - removed: List of container names that were removed
                - failed: List of (name, error) tuples for failed removals
                - would_remove: (dry_run only) List of containers that would be removed
        """
        stale = self.find_stale_containers(
            include_all=include_all,
            max_age_hours=max_age_hours,
        )

        result: Dict[str, Any] = {
            "removed": [],
            "failed": [],
            "total_found": len(stale),
        }

        if dry_run:
            result["would_remove"] = [
                {"name": c.name, "status": c.status, "created": c.created}
                for c in stale
            ]
            return result

        for container in stale:
            container_id = container.name or container.container_id
            try:
                # Try to stop first if it's in a stoppable state
                if container.status in ("running", "paused"):
                    try:
                        self.stop_container(container_id, timeout=5)
                    except ExecutorError:
                        pass  # Continue to force remove

                # Remove the container
                self.remove_container(container_id, force=force)
                result["removed"].append(container_id)
            except ExecutorError as e:
                result["failed"].append((container_id, str(e)))

        return result

    def find_orphaned_amprealize_containers(
        self,
        prefix: str = "amp-",
        exclude_run_id: Optional[str] = None
    ) -> List[ContainerInfo]:
        """Find orphaned Amprealize containers from previous runs.

        Args:
            prefix: Container name prefix to match (default: "amp-")
            exclude_run_id: Run ID to exclude from cleanup (current run)

        Returns:
            List of orphaned containers that can be cleaned up
        """
        all_containers = self.list_containers(all_containers=True)
        orphaned = []

        for container in all_containers:
            name = container.name or ""
            # Match Amprealize naming pattern: amp-<uuid>-<service>
            if name.startswith(prefix):
                # Extract run ID from container name (amp-<run-id>-<service>)
                parts = name.split("-", 6)  # amp + 5 uuid parts + service
                if len(parts) >= 6:
                    run_id = "-".join(parts[:6])  # amp-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
                    if exclude_run_id and run_id == exclude_run_id:
                        continue
                orphaned.append(container)

        return orphaned

    def cleanup_orphaned_containers(
        self,
        prefix: str = "amp-",
        exclude_run_id: Optional[str] = None,
        force: bool = True
    ) -> int:
        """Clean up orphaned Amprealize containers from previous runs.

        Args:
            prefix: Container name prefix to match (default: "amp-")
            exclude_run_id: Run ID to exclude from cleanup (current run)
            force: Whether to force remove running containers

        Returns:
            Number of containers cleaned up
        """
        orphaned = self.find_orphaned_amprealize_containers(prefix, exclude_run_id)
        cleaned = 0

        for container in orphaned:
            container_id = container.name or container.container_id
            try:
                # Stop if running
                if container.status in ("running", "paused"):
                    self.stop_container(container_id, timeout=5)
                # Remove
                self.remove_container(container_id, force=force)
                cleaned += 1
            except ExecutorError:
                # Best effort - continue with other containers
                pass

        return cleaned

    def resolve_port_conflicts(
        self,
        required_ports: List[int],
        cleanup: bool = True
    ) -> Dict[int, Optional[ContainerInfo]]:
        """Check for and optionally resolve port conflicts.

        Args:
            required_ports: List of host ports that need to be available
            cleanup: Whether to clean up conflicting containers

        Returns:
            Dict mapping port to conflicting container (None if port is free)
        """
        conflicts: Dict[int, Optional[ContainerInfo]] = {}

        for port in required_ports:
            conflicting = self.find_container_by_port(port)
            conflicts[port] = conflicting

            if conflicting and cleanup:
                container_id = conflicting.name or conflicting.container_id
                try:
                    self.stop_container(container_id, timeout=5)
                    self.remove_container(container_id, force=True)
                    conflicts[port] = None  # Port is now free
                except ExecutorError:
                    pass  # Port still blocked

        return conflicts

    def prepare_for_apply(
        self,
        ports: List[int],
        preserve_run_id: Optional[str] = None,
        cleanup_stale: bool = True,
        stale_max_age_hours: Optional[float] = 24.0,
    ) -> Dict[str, Any]:
        """Prepare the environment for a new apply operation.

        Performs comprehensive cleanup:
        1. Removes stale containers (exited, dead, etc.) older than max_age_hours
        2. Removes orphaned Amprealize containers from previous runs
        3. Resolves port conflicts by stopping containers using required ports
        4. Resolves native process port conflicts

        Args:
            ports: List of host ports that will be used
            preserve_run_id: Run ID to preserve (don't clean up its containers)
            cleanup_stale: Whether to clean up stale containers
            stale_max_age_hours: Only clean stale containers older than this (None = any age)

        Returns:
            Dict with cleanup stats: orphans_removed, conflicts_resolved, stale_removed
        """
        result = {
            "stale_removed": 0,
            "stale_found": [],
            "orphans_removed": 0,
            "conflicts_resolved": 0,
            "orphans_found": [],
            "conflicts_found": []
        }

        # Step 0: Clean up stale containers (exited, dead, etc.)
        if cleanup_stale:
            stale_result = self.cleanup_stale_containers(
                include_all=False,  # Only truly stale statuses
                max_age_hours=stale_max_age_hours,
                force=True,
            )
            result["stale_found"] = [c["name"] for c in stale_result.get("would_remove", [])] or stale_result.get("removed", [])
            result["stale_removed"] = len(stale_result.get("removed", []))

        # Step 1: Clean up orphaned Amprealize containers
        orphans = self.find_orphaned_amprealize_containers(exclude_run_id=preserve_run_id)
        result["orphans_found"] = [c.name for c in orphans]
        result["orphans_removed"] = self.cleanup_orphaned_containers(
            exclude_run_id=preserve_run_id
        )

        # Step 2: Resolve container port conflicts
        if ports:
            conflicts = self.resolve_port_conflicts(ports, cleanup=True)
            for port, container in conflicts.items():
                if container:
                    # Container couldn't be removed - still blocking
                    result["conflicts_found"].append({
                        "port": port,
                        "container": container.name,
                        "status": "blocked"
                    })
                else:
                    # Port was freed
                    result["conflicts_resolved"] += 1

        # Step 3: Resolve native process port conflicts (stale API servers, etc.)
        # This handles non-container processes that may be blocking ports
        if ports:
            native_conflicts = self.resolve_native_port_conflicts(ports, cleanup=True)
            for port, process in native_conflicts.items():
                if process:
                    # Process couldn't be killed - still blocking
                    result["conflicts_found"].append({
                        "port": port,
                        "process": process,
                        "status": "blocked"
                    })
                elif port not in [c.get("port") for c in result["conflicts_found"]]:
                    # Only count if not already resolved by container cleanup
                    pass  # Native process was killed

        return result

    def ensure_container_ready(
        self,
        container_name: str,
        config: ContainerRunConfig,
        reuse_if_running: bool = False
    ) -> str:
        """Ensure a container is running with the specified config.

        Handles various conflict scenarios:
        - Container exists and is running: optionally reuse or replace
        - Container exists but stopped/exited: remove and recreate
        - Container doesn't exist: create new
        - Port conflicts: resolve before creating

        Args:
            container_name: Desired container name
            config: Container configuration
            reuse_if_running: If True, reuse existing running container with same name

        Returns:
            Container ID
        """
        # Check if container already exists
        existing = None
        try:
            existing = self.inspect_container(container_name)
        except ExecutorError:
            pass  # Container doesn't exist

        if existing:
            # Container exists - check its state
            if existing.status == "running":
                if reuse_if_running:
                    # Verify it's the same image
                    if existing.image == config.image or config.image in existing.image:
                        return existing.container_id
                # Running but we need fresh - stop and remove
                self.stop_container(container_name, timeout=5)

            # Remove the existing container (stopped or dead)
            self.remove_container(container_name, force=True)

        # Resolve port conflicts before creating
        if config.ports:
            required_ports = []
            for port_mapping in config.ports:
                parts = port_mapping.split(":")
                try:
                    host_port = int(parts[-2] if len(parts) > 2 else parts[0])
                    required_ports.append(host_port)
                except (ValueError, IndexError):
                    pass

            if required_ports:
                self.resolve_port_conflicts(required_ports, cleanup=True)

        # Create the container
        return self.run_container(config)

    def get_container_health_summary(self) -> Dict[str, List[ContainerInfo]]:
        """Get a summary of container health states.

        Returns:
            Dict with keys: 'running', 'exited', 'dead', 'paused', 'other'
        """
        all_containers = self.list_containers(all_containers=True)

        summary: Dict[str, List[ContainerInfo]] = {
            "running": [],
            "exited": [],
            "dead": [],
            "paused": [],
            "other": []
        }

        for container in all_containers:
            status = container.status.lower()
            if status in summary:
                summary[status].append(container)
            else:
                summary["other"].append(container)

        return summary

    # -------------------------------------------------------------------------
    # Resource Monitoring
    # -------------------------------------------------------------------------

    def get_disk_usage(self) -> Dict[str, Any]:
        """Get Podman disk usage information.

        Returns dict with:
            - images: list of image info with size
            - containers: list of container info with size
            - volumes: list of volume info with size
            - total_mb: total disk usage in MB
            - reclaimable_mb: space that can be reclaimed
        """
        result = self._run_podman(["system", "df", "--format", "json"], check=False)

        if result.returncode != 0:
            return {"total_mb": 0, "reclaimable_mb": 0, "images": [], "containers": [], "volumes": []}

        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return {"total_mb": 0, "reclaimable_mb": 0, "images": [], "containers": [], "volumes": []}

        # Parse sizes (podman returns bytes)
        total_bytes = 0
        reclaimable_bytes = 0

        images = data.get("Images", [])
        containers = data.get("Containers", [])
        volumes = data.get("Volumes", [])

        for img in images:
            total_bytes += img.get("Size", 0) or 0
            reclaimable_bytes += img.get("Reclaimable", 0) or 0

        for container in containers:
            total_bytes += container.get("Size", 0) or 0
            reclaimable_bytes += container.get("RWSize", 0) or 0

        for volume in volumes:
            total_bytes += volume.get("Size", 0) or 0
            reclaimable_bytes += volume.get("Reclaimable", 0) or 0

        return {
            "images": images,
            "containers": containers,
            "volumes": volumes,
            "total_mb": total_bytes / (1024 * 1024),
            "reclaimable_mb": reclaimable_bytes / (1024 * 1024),
        }

    def get_machine_resources(self, name: Optional[str] = None) -> Dict[str, Any]:
        """Get resource information for a Podman machine.

        Returns dict with:
            - memory_total_mb: Total memory allocated to machine
            - memory_used_mb: Memory in use (estimated from containers)
            - cpu_cores: Number of CPU cores
            - disk_total_mb: Disk allocated to machine
            - disk_used_mb: Disk in use
        """
        # Get machine info
        machines = self.list_machines()
        machine = None

        if name:
            machine = self.get_machine(name)
        elif machines:
            # Use the first/default machine
            machine = machines[0]

        if not machine:
            return {
                "memory_total_mb": 0,
                "memory_used_mb": 0,
                "cpu_cores": 0,
                "disk_total_mb": 0,
                "disk_used_mb": 0,
            }

        # Get disk usage
        disk_info = self.get_disk_usage()

        # Estimate memory usage from running containers
        memory_used_mb = 0
        running_containers = self.list_containers(all_containers=False)
        for container in running_containers:
            # Try to get container stats
            try:
                stats = self.get_container_stats(container.container_id)
                memory_used_mb += stats.get("memory_mb", 0)
            except ExecutorError:
                pass

        return {
            "memory_total_mb": machine.memory_mb or 0,
            "memory_used_mb": memory_used_mb,
            "cpu_cores": machine.cpus or 0,
            "disk_total_mb": (machine.disk_gb or 0) * 1024,
            "disk_used_mb": disk_info.get("total_mb", 0),
        }

    def get_container_stats(self, container_id: str) -> Dict[str, Any]:
        """Get resource stats for a specific container.

        Returns dict with:
            - memory_mb: Memory usage in MB
            - memory_limit_mb: Memory limit in MB
            - cpu_percent: CPU usage percentage
            - pids: Number of processes
        """
        result = self._run_podman(
            ["stats", "--no-stream", "--format", "json", container_id],
            check=False
        )

        if result.returncode != 0:
            return {"memory_mb": 0, "memory_limit_mb": 0, "cpu_percent": 0, "pids": 0}

        try:
            data = json.loads(result.stdout or "[]")
            if isinstance(data, list) and data:
                stats = data[0]
            elif isinstance(data, dict):
                stats = data
            else:
                return {"memory_mb": 0, "memory_limit_mb": 0, "cpu_percent": 0, "pids": 0}
        except json.JSONDecodeError:
            return {"memory_mb": 0, "memory_limit_mb": 0, "cpu_percent": 0, "pids": 0}

        # Parse memory (format: "123.4MiB / 8GiB")
        mem_usage = stats.get("MemUsage", "0 / 0")
        memory_mb = 0
        memory_limit_mb = 0

        if "/" in mem_usage:
            used, limit = mem_usage.split("/")
            memory_mb = self._parse_size_to_mb(used.strip())
            memory_limit_mb = self._parse_size_to_mb(limit.strip())

        # Parse CPU (format: "12.34%")
        cpu_str = stats.get("CPU", "0%")
        try:
            cpu_percent = float(cpu_str.rstrip("%"))
        except ValueError:
            cpu_percent = 0.0

        return {
            "memory_mb": memory_mb,
            "memory_limit_mb": memory_limit_mb,
            "cpu_percent": cpu_percent,
            "pids": stats.get("PIDs", 0) or 0,
        }

    def _parse_size_to_mb(self, size_str: str) -> float:
        """Parse size string (e.g., '123.4MiB', '1GiB') to MB."""
        size_str = size_str.strip().upper()

        multipliers = {
            "B": 1 / (1024 * 1024),
            "KB": 1 / 1024,
            "KIB": 1 / 1024,
            "MB": 1,
            "MIB": 1,
            "GB": 1024,
            "GIB": 1024,
            "TB": 1024 * 1024,
            "TIB": 1024 * 1024,
        }

        for suffix, multiplier in multipliers.items():
            if size_str.endswith(suffix):
                try:
                    value = float(size_str[:-len(suffix)].strip())
                    return value * multiplier
                except ValueError:
                    return 0

        # Try parsing as plain number (assume bytes)
        try:
            return float(size_str) / (1024 * 1024)
        except ValueError:
            return 0

    def get_resource_insights(
        self,
        machine_name: Optional[str] = None,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """Get resource insights with plain-English descriptions.

        Combines machine resources with the insights analyzer to provide
        human-readable status messages.

        Returns dict with:
            - resources: Raw resource metrics
            - insights: Dict of resource name -> ResourceInsight
            - summary: Formatted summary string
        """
        from .insights import ResourceInsightAnalyzer

        resources = self.get_machine_resources(machine_name)

        # Get container health for additional context
        health_summary = self.get_container_health_summary()
        container_health = {}
        for container in health_summary.get("running", []):
            container_health[container.name] = "running"
        for container in health_summary.get("exited", []):
            container_health[container.name] = "exited"
        for container in health_summary.get("dead", []):
            container_health[container.name] = "dead"

        # Analyze resources
        analyzer = ResourceInsightAnalyzer()
        insights = analyzer.analyze(
            memory_used_mb=resources.get("memory_used_mb"),
            memory_total_mb=resources.get("memory_total_mb"),
            disk_used_mb=resources.get("disk_used_mb"),
            disk_total_mb=resources.get("disk_total_mb"),
            container_health=container_health if container_health else None,
        )

        summary = analyzer.format_summary(insights, verbose=verbose)

        return {
            "resources": resources,
            "insights": {k: v.to_dict() for k, v in insights.items()},
            "summary": summary,
        }

    # -------------------------------------------------------------------------
    # Resource Monitoring (Host + Machine)
    # -------------------------------------------------------------------------

    def get_host_resources(self) -> ResourceInfo:
        """Get resource usage for the host machine.

        Monitors:
        - Disk: Available space on the data volume (macOS: /System/Volumes/Data)
        - Memory: System memory via /proc/meminfo (Linux) or vm_stat (macOS)
        - CPU: Load average and core count

        Returns:
            ResourceInfo with disk, memory, and CPU usage for the host
        """
        warnings: List[str] = []
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get disk usage
        disk = self._get_host_disk_usage()
        if disk and disk.is_critical:
            warnings.append(f"Host disk critically low: {disk.available:.1f}{disk.unit} available ({disk.percent_used:.1f}% used)")
        elif disk and disk.is_warning:
            warnings.append(f"Host disk warning: {disk.available:.1f}{disk.unit} available ({disk.percent_used:.1f}% used)")

        # Get memory usage
        memory = self._get_host_memory_usage()
        if memory and memory.is_critical:
            warnings.append(f"Host memory critically low: {memory.available:.0f}{memory.unit} available ({memory.percent_used:.1f}% used)")
        elif memory and memory.is_warning:
            warnings.append(f"Host memory warning: {memory.available:.0f}{memory.unit} available ({memory.percent_used:.1f}% used)")

        # Get CPU info
        cpu = self._get_host_cpu_usage()

        healthy = not any(w.startswith("Host disk critically") or w.startswith("Host memory critically") for w in warnings)

        return ResourceInfo(
            source="host",
            disk=disk,
            memory=memory,
            cpu=cpu,
            timestamp=timestamp,
            healthy=healthy,
            warnings=warnings,
        )

    def _get_host_disk_usage(self) -> Optional[ResourceUsage]:
        """Get host disk usage."""
        system = platform.system()

        try:
            if system == "Darwin":
                # macOS: Check /System/Volumes/Data (where user data lives)
                path = "/System/Volumes/Data"
                if not os.path.exists(path):
                    path = "/"
            else:
                # Linux: Check root filesystem
                path = "/"

            usage = shutil.disk_usage(path)
            total_gb = usage.total / (1024 ** 3)
            used_gb = usage.used / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
            percent = (usage.used / usage.total) * 100

            return ResourceUsage(
                total=total_gb,
                used=used_gb,
                available=free_gb,
                percent_used=percent,
                unit="GB",
            )
        except Exception:
            return None

    def _get_host_memory_usage(self) -> Optional[ResourceUsage]:
        """Get host memory usage."""
        system = platform.system()

        try:
            if system == "Darwin":
                # macOS: Use vm_stat and sysctl
                # Get total memory
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True,
                    text=True,
                )
                total_bytes = int(result.stdout.strip()) if result.returncode == 0 else 0

                # Get memory stats via vm_stat
                result = subprocess.run(
                    ["vm_stat"],
                    capture_output=True,
                    text=True,
                )

                if result.returncode == 0:
                    # Parse vm_stat output
                    stats = {}
                    for line in result.stdout.split("\n"):
                        if ":" in line:
                            key, value = line.split(":", 1)
                            # Remove "Pages" suffix and trailing period
                            value = value.strip().rstrip(".")
                            try:
                                stats[key.strip()] = int(value)
                            except ValueError:
                                pass

                    # Page size is typically 4096 or 16384 on Apple Silicon
                    page_size = 16384 if platform.machine() == "arm64" else 4096

                    # Calculate free/inactive memory
                    free_pages = stats.get("Pages free", 0)
                    inactive_pages = stats.get("Pages inactive", 0)
                    available_bytes = (free_pages + inactive_pages) * page_size

                    total_mb = total_bytes / (1024 * 1024)
                    available_mb = available_bytes / (1024 * 1024)
                    used_mb = total_mb - available_mb
                    percent = (used_mb / total_mb) * 100 if total_mb > 0 else 0

                    return ResourceUsage(
                        total=total_mb,
                        used=used_mb,
                        available=available_mb,
                        percent_used=percent,
                        unit="MB",
                    )
            else:
                # Linux: Read /proc/meminfo
                meminfo: Dict[str, int] = {}
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 2:
                            key = parts[0].rstrip(":")
                            # Values are in kB
                            meminfo[key] = int(parts[1])

                total_mb = meminfo.get("MemTotal", 0) / 1024
                available_mb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1024
                used_mb = total_mb - available_mb
                percent = (used_mb / total_mb) * 100 if total_mb > 0 else 0

                return ResourceUsage(
                    total=total_mb,
                    used=used_mb,
                    available=available_mb,
                    percent_used=percent,
                    unit="MB",
                )
        except Exception:
            return None

        return None

    def _get_host_cpu_usage(self) -> Optional[ResourceUsage]:
        """Get host CPU info (core count and load)."""
        try:
            cpu_count = os.cpu_count() or 1

            # Get load average
            load_avg = os.getloadavg()  # 1, 5, 15 minute averages
            current_load = load_avg[0]  # 1-minute average

            # Calculate usage as percentage of total cores
            percent = (current_load / cpu_count) * 100

            return ResourceUsage(
                total=float(cpu_count),
                used=current_load,
                available=float(cpu_count) - current_load,
                percent_used=min(percent, 100),  # Cap at 100%
                unit="cores",
            )
        except Exception:
            return None

    def get_vm_resources(self, name: str) -> ResourceInfo:
        """Get resource usage inside a container machine/VM.

        Runs commands inside the VM to get actual usage (not just allocation).

        Args:
            name: Machine name

        Returns:
            ResourceInfo with disk, memory, and CPU usage inside the machine
        """
        warnings: List[str] = []
        timestamp = datetime.now(timezone.utc).isoformat()

        machine = self.get_machine(name)
        if not machine or not machine.running:
            return ResourceInfo(
                source=f"machine:{name}",
                timestamp=timestamp,
                healthy=False,
                warnings=[f"Machine '{name}' is not running"],
            )

        # Get disk usage inside VM
        disk = self._get_vm_disk_usage(name, machine)
        if disk and disk.is_critical:
            warnings.append(f"VM disk critically low: {disk.available:.1f}{disk.unit} available ({disk.percent_used:.1f}% used)")
        elif disk and disk.is_warning:
            warnings.append(f"VM disk warning: {disk.available:.1f}{disk.unit} available ({disk.percent_used:.1f}% used)")

        # Get memory usage inside VM
        memory = self._get_vm_memory_usage(name, machine)
        if memory and memory.is_critical:
            warnings.append(f"VM memory critically low: {memory.available:.0f}{memory.unit} available ({memory.percent_used:.1f}% used)")
        elif memory and memory.is_warning:
            warnings.append(f"VM memory warning: {memory.available:.0f}{memory.unit} available ({memory.percent_used:.1f}% used)")

        # CPU allocation (not actual usage)
        cpu = None
        if machine.cpus:
            cpu = ResourceUsage(
                total=float(machine.cpus),
                used=0,  # We can't easily get VM CPU usage
                available=float(machine.cpus),
                percent_used=0,
                unit="cores",
            )

        healthy = not any("critically" in w for w in warnings)

        return ResourceInfo(
            source=f"machine:{name}",
            disk=disk,
            memory=memory,
            cpu=cpu,
            timestamp=timestamp,
            healthy=healthy,
            warnings=warnings,
        )

    def _get_vm_disk_usage(self, name: str, machine: MachineInfo) -> Optional[ResourceUsage]:
        """Get disk usage inside a VM by running df command."""
        try:
            # Run df inside the VM via podman machine ssh
            result = subprocess.run(
                ["podman", "machine", "ssh", name, "df", "-B1", "/"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                # Fallback to allocated disk size
                if machine.disk_gb:
                    return ResourceUsage(
                        total=float(machine.disk_gb),
                        used=0,
                        available=float(machine.disk_gb),
                        percent_used=0,
                        unit="GB",
                    )
                return None

            # Parse df output
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                # Skip header, parse data line
                parts = lines[1].split()
                if len(parts) >= 4:
                    total_bytes = int(parts[1])
                    used_bytes = int(parts[2])
                    available_bytes = int(parts[3])

                    total_gb = total_bytes / (1024 ** 3)
                    used_gb = used_bytes / (1024 ** 3)
                    available_gb = available_bytes / (1024 ** 3)
                    percent = (used_bytes / total_bytes) * 100 if total_bytes > 0 else 0

                    return ResourceUsage(
                        total=total_gb,
                        used=used_gb,
                        available=available_gb,
                        percent_used=percent,
                        unit="GB",
                    )
        except Exception:
            pass

        return None

    def _get_vm_memory_usage(self, name: str, machine: MachineInfo) -> Optional[ResourceUsage]:
        """Get memory usage inside a VM by reading /proc/meminfo."""
        try:
            # Run cat /proc/meminfo inside the VM
            result = subprocess.run(
                ["podman", "machine", "ssh", name, "cat", "/proc/meminfo"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                # Fallback to allocated memory
                if machine.memory_mb:
                    return ResourceUsage(
                        total=float(machine.memory_mb),
                        used=0,
                        available=float(machine.memory_mb),
                        percent_used=0,
                        unit="MB",
                    )
                return None

            # Parse /proc/meminfo
            meminfo: Dict[str, int] = {}
            for line in result.stdout.split("\n"):
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    meminfo[key] = int(parts[1])  # Values in kB

            total_mb = meminfo.get("MemTotal", 0) / 1024
            available_mb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1024
            used_mb = total_mb - available_mb
            percent = (used_mb / total_mb) * 100 if total_mb > 0 else 0

            return ResourceUsage(
                total=total_mb,
                used=used_mb,
                available=available_mb,
                percent_used=percent,
                unit="MB",
            )
        except Exception:
            pass

        return None

    def get_all_resources(self) -> List[ResourceInfo]:
        """Get resource usage for host and all running machines.

        Returns:
            List of ResourceInfo for host and each running machine
        """
        results: List[ResourceInfo] = []

        # Always include host
        results.append(self.get_host_resources())

        # Add all running machines
        for machine in self.list_machines():
            if machine.running:
                results.append(self.get_vm_resources(machine.name))

        return results

    def check_resource_health(
        self,
        min_disk_gb: float = 5.0,
        min_memory_mb: float = 1024.0,
    ) -> Tuple[bool, List[str]]:
        """Check if resources meet minimum requirements.

        Checks both host and all running machines for sufficient resources.

        Args:
            min_disk_gb: Minimum free disk space in GB
            min_memory_mb: Minimum free memory in MB

        Returns:
            Tuple of (healthy: bool, warnings: List[str])
        """
        result = self.check_resource_health_detailed(min_disk_gb, min_memory_mb)
        return result.healthy, result.warnings

    def check_resource_health_detailed(
        self,
        min_disk_gb: float = 5.0,
        min_memory_mb: float = 1024.0,
    ) -> ResourceHealthResult:
        """Check if resources meet minimum requirements with detailed breakdown.

        Checks both host and all running machines for sufficient resources,
        returning separate health status for host vs VM resources.

        Args:
            min_disk_gb: Minimum free disk space in GB
            min_memory_mb: Minimum free memory in MB

        Returns:
            ResourceHealthResult with detailed health info for host and VMs
        """
        result = ResourceHealthResult()

        for resource_info in self.get_all_resources():
            is_host = resource_info.source == "host"
            source_warnings: List[str] = []
            source_healthy = True

            # Check disk
            if resource_info.disk:
                available_gb = resource_info.disk.available
                if resource_info.disk.unit == "MB":
                    available_gb = resource_info.disk.available / 1024

                if is_host:
                    result.host_disk_available_gb = available_gb

                if available_gb < min_disk_gb:
                    source_warnings.append(
                        f"{resource_info.source}: Disk space low - {available_gb:.1f}GB available (need {min_disk_gb}GB)"
                    )
                    source_healthy = False

            # Check memory
            if resource_info.memory:
                available_mb = resource_info.memory.available
                if resource_info.memory.unit == "GB":
                    available_mb = resource_info.memory.available * 1024

                if is_host:
                    result.host_memory_available_mb = available_mb

                if available_mb < min_memory_mb:
                    source_warnings.append(
                        f"{resource_info.source}: Memory low - {available_mb:.0f}MB available (need {min_memory_mb:.0f}MB)"
                    )
                    source_healthy = False

            # Include any warnings from the resource check itself
            source_warnings.extend(resource_info.warnings)

            # Update result based on source
            if is_host:
                result.host_healthy = source_healthy
                result.host_warnings.extend(source_warnings)
            else:
                if not source_healthy:
                    result.vm_healthy = False
                result.vm_warnings.extend(source_warnings)

            result.warnings.extend(source_warnings)

        result.healthy = result.host_healthy and result.vm_healthy
        return result

    def mitigate_resources(
        self,
        dry_run: bool = False,
        prune_containers: bool = True,
        prune_images: bool = True,
        prune_volumes: bool = False,
        prune_cache: bool = True,
        prune_networks: bool = False,
        prune_pods: bool = False,
        prune_logs: bool = False,
        aggressive: bool = False,
    ) -> CleanupResult:
        """Attempt to free up VM resources by cleaning unused items.

        This cleans resources INSIDE the Podman VM, not on the host.
        For host cleanup, use mitigate_host_resources().

        This is a SAFE cleanup operation that only removes:
        - Stopped/exited containers (not running ones)
        - Dangling/unused images (not images used by running containers)
        - Build cache
        - Optionally: unused volumes (off by default as may contain data)
        - Optionally: unused networks
        - Optionally: stopped pods
        - Optionally: container logs

        Args:
            dry_run: If True, only report what would be cleaned without doing it
            prune_containers: Remove stopped containers
            prune_images: Remove dangling images
            prune_volumes: Remove unused volumes (USE WITH CAUTION)
            prune_cache: Clear build cache
            prune_networks: Remove unused networks
            prune_pods: Remove stopped pods
            prune_logs: Clear container logs
            aggressive: Enable ALL cleanup options (including volumes)

        Returns:
            CleanupResult with details of what was (or would be) removed
        """
        # Aggressive mode enables all options
        if aggressive:
            prune_containers = True
            prune_images = True
            prune_volumes = True
            prune_cache = True
            prune_networks = True
            prune_pods = True
            prune_logs = True

        result = CleanupResult(source="vm", dry_run=dry_run)
        details: Dict[str, Any] = {
            "containers": [],
            "images": [],
            "volumes": [],
            "networks": [],
            "pods": [],
            "logs": [],
        }

        # Helper to run podman and get stdout
        def run_podman(args: List[str]) -> str:
            proc = self._run_podman(args, check=False)
            return proc.stdout or ""

        # Step 1: Find and optionally remove stopped containers
        if prune_containers:
            try:
                # List all stopped containers
                stopped = run_podman([
                    "ps", "-a", "--filter", "status=exited",
                    "--filter", "status=created",
                    "--filter", "status=dead",
                    "--format", "{{.ID}}|{{.Names}}|{{.Size}}"
                ])

                stopped_containers = []
                for line in stopped.strip().split("\n"):
                    if line:
                        parts = line.split("|")
                        if len(parts) >= 2:
                            stopped_containers.append({
                                "id": parts[0],
                                "name": parts[1],
                                "size": parts[2] if len(parts) > 2 else "unknown"
                            })

                details["containers"] = stopped_containers

                if not dry_run and stopped_containers:
                    # Remove stopped containers
                    container_ids = [c["id"] for c in stopped_containers]
                    run_podman(["rm", "-f"] + container_ids)
                    result.containers_removed = len(stopped_containers)
                else:
                    result.containers_removed = len(stopped_containers)

            except Exception as e:
                result.errors.append(f"Container cleanup error: {str(e)}")

        # Step 2: Find and optionally remove dangling images
        if prune_images:
            try:
                # List dangling images (no tag)
                dangling = run_podman([
                    "images", "-f", "dangling=true",
                    "--format", "{{.ID}}|{{.Repository}}|{{.Size}}"
                ])

                dangling_images = []
                for line in dangling.strip().split("\n"):
                    if line:
                        parts = line.split("|")
                        if len(parts) >= 1:
                            dangling_images.append({
                                "id": parts[0],
                                "repo": parts[1] if len(parts) > 1 else "<none>",
                                "size": parts[2] if len(parts) > 2 else "unknown"
                            })

                # Also list unused images (not referenced by any container)
                # Get images used by running containers
                used_images_output = run_podman([
                    "ps", "-a", "--format", "{{.Image}}"
                ])
                used_images = set(used_images_output.strip().split("\n")) if used_images_output.strip() else set()

                # Get all images
                all_images_output = run_podman([
                    "images", "--format", "{{.ID}}|{{.Repository}}:{{.Tag}}|{{.Size}}"
                ])

                unused_images = []
                for line in all_images_output.strip().split("\n"):
                    if line:
                        parts = line.split("|")
                        if len(parts) >= 2:
                            image_ref = parts[1]
                            if image_ref not in used_images and parts[0] not in [d["id"] for d in dangling_images]:
                                # Check if it's a base/builder image we should keep
                                if not self._is_protected_image(image_ref):
                                    unused_images.append({
                                        "id": parts[0],
                                        "name": image_ref,
                                        "size": parts[2] if len(parts) > 2 else "unknown"
                                    })

                all_to_remove = dangling_images + unused_images
                details["images"] = all_to_remove

                if not dry_run and all_to_remove:
                    # Remove images (dangling first, then unused)
                    image_ids = [i["id"] for i in all_to_remove]
                    try:
                        self._run_podman(["rmi", "-f"] + image_ids)
                    except ExecutorError:
                        # Some images might still be in use, try one by one
                        for img_id in image_ids:
                            try:
                                self._run_podman(["rmi", "-f", img_id])
                                result.images_removed += 1
                            except ExecutorError:
                                pass  # Skip images that can't be removed
                    else:
                        result.images_removed = len(all_to_remove)
                else:
                    result.images_removed = len(all_to_remove)

            except Exception as e:
                result.errors.append(f"Image cleanup error: {str(e)}")

        # Step 3: Optionally remove unused volumes (dangerous!)
        if prune_volumes:
            try:
                # List dangling volumes (not used by any container)
                dangling_vols = run_podman([
                    "volume", "ls", "-f", "dangling=true",
                    "--format", "{{.Name}}"
                ])

                volume_list = [v for v in dangling_vols.strip().split("\n") if v]
                details["volumes"] = volume_list

                if not dry_run and volume_list:
                    run_podman(["volume", "rm"] + volume_list)
                    result.volumes_removed = len(volume_list)
                else:
                    result.volumes_removed = len(volume_list)

            except Exception as e:
                result.errors.append(f"Volume cleanup error: {str(e)}")

        # Step 4: Optionally remove unused networks
        if prune_networks:
            try:
                # List networks - we'll keep default ones
                all_networks = run_podman([
                    "network", "ls", "--format", "{{.Name}}"
                ])

                # Protected networks that should never be removed
                protected_networks = {"podman", "host", "bridge", "none"}

                # Get networks in use by running containers
                used_networks_output = run_podman([
                    "ps", "--format", "{{.Networks}}"
                ])
                used_networks = set()
                for line in used_networks_output.strip().split("\n"):
                    if line:
                        # Networks can be comma-separated
                        used_networks.update(n.strip() for n in line.split(","))

                # Find unused networks to remove
                unused_networks = []
                for network in all_networks.strip().split("\n"):
                    network = network.strip()
                    if network and network not in protected_networks and network not in used_networks:
                        unused_networks.append(network)

                details["networks"] = unused_networks

                if not dry_run and unused_networks:
                    for network in unused_networks:
                        try:
                            run_podman(["network", "rm", network])
                            result.networks_removed += 1
                        except Exception:
                            pass  # Skip networks that can't be removed
                else:
                    result.networks_removed = len(unused_networks)

            except Exception as e:
                result.errors.append(f"Network cleanup error: {str(e)}")

        # Step 5: Optionally remove stopped pods
        if prune_pods:
            try:
                # List pods that are not running
                stopped_pods = run_podman([
                    "pod", "ps", "-f", "status=exited",
                    "-f", "status=created",
                    "-f", "status=stopped",
                    "-f", "status=dead",
                    "--format", "{{.Name}}"
                ])

                pod_list = [p for p in stopped_pods.strip().split("\n") if p]
                details["pods"] = pod_list

                if not dry_run and pod_list:
                    for pod in pod_list:
                        try:
                            run_podman(["pod", "rm", "-f", pod])
                            result.pods_removed += 1
                        except Exception:
                            pass  # Skip pods that can't be removed
                else:
                    result.pods_removed = len(pod_list)

            except Exception as e:
                result.errors.append(f"Pod cleanup error: {str(e)}")

        # Step 6: Optionally clear container logs
        if prune_logs:
            try:
                # Get all containers (running and stopped)
                all_containers = run_podman([
                    "ps", "-a", "--format", "{{.ID}}|{{.Names}}"
                ])

                logs_found = []
                for line in all_containers.strip().split("\n"):
                    if line:
                        parts = line.split("|")
                        if len(parts) >= 1:
                            container_id = parts[0]
                            container_name = parts[1] if len(parts) > 1 else container_id

                            # Get log file path and size before clearing
                            # For podman, logs are typically in:
                            # ~/.local/share/containers/storage/overlay-containers/<id>/userdata/ctr.log
                            # But we can use 'podman logs --since 0s' with truncation isn't directly supported
                            # Instead, we'll note the containers for log rotation
                            logs_found.append({
                                "id": container_id,
                                "name": container_name,
                            })

                details["logs"] = logs_found

                if not dry_run and logs_found:
                    # Podman doesn't have a direct "clear logs" command
                    # The safest approach is to note this limitation
                    # For actual cleanup, container logs are at:
                    # $HOME/.local/share/containers/storage/overlay-containers/*/userdata/ctr.log
                    # We can truncate these files, but it requires knowing the storage path
                    storage_root = None
                    try:
                        info_output = run_podman(["info", "--format", "{{.Store.GraphRoot}}"])
                        storage_root = info_output.strip()
                    except Exception:
                        pass

                    if storage_root:
                        import os
                        import glob

                        # Find and truncate container log files
                        overlay_path = storage_root.replace("/storage", "/storage/overlay-containers/*/userdata/ctr.log")
                        log_files = glob.glob(overlay_path)

                        for log_file in log_files:
                            try:
                                # Truncate the log file
                                with open(log_file, 'w') as f:
                                    f.truncate(0)
                                result.logs_truncated += 1
                            except (PermissionError, FileNotFoundError):
                                pass  # Skip files we can't access
                    else:
                        result.errors.append("Could not determine container storage path for log cleanup")
                else:
                    result.logs_truncated = len(logs_found)

            except Exception as e:
                result.errors.append(f"Log cleanup error: {str(e)}")

        # Step 7: Clear build cache
        if prune_cache:
            try:
                if not dry_run:
                    # Use system prune for build cache (but not containers/images/volumes)
                    self._run_podman(["system", "prune", "-f", "--filter", "until=24h"], check=False)
                result.cache_cleared = True
            except Exception as e:
                result.errors.append(f"Cache cleanup error: {str(e)}")

        # Estimate space reclaimed (rough calculation from size strings)
        try:
            result.space_reclaimed_mb = self._estimate_reclaimed_space(details)
        except Exception:
            pass  # Non-critical if estimation fails

        result.details = details
        return result

    def _is_protected_image(self, image_ref: str) -> bool:
        """Check if an image should be protected from cleanup.

        Protects commonly used base images and any with 'latest' tag
        that might be actively pulled.
        """
        protected_prefixes = [
            "docker.io/library/",
            "docker.io/postgres",
            "docker.io/redis",
            "docker.io/nginx",
            "docker.io/python",
            "docker.io/node",
            "gcr.io/",
            "ghcr.io/",
        ]

        # Keep images tagged as 'latest' or with specific version tags
        if ":latest" in image_ref:
            return True

        # Keep base images from common registries
        for prefix in protected_prefixes:
            if image_ref.startswith(prefix):
                return True

        return False

    def _estimate_reclaimed_space(self, details: Dict[str, Any]) -> float:
        """Estimate space reclaimed in MB from cleanup details."""
        total_mb = 0.0

        def parse_size(size_str: str) -> float:
            """Parse size string like '100MB', '1.5GB' to MB."""
            if not size_str or size_str == "unknown":
                return 0.0
            size_str = size_str.upper().strip()
            try:
                if "GB" in size_str:
                    return float(size_str.replace("GB", "").strip()) * 1024
                elif "MB" in size_str:
                    return float(size_str.replace("MB", "").strip())
                elif "KB" in size_str:
                    return float(size_str.replace("KB", "").strip()) / 1024
                elif "B" in size_str:
                    return float(size_str.replace("B", "").strip()) / (1024 * 1024)
            except ValueError:
                pass
            return 0.0

        for container in details.get("containers", []):
            total_mb += parse_size(container.get("size", ""))

        for image in details.get("images", []):
            total_mb += parse_size(image.get("size", ""))

        return total_mb

    def mitigate_host_resources(
        self,
        dry_run: bool = False,
        clean_container_cache: bool = True,
        clean_tmp_files: bool = True,
        aggressive: bool = False,
    ) -> CleanupResult:
        """Attempt to free up HOST disk space by cleaning Podman-related caches.

        Unlike mitigate_resources() which cleans inside the VM, this method
        cleans files on the HOST filesystem that Podman uses, such as:
        - Container storage cache (~/.local/share/containers/cache/)
        - Temporary files from image pulls
        - Old machine disk images (if aggressive)

        This is useful when the host disk is low but the VM has sufficient space.

        Note: This is limited in what it can clean safely. For significant space
        recovery, users may need to manually clean other disk space.

        Args:
            dry_run: If True, only report what would be cleaned without doing it
            clean_container_cache: Clean container storage cache directories
            clean_tmp_files: Clean temporary files from image operations
            aggressive: Enable deeper cleanup (machine disk images, blob cache)

        Returns:
            CleanupResult with details of what was (or would be) removed
        """
        import glob

        result = CleanupResult(source="host", dry_run=dry_run)
        details: Dict[str, Any] = {
            "cache_dirs": [],
            "tmp_files": [],
            "blob_cache": [],
        }
        total_freed_bytes = 0

        # Determine storage paths based on platform
        system = platform.system()
        if system == "Darwin":
            # macOS paths
            container_storage_base = os.path.expanduser("~/.local/share/containers")
            podman_cache_base = os.path.expanduser("~/Library/Caches/containers")
            tmp_base = "/tmp"
        else:
            # Linux paths
            container_storage_base = os.path.expanduser("~/.local/share/containers")
            podman_cache_base = os.path.expanduser("~/.cache/containers")
            tmp_base = "/tmp"

        # Step 1: Clean container storage cache
        if clean_container_cache:
            cache_paths = [
                os.path.join(container_storage_base, "cache"),
                podman_cache_base,
            ]

            for cache_path in cache_paths:
                if os.path.exists(cache_path) and os.path.isdir(cache_path):
                    try:
                        # Calculate size before deletion
                        size_bytes = self._get_dir_size(cache_path)
                        details["cache_dirs"].append({
                            "path": cache_path,
                            "size_mb": size_bytes / (1024 * 1024),
                        })

                        if not dry_run:
                            shutil.rmtree(cache_path, ignore_errors=True)
                            # Recreate the directory
                            os.makedirs(cache_path, exist_ok=True)
                            total_freed_bytes += size_bytes
                    except (PermissionError, OSError) as e:
                        result.errors.append(f"Cannot clean {cache_path}: {e}")

        # Step 2: Clean temporary files from image operations
        if clean_tmp_files:
            tmp_patterns = [
                os.path.join(tmp_base, "podman-*"),
                os.path.join(tmp_base, "containers-*"),
                os.path.join(tmp_base, "buildah*"),
            ]

            for pattern in tmp_patterns:
                for tmp_path in glob.glob(pattern):
                    try:
                        if os.path.isdir(tmp_path):
                            size_bytes = self._get_dir_size(tmp_path)
                            details["tmp_files"].append({
                                "path": tmp_path,
                                "size_mb": size_bytes / (1024 * 1024),
                            })

                            if not dry_run:
                                shutil.rmtree(tmp_path, ignore_errors=True)
                                total_freed_bytes += size_bytes
                        elif os.path.isfile(tmp_path):
                            size_bytes = os.path.getsize(tmp_path)
                            details["tmp_files"].append({
                                "path": tmp_path,
                                "size_mb": size_bytes / (1024 * 1024),
                            })

                            if not dry_run:
                                os.remove(tmp_path)
                                total_freed_bytes += size_bytes
                    except (PermissionError, OSError) as e:
                        result.errors.append(f"Cannot clean {tmp_path}: {e}")

        # Step 3: Clean blob cache (aggressive mode only)
        if aggressive:
            blob_cache_paths = [
                os.path.join(container_storage_base, "storage", "overlay-images"),
                os.path.join(container_storage_base, "storage", "overlay-layers"),
            ]

            for blob_path in blob_cache_paths:
                if os.path.exists(blob_path) and os.path.isdir(blob_path):
                    # Only clean items older than 7 days to be safe
                    try:
                        import time
                        cutoff_time = time.time() - (7 * 24 * 60 * 60)  # 7 days

                        for item in os.listdir(blob_path):
                            item_path = os.path.join(blob_path, item)
                            try:
                                mtime = os.path.getmtime(item_path)
                                if mtime < cutoff_time:
                                    if os.path.isdir(item_path):
                                        size_bytes = self._get_dir_size(item_path)
                                    else:
                                        size_bytes = os.path.getsize(item_path)

                                    details["blob_cache"].append({
                                        "path": item_path,
                                        "size_mb": size_bytes / (1024 * 1024),
                                        "age_days": (time.time() - mtime) / (24 * 60 * 60),
                                    })

                                    # Note: We don't actually delete blob cache in aggressive mode
                                    # because it can break running containers. Just report.
                                    # Users can manually clean if needed.
                            except (PermissionError, OSError):
                                pass
                    except Exception as e:
                        result.errors.append(f"Error scanning blob cache: {e}")

        result.host_space_reclaimed_mb = total_freed_bytes / (1024 * 1024)
        result.space_reclaimed_mb = result.host_space_reclaimed_mb
        result.cache_cleared = clean_container_cache or clean_tmp_files
        result.details = details

        return result

    def _get_dir_size(self, path: str) -> int:
        """Calculate total size of a directory in bytes."""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(filepath)
                    except (OSError, FileNotFoundError):
                        pass
        except (OSError, PermissionError):
            pass
        return total_size
