"""FastAPI routes for billing API.

Following: behavior_design_api_contract

Provides REST API endpoints for billing operations:
- Customer management (CRUD)
- Subscription management
- Usage tracking and limits
- Invoice retrieval

All routes use consistent patterns matching CLI and MCP surfaces.
"""

from __future__ import annotations

import logging
from typing import Optional, List, Callable, Awaitable, Any
from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, Query, Path
from pydantic import BaseModel, Field, EmailStr

from billing import (
    BillingPlan,
    SubscriptionStatus,
    UsageMetric,
    Customer,
    Subscription,
    Invoice,
    UsageRecord,
    UsageAggregate,
    BillingService,
    PLAN_LIMITS,
    PLAN_PRICING,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Request/Response Models
# =============================================================================

class CreateCustomerRequest(BaseModel):
    """Request model for creating a customer."""

    org_id: str = Field(..., description="Organization ID")
    email: EmailStr = Field(..., description="Customer email")
    name: Optional[str] = Field(None, description="Customer name")
    metadata: Optional[dict] = Field(None, description="Additional metadata")


class UpdateCustomerRequest(BaseModel):
    """Request model for updating a customer."""

    email: Optional[EmailStr] = Field(None, description="Updated email")
    name: Optional[str] = Field(None, description="Updated name")
    metadata: Optional[dict] = Field(None, description="Updated metadata")


class CustomerResponse(BaseModel):
    """Response model for customer."""

    id: str
    org_id: str
    email: str
    name: Optional[str]
    provider_customer_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreateSubscriptionRequest(BaseModel):
    """Request model for creating a subscription."""

    customer_id: str = Field(..., description="Customer ID")
    plan: BillingPlan = Field(..., description="Billing plan")
    trial_days: Optional[int] = Field(None, description="Trial period days", ge=0, le=90)
    metadata: Optional[dict] = Field(None, description="Additional metadata")


class UpdateSubscriptionRequest(BaseModel):
    """Request model for updating a subscription."""

    plan: Optional[BillingPlan] = Field(None, description="New plan")
    status: Optional[SubscriptionStatus] = Field(None, description="New status")


class SubscriptionResponse(BaseModel):
    """Response model for subscription."""

    id: str
    customer_id: str
    plan: BillingPlan
    status: SubscriptionStatus
    current_period_start: datetime
    current_period_end: datetime
    trial_end: Optional[datetime]
    cancel_at_period_end: bool
    canceled_at: Optional[datetime]
    provider_subscription_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RecordUsageRequest(BaseModel):
    """Request model for recording usage."""

    subscription_id: str = Field(..., description="Subscription ID")
    metric: UsageMetric = Field(..., description="Usage metric")
    quantity: int = Field(..., description="Quantity used", ge=0)
    idempotency_key: Optional[str] = Field(None, description="Idempotency key")
    metadata: Optional[dict] = Field(None, description="Additional metadata")


class UsageResponse(BaseModel):
    """Response model for usage record."""

    id: str
    subscription_id: str
    metric: UsageMetric
    quantity: int
    timestamp: datetime
    idempotency_key: Optional[str]

    class Config:
        from_attributes = True


class UsageSummaryResponse(BaseModel):
    """Response model for usage summary."""

    metric: UsageMetric
    total: int
    limit: Optional[int]
    percentage_used: float
    period_start: datetime
    period_end: datetime


class InvoiceResponse(BaseModel):
    """Response model for invoice."""

    id: str
    customer_id: str
    subscription_id: Optional[str]
    amount_due: int
    amount_paid: int
    currency: str
    status: str
    period_start: datetime
    period_end: datetime
    due_date: Optional[datetime]
    paid_at: Optional[datetime]
    hosted_invoice_url: Optional[str]
    pdf_url: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class PlanResponse(BaseModel):
    """Response model for billing plan info."""

    plan: BillingPlan
    name: str
    price_monthly: int
    price_annual: Optional[int]
    limits: dict


class LimitCheckResponse(BaseModel):
    """Response model for limit check."""

    metric: UsageMetric
    allowed: bool
    current_usage: int
    limit: Optional[int]
    message: str


# =============================================================================
# Route Factory
# =============================================================================

def create_billing_router(
    billing_service: BillingService,
) -> APIRouter:
    """Create FastAPI router for billing API.

    Args:
        billing_service: BillingService instance

    Returns:
        APIRouter with billing endpoints

    Example:
        from fastapi import FastAPI
        from billing import BillingService, MockBillingProvider

        app = FastAPI()
        provider = MockBillingProvider()
        service = BillingService(provider=provider)

        router = create_billing_router(service)
        app.include_router(router)
    """
    router = APIRouter(prefix="/v1/billing", tags=["billing"])

    # -------------------------------------------------------------------------
    # Customer Endpoints
    # -------------------------------------------------------------------------

    @router.post(
        "/customers",
        response_model=CustomerResponse,
        status_code=201,
        summary="Create customer",
        description="Create a new billing customer for an organization.",
    )
    async def create_customer(request: CreateCustomerRequest) -> CustomerResponse:
        """Create a new billing customer."""
        try:
            customer = await billing_service.create_customer(
                org_id=request.org_id,
                email=request.email,
                name=request.name,
                metadata=request.metadata,
            )
            return CustomerResponse(
                id=customer.id,
                org_id=customer.org_id,
                email=customer.email,
                name=customer.name,
                provider_customer_id=customer.provider_customer_id,
                created_at=customer.created_at,
                updated_at=customer.updated_at,
            )
        except Exception as e:
            logger.exception("Failed to create customer")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/customers/{customer_id}",
        response_model=CustomerResponse,
        summary="Get customer",
        description="Get a billing customer by ID.",
    )
    async def get_customer(
        customer_id: str = Path(..., description="Customer ID"),
    ) -> CustomerResponse:
        """Get a customer by ID."""
        customer = await billing_service.get_customer(customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return CustomerResponse(
            id=customer.id,
            org_id=customer.org_id,
            email=customer.email,
            name=customer.name,
            provider_customer_id=customer.provider_customer_id,
            created_at=customer.created_at,
            updated_at=customer.updated_at,
        )

    @router.get(
        "/customers/org/{org_id}",
        response_model=CustomerResponse,
        summary="Get customer by org",
        description="Get a billing customer by organization ID.",
    )
    async def get_customer_by_org(
        org_id: str = Path(..., description="Organization ID"),
    ) -> CustomerResponse:
        """Get a customer by organization ID."""
        customer = await billing_service.get_customer_by_org(org_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return CustomerResponse(
            id=customer.id,
            org_id=customer.org_id,
            email=customer.email,
            name=customer.name,
            provider_customer_id=customer.provider_customer_id,
            created_at=customer.created_at,
            updated_at=customer.updated_at,
        )

    @router.patch(
        "/customers/{customer_id}",
        response_model=CustomerResponse,
        summary="Update customer",
        description="Update a billing customer.",
    )
    async def update_customer(
        request: UpdateCustomerRequest,
        customer_id: str = Path(..., description="Customer ID"),
    ) -> CustomerResponse:
        """Update a customer."""
        customer = await billing_service.update_customer(
            customer_id=customer_id,
            email=request.email,
            name=request.name,
            metadata=request.metadata,
        )
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return CustomerResponse(
            id=customer.id,
            org_id=customer.org_id,
            email=customer.email,
            name=customer.name,
            provider_customer_id=customer.provider_customer_id,
            created_at=customer.created_at,
            updated_at=customer.updated_at,
        )

    # -------------------------------------------------------------------------
    # Subscription Endpoints
    # -------------------------------------------------------------------------

    @router.post(
        "/subscriptions",
        response_model=SubscriptionResponse,
        status_code=201,
        summary="Create subscription",
        description="Create a new subscription for a customer.",
    )
    async def create_subscription(
        request: CreateSubscriptionRequest,
    ) -> SubscriptionResponse:
        """Create a new subscription."""
        try:
            subscription = await billing_service.create_subscription(
                customer_id=request.customer_id,
                plan=request.plan,
                trial_days=request.trial_days,
                metadata=request.metadata,
            )
            return SubscriptionResponse(
                id=subscription.id,
                customer_id=subscription.customer_id,
                plan=subscription.plan,
                status=subscription.status,
                current_period_start=subscription.current_period_start,
                current_period_end=subscription.current_period_end,
                trial_end=subscription.trial_end,
                cancel_at_period_end=subscription.cancel_at_period_end,
                canceled_at=subscription.canceled_at,
                provider_subscription_id=subscription.provider_subscription_id,
                created_at=subscription.created_at,
                updated_at=subscription.updated_at,
            )
        except Exception as e:
            logger.exception("Failed to create subscription")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/subscriptions/{subscription_id}",
        response_model=SubscriptionResponse,
        summary="Get subscription",
        description="Get a subscription by ID.",
    )
    async def get_subscription(
        subscription_id: str = Path(..., description="Subscription ID"),
    ) -> SubscriptionResponse:
        """Get a subscription by ID."""
        subscription = await billing_service.get_subscription(subscription_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return SubscriptionResponse(
            id=subscription.id,
            customer_id=subscription.customer_id,
            plan=subscription.plan,
            status=subscription.status,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            trial_end=subscription.trial_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            canceled_at=subscription.canceled_at,
            provider_subscription_id=subscription.provider_subscription_id,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

    @router.get(
        "/subscriptions/customer/{customer_id}",
        response_model=SubscriptionResponse,
        summary="Get subscription by customer",
        description="Get active subscription for a customer.",
    )
    async def get_subscription_by_customer(
        customer_id: str = Path(..., description="Customer ID"),
    ) -> SubscriptionResponse:
        """Get active subscription for a customer."""
        subscription = await billing_service.get_subscription_by_customer(customer_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return SubscriptionResponse(
            id=subscription.id,
            customer_id=subscription.customer_id,
            plan=subscription.plan,
            status=subscription.status,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            trial_end=subscription.trial_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            canceled_at=subscription.canceled_at,
            provider_subscription_id=subscription.provider_subscription_id,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

    @router.patch(
        "/subscriptions/{subscription_id}/plan",
        response_model=SubscriptionResponse,
        summary="Change plan",
        description="Change a subscription's plan.",
    )
    async def change_plan(
        subscription_id: str = Path(..., description="Subscription ID"),
        new_plan: BillingPlan = Query(..., description="New plan"),
    ) -> SubscriptionResponse:
        """Change a subscription's plan."""
        subscription = await billing_service.change_plan(
            subscription_id=subscription_id,
            new_plan=new_plan,
        )
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return SubscriptionResponse(
            id=subscription.id,
            customer_id=subscription.customer_id,
            plan=subscription.plan,
            status=subscription.status,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            trial_end=subscription.trial_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            canceled_at=subscription.canceled_at,
            provider_subscription_id=subscription.provider_subscription_id,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

    @router.post(
        "/subscriptions/{subscription_id}/cancel",
        response_model=SubscriptionResponse,
        summary="Cancel subscription",
        description="Cancel a subscription.",
    )
    async def cancel_subscription(
        subscription_id: str = Path(..., description="Subscription ID"),
        immediate: bool = Query(False, description="Cancel immediately"),
    ) -> SubscriptionResponse:
        """Cancel a subscription."""
        subscription = await billing_service.cancel_subscription(
            subscription_id=subscription_id,
            immediate=immediate,
        )
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return SubscriptionResponse(
            id=subscription.id,
            customer_id=subscription.customer_id,
            plan=subscription.plan,
            status=subscription.status,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            trial_end=subscription.trial_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            canceled_at=subscription.canceled_at,
            provider_subscription_id=subscription.provider_subscription_id,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

    @router.post(
        "/subscriptions/{subscription_id}/resume",
        response_model=SubscriptionResponse,
        summary="Resume subscription",
        description="Resume a canceled subscription before period end.",
    )
    async def resume_subscription(
        subscription_id: str = Path(..., description="Subscription ID"),
    ) -> SubscriptionResponse:
        """Resume a canceled subscription."""
        subscription = await billing_service.resume_subscription(subscription_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return SubscriptionResponse(
            id=subscription.id,
            customer_id=subscription.customer_id,
            plan=subscription.plan,
            status=subscription.status,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            trial_end=subscription.trial_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            canceled_at=subscription.canceled_at,
            provider_subscription_id=subscription.provider_subscription_id,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

    # -------------------------------------------------------------------------
    # Usage Endpoints
    # -------------------------------------------------------------------------

    @router.post(
        "/usage",
        response_model=UsageResponse,
        status_code=201,
        summary="Record usage",
        description="Record usage for a subscription.",
    )
    async def record_usage(request: RecordUsageRequest) -> UsageResponse:
        """Record usage for a subscription."""
        try:
            record = await billing_service.record_usage(
                subscription_id=request.subscription_id,
                metric=request.metric,
                quantity=request.quantity,
                idempotency_key=request.idempotency_key,
                metadata=request.metadata,
            )
            return UsageResponse(
                id=record.id,
                subscription_id=record.subscription_id,
                metric=record.metric,
                quantity=record.quantity,
                timestamp=record.timestamp,
                idempotency_key=record.idempotency_key,
            )
        except Exception as e:
            logger.exception("Failed to record usage")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/usage/{subscription_id}",
        response_model=list[UsageSummaryResponse],
        summary="Get usage summary",
        description="Get usage summary for a subscription.",
    )
    async def get_usage_summary(
        subscription_id: str = Path(..., description="Subscription ID"),
    ) -> list[UsageSummaryResponse]:
        """Get usage summary for a subscription."""
        subscription = await billing_service.get_subscription(subscription_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        summaries = []
        limits = PLAN_LIMITS.get(subscription.plan, {})

        for metric in UsageMetric:
            usage = await billing_service.get_usage(
                subscription_id=subscription_id,
                metric=metric,
            )
            limit = limits.get(metric.value)
            percentage = (usage / limit * 100) if limit else 0

            summaries.append(UsageSummaryResponse(
                metric=metric,
                total=usage,
                limit=limit,
                percentage_used=percentage,
                period_start=subscription.current_period_start,
                period_end=subscription.current_period_end,
            ))

        return summaries

    @router.get(
        "/usage/{subscription_id}/check",
        response_model=LimitCheckResponse,
        summary="Check usage limit",
        description="Check if usage is within limits for a metric.",
    )
    async def check_limit(
        subscription_id: str = Path(..., description="Subscription ID"),
        metric: UsageMetric = Query(..., description="Usage metric"),
        quantity: int = Query(1, description="Quantity to check", ge=1),
    ) -> LimitCheckResponse:
        """Check if usage is within limits."""
        allowed, current, limit = await billing_service.check_limit(
            subscription_id=subscription_id,
            metric=metric,
            quantity=quantity,
        )

        if allowed:
            message = f"Usage allowed ({current + quantity} / {limit if limit else '∞'})"
        else:
            message = f"Usage would exceed limit ({current + quantity} > {limit})"

        return LimitCheckResponse(
            metric=metric,
            allowed=allowed,
            current_usage=current,
            limit=limit,
            message=message,
        )

    # -------------------------------------------------------------------------
    # Invoice Endpoints
    # -------------------------------------------------------------------------

    @router.get(
        "/invoices/{customer_id}",
        response_model=list[InvoiceResponse],
        summary="Get invoices",
        description="Get invoices for a customer.",
    )
    async def get_invoices(
        customer_id: str = Path(..., description="Customer ID"),
        limit: int = Query(10, description="Number of invoices", ge=1, le=100),
        starting_after: Optional[str] = Query(None, description="Cursor for pagination"),
    ) -> list[InvoiceResponse]:
        """Get invoices for a customer."""
        invoices = await billing_service.get_invoices(
            customer_id=customer_id,
            limit=limit,
            starting_after=starting_after,
        )
        return [
            InvoiceResponse(
                id=invoice.id,
                customer_id=invoice.customer_id,
                subscription_id=invoice.subscription_id,
                amount_due=invoice.amount_due,
                amount_paid=invoice.amount_paid,
                currency=invoice.currency,
                status=invoice.status,
                period_start=invoice.period_start,
                period_end=invoice.period_end,
                due_date=invoice.due_date,
                paid_at=invoice.paid_at,
                hosted_invoice_url=invoice.hosted_invoice_url,
                pdf_url=invoice.pdf_url,
                created_at=invoice.created_at,
            )
            for invoice in invoices
        ]

    # -------------------------------------------------------------------------
    # Plan Information Endpoints
    # -------------------------------------------------------------------------

    @router.get(
        "/plans",
        response_model=list[PlanResponse],
        summary="Get plans",
        description="Get all available billing plans.",
    )
    async def get_plans() -> list[PlanResponse]:
        """Get all available billing plans."""
        plans = []
        plan_names = {
            BillingPlan.FREE: "Free",
            BillingPlan.STARTER: "Starter",
            BillingPlan.TEAM: "Team",
            BillingPlan.ENTERPRISE: "Enterprise",
        }

        for plan in BillingPlan:
            pricing = PLAN_PRICING.get(plan, {})
            limits = PLAN_LIMITS.get(plan, {})

            plans.append(PlanResponse(
                plan=plan,
                name=plan_names.get(plan, plan.value.title()),
                price_monthly=pricing.get("monthly", 0),
                price_annual=pricing.get("annual"),
                limits=limits,
            ))

        return plans

    @router.get(
        "/plans/{plan}",
        response_model=PlanResponse,
        summary="Get plan details",
        description="Get details for a specific billing plan.",
    )
    async def get_plan(
        plan: BillingPlan = Path(..., description="Billing plan"),
    ) -> PlanResponse:
        """Get details for a specific billing plan."""
        plan_names = {
            BillingPlan.FREE: "Free",
            BillingPlan.STARTER: "Starter",
            BillingPlan.TEAM: "Team",
            BillingPlan.ENTERPRISE: "Enterprise",
        }

        pricing = PLAN_PRICING.get(plan, {})
        limits = PLAN_LIMITS.get(plan, {})

        return PlanResponse(
            plan=plan,
            name=plan_names.get(plan, plan.value.title()),
            price_monthly=pricing.get("monthly", 0),
            price_annual=pricing.get("annual"),
            limits=limits,
        )

    return router
