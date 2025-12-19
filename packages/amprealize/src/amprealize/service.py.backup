"""Amprealize Service - Infrastructure orchestration with blueprints.

This module contains the core AmprealizeService class that provides
plan/apply/destroy workflow for containerized environments.
"""

import json
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import yaml

from .executors.base import ContainerRunConfig, ExecutorError, MachineCapableExecutor, MachineInfo, ResourceCapableExecutor, ResourceHealthResult
from .executors.podman import PodmanExecutor
from .hooks import AmprealizeHooks
from .models import (
    ApplyRequest,
    ApplyResponse,
    AuditEntry,
    Blueprint,
    DestroyRequest,
    DestroyResponse,
    EnvironmentDefinition,
    EnvironmentEstimates,
    EnvironmentManifest,
    HealthCheck,
    InfrastructureConfig,
    PlanRequest,
    PlanResponse,
    RuntimeConfig,
    ServiceSpec,
    StatusEvent,
    StatusResponse,
    TelemetryData,
)


class BandwidthEnforcer:
    """Enforces network bandwidth limits during apply operations."""

    def __init__(self, limit_mbps: Optional[int] = None):
        self.limit_mbps = limit_mbps
        self._last_rx_bytes: Dict[str, int] = {}
        self._last_tx_bytes: Dict[str, int] = {}
        self._last_check_time = time.time()

    def check_usage(self, stats: Dict[str, Dict[str, Any]]) -> bool:
        """Returns True if bandwidth is within limits, False otherwise."""
        if not self.limit_mbps:
            return True

        current_time = time.time()
        elapsed = current_time - self._last_check_time
        if elapsed < 1:
            return True

        total_bytes = 0
        for cid, info in stats.items():
            rx = info.get("net_input_bytes", 0)
            tx = info.get("net_output_bytes", 0)

            if cid in self._last_rx_bytes:
                total_bytes += (rx - self._last_rx_bytes[cid])
                total_bytes += (tx - self._last_tx_bytes.get(cid, 0))

            self._last_rx_bytes[cid] = rx
            self._last_tx_bytes[cid] = tx

        self._last_check_time = current_time
        mbps = (total_bytes * 8) / (elapsed * 1_000_000)
        return mbps <= self.limit_mbps

    def get_current_usage_mbps(self, stats: Dict[str, Dict[str, Any]]) -> float:
        """Get current usage in Mbps."""
        # Simplified - actual implementation would track deltas
        return 0.0


