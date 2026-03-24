"""Report renderer - OSS Stub. Full implementation in guideai-enterprise."""

try:
    from guideai_enterprise.research.report import render_report
except ImportError:
    def render_report(*args, **kwargs):
        raise ImportError(
            "Research report rendering requires guideai-enterprise[research]. "
            "Install with: pip install guideai-enterprise[research]"
        )
