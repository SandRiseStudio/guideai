"""Billing webhook routes - OSS Stub.

Full implementation in guideai-enterprise.
Install guideai-enterprise[billing] for webhook integration.
"""

try:
    from guideai_enterprise.billing.webhook_routes import (
        create_webhook_router,
        create_guideai_webhook_router,
        WebhookResponse,
        WebhookStatusResponse,
    )
except ImportError:
    create_webhook_router = None  # type: ignore[assignment]
    create_guideai_webhook_router = None  # type: ignore[assignment]
    WebhookResponse = None  # type: ignore[assignment,misc]
    WebhookStatusResponse = None  # type: ignore[assignment,misc]