class AmprealizeService:
    """Infrastructure-as-Code orchestration service.

    Provides Terraform-like plan/apply/destroy workflow for containerized
    development environments using blueprints.

    Example:
        from amprealize import AmprealizeService
        from amprealize.executors import PodmanExecutor

        service = AmprealizeService(executor=PodmanExecutor())

        # Plan an environment
        plan = service.plan(PlanRequest(
            blueprint_id="postgres-dev",
            environment="development"
        ))

        # Apply the plan
        result = service.apply(ApplyRequest(plan_id=plan.plan_id))

        # Clean up
        service.destroy(DestroyRequest(amp_run_id=result.amp_run_id, reason="Done"))

    Args:
        executor: Container executor (defaults to PodmanExecutor)
        hooks: Optional hooks for external integrations
        base_dir: Base directory for storage (defaults to ~/.guideai/amprealize)
    """

    def __init__(
        self,
        executor: Optional[MachineCapableExecutor] = None,
        hooks: Optional[AmprealizeHooks] = None,
        base_dir: Optional[Path] = None,
    ):
        self.executor = executor or PodmanExecutor()
        self.hooks = hooks or AmprealizeHooks()

        # Initialize storage paths
        self.base_dir = base_dir or Path.home() / ".guideai" / "amprealize"
        self.manifests_dir = self.base_dir / "manifests"
        self.environments_dir = self.base_dir / "environments"
        self.user_blueprints_dir = self.base_dir / "blueprints"

        # Package blueprints directory
        self.pkg_blueprints_dir = Path(__file__).parent / "blueprints"

        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        self.environments_dir.mkdir(parents=True, exist_ok=True)
        self.user_blueprints_dir.mkdir(parents=True, exist_ok=True)

        self.environments: Dict[str, EnvironmentDefinition] = {}
        self.environment_manifest_path: Optional[Path] = None

        # Load environments from file if available
        self.load_environments()

        # Register default environments if none loaded
        if not self.environments:
            self.register_environment(
                EnvironmentDefinition(name="development", description="Local development environment")
            )
            self.register_environment(
                EnvironmentDefinition(name="staging", description="Staging environment")
            )
            self.register_environment(
                EnvironmentDefinition(
                    name="production",
                    description="Production environment",
                    default_compliance_tier="strict",
                )
            )

    # =========================================================================
    # Environment Management
    # =========================================================================

    def load_environments(self) -> None:
        """Load environment definitions from a YAML file."""
        path = self._resolve_environment_file()
        if not path or not path.exists():
            return

        self.environment_manifest_path = path

        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)

            if data and "environments" in data:
                for env_name, env_data in data["environments"].items():
                    if not isinstance(env_data, dict):
                        print(f"Warning: Environment '{env_name}' must be a mapping")
                        continue

                    env_payload = env_data.copy()
                    env_payload.setdefault("name", env_name)

                    if "compliance_tier" in env_payload and "default_compliance_tier" not in env_payload:
                        env_payload["default_compliance_tier"] = env_payload.pop("compliance_tier")
                    if "lifetime" in env_payload and "default_lifetime" not in env_payload:
                        env_payload["default_lifetime"] = env_payload.pop("lifetime")
                    if "blueprint_id" in env_payload and "infrastructure" not in env_payload:
                        env_payload["infrastructure"] = {"blueprint_id": env_payload.pop("blueprint_id")}

                    try:
                        env_def = EnvironmentDefinition(**env_payload)
                        self.register_environment(env_def)
                    except Exception as e:
                        print(f"Warning: Failed to parse environment '{env_name}': {e}")
        except Exception as e:
            print(f"Warning: Failed to load environments from {path}: {e}")

    def register_environment(self, env_def: EnvironmentDefinition) -> None:
        """Register an environment definition."""
        self.environments[env_def.name] = env_def

    def _resolve_environment_file(self) -> Optional[Path]:
        """Resolve the environment configuration file path."""
        override = os.environ.get("GUIDEAI_ENV_FILE") or os.environ.get("AMPREALIZE_ENV_FILE")
        candidates = []
        if override:
            candidates.append(Path(override).expanduser())

        cwd = Path.cwd()
        candidates.append(cwd / "config" / "amprealize" / "environments.yaml")
        candidates.append(cwd / "environments.yaml")

        package_root = Path(__file__).resolve().parents[2]
        candidates.append(package_root / "config" / "amprealize" / "environments.yaml")
        candidates.append(package_root / "environments.yaml")

        for candidate in candidates:
            if candidate.exists():
                return candidate

        if override:
            return Path(override).expanduser()
        return None

    def validate_environment_file(
        self, path: Optional[str | Path] = None, strict: bool = True
    ) -> Dict[str, Any]:
        """Validate an environment configuration file.

        Args:
            path: Path to environments.yaml (uses resolved path if not provided)
            strict: If True, raises errors on unknown fields (default: True)

        Returns:
            Validation result dict with:
                - valid: bool
                - path: str (resolved path)
                - environments: list of environment names
                - errors: list of error messages (if invalid)
                - warnings: list of warning messages

        Raises:
            FileNotFoundError: If the file does not exist
            ValueError: If strict=True and validation fails
        """
        from pydantic import ValidationError

        # Resolve path
        if path:
            file_path = Path(path)
        else:
            file_path = self._resolve_environment_file()

        if not file_path or not file_path.exists():
            raise FileNotFoundError(
                f"Environment file not found: {path or 'no file resolved'}"
            )

        result: Dict[str, Any] = {
            "valid": False,
            "path": str(file_path),
            "environments": [],
            "errors": [],
            "warnings": [],
        }

        try:
            # Use strict validation model
            manifest = EnvironmentManifest.validate_file(file_path)
            result["valid"] = True
            result["environments"] = manifest.list_environments()

            # Add warnings for common issues
            for env_name, env_def in manifest.environments.items():
                if env_def.runtime.provider == "podman" and not env_def.runtime.podman_machine:
                    result["warnings"].append(
                        f"Environment '{env_name}': podman provider without podman_machine set"
                    )
                if env_def.default_compliance_tier == "strict" and env_def.runtime.auto_start:
                    result["warnings"].append(
                        f"Environment '{env_name}': strict compliance with auto_start=true (consider false)"
                    )

        except ValidationError as e:
            result["errors"] = [str(err) for err in e.errors()]
            if strict:
                raise ValueError(
                    f"Environment file validation failed: {file_path}\n"
                    + "\n".join(result["errors"])
                ) from e
        except yaml.YAMLError as e:
            result["errors"] = [f"YAML parse error: {e}"]
            if strict:
                raise ValueError(f"Invalid YAML in {file_path}: {e}") from e
        except Exception as e:
            result["errors"] = [str(e)]
            if strict:
                raise

        return result

    # =========================================================================
    # Blueprint Management
    # =========================================================================

    def _resolve_blueprint(self, blueprint_id: str) -> Blueprint:
        """Resolve a blueprint by ID or path."""
        # 1. Try as absolute path
        path = Path(blueprint_id)
        if path.exists() and path.is_file():
            return self._load_blueprint_from_file(path)

        # 2. Try in user blueprints dir
        for ext in [".yaml", ".yml", ".json"]:
            path = self.user_blueprints_dir / f"{blueprint_id}{ext}"
            if path.exists():
                return self._load_blueprint_from_file(path)

        # 3. Try in package blueprints dir
        for ext in [".yaml", ".yml", ".json"]:
            path = self.pkg_blueprints_dir / f"{blueprint_id}{ext}"
            if path.exists():
                return self._load_blueprint_from_file(path)

        raise ValueError(f"Blueprint '{blueprint_id}' not found")

    def _expand_env_vars(self, data: Any) -> Any:
        """Recursively expand environment variables in data structures.

        Handles ${VAR} and ${VAR:-default} syntax in strings.
        """
        if isinstance(data, str):
            # Pattern to match ${VAR} or ${VAR:-default}
            pattern = re.compile(r'\$\{([^}:]+)(?::-([^}]*))?\}')

            def replace_var(match):
                var_name = match.group(1)
                default_value = match.group(2) if match.group(2) is not None else ""
                return os.environ.get(var_name, default_value)

            return pattern.sub(replace_var, data)
        elif isinstance(data, dict):
            return {k: self._expand_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._expand_env_vars(item) for item in data]
        else:
            return data

    def _load_blueprint_from_file(self, path: Path) -> Blueprint:
        """Load a blueprint from a file, expanding environment variables."""
        with open(path, "r") as f:
            if path.suffix == ".json":
                data = json.load(f)
            else:
                data = yaml.safe_load(f)
        # Expand environment variables in the loaded data
        data = self._expand_env_vars(data)
        return Blueprint(**data)

    def _discover_packaged_blueprints(self) -> Dict[str, Path]:
        """Discover all packaged blueprints."""
        blueprints: Dict[str, Path] = {}

        if self.pkg_blueprints_dir.exists():
            for ext in ["*.yaml", "*.yml", "*.json"]:
                for path in self.pkg_blueprints_dir.glob(ext):
                    # Use stem as key (e.g., "postgres-dev" from "postgres-dev.yaml")
                    blueprints[path.stem] = path

        return blueprints

    def list_blueprints(self) -> List[Dict[str, Any]]:
        """List all available blueprints."""
        result = []

        # Packaged blueprints
        packaged = self._discover_packaged_blueprints()
        for name, path in packaged.items():
            result.append({
                "id": name,
                "path": str(path),
                "source": "package",
            })

        # User blueprints
        if self.user_blueprints_dir.exists():
            for ext in ["*.yaml", "*.yml", "*.json"]:
                for path in self.user_blueprints_dir.glob(ext):
                    result.append({
                        "id": path.stem,
                        "path": str(path),
                        "source": "user",
                    })

        return result

    def _calculate_blueprint_resources(self, blueprint: Blueprint) -> tuple[int, float, int]:
        """Calculate total resources required by a blueprint."""
        total_memory = 0
        total_cpus = 0.0
        total_bandwidth = 0
        for service in blueprint.services.values():
            if service.memory_mb:
                total_memory += service.memory_mb
            if service.cpu_cores:
                total_cpus += service.cpu_cores
            if service.bandwidth_mbps:
                total_bandwidth += service.bandwidth_mbps
        return total_memory, total_cpus, total_bandwidth

    # =========================================================================
    # Runtime Management
    # =========================================================================

    def _ensure_runtime_ready(
        self, env_def: EnvironmentDefinition, *, force: bool = False
    ) -> None:
        """Ensure the container runtime is ready and configure executor connection."""
        runtime = env_def.runtime
        if runtime.provider not in ("podman", "docker"):
            return

        if not isinstance(self.executor, MachineCapableExecutor):
            return

        machine_name = runtime.podman_machine or "podman-machine-default"

        try:
            machine = self.executor.get_machine(machine_name)
        except ExecutorError:
            if force:
                print(f"Warning: Could not check machine status", file=sys.stderr)
                return
            raise

        if not machine:
            if runtime.auto_init:
                self.executor.init_machine(
                    machine_name,
                    cpus=runtime.cpu_limit,
                    memory_mb=runtime.memory_limit_mb,
                )
                machine = self.executor.get_machine(machine_name)
            elif force:
                print(f"Warning: Machine '{machine_name}' not found", file=sys.stderr)
                return
            else:
                raise RuntimeError(
                    f"Podman machine '{machine_name}' not found. "
                    f"Enable auto_init or run 'podman machine init {machine_name}'."
                )

        if machine and not machine.running:
            if runtime.auto_start:
                self.executor.start_machine(machine_name)
            elif force:
                print(f"Warning: Machine '{machine_name}' is stopped", file=sys.stderr)
                return
            else:
                raise RuntimeError(
                    f"Podman machine '{machine_name}' is stopped. "
                    f"Start it or enable auto_start."
                )

        # Set the executor connection to use the correct machine
        # Use -root suffix for rootful machines (required for port forwarding on macOS)
        from .executors.podman import PodmanExecutor
        if isinstance(self.executor, PodmanExecutor):
            connection_name = machine_name
            try:
                inspect = self.executor.inspect_machine(machine_name)
                if inspect.get("Rootful", False):
                    connection_name = f"{machine_name}-root"
            except Exception:
                pass  # Fall back to base machine name
            self.executor.connection = connection_name

        self._verify_podman_resources(machine_name, runtime, env_def.name, force=force)

    def _verify_podman_resources(
        self,
        machine_name: str,
        runtime: RuntimeConfig,
        environment: str,
        *,
        force: bool,
    ) -> None:
        """Verify the Podman machine has sufficient resources."""
        if not isinstance(self.executor, MachineCapableExecutor):
            return

        warnings = []
        try:
            inspect = self.executor.inspect_machine(machine_name)
            config = inspect.get("Config", {})
        except Exception as exc:
            if force:
                print(f"Warning: Unable to inspect machine '{machine_name}': {exc}", file=sys.stderr)
                return
            raise

        memory_bytes = config.get("Memory")
        cpus = config.get("CPUs")

        if runtime.memory_limit_mb and isinstance(memory_bytes, int):
            allocated_mb = memory_bytes // (1024 * 1024)
            if allocated_mb < runtime.memory_limit_mb:
                warnings.append(
                    f"configured memory {allocated_mb}MB < requested {runtime.memory_limit_mb}MB"
                )

        if runtime.cpu_limit and isinstance(cpus, int) and cpus < runtime.cpu_limit:
            warnings.append(f"configured CPUs {cpus} < requested {runtime.cpu_limit}")

        if warnings:
            message = (
                f"Machine '{machine_name}' does not meet requirements for '{environment}': "
                + "; ".join(warnings)
            )
            self.hooks.emit_metric(
                "amprealize.runtime.resource_warning",
                machine=machine_name,
                environment=environment,
                warnings=warnings,
            )
            if force:
                print(f"Warning: {message}", file=sys.stderr)
            else:
                raise RuntimeError(message)
        else:
            self.hooks.emit_metric(
                "amprealize.runtime.resource_ok",
                machine=machine_name,
                environment=environment,
                memory_mb=(memory_bytes // (1024 * 1024)) if isinstance(memory_bytes, int) else None,
                cpus=cpus,
            )

    def _perform_tiered_cleanup(
        self,
        request: "ApplyRequest",
        initial_warnings: List[str],
    ) -> Tuple[bool, List[str]]:
        """Perform tiered auto-cleanup with escalating aggressiveness.

        This method now performs SEPARATE cleanup for host vs VM resources:
        - If only HOST is low: attempt host cleanup first (cache, tmp files)
        - If only VM is low: perform standard VM cleanup (podman system prune)
        - If BOTH are low: attempt both cleanups

        Cleanup tiers (for VM):
        1. Standard: containers, images, cache (no volumes)
        2. Aggressive: all options except volumes (+ networks, pods, logs)
        3. Full: include volumes (only if auto_cleanup_include_volumes=True)

        Args:
            request: The apply request with cleanup configuration
            initial_warnings: Initial resource warnings

        Returns:
            Tuple of (healthy: bool, warnings: List[str]) after cleanup attempts
        """
        from .executors.base import ResourceCapableExecutor

        if not isinstance(self.executor, ResourceCapableExecutor):
            return False, initial_warnings

        max_retries = request.auto_cleanup_max_retries
        total_space_freed_mb = 0.0
        total_host_space_freed_mb = 0.0
        current_warnings = initial_warnings

        # Get detailed health info to distinguish host vs VM issues
        detailed_health: Optional[ResourceHealthResult] = None
        if hasattr(self.executor, 'check_resource_health_detailed'):
            detailed_health = self.executor.check_resource_health_detailed(
                min_disk_gb=request.min_disk_gb,
                min_memory_mb=request.min_memory_mb,
            )
            self.hooks.emit_metric(
                "amprealize.apply.detailed_health_check",
                host_healthy=detailed_health.host_healthy,
                vm_healthy=detailed_health.vm_healthy,
                only_host_unhealthy=detailed_health.only_host_unhealthy,
                only_vm_unhealthy=detailed_health.only_vm_unhealthy,
                host_warnings=detailed_health.host_warnings,
                vm_warnings=detailed_health.vm_warnings,
            )

        # Step 1: If only HOST is unhealthy, try host cleanup first
        if detailed_health and detailed_health.only_host_unhealthy:
            self.hooks.emit_metric(
                "amprealize.apply.host_only_cleanup_triggered",
                host_warnings=detailed_health.host_warnings,
            )

            # Attempt host cleanup
            if hasattr(self.executor, 'mitigate_host_resources'):
                try:
                    host_cleanup = self.executor.mitigate_host_resources(
                        dry_run=False,
                        clean_container_cache=True,
                        clean_tmp_files=True,
                        aggressive=request.auto_cleanup_aggressive,
                    )

                    total_host_space_freed_mb += host_cleanup.host_space_reclaimed_mb

                    self.hooks.emit_metric(
                        "amprealize.apply.host_cleanup_completed",
                        space_reclaimed_mb=host_cleanup.host_space_reclaimed_mb,
                        cache_cleared=host_cleanup.cache_cleared,
                        errors=host_cleanup.errors,
                    )
                except Exception as e:
                    self.hooks.emit_metric(
                        "amprealize.apply.host_cleanup_error",
                        error=str(e),
                    )

            # Re-check detailed health
            detailed_health = self.executor.check_resource_health_detailed(
                min_disk_gb=request.min_disk_gb,
                min_memory_mb=request.min_memory_mb,
            )

            if detailed_health.host_healthy and detailed_health.vm_healthy:
                self.hooks.emit_metric(
                    "amprealize.apply.host_cleanup_success",
                    total_host_space_freed_mb=total_host_space_freed_mb,
                )
                return True, []

            # If host is STILL unhealthy after cleanup, check if we should allow override
            if not detailed_health.host_healthy:
                if request.allow_host_resource_warning:
                    self.hooks.emit_metric(
                        "amprealize.apply.host_warning_override",
                        host_warnings=detailed_health.host_warnings,
                    )
                    # Warn but continue if VM is healthy
                    if detailed_health.vm_healthy:
                        print(
                            f"Warning: Host disk space is low but proceeding with "
                            f"allow_host_resource_warning=True. Warnings:\n"
                            + "\n".join(f"  - {w}" for w in detailed_health.host_warnings),
                            file=sys.stderr,
                        )
                        return True, detailed_health.host_warnings
                else:
                    # Return failure with specific host warning
                    return False, [
                        "Host disk space is low. VM cleanup cannot help. Options:\n"
                        "  1. Free up space on your host disk manually\n"
                        "  2. Use allow_host_resource_warning=True to proceed anyway\n"
                        "  3. Use skip_resource_check=True to skip all checks"
                    ] + detailed_health.host_warnings

        # Step 2: If VM is unhealthy (either only VM or both), perform VM cleanup
        # Define cleanup tiers with escalating aggressiveness
        cleanup_tiers = [
            {
                "name": "standard",
                "prune_containers": True,
                "prune_images": True,
                "prune_volumes": False,
                "prune_cache": True,
                "prune_networks": False,
                "prune_pods": False,
                "prune_logs": False,
                "aggressive": False,
            },
            {
                "name": "aggressive",
                "prune_containers": True,
                "prune_images": True,
                "prune_volumes": False,
                "prune_cache": True,
                "prune_networks": True,
                "prune_pods": True,
                "prune_logs": True,
                "aggressive": True,
            },
        ]

        # Add full cleanup tier if volumes are allowed
        if request.auto_cleanup_include_volumes:
            cleanup_tiers.append({
                "name": "full_with_volumes",
                "prune_containers": True,
                "prune_images": True,
                "prune_volumes": True,  # ⚠️ May lose data
                "prune_cache": True,
                "prune_networks": True,
                "prune_pods": True,
                "prune_logs": True,
                "aggressive": True,
            })

        # Skip to aggressive tier if requested
        start_tier = 1 if request.auto_cleanup_aggressive else 0

        for tier_idx in range(start_tier, len(cleanup_tiers)):
            tier = cleanup_tiers[tier_idx].copy()  # Copy to avoid mutation
            tier_name = tier.pop("name")

            for attempt in range(max_retries):
                self.hooks.emit_metric(
                    "amprealize.apply.auto_cleanup_triggered",
                    tier=tier_name,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    warnings=current_warnings,
                )

                try:
                    cleanup_result = self.executor.mitigate_resources(
                        dry_run=False,
                        **tier,
                    )

                    total_space_freed_mb += cleanup_result.space_reclaimed_mb

                    self.hooks.emit_metric(
                        "amprealize.apply.auto_cleanup_completed",
                        tier=tier_name,
                        attempt=attempt + 1,
                        containers_removed=cleanup_result.containers_removed,
                        images_removed=cleanup_result.images_removed,
                        volumes_removed=cleanup_result.volumes_removed,
                        space_reclaimed_mb=cleanup_result.space_reclaimed_mb,
                        total_space_freed_mb=total_space_freed_mb,
                        success=cleanup_result.success,
                    )

                    # Re-check resources after cleanup
                    healthy, current_warnings = self.executor.check_resource_health(
                        min_disk_gb=request.min_disk_gb,
                        min_memory_mb=request.min_memory_mb,
                    )

                    if healthy:
                        self.hooks.emit_metric(
                            "amprealize.apply.auto_cleanup_success",
                            tier=tier_name,
                            attempt=attempt + 1,
                            total_space_freed_mb=total_space_freed_mb,
                        )
                        return True, current_warnings

                    # If cleanup freed less than 100MB, don't retry at this tier
                    if cleanup_result.space_reclaimed_mb < 100:
                        self.hooks.emit_metric(
                            "amprealize.apply.auto_cleanup_tier_exhausted",
                            tier=tier_name,
                            reason="insufficient_space_freed",
                            space_freed_mb=cleanup_result.space_reclaimed_mb,
                        )
                        break  # Move to next tier

                except Exception as e:
                    self.hooks.emit_metric(
                        "amprealize.apply.auto_cleanup_error",
                        tier=tier_name,
                        attempt=attempt + 1,
                        error=str(e),
                    )
                    # Continue to next attempt/tier

        # All tiers exhausted
        self.hooks.emit_metric(
            "amprealize.apply.auto_cleanup_exhausted",
            total_space_freed_mb=total_space_freed_mb,
            final_warnings=current_warnings,
        )

        return False, current_warnings

    # =========================================================================
    # Core Operations
    # =========================================================================

    def plan(self, request: PlanRequest) -> PlanResponse:
        """Create a plan for an environment deployment.

        Args:
            request: Plan request with blueprint and environment info

        Returns:
            Plan response with estimates and manifest

        Raises:
            ValueError: If environment or blueprint not found
        """
        if request.environment not in self.environments:
            raise ValueError(
                f"Environment '{request.environment}' not defined. "
                f"Available: {list(self.environments.keys())}"
            )

        env_def = self.environments[request.environment]
        self._ensure_runtime_ready(env_def, force=request.force_podman)

        # Merge variables: request overrides environment
        merged_variables = env_def.variables.copy()
        merged_variables.update(request.variables)

        # Apply defaults
        lifetime = request.lifetime or env_def.default_lifetime
        compliance_tier = request.compliance_tier or env_def.default_compliance_tier

        blueprint_id = request.blueprint_id or env_def.infrastructure.blueprint_id
        if not blueprint_id:
            raise ValueError(
                f"Environment '{env_def.name}' does not define a blueprint. "
                f"Provide blueprint_id or update the manifest."
            )

        blueprint = self._resolve_blueprint(blueprint_id)

        # Filter services by module if active_modules is set
        active_modules = request.active_modules or env_def.active_modules
        if active_modules:
            filtered_services = {}
            for name, svc in blueprint.services.items():
                if svc.module and svc.module in active_modules:
                    filtered_services[name] = svc
                elif not svc.module and "core" in active_modules:
                    filtered_services[name] = svc
            blueprint.services = filtered_services

        # Calculate resources
        req_mem, req_cpu, req_bandwidth = self._calculate_blueprint_resources(blueprint)

        plan_id = f"plan-{uuid.uuid4()}"
        amp_run_id = f"amp-{uuid.uuid4()}"

        # Generate manifest
        runtime_payload = (
            env_def.runtime.model_dump()
            if hasattr(env_def.runtime, "model_dump")
            else env_def.runtime.dict()
        )
        infra_payload = (
            env_def.infrastructure.model_dump()
            if hasattr(env_def.infrastructure, "model_dump")
            else env_def.infrastructure.dict()
        )

        manifest = {
            "blueprint": blueprint.model_dump() if hasattr(blueprint, "model_dump") else blueprint.dict(),
            "blueprint_id": blueprint_id,
            "tier": compliance_tier,
            "created_at": datetime.utcnow().isoformat(),
            "variables": merged_variables,
            "plan_id": plan_id,
            "amp_run_id": amp_run_id,
            "phase": "PLANNED",
            "environment": request.environment,
            "lifetime": lifetime,
            "checklist_id": request.checklist_id,
            "runtime": runtime_payload,
            "infrastructure": infra_payload,
            "environment_manifest": str(self.environment_manifest_path) if self.environment_manifest_path else None,
            "teardown_on_exit": env_def.infrastructure.teardown_on_exit,
        }

        # Save manifest
        manifest_path = self.manifests_dir / f"{plan_id}.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        # Record action via hooks
        self.hooks.record_action(
            "amprealize.plan",
            blueprint_id=blueprint_id,
            environment=request.environment,
            plan_id=plan_id,
            amp_run_id=amp_run_id,
        )

        # Record compliance step via hooks
        if request.checklist_id:
            self.hooks.record_compliance_step(
                "plan_created",
                checklist_id=request.checklist_id,
                plan_id=plan_id,
                blueprint_id=blueprint_id,
                manifest_path=str(manifest_path),
            )

        # Emit metric
        self.hooks.emit_metric(
            "amprealize.plan.created",
            plan_id=plan_id,
            blueprint_id=blueprint_id,
        )

        return PlanResponse(
            plan_id=plan_id,
            amp_run_id=amp_run_id,
            signed_manifest=manifest,
            environment_estimates=EnvironmentEstimates(
                cost_estimate=0.50,
                memory_footprint_mb=req_mem or env_def.runtime.memory_limit_mb or 1024,
                bandwidth_mbps=req_bandwidth,
                region="local",
                expected_boot_duration_s=60,
            ),
        )

    def apply(self, request: ApplyRequest) -> ApplyResponse:
        """Apply a plan and provision the environment.

        Args:
            request: Apply request with plan_id or manifest

        Returns:
            Apply response with environment outputs

        Raises:
            ValueError: If plan not found
            RuntimeError: If provisioning fails
        """
        plan_id = request.plan_id
        manifest = request.manifest

        if not plan_id and not manifest:
            raise ValueError("Either plan_id or manifest must be provided")

        if plan_id:
            manifest_path = self.manifests_dir / f"{plan_id}.json"
            if manifest_path.exists():
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
            elif not manifest:
                raise ValueError(f"Plan {plan_id} not found")

        assert manifest is not None  # Type narrowing

        # Configure executor for the environment's runtime
        runtime_config = manifest.get("runtime", {})
        if runtime_config.get("provider") in ("podman", "docker"):
            machine_name = runtime_config.get("podman_machine") or "podman-machine-default"
            from .executors.podman import PodmanExecutor
            if isinstance(self.executor, PodmanExecutor):
                # Use -root suffix for rootful machines (required for port forwarding on macOS)
                connection_name = machine_name
                try:
                    inspect = self.executor.inspect_machine(machine_name)
                    if inspect.get("Rootful", False):
                        connection_name = f"{machine_name}-root"
                except Exception:
                    pass  # Fall back to base machine name
                self.executor.connection = connection_name
                # Ensure the machine is running if auto_start is enabled
                if runtime_config.get("auto_start"):
                    machine = self.executor.get_machine(machine_name)
                    if machine and not machine.running:
                        self.executor.start_machine(machine_name)

        # Calculate blueprint memory requirements for smart resource checking
        blueprint_data = manifest.get("blueprint", manifest)
        services = blueprint_data.get("services", {})
        blueprint_memory_mb = 0
        for svc_spec in services.values():
            svc_mem = svc_spec.get("memory_mb")
            if svc_mem:
                blueprint_memory_mb += svc_mem

        # Use blueprint-aware memory threshold if enabled and blueprint has memory info
        min_memory_for_check = request.min_memory_mb
        if request.blueprint_aware_memory_check and blueprint_memory_mb > 0:
            # Add safety margin to blueprint estimate
            min_memory_for_check = blueprint_memory_mb + request.memory_safety_margin_mb
            self.hooks.emit_metric(
                "amprealize.apply.blueprint_memory_estimate",
                blueprint_memory_mb=blueprint_memory_mb,
                safety_margin_mb=request.memory_safety_margin_mb,
                total_required_mb=min_memory_for_check,
            )

        # Proactive cleanup: clean BEFORE checking resources (maximizes available resources)
        if request.proactive_cleanup and isinstance(self.executor, ResourceCapableExecutor):
            self.hooks.emit_metric(
                "amprealize.apply.proactive_cleanup_started",
            )
            try:
                # Run standard cleanup to free resources before we even check
                cleanup_result = self.executor.mitigate_resources(
                    dry_run=False,
                    prune_containers=True,
                    prune_images=True,
                    prune_volumes=False,  # Never proactively delete volumes
                    prune_cache=True,
                    prune_networks=True,
                    prune_pods=True,
                    prune_logs=request.auto_cleanup_aggressive,
                )
                self.hooks.emit_metric(
                    "amprealize.apply.proactive_cleanup_completed",
                    space_reclaimed_mb=cleanup_result.space_reclaimed_mb,
                    containers_removed=cleanup_result.containers_removed,
                    images_removed=cleanup_result.images_removed,
                )
            except Exception as e:
                self.hooks.emit_metric(
                    "amprealize.apply.proactive_cleanup_error",
                    error=str(e),
                )

        # Pre-flight resource health check with tiered auto-remediation
        if not request.skip_resource_check:
            if isinstance(self.executor, ResourceCapableExecutor):
                try:
                    healthy, warnings = self.executor.check_resource_health(
                        min_disk_gb=request.min_disk_gb,
                        min_memory_mb=min_memory_for_check,
                    )
                    if warnings:
                        for warning in warnings:
                            self.hooks.emit_metric(
                                "amprealize.apply.resource_warning",
                                warning=warning,
                            )
                    if not healthy:
                        # Resource shortage detected - attempt auto-remediation if enabled
                        if request.auto_cleanup:
                            healthy, warnings = self._perform_tiered_cleanup(
                                request=request,
                                initial_warnings=warnings,
                            )

                        if not healthy:
                            # Still not healthy after cleanup attempts (or auto_cleanup not enabled)
                            raise RuntimeError(
                                f"Resource shortage detected. Use skip_resource_check=True to override, "
                                f"or auto_cleanup=True to automatically free up space.\n"
                                f"Warnings:\n" + "\n".join(f"  - {w}" for w in warnings)
                            )
                except Exception as e:
                    if "Resource shortage" in str(e) or "Critical resource" in str(e):
                        raise
                    # Non-blocking: log but continue if resource check fails
                    self.hooks.emit_metric(
                        "amprealize.apply.resource_check_error",
                        error=str(e),
                    )

        amp_run_id = manifest.get("amp_run_id") or f"amp-{uuid.uuid4()}"
        checklist_id = manifest.get("checklist_id")

        # Update manifest state
        manifest["phase"] = "PROVISIONING"
        manifest["updated_at"] = datetime.utcnow().isoformat()

        # Record action
        self.hooks.record_action(
            "amprealize.apply.started",
            plan_id=plan_id,
            amp_run_id=amp_run_id,
        )

        # Emit metric
        self.hooks.emit_metric(
            "amprealize.apply.started",
            plan_id=plan_id,
            amp_run_id=amp_run_id,
        )

        # Record compliance step
        if checklist_id:
            self.hooks.record_compliance_step(
                "apply_started",
                checklist_id=checklist_id,
                plan_id=plan_id,
                amp_run_id=amp_run_id,
            )

        # Execute plan
        blueprint_data = manifest.get("blueprint", manifest)
        services = blueprint_data.get("services", {})

        outputs: Dict[str, Any] = {}

        # Collect all ports that will be used
        all_ports: List[int] = []
        for name, spec in services.items():
            for port_mapping in spec.get("ports", []):
                if isinstance(port_mapping, str) and ":" in port_mapping:
                    host_port = int(port_mapping.split(":")[0])
                    all_ports.append(host_port)
                elif isinstance(port_mapping, dict) and "host" in port_mapping:
                    all_ports.append(int(port_mapping["host"]))

        # Pre-apply cleanup: remove stale/orphaned containers and resolve port conflicts
        # Uses request options for auto-resolve behavior (enabled by default for zero-friction apply)
        should_cleanup = request.auto_resolve_stale or request.auto_resolve_conflicts
        if should_cleanup:
            try:
                cleanup_result = self.executor.prepare_for_apply(
                    ports=all_ports if request.auto_resolve_conflicts else [],
                    preserve_run_id=amp_run_id,
                    cleanup_stale=request.auto_resolve_stale,
                    stale_max_age_hours=request.stale_max_age_hours,  # None = any age, 0 = all stale
                )
                stale_removed = cleanup_result.get("stale_removed", 0)
                orphans_removed = cleanup_result.get("orphans_removed", 0)
                conflicts_resolved = cleanup_result.get("conflicts_resolved", 0)
                conflicts_found = cleanup_result.get("conflicts_found", [])

                if stale_removed > 0 or orphans_removed > 0 or conflicts_resolved > 0:
                    self.hooks.emit_metric(
                        "amprealize.apply.cleanup",
                        plan_id=plan_id,
                        amp_run_id=amp_run_id,
                        stale_removed=stale_removed,
                        orphans_removed=orphans_removed,
                        conflicts_resolved=conflicts_resolved,
                    )

                # Log any unresolved conflicts (ports still blocked)
                if conflicts_found:
                    self.hooks.emit_metric(
                        "amprealize.apply.conflicts_remaining",
                        plan_id=plan_id,
                        amp_run_id=amp_run_id,
                        conflicts=conflicts_found,
                    )
            except Exception as e:
                # Log but don't fail - the main apply might still succeed
                self.hooks.emit_metric(
                    "amprealize.apply.cleanup_warning",
                    plan_id=plan_id,
                    amp_run_id=amp_run_id,
                    warning=str(e),
                )

        try:
            # Create a dedicated network for this run (enables inter-container DNS)
            network_name = f"amp-net-{amp_run_id}"
            from .executors.podman import PodmanExecutor
            if isinstance(self.executor, PodmanExecutor):
                self.executor.create_network(network_name, ignore_exists=True)
                manifest["network_name"] = network_name
            else:
                network_name = None  # Non-Podman executors don't need this

            for name, spec in services.items():
                container_name = f"{amp_run_id}-{name}"

                # Stop existing if any (simple reconciliation)
                self.executor.stop_container(container_name)
                self.executor.remove_container(container_name)

                # Build run config
                # Use the service name as a network alias so containers can reference
                # each other by simple names (e.g., "zookeeper" instead of "amp-xxx-zookeeper")
                config = ContainerRunConfig(
                    image=spec.get("image"),
                    name=container_name,
                    ports=spec.get("ports", []),
                    environment=spec.get("environment", {}),
                    volumes=spec.get("volumes", []),
                    command=spec.get("command"),
                    detach=True,
                    network=network_name,
                    network_aliases=[name] if network_name else [],
                )

                container_id = self.executor.run_container(config)
                outputs[name] = {"container_id": container_id, "status": "running"}

        except Exception as e:
            self.hooks.emit_metric(
                "amprealize.apply.failed",
                plan_id=plan_id,
                amp_run_id=amp_run_id,
                error=str(e),
            )
            if checklist_id:
                self.hooks.record_compliance_step(
                    "apply_failed",
                    checklist_id=checklist_id,
                    error=str(e),
                )
            raise

        manifest["phase"] = "APPLIED"
        manifest["environment_outputs"] = outputs

        # Save environment state
        env_path = self.environments_dir / f"{amp_run_id}.json"
        with open(env_path, "w") as f:
            json.dump(manifest, f, indent=2)

        # Record action
        action_id = self.hooks.record_action(
            "amprealize.apply.completed",
            plan_id=plan_id,
            amp_run_id=amp_run_id,
        )

        # Record compliance step
        if checklist_id:
            self.hooks.record_compliance_step(
                "apply_completed",
                checklist_id=checklist_id,
                plan_id=plan_id,
                environment_outputs=outputs,
                env_path=str(env_path),
            )

        # Emit metric
        self.hooks.emit_metric(
            "amprealize.apply.completed",
            plan_id=plan_id,
            amp_run_id=amp_run_id,
            services_count=len(outputs),
        )

        return ApplyResponse(
            environment_outputs=outputs,
            status_stream_url=f"/v1/amprealize/status/{amp_run_id}/stream",
            action_id=action_id,
            amp_run_id=amp_run_id,
        )

    def status(self, amp_run_id: str) -> StatusResponse:
        """Get the status of an environment.

        Args:
            amp_run_id: Run identifier

        Returns:
            Status response with health checks and telemetry
        """
        env_path = self.environments_dir / f"{amp_run_id}.json"

        if not env_path.exists():
            return StatusResponse(
                amp_run_id=amp_run_id,
                phase="UNKNOWN",
                progress_pct=0,
                checks=[],
                telemetry=None,
            )

        with open(env_path, "r") as f:
            run = json.load(f)

        phase = run.get("phase", "UNKNOWN")
        outputs = run.get("environment_outputs", {})
        checks = []
        all_running = True

        for name, info in outputs.items():
            container_id = info.get("container_id")
            if not container_id:
                continue

            status = self.executor.get_container_status(container_id)
            if status != "running":
                all_running = False

            checks.append(
                HealthCheck(
                    name=name,
                    status=status,
                    last_probe=datetime.utcnow(),
                )
            )

        if phase == "APPLIED" and not all_running:
            phase = "DEGRADED"

        return StatusResponse(
            amp_run_id=amp_run_id,
            phase=phase,
            progress_pct=100 if phase in ["APPLIED", "DEGRADED"] else 50,
            checks=checks,
            telemetry=TelemetryData(token_savings_pct=0.3, behavior_reuse_pct=0.7),
            environment_outputs_path=str(env_path),
            audit_trail=[],
        )

    def destroy(self, request: DestroyRequest) -> DestroyResponse:
        """Destroy an environment.

        Args:
            request: Destroy request with run ID and reason

        Returns:
            Destroy response with teardown report
        """
        env_path = self.environments_dir / f"{request.amp_run_id}.json"
        teardown_report: List[str] = []
        checklist_id = None

        if env_path.exists():
            with open(env_path, "r") as f:
                run = json.load(f)
            checklist_id = run.get("checklist_id")
        else:
            run = {}

        # Emit start metric
        self.hooks.emit_metric(
            "amprealize.destroy.started",
            amp_run_id=request.amp_run_id,
        )

        # Record compliance step
        if checklist_id:
            self.hooks.record_compliance_step(
                "destroy_started",
                checklist_id=checklist_id,
                amp_run_id=request.amp_run_id,
                reason=request.reason,
            )

        try:
            if env_path.exists():
                outputs = run.get("environment_outputs", {})
                for name, info in outputs.items():
                    container_id = info.get("container_id")
                    if container_id:
                        self.executor.stop_container(container_id)
                        self.executor.remove_container(container_id)
                        teardown_report.append(name)

                # Clean up the network if one was created
                network_name = run.get("network_name")
                if network_name:
                    from .executors.podman import PodmanExecutor
                    if isinstance(self.executor, PodmanExecutor):
                        try:
                            self.executor.remove_network(network_name, force=True)
                            teardown_report.append(f"network:{network_name}")
                        except Exception:
                            pass  # Network cleanup is best-effort

                run["phase"] = "DESTROYED"
                run["destroyed_at"] = datetime.utcnow().isoformat()

                with open(env_path, "w") as f:
                    json.dump(run, f, indent=2)

        except Exception as e:
            self.hooks.emit_metric(
                "amprealize.destroy.failed",
                amp_run_id=request.amp_run_id,
                error=str(e),
            )
            if checklist_id:
                self.hooks.record_compliance_step(
                    "destroy_failed",
                    checklist_id=checklist_id,
                    error=str(e),
                )
            raise

        # Record action
        action_id = self.hooks.record_action(
            "amprealize.destroy",
            amp_run_id=request.amp_run_id,
            reason=request.reason,
        )

        # Record compliance step
        if checklist_id:
            self.hooks.record_compliance_step(
                "destroy_completed",
                checklist_id=checklist_id,
                teardown_report=teardown_report,
                destroyed_at=run.get("destroyed_at"),
            )

        # Emit metric
        self.hooks.emit_metric(
            "amprealize.destroy.completed",
            amp_run_id=request.amp_run_id,
            services_removed=len(teardown_report),
        )

        # Post-destroy cleanup: reclaim disk/memory from dangling images, unused caches
        cleanup_space_reclaimed_mb = 0.0
        if request.cleanup_after_destroy and isinstance(self.executor, ResourceCapableExecutor):
            try:
                self.hooks.emit_metric(
                    "amprealize.destroy.post_cleanup_started",
                    amp_run_id=request.amp_run_id,
                    aggressive=request.cleanup_aggressive,
                )

                cleanup_result = self.executor.mitigate_resources(
                    dry_run=False,
                    prune_containers=True,
                    prune_images=request.cleanup_aggressive,
                    prune_volumes=request.cleanup_include_volumes,
                    prune_cache=request.cleanup_aggressive,
                    prune_networks=True,
                    prune_pods=True,
                    prune_logs=request.cleanup_aggressive,
                )

                cleanup_space_reclaimed_mb = cleanup_result.space_reclaimed_mb
                teardown_report.append(
                    f"cleanup:freed {cleanup_space_reclaimed_mb:.1f}MB "
                    f"(images:{cleanup_result.images_removed}, "
                    f"containers:{cleanup_result.containers_removed})"
                )

                self.hooks.emit_metric(
                    "amprealize.destroy.post_cleanup_completed",
                    amp_run_id=request.amp_run_id,
                    space_reclaimed_mb=cleanup_space_reclaimed_mb,
                    containers_removed=cleanup_result.containers_removed,
                    images_removed=cleanup_result.images_removed,
                    cache_cleared=cleanup_result.cache_cleared,
                )
            except Exception as e:
                # Post-cleanup is best-effort, don't fail the destroy
                self.hooks.emit_metric(
                    "amprealize.destroy.post_cleanup_error",
                    amp_run_id=request.amp_run_id,
                    error=str(e),
                )

        return DestroyResponse(
            teardown_report=teardown_report,
            action_id=action_id,
        )

    def watch(self, amp_run_id: str) -> Generator[StatusEvent, None, None]:
        """Watch status events for a run.

        Args:
            amp_run_id: Run identifier

        Yields:
            Status events
        """
        status = self.status(amp_run_id)
        yield StatusEvent(
            timestamp=datetime.utcnow().isoformat(),
            status=status.phase,
            message=f"Run is in phase {status.phase}",
            details={"progress": status.progress_pct},
        )

    def list_environments(self) -> List[Dict[str, Any]]:
        """List all active environments.

        Returns:
            List of environment status dicts
        """
        result = []
        for path in self.environments_dir.glob("*.json"):
            with open(path, "r") as f:
                data = json.load(f)
            result.append({
                "amp_run_id": data.get("amp_run_id"),
                "environment": data.get("environment"),
                "phase": data.get("phase"),
                "blueprint_id": data.get("blueprint_id"),
                "created_at": data.get("created_at"),
            })
        return result

    # =========================================================================
    # Configuration
    # =========================================================================

    def configure(
        self,
        config_dir: Optional[Path] = None,
        include_blueprints: bool = False,
        blueprints: Optional[List[str]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Bootstrap Amprealize configuration in a directory.

        Args:
            config_dir: Target directory (defaults to ./config/amprealize)
            include_blueprints: Whether to copy packaged blueprints
            blueprints: Specific blueprints to copy (or all if None)
            force: Overwrite existing files

        Returns:
            Summary of what was created
        """
        config_dir = config_dir or Path.cwd() / "config" / "amprealize"
        config_dir.mkdir(parents=True, exist_ok=True)

        # Copy environment template
        template = Path(__file__).parent / "templates" / "environments.yaml"
        if not template.exists():
            # Create a default template
            default_env = """environments:
  development:
    description: Local development environment
    default_compliance_tier: standard
    default_lifetime: 90m
    runtime:
      provider: podman
      auto_start: true
    infrastructure:
      blueprint_id: postgres-dev
      teardown_on_exit: true

  staging:
    description: Staging environment
    default_compliance_tier: strict
    default_lifetime: 4h
    runtime:
      provider: podman
      memory_limit_mb: 4096
"""
            destination_env = config_dir / "environments.yaml"
            env_status = "created"
            if destination_env.exists() and not force:
                env_status = "skipped"
            else:
                if destination_env.exists():
                    env_status = "overwritten"
                destination_env.write_text(default_env)
        else:
            destination_env = config_dir / "environments.yaml"
            env_status = "created"
            if destination_env.exists() and not force:
                env_status = "skipped"
            else:
                if destination_env.exists():
                    env_status = "overwritten"
                shutil.copyfile(template, destination_env)

        blueprint_records: List[Dict[str, Any]] = []
        blueprints_dir: Optional[Path] = None

        if include_blueprints:
            blueprints_dir = config_dir / "blueprints"
            blueprints_dir.mkdir(parents=True, exist_ok=True)

            packaged = self._discover_packaged_blueprints()
            selected = blueprints or sorted(packaged.keys())

            for bp in selected:
                source = packaged.get(bp)
                if not source:
                    blueprint_records.append({
                        "blueprint": bp,
                        "status": "missing",
                        "reason": "Blueprint not found",
                    })
                    continue

                target_path = blueprints_dir / source.name
                existed_before = target_path.exists()

                if existed_before and not force:
                    blueprint_records.append({
                        "blueprint": bp,
                        "status": "skipped",
                        "path": str(target_path),
                        "reason": "File exists",
                    })
                    continue

                shutil.copyfile(source, target_path)
                blueprint_records.append({
                    "blueprint": bp,
                    "status": "overwritten" if existed_before else "copied",
                    "path": str(target_path),
                })

        return {
            "environment_file": str(destination_env),
            "environment_status": env_status,
            "blueprints_dir": str(blueprints_dir) if blueprints_dir else None,
            "blueprints": blueprint_records,
        }
