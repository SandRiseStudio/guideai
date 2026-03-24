"""URL ingester - OSS Stub. Full implementation in guideai-enterprise."""

try:
    from guideai_enterprise.research.ingesters.url_ingester import URLIngester
except ImportError:
    URLIngester = None  # type: ignore[assignment,misc]
