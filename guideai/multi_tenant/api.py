"""Organization management API routes — enterprise feature.

Full implementation available in guideai-enterprise package.
Install: pip install guideai-enterprise
"""

try:
    from guideai_enterprise.multi_tenant.api import create_org_routes
except ImportError:
    def create_org_routes(*args, **kwargs):
        """No-op: org management routes require guideai-enterprise."""
        raise ImportError(
            "Organization management API requires guideai-enterprise. "
            "Install: pip install guideai-enterprise"
        )

__all__ = ["create_org_routes"]
