"""MCP tool handlers for ProjectService.

Provides handlers for project management within organizations.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
# NOTE: Project is a Pydantic model - use .model_dump() not asdict()

from guideai.multi_tenant.contracts import (
    Project,
    ProjectVisibility,
    MemberRole,
)


# ==============================================================================
# Serialization Helpers
# ==============================================================================


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'value'):  # Enum
        return value.value
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _project_to_dict(project: Project) -> Dict[str, Any]:
    """Convert Project Pydantic model to dict with serialized timestamps."""
    result = project.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


# ==============================================================================
# Authorization Helpers
# ==============================================================================


async def _check_org_access(
    org_service: OrganizationService,
    org_id: str,
    user_id: str,
    require_admin: bool = False,
) -> tuple[bool, Optional[str], Optional[MemberRole]]:
    """
    Check if user has access to the organization.

    Returns: (has_access, error_message, role)
    """
    membership = await org_service.get_membership(org_id=org_id, user_id=user_id)
    if not membership:
        return False, "Access denied or organization not found", None

    if require_admin and membership.role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        return False, "Access denied. Requires admin or owner role.", membership.role

    return True, None, membership.role


async def _check_project_access(
    project_service: ProjectService,
    org_service: OrganizationService,
    project_id: str,
    user_id: str,
    require_write: bool = False,
) -> tuple[bool, Optional[str], Optional[Project]]:
    """
    Check if user has access to the project.

    Returns: (has_access, error_message, project)
    """
    project = await project_service.get_project(project_id)
    if not project:
        return False, f"Project {project_id} not found", None

    has_access, error, role = await _check_org_access(
        org_service,
        project.org_id,
        user_id,
        require_admin=require_write,
    )

    if not has_access:
        return False, error, None

    return True, None, project


# ==============================================================================
# Handler Functions - Project CRUD
# ==============================================================================


async def handle_create_project(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a new project within an organization.

    MCP Tool: projects.create
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    name = arguments["name"]
    description = arguments.get("description")
    settings = arguments.get("settings", {})
    metadata = arguments.get("metadata", {})

    # Check user has admin access to org
    has_access, error, _ = await _check_org_access(
        org_service, org_id, user_id, require_admin=True
    )
    if not has_access:
        return {"success": False, "error": error}

    project = await project_service.create_project(
        org_id=org_id,
        name=name,
        description=description,
        created_by=user_id,
        settings=settings,
        metadata=metadata,
    )

    return {
        "success": True,
        "project": _project_to_dict(project),
        "message": f"Project '{name}' created successfully",
    }


async def handle_get_project(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get project details by ID.

    MCP Tool: projects.get
    """
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id
    )
    if not has_access:
        return {"success": False, "error": error}

    return {
        "success": True,
        "project": _project_to_dict(project),
    }


async def handle_list_projects(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List projects within an organization.

    MCP Tool: projects.list
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    status = arguments.get("status")
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)

    # Check user has access to org
    has_access, error, _ = await _check_org_access(org_service, org_id, user_id)
    if not has_access:
        return {"success": False, "error": error}

    # Parse status filter if provided
    status_filter = None
    if status:
        try:
            status_filter = ProjectStatus(status)
        except ValueError:
            pass

    projects = await project_service.list_projects(
        org_id=org_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )

    return {
        "success": True,
        "projects": [_project_to_dict(p) for p in projects],
        "total": len(projects),
        "org_id": org_id,
        "limit": limit,
        "offset": offset,
    }


async def handle_update_project(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update project settings.

    MCP Tool: projects.update
    """
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
    )
    if not has_access:
        return {"success": False, "error": error}

    # Build update kwargs
    updates = {}
    if "name" in arguments:
        updates["name"] = arguments["name"]
    if "description" in arguments:
        updates["description"] = arguments["description"]
    if "status" in arguments:
        try:
            updates["status"] = ProjectStatus(arguments["status"])
        except ValueError:
            pass
    if "settings" in arguments:
        updates["settings"] = arguments["settings"]
    if "metadata" in arguments:
        updates["metadata"] = arguments["metadata"]

    updated_project = await project_service.update_project(project_id, **updates)
    if not updated_project:
        return {
            "success": False,
            "error": f"Failed to update project {project_id}",
        }

    return {
        "success": True,
        "project": _project_to_dict(updated_project),
        "message": "Project updated successfully",
    }


async def handle_delete_project(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Delete a project (soft delete).

    MCP Tool: projects.delete
    """
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
    )
    if not has_access:
        return {"success": False, "error": error}

    success = await project_service.delete_project(project_id)
    if not success:
        return {
            "success": False,
            "error": f"Failed to delete project {project_id}",
        }

    return {
        "success": True,
        "project_id": project_id,
        "message": "Project deleted successfully",
    }


