"""Tests for executor implementations."""

import pytest
from typing import Any, Dict, List

from amprealize.executors.base import (
    ContainerRunConfig,
    ContainerInfo,
    MachineInfo,
)


class TestContainerRunConfig:
    """Tests for ContainerRunConfig dataclass."""

    def test_minimal_config(self):
        """ContainerRunConfig can be created with minimal fields."""
        config = ContainerRunConfig(
            image="postgres:16",
            name="test-postgres",
        )
        assert config.image == "postgres:16"
        assert config.name == "test-postgres"
        assert config.ports == []
        assert config.environment == {}
        assert config.volumes == []
        assert config.command is None
        assert config.detach is True

    def test_full_config(self):
        """ContainerRunConfig can be created with all fields."""
        config = ContainerRunConfig(
            image="postgres:16-alpine",
            name="my-postgres",
            ports=["5432:5432", "5433:5433"],
            environment={"POSTGRES_PASSWORD": "secret", "POSTGRES_DB": "testdb"},
            volumes=["/data:/var/lib/postgresql/data"],
            command=["postgres", "-c", "shared_buffers=256MB"],
            detach=False,
        )
        assert config.image == "postgres:16-alpine"
        assert len(config.ports) == 2
        assert config.environment["POSTGRES_PASSWORD"] == "secret"
        assert len(config.volumes) == 1
        assert config.command == ["postgres", "-c", "shared_buffers=256MB"]
        assert config.detach is False


class TestContainerInfo:
    """Tests for ContainerInfo dataclass."""

    def test_minimal_info(self):
        """ContainerInfo can be created with minimal fields."""
        info = ContainerInfo(
            container_id="abc123",
            name="test-container",
            status="running",
            image="postgres:16",
        )
        assert info.container_id == "abc123"
        assert info.name == "test-container"
        assert info.status == "running"
        assert info.image == "postgres:16"
        assert info.created is None
        assert info.ports == {}

    def test_full_info(self):
        """ContainerInfo can be created with all fields."""
        info = ContainerInfo(
            container_id="abc123def456",
            name="prod-postgres",
            status="running",
            image="postgres:16-alpine",
            created="2025-11-25T10:00:00Z",
            ports={"5432/tcp": "5432"},
        )
        assert info.container_id == "abc123def456"
        assert info.created == "2025-11-25T10:00:00Z"
        assert info.ports["5432/tcp"] == "5432"


class TestMachineInfo:
    """Tests for MachineInfo dataclass."""

    def test_minimal_info(self):
        """MachineInfo can be created with minimal fields."""
        info = MachineInfo(
            name="default",
            running=True,
        )
        assert info.name == "default"
        assert info.running is True
        assert info.cpus is None
        assert info.memory_mb is None
        assert info.disk_gb is None

    def test_full_info(self):
        """MachineInfo can be created with all fields."""
        info = MachineInfo(
            name="guideai-dev",
            running=True,
            cpus=4,
            memory_mb=8192,
            disk_gb=100,
        )
        assert info.name == "guideai-dev"
        assert info.cpus == 4
        assert info.memory_mb == 8192
        assert info.disk_gb == 100


class TestMockExecutor:
    """Tests for the mock executor (from conftest)."""

    def test_run_container(self, mock_executor):
        """Mock executor can run containers."""
        config = ContainerRunConfig(
            image="postgres:16",
            name="test-postgres",
            ports=["5432:5432"],
        )

        container_id = mock_executor.run_container(config)

        assert container_id.startswith("mock-container-")
        assert config in mock_executor.run_calls
        assert container_id in mock_executor.containers

    def test_stop_container(self, mock_executor):
        """Mock executor can stop containers."""
        config = ContainerRunConfig(image="postgres:16", name="test")
        container_id = mock_executor.run_container(config)

        result = mock_executor.stop_container(container_id)

        assert result is True
        assert container_id in mock_executor.stop_calls
        assert mock_executor.containers[container_id].status == "stopped"

    def test_remove_container(self, mock_executor):
        """Mock executor can remove containers."""
        config = ContainerRunConfig(image="postgres:16", name="test")
        container_id = mock_executor.run_container(config)

        result = mock_executor.remove_container(container_id)

        assert result is True
        assert container_id in mock_executor.remove_calls
        assert container_id not in mock_executor.containers

    def test_list_containers(self, mock_executor):
        """Mock executor can list containers."""
        # Run a few containers
        for i in range(3):
            config = ContainerRunConfig(image="postgres:16", name=f"test-{i}")
            mock_executor.run_container(config)

        # Stop one
        containers = list(mock_executor.containers.keys())
        mock_executor.stop_container(containers[0])

        # List running only
        running = mock_executor.list_containers(all_containers=False)
        assert len(running) == 2

        # List all
        all_containers = mock_executor.list_containers(all_containers=True)
        assert len(all_containers) == 3

    def test_get_container_stats(self, mock_executor):
        """Mock executor returns container stats."""
        config = ContainerRunConfig(image="postgres:16", name="test")
        container_id = mock_executor.run_container(config)

        stats = mock_executor.get_container_stats(container_id)

        assert "cpu_percent" in stats
        assert "memory_usage_mb" in stats
        assert "net_input_bytes" in stats

    def test_exec_in_container(self, mock_executor):
        """Mock executor can execute commands."""
        config = ContainerRunConfig(image="postgres:16", name="test")
        container_id = mock_executor.run_container(config)

        exit_code, stdout, stderr = mock_executor.exec_in_container(
            container_id, ["echo", "hello"]
        )

        assert exit_code == 0
        assert "mock output" in stdout

    def test_get_container_logs(self, mock_executor):
        """Mock executor returns logs."""
        config = ContainerRunConfig(image="postgres:16", name="test")
        container_id = mock_executor.run_container(config)

        logs = mock_executor.get_container_logs(container_id)

        assert container_id in logs

    def test_get_machine_info(self, mock_executor):
        """Mock executor returns machine info."""
        info = mock_executor.get_machine_info()

        assert info.name == "test-machine"
        assert info.running is True
        assert info.cpus == 4
        assert info.memory_mb == 8192

    def test_ensure_machine_running(self, mock_executor):
        """Mock executor can ensure machine is running."""
        result = mock_executor.ensure_machine_running()

        assert result is True
        assert mock_executor._machine_info.running is True


