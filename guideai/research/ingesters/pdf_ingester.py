"""PDF ingester - OSS Stub. Full implementation in guideai-enterprise."""

try:
    from guideai_enterprise.research.ingesters.pdf_ingester import PDFIngester
except ImportError:
    PDFIngester = None  # type: ignore[assignment,misc]
