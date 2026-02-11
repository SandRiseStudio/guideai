"""Research paper ingesters for various source types."""

from guideai.research.ingesters.base import (
    BaseIngester,
    count_words,
    extract_figure_captions,
    extract_metadata_from_markdown,
    extract_table_captions,
    parse_markdown_sections,
)
from guideai.research.ingesters.markdown_ingester import MarkdownIngester
from guideai.research.ingesters.url_ingester import URLIngester
from guideai.research.ingesters.pdf_ingester import PDFIngester

__all__ = [
    # Base
    "BaseIngester",
    "count_words",
    "extract_figure_captions",
    "extract_metadata_from_markdown",
    "extract_table_captions",
    "parse_markdown_sections",
    # Ingesters
    "MarkdownIngester",
    "URLIngester",
    "PDFIngester",
]
