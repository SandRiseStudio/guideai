"""FastAPI integration for Amprealize.

Provides factory functions to create FastAPI routers that expose
Amprealize functionality as REST endpoints.

Example:
    from fastapi import FastAPI
    from amprealize import AmprealizeService
    from amprealize.executors import PodmanExecutor
    from amprealize.integrations.fastapi import create_amprealize_routes

    app = FastAPI()
    service = AmprealizeService(executor=PodmanExecutor())
    app.include_router(create_amprealize_routes(service), prefix="/api/v1/amprealize")
"""

from typing import Any, Dict, List, Optional, Union, Sequence, cast

try:
    from fastapi import APIRouter, HTTPException, BackgroundTasks, Response
except ImportError as e:
    raise ImportError(
        "FastAPI integration requires fastapi. Install with: pip install amprealize[fastapi]"
    ) from e

from ..models import (
    ApplyRequest,
    ApplyResponse,
    Blueprint,
    DestroyRequest,
    DestroyResponse,
    EnvironmentDefinition,
    PlanRequest,
    PlanResponse,
    StatusResponse,
)
from ..service import AmprealizeService


def create_amprealize_routes(
    service: AmprealizeService,
    *,
    prefix: str = "",
    tags: Optional[List[str]] = None,
    include_blueprint_routes: bool = True,
    include_environment_routes: bool = True,
) -> APIRouter:
    """Create a FastAPI router with Amprealize endpoints.

    Args:
        service: The AmprealizeService instance to use
        prefix: Optional prefix for all routes (in addition to any prefix when including)
        tags: OpenAPI tags for these endpoints
        include_blueprint_routes: Whether to include blueprint management routes
        include_environment_routes: Whether to include environment management routes

    Returns:
        Configured APIRouter with Amprealize endpoints

    Example:
        >>> service = AmprealizeService(executor=PodmanExecutor())
        >>> router = create_amprealize_routes(service, tags=["Infrastructure"])
        >>> app.include_router(router, prefix="/api/v1/amprealize")
    """
    resolved_tags: List[str] = tags if tags is not None else ["amprealize"]
    router = APIRouter(prefix=prefix, tags=cast(List[Any], resolved_tags))

    # =========================================================================
    # Core Operations
    # =========================================================================

    @router.post("/plan", response_model=PlanResponse)
    async def plan_environment(request: PlanRequest) -> PlanResponse:
        """Plan an environment deployment.

        Analyzes the requested environment and blueprint, returning a plan
        that describes what actions will be taken during apply.
        """
        try:
            response = service.plan(request)
            return response
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Plan failed: {e}")

    @router.post("/apply", response_model=ApplyResponse)
    async def apply_environment(
        request: ApplyRequest,
        background_tasks: BackgroundTasks,
    ) -> ApplyResponse:
        """Apply an environment plan.

        Executes the plan to create or update the environment. For long-running
        operations, use the run_id to poll for status.
        """
        try:
            response = service.apply(request)
            return response
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Apply failed: {e}")

    @router.get("/status/{run_id}", response_model=StatusResponse)
    async def get_run_status(run_id: str) -> StatusResponse:
        """Get the status of a run.

        Returns the current status of an apply or destroy operation.
        """
        try:
            response = service.status(run_id)
            return response
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Status check failed: {e}")

    @router.post("/destroy", response_model=DestroyResponse)
    async def destroy_environment(request: DestroyRequest) -> DestroyResponse:
        """Destroy an environment.

        Tears down all resources associated with the specified environment.
        """
        try:
            response = service.destroy(request)
            return response
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Destroy failed: {e}")

    # =========================================================================
    # Blueprint Management
    # =========================================================================

    if include_blueprint_routes:
        @router.get("/blueprints", response_model=List[Dict[str, Any]])
        async def list_blueprints() -> List[Dict[str, Any]]:
            """List available blueprints.

            Returns both built-in and user-defined blueprints.
            """
            try:
                return service.list_blueprints()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"List blueprints failed: {e}")

    # =========================================================================
    # Environment Management
    # =========================================================================

    if include_environment_routes:
        @router.get("/environments", response_model=List[Dict[str, Any]])
        async def list_environments() -> List[Dict[str, Any]]:
            """List active environments.

            Returns all environments currently deployed or in progress.
            """
            try:
                return service.list_environments()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"List environments failed: {e}")

        @router.post("/environments/register", response_model=Dict[str, str])
        async def register_environment(environment: EnvironmentDefinition) -> Dict[str, str]:
            """Register a new environment definition.

            Adds an environment definition for use in plan/apply operations.
            """
            try:
                service.register_environment(environment)
                return {"name": environment.name, "status": "registered"}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Register environment failed: {e}")

    # =========================================================================
    # Bootstrap
    # =========================================================================

    @router.post("/bootstrap", response_model=Dict[str, Any])
    async def bootstrap(
        include_blueprints: bool = False,
        blueprints: Optional[List[str]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Bootstrap Amprealize configuration.

        Creates environment templates and optionally copies blueprints to
        a configuration directory.
        """
        try:
            return service.bootstrap(
                include_blueprints=include_blueprints,
                blueprints=blueprints,
                force=force,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Bootstrap failed: {e}")

    # =========================================================================
    # Health Check
    # =========================================================================

    @router.get("/health")
    async def health_check() -> Dict[str, Any]:
        """Check service health.

        Returns health status including executor availability.
        """
        try:
            return {
                "status": "healthy",
                "executor": service.executor.__class__.__name__,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    return router


# Convenience function for minimal setup
def create_amprealize_app(
    *,
    executor: Optional[Any] = None,
    title: str = "Amprealize",
    version: str = "0.1.0",
    cors_origins: Optional[List[str]] = None,
) -> Any:
    """Create a standalone FastAPI application with Amprealize routes.

    This is a convenience function for quickly setting up a standalone
    Amprealize API server.

    Args:
        executor: Container executor to use (defaults to PodmanExecutor)
        title: API title for OpenAPI docs
        version: API version for OpenAPI docs
        cors_origins: Optional list of CORS origins to allow

    Returns:
        Configured FastAPI application

    Example:
        >>> app = create_amprealize_app(cors_origins=["http://localhost:3000"])
        >>> # Run with: uvicorn module:app --reload
    """
    from fastapi import FastAPI

    # Import here to avoid circular imports and allow optional executor
    if executor is None:
        from ..executors import PodmanExecutor
        executor = PodmanExecutor()

    app = FastAPI(title=title, version=version)

    # Add CORS if origins specified
    if cors_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Create and mount service
    service = AmprealizeService(executor=executor)
    app.include_router(
        create_amprealize_routes(service),
        prefix="/api/v1",
    )

    return app
