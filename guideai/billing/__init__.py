"""GuideAI Billing integration — OSS Stub.

The enterprise billing wrappers (GuideAIBillingService, API routes, webhooks)
have moved to guideai-enterprise. The standalone billing package at
packages/billing/ remains available for provider-agnostic billing.

For standalone usage:
    pip install -e ./packages/billing
    from billing import BillingService
    from billing.providers.mock import MockBillingProvider

For enterprise integration:
    pip install guideai-enterprise[billing]
"""

# Re-export models from standalone package (stays in OSS)
try:
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
    _BILLING_PKG_AVAILABLE = True
except ImportError:
    _BILLING_PKG_AVAILABLE = False

# Enterprise integration wrappers (moved to guideai-enterprise)
try:
    from guideai_enterprise.billing.service import (
        GuideAIBillingService as BillingService,
        GuideAIBillingHooks,
    )
    from guideai_enterprise.billing.webhook_routes import (
        create_webhook_router,
        create_guideai_webhook_router,
        WebhookResponse,
        WebhookStatusResponse,
    )
    from guideai_enterprise.billing.api import (
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
except ImportError:
    # Enterprise not installed — billing wrappers unavailable
    BillingService = None  # type: ignore[assignment,misc]
    GuideAIBillingHooks = None  # type: ignore[assignment,misc]
    create_webhook_router = None  # type: ignore[assignment]
    create_guideai_webhook_router = None  # type: ignore[assignment]
    create_billing_router = None  # type: ignore[assignment]

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
