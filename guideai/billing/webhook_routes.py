"""FastAPI routes for billing webhooks.

Following: behavior_design_api_contract

Provides endpoints for receiving and processing webhooks from billing providers
(Stripe, etc.). Uses the standalone WebhookHandler for provider-agnostic processing.

Routes:
- POST /v1/billing/webhooks/{provider} - Receive provider webhooks
- GET /v1/billing/webhooks/status - Health check for webhook endpoint
"""

from __future__ import annotations

import logging
from typing import Optional, Callable, Awaitable, Any, Dict
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, HTTPException, Depends, Header
from pydantic import BaseModel

from billing import WebhookHandler, WebhookResult, WebhookHandlerStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Response Models
# =============================================================================

class WebhookResponse(BaseModel):
    """Response model for webhook processing."""

    status: str
    event_id: Optional[str] = None
    event_type: Optional[str] = None
    message: Optional[str] = None


class WebhookStatusResponse(BaseModel):
    """Response model for webhook health check."""

    healthy: bool
    timestamp: str
    providers: list[str]


# =============================================================================
# Route Factory
# =============================================================================

def create_webhook_router(
    handler: WebhookHandler,
    get_raw_body: Optional[Callable[[Request], Awaitable[bytes]]] = None,
) -> APIRouter:
    """Create FastAPI router for billing webhooks.

    Args:
        handler: WebhookHandler instance configured with provider
        get_raw_body: Optional custom function to get raw request body
                     (for signature verification)

    Returns:
        APIRouter with webhook endpoints

    Example:
        from fastapi import FastAPI
        from billing import WebhookHandler, MockBillingProvider, BillingService

        app = FastAPI()
        provider = MockBillingProvider()
        service = BillingService(provider=provider)
        webhook_handler = WebhookHandler(service=service, provider=provider)

        router = create_webhook_router(webhook_handler)
        app.include_router(router)
    """
    router = APIRouter(prefix="/v1/billing/webhooks", tags=["billing-webhooks"])

    async def default_get_raw_body(request: Request) -> bytes:
        """Default implementation to get raw request body."""
        return await request.body()

    body_getter = get_raw_body or default_get_raw_body

    @router.post(
        "/{provider}",
        response_model=WebhookResponse,
        summary="Receive billing webhook",
        description="Endpoint for receiving webhooks from billing providers (e.g., Stripe).",
        responses={
            200: {"description": "Webhook processed successfully"},
            400: {"description": "Invalid webhook payload"},
            401: {"description": "Invalid webhook signature"},
            500: {"description": "Internal processing error"},
        },
    )
    async def receive_webhook(
        provider: str,
        request: Request,
        stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    ) -> WebhookResponse:
        """Receive and process a billing webhook.

        This endpoint handles webhooks from billing providers like Stripe.
        It verifies the signature (if applicable), processes the event,
        and returns the result.

        Args:
            provider: The billing provider name (e.g., "stripe", "mock")
            request: The incoming request
            stripe_signature: The Stripe webhook signature (for Stripe webhooks)

        Returns:
            WebhookResponse with processing status

        Raises:
            HTTPException: On signature verification failure or processing error
        """
        # Get raw body for signature verification
        raw_body = await body_getter(request)

        # Determine signature based on provider
        signature = None
        if provider.lower() == "stripe":
            signature = stripe_signature

        try:
            # Process webhook
            result = await handler.handle_webhook(
                provider=provider,
                payload=raw_body,
                signature=signature,
            )

            # Map result to HTTP response
            if result.status == WebhookHandlerStatus.SUCCESS:
                return WebhookResponse(
                    status="success",
                    event_id=result.event_id,
                    event_type=result.event_type,
                )

            elif result.status == WebhookHandlerStatus.DUPLICATE:
                return WebhookResponse(
                    status="duplicate",
                    event_id=result.event_id,
                    message="Event already processed",
                )

            elif result.status == WebhookHandlerStatus.SIGNATURE_INVALID:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid webhook signature",
                )

            elif result.status == WebhookHandlerStatus.PARSE_ERROR:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to parse webhook payload: {result.error}",
                )

            elif result.status == WebhookHandlerStatus.HANDLER_ERROR:
                # Log error but return 200 to prevent retries
                # (following Stripe best practice)
                logger.error(
                    f"Webhook handler error: {result.error}",
                    extra={
                        "provider": provider,
                        "event_id": result.event_id,
                        "event_type": result.event_type,
                    },
                )
                return WebhookResponse(
                    status="error",
                    event_id=result.event_id,
                    event_type=result.event_type,
                    message="Handler error (logged)",
                )

            elif result.status == WebhookHandlerStatus.SKIPPED:
                return WebhookResponse(
                    status="skipped",
                    event_type=result.event_type,
                    message="Event type not handled",
                )

            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Unknown webhook status: {result.status}",
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Unexpected error processing webhook from {provider}")
            raise HTTPException(
                status_code=500,
                detail=f"Internal error: {str(e)}",
            )

    @router.get(
        "/status",
        response_model=WebhookStatusResponse,
        summary="Webhook endpoint health check",
        description="Check health of webhook endpoint and configured providers.",
    )
    async def webhook_status() -> WebhookStatusResponse:
        """Get webhook endpoint status.

        Returns health check information including configured providers.
        """
        return WebhookStatusResponse(
            healthy=True,
            timestamp=datetime.now(timezone.utc).isoformat(),
            providers=["stripe", "mock"],  # List configured providers
        )

    return router


# =============================================================================
# Convenience Factory for GuideAI Integration
# =============================================================================

def create_guideai_webhook_router(
    webhook_handler: Optional[WebhookHandler] = None,
) -> APIRouter:
    """Create webhook router with GuideAI defaults.

    This factory creates a webhook router pre-configured for GuideAI
    integration, including logging and action tracking.

    Args:
        webhook_handler: Optional pre-configured WebhookHandler.
                        If not provided, must be set later.

    Returns:
        APIRouter configured for GuideAI

    Example:
        from guideai.billing import GuideAIBillingService
        from guideai.billing.webhook_routes import create_guideai_webhook_router

        # Create service (handles webhook handler creation)
        service = GuideAIBillingService(provider=provider)

        # Create router with service's webhook handler
        router = create_guideai_webhook_router(service.webhook_handler)
        app.include_router(router)
    """
    if webhook_handler is None:
        # Return a placeholder router that requires handler injection
        router = APIRouter(prefix="/v1/billing/webhooks", tags=["billing-webhooks"])

        @router.post("/{provider}")
        async def webhook_not_configured(provider: str):
            raise HTTPException(
                status_code=503,
                detail="Webhook handler not configured",
            )

        @router.get("/status")
        async def status_not_configured():
            return WebhookStatusResponse(
                healthy=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
                providers=[],
            )

        return router

    return create_webhook_router(webhook_handler)