async def handle_archive_project(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Archive a project.

    MCP Tool: projects.archive
    """
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
    )
    if not has_access:
        return {"success": False, "error": error}

    # Archive by updating settings (Project model doesn't have status field)
    updated_project = await project_service.update_project(
        project_id, settings={"archived": True, "archived_at": datetime.utcnow().isoformat()}
    )
    if not updated_project:
        return {
            "success": False,
            "error": f"Failed to archive project {project_id}",
        }

    return {
        "success": True,
        "project": _project_to_dict(updated_project),
        "message": "Project archived successfully",
    }


async def handle_restore_project(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Restore an archived project.

    MCP Tool: projects.restore
    """
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
    )
    if not has_access:
        return {"success": False, "error": error}

    # Restore by removing archive flag from settings
    updated_project = await project_service.update_project(
        project_id, settings={"archived": False, "archived_at": None}
    )
    if not updated_project:
        return {
            "success": False,
            "error": f"Failed to restore project {project_id}",
        }

    return {
        "success": True,
        "project": _project_to_dict(updated_project),
        "message": "Project restored successfully",
    }


# ==============================================================================
# Handler Functions - Project Settings
# ==============================================================================


async def handle_get_settings(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get project settings.

    MCP Tool: projects.getSettings
    """
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id
    )
    if not has_access:
        return {"success": False, "error": error}

    return {
        "success": True,
        "project_id": project_id,
        "settings": project.settings or {},
    }


async def handle_update_settings(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update project settings.

    MCP Tool: projects.updateSettings
    """
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]
    settings = arguments["settings"]
    merge = arguments.get("merge", True)

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
    )
    if not has_access:
        return {"success": False, "error": error}

    # Merge or replace settings
    if merge and project.settings:
        new_settings = {**project.settings, **settings}
    else:
        new_settings = settings

    updated_project = await project_service.update_project(
        project_id, settings=new_settings
    )
    if not updated_project:
        return {
            "success": False,
            "error": f"Failed to update project settings",
        }

    return {
        "success": True,
        "project_id": project_id,
        "settings": updated_project.settings or {},
        "message": "Project settings updated successfully",
    }


# ==============================================================================
# Handler Functions - Project Stats
# ==============================================================================


async def handle_get_stats(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get project statistics and usage.

    MCP Tool: projects.getStats
    """
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id
    )
    if not has_access:
        return {"success": False, "error": error}

    stats = await project_service.get_project_stats(project_id)

    return {
        "success": True,
        "project_id": project_id,
        "stats": _serialize_value(stats),
    }


async def handle_get_usage(
    project_service: ProjectService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get detailed project usage metrics.

    MCP Tool: projects.getUsage
    """
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]
    period = arguments.get("period", "30d")

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id
    )
    if not has_access:
        return {"success": False, "error": error}

    usage = await project_service.get_project_usage(project_id, period=period)

    return {
        "success": True,
        "project_id": project_id,
        "period": period,
        "usage": _serialize_value(usage),
    }


# ==============================================================================
# Handler Registry
# ==============================================================================


PROJECT_HANDLERS = {
    "projects.create": handle_create_project,
    "projects.get": handle_get_project,
    "projects.list": handle_list_projects,
    "projects.update": handle_update_project,
    "projects.delete": handle_delete_project,
    "projects.archive": handle_archive_project,
    "projects.restore": handle_restore_project,
    "projects.getSettings": handle_get_settings,
    "projects.updateSettings": handle_update_settings,
    "projects.getStats": handle_get_stats,
    "projects.getUsage": handle_get_usage,
}
