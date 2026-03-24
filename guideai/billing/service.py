"""GuideAI Billing service wrapper - OSS Stub.

Full implementation in guideai-enterprise.
Install guideai-enterprise[billing] for GuideAI billing integration.
"""

try:
    from guideai_enterprise.billing.service import (
        GuideAIBillingService,
        GuideAIBillingHooks,
    )
except ImportError:
    GuideAIBillingService = None  # type: ignore[assignment,misc]
    GuideAIBillingHooks = None  # type: ignore[assignment,misc]