class TestPodmanExecutorNativeProcessMethods:
    """Tests for PodmanExecutor native process cleanup methods."""

    def test_find_native_process_on_port_returns_none_for_free_port(self, mocker):
        """find_native_process_on_port returns None when port is free."""
        from amprealize.executors.podman import PodmanExecutor

        executor = PodmanExecutor()

        # Mock lsof to return nothing (port free)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=1, stdout="")

        result = executor.find_native_process_on_port(8000)

        assert result is None

    def test_find_native_process_on_port_returns_process_info(self, mocker):
        """find_native_process_on_port returns process info when port is in use."""
        from amprealize.executors.podman import PodmanExecutor
        import shutil

        executor = PodmanExecutor()

        # Mock shutil.which to find lsof
        mocker.patch.object(shutil, "which", return_value="/usr/bin/lsof")

        # Mock subprocess.run for lsof and ps
        def mock_subprocess_run(cmd, **kwargs):
            result = mocker.Mock()
            if "lsof" in cmd:
                result.returncode = 0
                result.stdout = "12345\n"
            elif "ps" in cmd:
                result.returncode = 0
                result.stdout = "  PID USER     COMM\n12345 nick     python3.12\n"
            return result

        mocker.patch("subprocess.run", side_effect=mock_subprocess_run)

        result = executor.find_native_process_on_port(8000)

        assert result is not None
        assert result["pid"] == 12345
        assert result["command"] == "python3.12"

    def test_cleanup_native_process_on_port_kills_safe_process(self, mocker):
        """cleanup_native_process_on_port kills processes matching safe commands."""
        from amprealize.executors.podman import PodmanExecutor
        import shutil
        import os

        executor = PodmanExecutor()

        # Mock shutil.which to find lsof
        mocker.patch.object(shutil, "which", return_value="/usr/bin/lsof")

        # Mock subprocess.run
        def mock_subprocess_run(cmd, **kwargs):
            result = mocker.Mock()
            if "lsof" in cmd:
                result.returncode = 0
                result.stdout = "12345\n"
            elif "ps" in cmd:
                result.returncode = 0
                result.stdout = "  PID USER     COMM\n12345 nick     python\n"
            return result

        mocker.patch("subprocess.run", side_effect=mock_subprocess_run)

        # Track kill calls
        kill_calls = []
        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == 0:  # Check if alive
                raise OSError("No such process")  # Process is gone

        mocker.patch.object(os, "kill", side_effect=mock_kill)

        result = executor.cleanup_native_process_on_port(8000)

        assert result is not None
        assert result["pid"] == 12345
        assert result.get("killed") is True
        assert len(kill_calls) >= 1
        assert kill_calls[0][0] == 12345  # Correct PID

    def test_cleanup_native_process_on_port_skips_unsafe_process(self, mocker):
        """cleanup_native_process_on_port does not kill non-matching processes."""
        from amprealize.executors.podman import PodmanExecutor
        import shutil
        import os

        executor = PodmanExecutor()

        # Mock shutil.which
        mocker.patch.object(shutil, "which", return_value="/usr/bin/lsof")

        # Mock subprocess.run - return a non-guideai process
        def mock_subprocess_run(cmd, **kwargs):
            result = mocker.Mock()
            if "lsof" in cmd:
                result.returncode = 0
                result.stdout = "99999\n"
            elif "ps" in cmd:
                result.returncode = 0
                result.stdout = "  PID USER     COMM\n99999 root     nginx\n"
            return result

        mocker.patch("subprocess.run", side_effect=mock_subprocess_run)

        # Track kill calls
        kill_calls = []
        mocker.patch.object(os, "kill", side_effect=lambda p, s: kill_calls.append((p, s)))

        result = executor.cleanup_native_process_on_port(8000)

        # Should return None (not killed) because nginx is not in safe list
        assert result is None
        assert len(kill_calls) == 0

    def test_resolve_native_port_conflicts(self, mocker):
        """resolve_native_port_conflicts handles multiple ports."""
        from amprealize.executors.podman import PodmanExecutor

        executor = PodmanExecutor()

        # Mock find_native_process_on_port to return process on port 8000 only
        def mock_find(port):
            if port == 8000:
                return {"pid": 12345, "command": "python", "user": "nick"}
            return None

        mocker.patch.object(executor, "find_native_process_on_port", side_effect=mock_find)

        # Mock cleanup to succeed
        mocker.patch.object(
            executor,
            "cleanup_native_process_on_port",
            return_value={"pid": 12345, "killed": True}
        )

        result = executor.resolve_native_port_conflicts([8000, 8001, 8002], cleanup=True)

        assert result[8000] is None  # Was cleaned up
        assert result[8001] is None  # Was free
        assert result[8002] is None  # Was free
