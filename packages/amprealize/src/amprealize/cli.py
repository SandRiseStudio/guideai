"""Amprealize Command-Line Interface.

Standalone CLI for managing container environments using Amprealize.

Usage:
    amprealize plan postgres-dev --env development
    amprealize apply --plan-id <plan-id>
    amprealize status amp-abc123
    amprealize destroy amp-abc123 --reason "cleanup"
    amprealize list

Install with CLI support:
    pip install amprealize[cli]
"""

from pathlib import Path
from typing import Optional, List
import json
import sys

try:
    import typer
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
except ImportError as e:
    raise ImportError(
        "CLI requires typer and rich. Install with: pip install amprealize[cli]"
    ) from e

from .service import AmprealizeService
from .executors import PodmanExecutor
from .models import PlanRequest, ApplyRequest, DestroyRequest

app = typer.Typer(
    name="amprealize",
    help="Container environment management made simple.",
    add_completion=False,
)
console = Console()


def get_service() -> AmprealizeService:
    """Get configured AmprealizeService instance."""
    executor = PodmanExecutor()
    return AmprealizeService(executor=executor)


# =============================================================================
# Plan Command
# =============================================================================

@app.command()
def plan(
    environment: str = typer.Argument(
        ...,
        help="Environment name (e.g., 'development')",
    ),
    blueprint: Optional[str] = typer.Option(
        None,
        "--blueprint", "-b",
        help="Blueprint ID to plan (e.g., 'postgres-dev')",
    ),
    lifetime: Optional[str] = typer.Option(
        None,
        "--lifetime", "-l",
        help="Environment lifetime (e.g., '2h', '90m')",
    ),
    compliance_tier: Optional[str] = typer.Option(
        None,
        "--compliance", "-c",
        help="Compliance tier override",
    ),
    modules: Optional[List[str]] = typer.Option(
        None,
        "--module", "-m",
        help="Modules to activate (can specify multiple times)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output plan to JSON file",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Only output plan ID",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed resource insights",
    ),
    force_podman: bool = typer.Option(
        False,
        "--force-podman",
        help="Skip Podman machine checks/warnings",
    ),
) -> None:
    """Plan an environment deployment.

    Analyzes the blueprint and environment, generating a deployment plan
    that shows what actions will be taken during apply.
    """
    service = get_service()

    request = PlanRequest(
        environment=environment,
        blueprint_id=blueprint,
        lifetime=lifetime,
        compliance_tier=compliance_tier,
        active_modules=modules,
        force_podman=force_podman,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Planning...", total=None)

        try:
            response = service.plan(request)
        except Exception as e:
            console.print(f"[red]Plan failed: {e}[/red]")
            raise typer.Exit(1)

    if quiet:
        console.print(response.plan_id)
        return

    if output:
        output.write_text(response.model_dump_json(indent=2))
        console.print(f"[green]Plan written to {output}[/green]")
        return

    # Display plan summary
    estimates = response.environment_estimates
    console.print(Panel(
        f"[bold]Plan ID:[/bold] {response.plan_id}\n"
        f"[bold]Run ID:[/bold] {response.amp_run_id}\n"
        f"[bold]Memory:[/bold] {estimates.memory_footprint_mb} MB\n"
        f"[bold]Boot Time:[/bold] ~{estimates.expected_boot_duration_s}s",
        title="Amprealize Plan",
        expand=False,
    ))

    # Show manifest services
    manifest = response.signed_manifest
    if manifest.get("services"):
        table = Table(title="Planned Services")
        table.add_column("Service", style="cyan")
        table.add_column("Image", style="green")
        table.add_column("Ports")

        for svc_name, svc_config in manifest.get("services", {}).items():
            ports = ", ".join(svc_config.get("ports", [])) if svc_config.get("ports") else "-"
            table.add_row(
                svc_name,
                svc_config.get("image", "unknown"),
                ports,
            )

        console.print(table)

    # Show resource insights
    try:
        executor = PodmanExecutor()
        resource_data = executor.get_resource_insights(verbose=verbose)
        if resource_data.get("summary"):
            console.print()
            console.print(Panel(
                resource_data["summary"],
                title="Resource Status",
                expand=False,
            ))
    except Exception:
        pass  # Skip insights if unavailable

    console.print()
    console.print(f"[dim]Run 'amprealize apply --plan-id {response.plan_id}' to execute this plan[/dim]")


# =============================================================================
# Apply Command
# =============================================================================

@app.command()
def apply(
    plan_id: Optional[str] = typer.Option(
        None,
        "--plan-id", "-p",
        help="Plan ID from a previous plan command",
    ),
    plan_file: Optional[Path] = typer.Option(
        None,
        "--plan-file", "-f",
        help="Apply from a saved plan JSON file",
    ),
    watch: bool = typer.Option(
        True,
        "--watch/--no-watch", "-w",
        help="Watch for completion",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Resume a partial apply",
    ),
    force_podman: bool = typer.Option(
        False,
        "--force-podman",
        help="Skip Podman machine checks/warnings",
    ),
    skip_resource_check: bool = typer.Option(
        False,
        "--skip-resource-check",
        help="Skip pre-flight resource health check",
    ),
    proactive_cleanup: bool = typer.Option(
        True,
        "--proactive-cleanup/--no-proactive-cleanup",
        help="Run cleanup BEFORE resource check to maximize available resources (default: enabled)",
    ),
    auto_cleanup: bool = typer.Option(
        True,
        "--auto-cleanup/--no-auto-cleanup",
        help="Automatically clean up resources if low during apply (default: enabled)",
    ),
    auto_cleanup_aggressive: bool = typer.Option(
        True,
        "--auto-cleanup-aggressive/--no-auto-cleanup-aggressive",
        help="Use aggressive cleanup including images/cache (default: enabled)",
    ),
    auto_cleanup_volumes: bool = typer.Option(
        False,
        "--auto-cleanup-volumes",
        help="Include volumes in cleanup (WARNING: may lose data)",
    ),
    blueprint_aware_memory: bool = typer.Option(
        True,
        "--blueprint-aware-memory/--no-blueprint-aware-memory",
        help="Use blueprint memory estimates for resource check (default: enabled)",
    ),
    memory_safety_margin_mb: float = typer.Option(
        512.0,
        "--memory-safety-margin-mb",
        help="Extra memory to require beyond blueprint estimate (default: 512 MB)",
    ),
    min_disk_gb: float = typer.Option(
        5.0,
        "--min-disk-gb",
        help="Minimum disk space required in GB (default: 5.0)",
    ),
    min_memory_mb: float = typer.Option(
        1024.0,
        "--min-memory-mb",
        help="Minimum memory required in MB (default: 1024)",
    ),
    auto_resolve_stale: bool = typer.Option(
        True,
        "--auto-resolve-stale/--no-auto-resolve-stale",
        help="Automatically remove stale/exited/dead containers before apply (default: enabled)",
    ),
    auto_resolve_conflicts: bool = typer.Option(
        True,
        "--auto-resolve-conflicts/--no-auto-resolve-conflicts",
        help="Automatically resolve port conflicts (stop conflicting containers/processes) (default: enabled)",
    ),
    stale_max_age_hours: Optional[float] = typer.Option(
        0.0,
        "--stale-max-age-hours",
        help="Max age for stale container cleanup in hours (0 = all stale, -1 = skip age check)",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Minimal output",
    ),
) -> None:
    """Apply an environment plan.

    Creates or updates the environment based on the blueprint and configuration.

    By default, proactive resource management is enabled:
    - Proactive cleanup runs BEFORE resource check to maximize available resources
    - Auto-cleanup handles low resources during provisioning
    - Blueprint-aware memory checking uses actual service memory requirements
    - Auto-resolve removes stale containers and resolves port conflicts automatically
    """
    service = get_service()

    manifest = None

    # Load plan from file if provided
    if plan_file and plan_file.exists():
        plan_data = json.loads(plan_file.read_text())
        plan_id = plan_data.get("plan_id")
        manifest = plan_data.get("signed_manifest")

    if not plan_id and not manifest:
        console.print("[red]Plan ID or plan file required[/red]")
        console.print("[dim]Run 'amprealize plan <environment>' first[/dim]")
        raise typer.Exit(1)

    # Handle special value -1 for stale_max_age_hours (skip age check)
    effective_stale_max_age = None if stale_max_age_hours == -1 else stale_max_age_hours

    request = ApplyRequest(
        plan_id=plan_id,
        manifest=manifest,
        watch=watch,
        resume=resume,
        force_podman=force_podman,
        skip_resource_check=skip_resource_check,
        proactive_cleanup=proactive_cleanup,
        auto_cleanup=auto_cleanup,
        auto_cleanup_aggressive=auto_cleanup_aggressive,
        auto_cleanup_include_volumes=auto_cleanup_volumes,
        blueprint_aware_memory_check=blueprint_aware_memory,
        memory_safety_margin_mb=memory_safety_margin_mb,
        min_disk_gb=min_disk_gb,
        min_memory_mb=min_memory_mb,
        auto_resolve_stale=auto_resolve_stale,
        auto_resolve_conflicts=auto_resolve_conflicts,
        stale_max_age_hours=effective_stale_max_age,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=not quiet,
    ) as progress:
        task = progress.add_task("Applying...", total=None)

        try:
            response = service.apply(request)
        except Exception as e:
            console.print(f"[red]Apply failed: {e}[/red]")
            raise typer.Exit(1)

    if quiet:
        console.print(response.amp_run_id)
        return

    # Display result
    console.print(Panel(
        f"[bold]Run ID:[/bold] {response.amp_run_id}\n"
        f"[bold]Action ID:[/bold] {response.action_id}",
        title="Apply Result",
        expand=False,
    ))

    if response.environment_outputs:
        table = Table(title="Environment Outputs")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")

        for key, value in response.environment_outputs.items():
            table.add_row(key, str(value)[:60])

        console.print(table)

    if response.status_stream_url:
        console.print(f"\n[dim]Status stream: {response.status_stream_url}[/dim]")


# =============================================================================
# Status Command
# =============================================================================

@app.command()
def status(
    run_id: str = typer.Argument(
        ...,
        help="Amprealize run ID to check",
    ),
    watch: bool = typer.Option(
        False,
        "--watch", "-w",
        help="Watch for status changes",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed resource insights",
    ),
) -> None:
    """Get the status of a run.

    Check the current status of an apply or destroy operation.
    """
    service = get_service()

    try:
        response = service.status(run_id)
    except FileNotFoundError:
        console.print(f"[red]Run {run_id} not found[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Status check failed: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        console.print(response.model_dump_json(indent=2))
        return

    # Display status
    phase_colors = {
        "PLANNED": "yellow",
        "PROVISIONING": "blue",
        "APPLIED": "green",
        "FAILED": "red",
        "DESTROYING": "orange",
        "DESTROYED": "dim",
    }
    phase_color = phase_colors.get(response.phase, "white")

    console.print(Panel(
        f"[bold]Run ID:[/bold] {response.amp_run_id}\n"
        f"[bold]Phase:[/bold] [{phase_color}]{response.phase}[/{phase_color}]\n"
        f"[bold]Progress:[/bold] {response.progress_pct}%",
        title="Run Status",
        expand=False,
    ))

    if response.checks:
        table = Table(title="Health Checks")
        table.add_column("Service", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Last Probe")

        for check in response.checks:
            status_color = "green" if check.status == "healthy" else "red"
            table.add_row(
                check.name,
                f"[{status_color}]{check.status}[/{status_color}]",
                check.last_probe.isoformat()[:19],
            )

        console.print(table)

    # Show resource insights
    try:
        executor = PodmanExecutor()
        resource_data = executor.get_resource_insights(verbose=verbose)
        if resource_data.get("summary"):
            console.print()
            console.print(Panel(
                resource_data["summary"],
                title="Resource Status",
                expand=False,
            ))
    except Exception:
        pass  # Skip insights if unavailable

    if response.telemetry:
        console.print(f"\n[dim]Token savings: {response.telemetry.token_savings_pct:.1f}%  |  Behavior reuse: {response.telemetry.behavior_reuse_pct:.1f}%[/dim]")


# =============================================================================
# Destroy Command
# =============================================================================

@app.command()
def destroy(
    run_id: str = typer.Argument(
        ...,
        help="Run ID to destroy",
    ),
    reason: str = typer.Option(
        "manual cleanup",
        "--reason", "-r",
        help="Reason for destruction",
    ),
    cascade: bool = typer.Option(
        True,
        "--cascade/--no-cascade",
        help="Cascade to dependent resources",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Force destroy without confirmation",
    ),
    force_podman: bool = typer.Option(
        False,
        "--force-podman",
        help="Skip Podman machine checks/warnings",
    ),
    cleanup_after_destroy: bool = typer.Option(
        True,
        "--cleanup/--no-cleanup",
        help="Run resource cleanup after destroying containers (default: enabled)",
    ),
    cleanup_aggressive: bool = typer.Option(
        True,
        "--cleanup-aggressive/--no-cleanup-aggressive",
        help="Use aggressive cleanup including dangling images/cache (default: enabled)",
    ),
    cleanup_volumes: bool = typer.Option(
        False,
        "--cleanup-volumes",
        help="Include volumes in cleanup (WARNING: may lose data)",
    ),
) -> None:
    """Destroy an environment.

    Tears down all resources associated with an environment.
    By default, post-destroy cleanup is enabled to reclaim disk space.
    """
    service = get_service()

    # Confirmation
    if not force:
        confirm = typer.confirm(f"Destroy run {run_id}?")
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    request = DestroyRequest(
        amp_run_id=run_id,
        cascade=cascade,
        reason=reason,
        force_podman=force_podman,
        cleanup_after_destroy=cleanup_after_destroy,
        cleanup_aggressive=cleanup_aggressive,
        cleanup_include_volumes=cleanup_volumes,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Destroying...", total=None)

        try:
            response = service.destroy(request)
        except Exception as e:
            console.print(f"[red]Destroy failed: {e}[/red]")
            raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Action ID:[/bold] {response.action_id}\n"
        f"[bold]Destroyed:[/bold] {len(response.teardown_report)} resources",
        title="Destroy Result",
        expand=False,
    ))

    if response.teardown_report:
        for item in response.teardown_report[:10]:
            console.print(f"  [dim]✓ {item}[/dim]")
        if len(response.teardown_report) > 10:
            console.print(f"  [dim]... and {len(response.teardown_report) - 10} more[/dim]")


# =============================================================================
# List Command
# =============================================================================

@app.command("list")
def list_environments(
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """List active environments.

    Shows all environments currently deployed or in progress.
    """
    service = get_service()

    try:
        environments = service.list_environments()
    except Exception as e:
        console.print(f"[red]List failed: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        console.print(json.dumps(environments, indent=2))
        return

    if not environments:
        console.print("[dim]No active environments[/dim]")
        return

    table = Table(title="Active Environments")
    table.add_column("Run ID", style="cyan")
    table.add_column("Environment", style="green")
    table.add_column("Phase")
    table.add_column("Blueprint")
    table.add_column("Created")

    for env in environments:
        phase_colors = {
            "PLANNED": "yellow",
            "PROVISIONING": "blue",
            "APPLIED": "green",
            "FAILED": "red",
        }
        phase = env.get("phase", "unknown")
        phase_styled = f"[{phase_colors.get(phase, 'white')}]{phase}[/{phase_colors.get(phase, 'white')}]"

        run_id = env.get("amp_run_id", "")
        display_id = run_id[:12] + "..." if len(run_id) > 12 else run_id

        table.add_row(
            display_id,
            env.get("environment", ""),
            phase_styled,
            env.get("blueprint_id", ""),
            (env.get("created_at", "") or "")[:19],
        )

    console.print(table)


# =============================================================================
# Blueprints Command
# =============================================================================

@app.command()
def blueprints(
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """List available blueprints.

    Shows both built-in and user-defined blueprints.
    """
    service = get_service()

    try:
        bps = service.list_blueprints()
    except Exception as e:
        console.print(f"[red]List failed: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        console.print(json.dumps(bps, indent=2))
        return

    if not bps:
        console.print("[dim]No blueprints found[/dim]")
        return

    table = Table(title="Available Blueprints")
    table.add_column("ID", style="cyan")
    table.add_column("Source", style="green")
    table.add_column("Path")

    for bp in bps:
        table.add_row(
            bp.get("id", ""),
            bp.get("source", ""),
            bp.get("path", ""),
        )

    console.print(table)


# =============================================================================
# Configure Command
# =============================================================================

@app.command()
def configure(
    path: Path = typer.Argument(
        Path("./config/amprealize"),
        help="Directory to configure",
    ),
    include_blueprints: bool = typer.Option(
        False,
        "--blueprints", "-b",
        help="Include packaged blueprints",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Overwrite existing files",
    ),
) -> None:
    """Configure Amprealize in a directory.

    Creates environment templates and optionally copies blueprints to
    help you get started quickly.
    """
    service = get_service()

    try:
        result = service.configure(
            config_dir=path,
            include_blueprints=include_blueprints,
            force=force,
        )
    except Exception as e:
        console.print(f"[red]Configure failed: {e}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Environment file:[/bold] {result['environment_file']} ({result['environment_status']})",
        title="Configuration Complete",
        expand=False,
    ))

    if result.get("blueprints"):
        table = Table(title="Blueprints")
        table.add_column("Blueprint", style="cyan")
        table.add_column("Status", style="green")

        for bp in result["blueprints"]:
            table.add_row(bp.get("blueprint", ""), bp.get("status", ""))

        console.print(table)

    console.print()
    console.print("[dim]Edit the environment file to customize your setup[/dim]")


# =============================================================================
# Resources Command
# =============================================================================

@app.command()
def resources(
    machine: Optional[str] = typer.Option(
        None,
        "--machine", "-m",
        help="Podman machine name (uses default if not specified)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed resource information",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """Show resource status with plain-English insights.

    Displays current resource utilization (memory, disk, CPU) with
    human-readable status messages like "plenty of memory" or
    "nearing capacity".

    Configure thresholds via environment variables:
        AMPREALIZE_INSIGHT_MEMORY_WARNING=70
        AMPREALIZE_INSIGHT_MEMORY_CRITICAL=90
    """
    executor = PodmanExecutor()

    try:
        resource_data = executor.get_resource_insights(
            machine_name=machine,
            verbose=verbose,
        )
    except Exception as e:
        console.print(f"[red]Failed to get resources: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        import json as json_module
        console.print(json_module.dumps(resource_data, indent=2, default=str))
        return

    # Show raw metrics first if verbose
    if verbose:
        resources_dict = resource_data.get("resources", {})
        metrics_table = Table(title="Resource Metrics")
        metrics_table.add_column("Metric", style="cyan")
        metrics_table.add_column("Value", style="green")
        metrics_table.add_column("Total", style="dim")

        if resources_dict.get("memory_total_mb"):
            used = resources_dict.get("memory_used_mb", 0)
            total = resources_dict.get("memory_total_mb", 0)
            pct = (used / total * 100) if total > 0 else 0
            metrics_table.add_row(
                "Memory",
                f"{used:.0f} MB ({pct:.1f}%)",
                f"{total:.0f} MB",
            )

        if resources_dict.get("disk_total_mb"):
            used = resources_dict.get("disk_used_mb", 0)
            total = resources_dict.get("disk_total_mb", 0)
            pct = (used / total * 100) if total > 0 else 0
            metrics_table.add_row(
                "Disk",
                f"{used:.0f} MB ({pct:.1f}%)",
                f"{total:.0f} MB",
            )

        if resources_dict.get("cpu_cores"):
            metrics_table.add_row(
                "CPU Cores",
                str(resources_dict.get("cpu_cores", 0)),
                "-",
            )

        console.print(metrics_table)
        console.print()

    # Show insights summary
    summary = resource_data.get("summary", "")
    if summary:
        console.print(Panel(
            summary,
            title="Resource Status",
            expand=False,
        ))
    else:
        console.print("[dim]No resource data available. Is Podman machine running?[/dim]")

    # Hint about threshold configuration
    if not json_output:
        console.print()
        console.print("[dim]Configure thresholds with AMPREALIZE_INSIGHT_* env vars[/dim]")


# =============================================================================
# Validate Command
# =============================================================================

@app.command()
def validate(
    path: Optional[Path] = typer.Argument(
        None,
        help="Path to environments.yaml file (auto-detects if not specified)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Only output errors (exit code indicates validity)",
    ),
) -> None:
    """Validate an environments.yaml configuration file.

    Checks that the file:
    - Is valid YAML
    - Has the correct structure
    - Contains no unknown fields (strict validation)
    - Has valid runtime/infrastructure configuration

    Examples:
        amprealize validate
        amprealize validate ./environments.yaml
        amprealize validate --json
    """
    import json as json_lib

    service = get_service()

    try:
        result = service.validate_environment_file(path=path, strict=False)
    except FileNotFoundError as e:
        if json_output:
            console.print(json_lib.dumps({
                "valid": False,
                "path": str(path) if path else None,
                "errors": [str(e)],
            }))
        else:
            console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        console.print(json_lib.dumps(result, indent=2))
        if not result["valid"]:
            raise typer.Exit(1)
        return

    if result["valid"]:
        if not quiet:
            console.print(f"[green]✓ Valid:[/green] {result['path']}")
            console.print()

            # Show environments table
            table = Table(title="Environments")
            table.add_column("Name", style="cyan")
            table.add_column("Description")

            # Load manifest to get descriptions
            from .models import EnvironmentManifest
            manifest = EnvironmentManifest.validate_file(result["path"])
            for env_name in result["environments"]:
                env_def = manifest.get_environment(env_name)
                desc = env_def.description if env_def else "-"
                table.add_row(env_name, desc or "-")

            console.print(table)

            # Show warnings if any
            if result["warnings"]:
                console.print()
                console.print("[yellow]Warnings:[/yellow]")
                for warning in result["warnings"]:
                    console.print(f"  [yellow]⚠[/yellow] {warning}")
    else:
        console.print(f"[red]✗ Invalid:[/red] {result['path']}")
        console.print()

        for error in result["errors"]:
            console.print(f"  [red]•[/red] {error}")

        raise typer.Exit(1)


# =============================================================================
# Version Command
# =============================================================================

@app.command()
def version() -> None:
    """Show version information."""
    from . import __version__
    console.print(f"amprealize {__version__}")


# =============================================================================
# Entry Point
# =============================================================================

def main() -> None:
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()
