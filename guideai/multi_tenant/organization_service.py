"""Organization service — enterprise feature.

Full implementation available in guideai-enterprise package.
Install: pip install guideai-enterprise
"""

try:
    from guideai_enterprise.multi_tenant.organization_service import OrganizationService
except ImportError:
    OrganizationService = None

__all__ = ["OrganizationService"]
