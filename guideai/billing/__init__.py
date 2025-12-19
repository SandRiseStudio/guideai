"""GuideAI Billing integration.

This module provides a thin wrapper around the standalone billing package,
wiring it to guideai services (ActionService, ComplianceService, etc.).

For standalone usage without guideai, use the billing package directly:
    pip install -e ./packages/billing
    from billing import BillingService
    from billing.providers.mock import MockBillingProvider

NOTE: The standalone billing package is REQUIRED. Install with:
    pip install -e ./packages/billing
"""

# Re-export models from standalone package
from billing import (
    # Enums
    BillingPlan,
    SubscriptionStatus,
    PaymentMethodType,
    InvoiceStatus,
    UsageMetric,
    WebhookEventType,
    # Plan limits
    PlanLimits,
    PLAN_LIMITS,
    PLAN_PRICING,
    # Core models
    Customer,
    Subscription,
    PaymentMethod,
    Invoice,
    InvoiceLineItem,
    UsageRecord,
    UsageAggregate,
    UsageSummary,
    WebhookEvent,
    WebhookEventResult,
    # Request models
    CreateCustomerRequest,
    UpdateCustomerRequest,
    CreateSubscriptionRequest,
    UpdateSubscriptionRequest,
    CancelSubscriptionRequest,
    CreatePaymentMethodRequest,
    RecordUsageRequest,
    CreateCheckoutRequest,
    CreatePortalSessionRequest,
    # Response models
    CheckoutSession,
    BillingPortalSession,
    # Helper functions
    get_plan_limits,
    get_plan_price,
    # Service
    BillingService as StandaloneBillingService,
    # Hooks
    BillingHooks,
    BillingEvent,
    BillingEventType,
    NoOpHooks,
    # Providers
    BillingProvider,
    MockBillingProvider,
    StripeBillingProvider,
    BillingProviderError,
    UsageLimitExceededError,
    # Webhooks
    WebhookHandler,
    WebhookResult,
    WebhookHandlerStatus,
    create_webhook_handler,
)

# Import the guideai-integrated service wrapper
from .service import GuideAIBillingService as BillingService
from .service import GuideAIBillingHooks

# Import FastAPI route factories
from .webhook_routes import (
    create_webhook_router,
    create_guideai_webhook_router,
    WebhookResponse,
    WebhookStatusResponse,
)
from .api import (
    create_billing_router,
    CreateCustomerRequest as APICreateCustomerRequest,
    UpdateCustomerRequest as APIUpdateCustomerRequest,
    CustomerResponse,
    CreateSubscriptionRequest as APICreateSubscriptionRequest,
    UpdateSubscriptionRequest as APIUpdateSubscriptionRequest,
    SubscriptionResponse,
    RecordUsageRequest as APIRecordUsageRequest,
    UsageResponse,
    UsageSummaryResponse,
    InvoiceResponse,
    PlanResponse,
    LimitCheckResponse,
)

__all__ = [
    # Enums
    "BillingPlan",
    "SubscriptionStatus",
    "PaymentMethodType",
    "InvoiceStatus",
    "UsageMetric",
    "WebhookEventType",
    # Plan configuration
    "PlanLimits",
    "PLAN_LIMITS",
    "PLAN_PRICING",
    "get_plan_limits",
    "get_plan_price",
    # Core models
    "Customer",
    "Subscription",
    "PaymentMethod",
    "Invoice",
    "InvoiceLineItem",
    "UsageRecord",
    "UsageAggregate",
    "UsageSummary",
    "WebhookEvent",
    "WebhookEventResult",
    # Request models
    "CreateCustomerRequest",
    "UpdateCustomerRequest",
    "CreateSubscriptionRequest",
    "UpdateSubscriptionRequest",
    "CancelSubscriptionRequest",
    "CreatePaymentMethodRequest",
    "RecordUsageRequest",
    "CreateCheckoutRequest",
    "CreatePortalSessionRequest",
    # Response models
    "CheckoutSession",
    "BillingPortalSession",
    # Service (guideai-integrated wrapper)
    "BillingService",
    "StandaloneBillingService",
    # Hooks
    "BillingHooks",
    "BillingEvent",
    "BillingEventType",
    "NoOpHooks",
    "GuideAIBillingHooks",
    # Providers
    "BillingProvider",
    "MockBillingProvider",
    "StripeBillingProvider",
    "BillingProviderError",
    "UsageLimitExceededError",
    # Webhooks
    "WebhookHandler",
    "WebhookResult",
    "WebhookHandlerStatus",
    "create_webhook_handler",
    # FastAPI Routes
    "create_webhook_router",
    "create_guideai_webhook_router",
    "create_billing_router",
    # API Response models
    "WebhookResponse",
    "WebhookStatusResponse",
    "CustomerResponse",
    "SubscriptionResponse",
    "UsageResponse",
    "UsageSummaryResponse",
    "InvoiceResponse",
    "PlanResponse",
    "LimitCheckResponse",
    # API Request models (prefixed to avoid collision with billing package)
    "APICreateCustomerRequest",
    "APIUpdateCustomerRequest",
    "APICreateSubscriptionRequest",
    "APIUpdateSubscriptionRequest",
    "APIRecordUsageRequest",
]
