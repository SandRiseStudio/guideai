"""GuideAI Billing Service wrapper.

This module provides a thin wrapper around the standalone billing.BillingService,
wiring hooks to guideai services for action tracking, compliance, and metrics.

The standalone package handles all billing logic; this wrapper only provides
the integration glue to guideai's infrastructure.

NOTE: The standalone billing package is REQUIRED. Install with:
    pip install -e ./packages/billing
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid
import logging

# Import from standalone billing package (required)
from billing import (
    BillingService as StandaloneBillingService,
    BillingHooks,
    BillingEvent,
    BillingEventType,
    BillingProvider,
    BillingPlan,
    Customer,
    Subscription,
    PaymentMethod,
    Invoice,
    UsageMetric,
    UsageRecord,
    UsageSummary,
    CreateCustomerRequest,
    UpdateCustomerRequest,
    CreateSubscriptionRequest,
    UpdateSubscriptionRequest,
    CancelSubscriptionRequest,
    CreatePaymentMethodRequest,
    RecordUsageRequest,
    get_plan_limits,
)

# guideai services
from guideai.action_service import ActionService
from guideai.action_contracts import ActionCreateRequest, Actor, Action
from guideai.compliance_service import ComplianceService, RecordStepRequest
from guideai.metrics_service import MetricsService

logger = logging.getLogger(__name__)


class GuideAIBillingHooks(BillingHooks):
    """Billing hooks wired to guideai services.

    Routes billing events to ActionService for audit logging,
    ComplianceService for policy checks, and MetricsService for telemetry.
    """

    def __init__(
        self,
        action_service: ActionService,
        compliance_service: Optional[ComplianceService] = None,
        metrics_service: Optional[MetricsService] = None,
        actor: Optional[Actor] = None,
    ):
        self.action_service = action_service
        self.compliance_service = compliance_service
        self.metrics_service = metrics_service
        self._default_actor = actor or Actor(
            id="billing-service",
            role="system",
            surface="api",
        )

    async def emit(self, event: BillingEvent) -> None:
        """Process a billing event and route to guideai services."""
        # Record as action for audit trail
        await self._record_action(event)

        # Emit metrics
        await self._emit_metrics(event)

        # Log event
        logger.info(
            f"Billing event: {event.type.value}",
            extra={
                "event_type": event.type.value,
                "customer_id": event.customer_id,
                "subscription_id": event.subscription_id,
                "invoice_id": event.invoice_id,
            },
        )

    async def _record_action(self, event: BillingEvent) -> None:
        """Record billing event as an action."""
        try:
            # Map billing event type to action type
            action_type = f"billing.{event.type.value.split('.')[-1]}"

            # Build action payload
            payload: Dict[str, Any] = {
                "event_type": event.type.value,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            }

            # Add entity references
            if event.customer_id:
                payload["customer_id"] = event.customer_id
            if event.subscription_id:
                payload["subscription_id"] = event.subscription_id
            if event.invoice_id:
                payload["invoice_id"] = event.invoice_id
            if event.payment_method_id:
                payload["payment_method_id"] = event.payment_method_id

            # Add event data (filtered to avoid sensitive info)
            if event.data:
                safe_data = {
                    k: v for k, v in event.data.items()
                    if k not in ("card_number", "account_number", "routing_number")
                }
                payload["data"] = safe_data

            request = ActionCreateRequest(
                action_type=action_type,
                actor=self._default_actor,
                payload=payload,
                metadata={"source": "billing_hooks"},
            )

            await self.action_service.create(request)

        except Exception as e:
            logger.warning(f"Failed to record billing action: {e}")

    async def _emit_metrics(self, event: BillingEvent) -> None:
        """Emit billing event metrics."""
        if not self.metrics_service:
            return

        try:
            # Emit event counter
            await self.metrics_service.emit(
                event_type="billing.event",
                data={
                    "event_type": event.type.value,
                    "customer_id": event.customer_id,
                    "subscription_id": event.subscription_id,
                },
            )

            # Emit specific metrics for important events
            if event.type == BillingEventType.PAYMENT_SUCCEEDED:
                amount = event.data.get("amount", 0) if event.data else 0
                await self.metrics_service.emit(
                    event_type="billing.revenue",
                    data={
                        "amount_cents": amount,
                        "customer_id": event.customer_id,
                    },
                )

            elif event.type == BillingEventType.SUBSCRIPTION_CREATED:
                plan = event.data.get("plan") if event.data else None
                await self.metrics_service.emit(
                    event_type="billing.subscription_created",
                    data={
                        "plan": plan,
                        "customer_id": event.customer_id,
                    },
                )

            elif event.type == BillingEventType.SUBSCRIPTION_CANCELED:
                await self.metrics_service.emit(
                    event_type="billing.churn",
                    data={
                        "customer_id": event.customer_id,
                        "subscription_id": event.subscription_id,
                    },
                )

            elif event.type == BillingEventType.USAGE_LIMIT_EXCEEDED:
                metric = event.data.get("metric") if event.data else None
                await self.metrics_service.emit(
                    event_type="billing.limit_exceeded",
                    data={
                        "metric": metric,
                        "customer_id": event.customer_id,
                    },
                )

        except Exception as e:
            logger.warning(f"Failed to emit billing metrics: {e}")


class GuideAIBillingService:
    """Billing service integrated with guideai infrastructure.

    This wrapper wires the standalone billing package to guideai services:
    - ActionService: Track actions for audit and replay
    - ComplianceService: Record compliance gates and steps
    - MetricsService: Emit telemetry events

    Usage:
        from guideai.billing import BillingService
        from guideai.action_service import ActionService
        from billing.providers.mock import MockBillingProvider

        provider = MockBillingProvider()
        service = BillingService(
            provider=provider,
            action_service=action_service,
        )

        customer = await service.create_customer(
            org_id="org_123",
            email="billing@acme.com",
        )
    """

    def __init__(
        self,
        provider: BillingProvider,
        action_service: ActionService,
        compliance_service: Optional[ComplianceService] = None,
        metrics_service: Optional[MetricsService] = None,
    ):
        self.action_service = action_service
        self.compliance_service = compliance_service
        self.metrics_service = metrics_service
        self.provider = provider

        # Create guideai-integrated hooks
        self._hooks = GuideAIBillingHooks(
            action_service=action_service,
            compliance_service=compliance_service,
            metrics_service=metrics_service,
        )

        # Create the standalone service with our hooks
        self._service = StandaloneBillingService(
            provider=provider,
            hooks=self._hooks,
        )

        # Default actor for service-initiated actions
        self._default_actor = Actor(
            id="billing-service",
            role="system",
            surface="api",
        )

    # =========================================================================
    # Customer Operations
    # =========================================================================

    async def create_customer(
        self,
        org_id: str,
        email: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Customer:
        """Create a billing customer for an organization.

        Args:
            org_id: Organization ID to link customer to
            email: Billing email address
            name: Customer name (defaults to org name)
            metadata: Additional metadata

        Returns:
            Created Customer
        """
        request = CreateCustomerRequest(
            org_id=org_id,
            email=email,
            name=name,
            metadata=metadata or {},
        )
        return await self._service.create_customer(request)

    async def get_customer(self, customer_id: str) -> Optional[Customer]:
        """Get customer by ID."""
        return await self._service.get_customer(customer_id)

    async def get_customer_by_org(self, org_id: str) -> Optional[Customer]:
        """Get customer by organization ID."""
        return await self._service.get_customer_by_org(org_id)

    async def update_customer(
        self,
        customer_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Customer:
        """Update customer details."""
        request = UpdateCustomerRequest(
            email=email,
            name=name,
            metadata=metadata,
        )
        return await self._service.update_customer(customer_id, request)

    # =========================================================================
    # Subscription Operations
    # =========================================================================

    async def create_subscription(
        self,
        customer_id: str,
        plan: BillingPlan,
        trial_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Subscription:
        """Create a subscription for a customer.

        Args:
            customer_id: Customer ID
            plan: Billing plan tier
            trial_days: Optional trial period in days
            metadata: Additional metadata

        Returns:
            Created Subscription
        """
        request = CreateSubscriptionRequest(
            customer_id=customer_id,
            plan=plan,
            trial_days=trial_days,
            metadata=metadata or {},
        )
        return await self._service.create_subscription(request)

    async def get_subscription(self, subscription_id: str) -> Optional[Subscription]:
        """Get subscription by ID."""
        return await self._service.get_subscription(subscription_id)

    async def get_subscription_by_customer(
        self,
        customer_id: str,
    ) -> Optional[Subscription]:
        """Get active subscription for a customer."""
        return await self._service.get_subscription_by_customer(customer_id)

    async def get_subscription_by_org(self, org_id: str) -> Optional[Subscription]:
        """Get active subscription for an organization."""
        customer = await self.get_customer_by_org(org_id)
        if not customer:
            return None
        return await self.get_subscription_by_customer(customer.id)

    async def update_subscription(
        self,
        subscription_id: str,
        plan: Optional[BillingPlan] = None,
        quantity: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Subscription:
        """Update subscription (e.g., change plan)."""
        request = UpdateSubscriptionRequest(
            plan=plan,
            quantity=quantity,
            metadata=metadata,
        )
        return await self._service.update_subscription(subscription_id, request)

    async def cancel_subscription(
        self,
        subscription_id: str,
        cancel_at_period_end: bool = True,
        reason: Optional[str] = None,
    ) -> Subscription:
        """Cancel a subscription.

        Args:
            subscription_id: Subscription ID
            cancel_at_period_end: If True, cancel at end of billing period
            reason: Optional cancellation reason

        Returns:
            Updated Subscription
        """
        request = CancelSubscriptionRequest(
            cancel_at_period_end=cancel_at_period_end,
            reason=reason,
        )
        return await self._service.cancel_subscription(subscription_id, request)

    async def reactivate_subscription(
        self,
        subscription_id: str,
    ) -> Subscription:
        """Reactivate a canceled subscription (if still in grace period)."""
        return await self._service.reactivate_subscription(subscription_id)

    # =========================================================================
    # Usage Operations
    # =========================================================================

    async def record_usage(
        self,
        subscription_id: str,
        metric: UsageMetric,
        quantity: int,
        action_id: Optional[str] = None,
        run_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> UsageRecord:
        """Record usage for metered billing.

        Args:
            subscription_id: Subscription ID
            metric: Usage metric type
            quantity: Usage amount
            action_id: Optional link to action
            run_id: Optional link to run
            idempotency_key: Key for deduplication

        Returns:
            Created UsageRecord
        """
        request = RecordUsageRequest(
            subscription_id=subscription_id,
            metric=metric,
            quantity=quantity,
            action_id=action_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
        )
        return await self._service.record_usage(request)

    async def get_usage_summary(
        self,
        subscription_id: str,
        metric: Optional[UsageMetric] = None,
    ) -> UsageSummary:
        """Get usage summary for current billing period."""
        return await self._service.get_usage_summary(subscription_id, metric)

    async def check_limit(
        self,
        subscription_id: str,
        metric: UsageMetric,
        additional_usage: int = 0,
    ) -> bool:
        """Check if usage is within plan limits.

        Args:
            subscription_id: Subscription ID
            metric: Usage metric to check
            additional_usage: Additional usage to account for

        Returns:
            True if within limits, False if would exceed
        """
        return await self._service.check_limit(
            subscription_id, metric, additional_usage
        )

    async def get_remaining_quota(
        self,
        subscription_id: str,
        metric: UsageMetric,
    ) -> int:
        """Get remaining quota for a metric.

        Returns:
            Remaining quota (negative if over limit, -1 for unlimited)
        """
        return await self._service.get_remaining_quota(subscription_id, metric)

    # =========================================================================
    # Payment Methods
    # =========================================================================

    async def get_payment_methods(
        self,
        customer_id: str,
    ) -> List[PaymentMethod]:
        """Get all payment methods for a customer."""
        return await self._service.get_payment_methods(customer_id)

    async def add_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
        set_default: bool = False,
    ) -> PaymentMethod:
        """Attach a payment method to a customer."""
        return await self._service.add_payment_method(
            customer_id, payment_method_id, set_default
        )

    async def remove_payment_method(
        self,
        payment_method_id: str,
    ) -> None:
        """Detach a payment method from a customer."""
        await self._service.remove_payment_method(payment_method_id)

    async def set_default_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
    ) -> None:
        """Set the default payment method for a customer."""
        await self._service.set_default_payment_method(
            customer_id, payment_method_id
        )

    # =========================================================================
    # Invoices
    # =========================================================================

    async def get_invoices(
        self,
        customer_id: str,
        limit: int = 10,
    ) -> List[Invoice]:
        """Get invoices for a customer."""
        return await self._service.get_invoices(customer_id, limit)

    async def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        """Get a specific invoice."""
        return await self._service.get_invoice(invoice_id)

    # =========================================================================
    # Checkout & Portal
    # =========================================================================

    async def create_checkout_session(
        self,
        customer_id: str,
        plan: BillingPlan,
        success_url: str,
        cancel_url: str,
    ):
        """Create a checkout session for plan purchase."""
        return await self._service.create_checkout_session(
            customer_id=customer_id,
            plan=plan,
            success_url=success_url,
            cancel_url=cancel_url,
        )

    async def create_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ):
        """Create a customer portal session for self-service."""
        return await self._service.create_portal_session(
            customer_id=customer_id,
            return_url=return_url,
        )

    # =========================================================================
    # Plan Helpers
    # =========================================================================

    def get_plan_limits(self, plan: BillingPlan):
        """Get limits for a billing plan."""
        return get_plan_limits(plan)

    def can_upgrade_to(
        self,
        current_plan: BillingPlan,
        target_plan: BillingPlan,
    ) -> bool:
        """Check if upgrade from current to target plan is allowed."""
        plan_order = [
            BillingPlan.FREE,
            BillingPlan.STARTER,
            BillingPlan.TEAM,
            BillingPlan.ENTERPRISE,
        ]
        return plan_order.index(target_plan) > plan_order.index(current_plan)

    def can_downgrade_to(
        self,
        current_plan: BillingPlan,
        target_plan: BillingPlan,
    ) -> bool:
        """Check if downgrade from current to target plan is allowed."""
        plan_order = [
            BillingPlan.FREE,
            BillingPlan.STARTER,
            BillingPlan.TEAM,
            BillingPlan.ENTERPRISE,
        ]
        return plan_order.index(target_plan) < plan_order.index(current_plan)
