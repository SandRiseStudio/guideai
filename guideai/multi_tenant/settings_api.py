"""Settings API routes — enterprise feature.

Full implementation available in guideai-enterprise package.
Install: pip install guideai-enterprise
"""

try:
    from guideai_enterprise.multi_tenant.settings_api import create_settings_routes
except ImportError:
    def create_settings_routes(*args, **kwargs):
        """No-op: settings routes require guideai-enterprise."""
        raise ImportError(
            "Settings API requires guideai-enterprise. "
            "Install: pip install guideai-enterprise"
        )

__all__ = ["create_settings_routes"]
