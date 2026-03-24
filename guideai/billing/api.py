"""Billing API routes - OSS Stub.

Full implementation in guideai-enterprise.
Install guideai-enterprise[billing] for billing API routes.
"""

try:
    from guideai_enterprise.billing.api import (
        create_billing_router,
        CreateCustomerRequest,
        UpdateCustomerRequest,
        CustomerResponse,
        CreateSubscriptionRequest,
        UpdateSubscriptionRequest,
        SubscriptionResponse,
        RecordUsageRequest,
        UsageResponse,
        UsageSummaryResponse,
        InvoiceResponse,
        PlanResponse,
        LimitCheckResponse,
    )
except ImportError:
    create_billing_router = None  # type: ignore[assignment]
