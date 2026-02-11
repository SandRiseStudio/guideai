"""URL/web page ingester for research papers and articles."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from guideai.research_contracts import (
    IngestedPaper,
    PaperMetadata,
    SourceType,
)
from guideai.research.ingesters.base import (
    BaseIngester,
    count_words,
    extract_figure_captions,
    extract_table_captions,
    parse_markdown_sections,
)


class URLIngester(BaseIngester):
    """Ingester for web URLs (articles, blog posts, etc.)."""

    def __init__(self) -> None:
        self._httpx_client = None

    def can_handle(self, source: str) -> bool:
        """Check if this is a URL."""
        return source.startswith("http://") or source.startswith("https://")

    @property
    def source_type(self) -> SourceType:
        return SourceType.URL

    def _get_client(self):
        """Lazy-load httpx client."""
        if self._httpx_client is None:
            try:
                import httpx
                self._httpx_client = httpx.Client(
                    timeout=30.0,
                    follow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                    },
                )
            except ImportError:
                raise ImportError(
                    "httpx is required for URL ingestion. "
                    "Install with: pip install httpx"
                )
        return self._httpx_client

    def ingest(self, source: str, title_override: Optional[str] = None) -> IngestedPaper:
        """Ingest content from a URL.

        Args:
            source: URL to fetch
            title_override: Optional title to use instead of extracted

        Returns:
            IngestedPaper with parsed content

        Raises:
            ValueError: If URL cannot be fetched
        """
        client = self._get_client()

        try:
            response = client.get(source)
            response.raise_for_status()
        except Exception as e:
            raise ValueError(f"Failed to fetch URL: {source}. Error: {e}")

        content_type = response.headers.get("content-type", "")
        html_content = response.text

        # Parse HTML and extract main content
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ImportError(
                "beautifulsoup4 is required for URL ingestion. "
                "Install with: pip install beautifulsoup4"
            )

        soup = BeautifulSoup(html_content, "html.parser")

        # Remove script, style, nav, footer elements
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()

        # Extract title
        title = title_override
        if not title:
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text().strip()
            else:
                h1 = soup.find("h1")
                if h1:
                    title = h1.get_text().strip()
                else:
                    title = urlparse(source).netloc

        # Try to find main content area
        main_content = None
        for selector in ["article", "main", "[role='main']", ".post-content", ".article-content", ".content"]:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if not main_content:
            main_content = soup.find("body") or soup

        # Convert to text with some structure preserved
        text_content = self._html_to_text(main_content)

        # Parse into sections
        sections = parse_markdown_sections(text_content)

        # Extract metadata
        metadata = self._extract_metadata(soup, source, title)

        # Calculate confidence based on content quality
        confidence = self._calculate_confidence(text_content, sections)

        warnings: list[str] = []
        if confidence < 0.7:
            warnings.append("Low extraction confidence - content may be incomplete")
        if len(text_content) < 500:
            warnings.append("Extracted content is short - may be missing main content")

        return IngestedPaper(
            id=IngestedPaper.generate_id(),
            source=source,
            source_type=SourceType.URL,
            raw_text=text_content,
            metadata=metadata,
            sections=sections,
            figure_captions=extract_figure_captions(text_content),
            table_captions=extract_table_captions(text_content),
            word_count=count_words(text_content),
            extraction_confidence=confidence,
            warnings=warnings,
        )

    def _html_to_text(self, element) -> str:
        """Convert HTML element to text preserving some structure."""
        lines: list[str] = []

        for child in element.descendants:
            if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(child.name[1])
                text = child.get_text().strip()
                if text:
                    lines.append("")
                    lines.append("#" * level + " " + text)
                    lines.append("")
            elif child.name == "p":
                text = child.get_text().strip()
                if text:
                    lines.append(text)
                    lines.append("")
            elif child.name == "li":
                text = child.get_text().strip()
                if text:
                    lines.append(f"- {text}")
            elif child.name == "pre" or child.name == "code":
                text = child.get_text().strip()
                if text and len(text) > 10:
                    lines.append(f"```\n{text}\n```")

        # Clean up
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)  # Remove excessive newlines
        return text.strip()

    def _extract_metadata(self, soup, source: str, title: str) -> PaperMetadata:
        """Extract metadata from HTML."""
        authors: list[str] = []
        publication_date: Optional[str] = None
        abstract: Optional[str] = None

        # Try to find author meta tags
        author_meta = soup.find("meta", attrs={"name": "author"})
        if author_meta and author_meta.get("content"):
            authors = [author_meta["content"]]

        # Try to find publication date
        date_meta = soup.find("meta", attrs={"property": "article:published_time"})
        if date_meta and date_meta.get("content"):
            publication_date = date_meta["content"]
        else:
            time_tag = soup.find("time")
            if time_tag and time_tag.get("datetime"):
                publication_date = time_tag["datetime"]

        # Try to find description/abstract
        desc_meta = soup.find("meta", attrs={"name": "description"})
        if desc_meta and desc_meta.get("content"):
            abstract = desc_meta["content"]

        return PaperMetadata(
            title=title,
            authors=authors,
            source_url=source,
            publication_date=publication_date,
            abstract=abstract,
        )

    def _calculate_confidence(self, text: str, sections: list) -> float:
        """Calculate extraction confidence based on content quality."""
        confidence = 1.0

        # Penalize short content
        word_count = count_words(text)
        if word_count < 200:
            confidence -= 0.3
        elif word_count < 500:
            confidence -= 0.1

        # Penalize lack of structure
        if len(sections) < 2:
            confidence -= 0.2

        # Penalize if mostly code/special characters
        alpha_ratio = sum(c.isalpha() for c in text) / max(len(text), 1)
        if alpha_ratio < 0.5:
            confidence -= 0.2

        return max(0.1, min(1.0, confidence))
