"""Invitation service — enterprise feature.

Full implementation available in guideai-enterprise package.
Install: pip install guideai-enterprise
"""

try:
    from guideai_enterprise.multi_tenant.invitation_service import InvitationService
except ImportError:
    InvitationService = None

__all__ = ["InvitationService"]
