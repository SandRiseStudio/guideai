"""Markdown file ingester for research papers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from guideai.research_contracts import (
    IngestedPaper,
    SourceType,
)
from guideai.research.ingesters.base import (
    BaseIngester,
    count_words,
    extract_figure_captions,
    extract_metadata_from_markdown,
    extract_table_captions,
    parse_markdown_sections,
)


class MarkdownIngester(BaseIngester):
    """Ingester for local markdown files."""

    def can_handle(self, source: str) -> bool:
        """Check if this is a markdown file path."""
        if source.startswith("http://") or source.startswith("https://"):
            return False

        path = Path(source)
        return path.suffix.lower() in (".md", ".markdown", ".txt")

    @property
    def source_type(self) -> SourceType:
        return SourceType.MARKDOWN

    def ingest(self, source: str, title_override: Optional[str] = None) -> IngestedPaper:
        """Ingest a markdown file.

        Args:
            source: Path to the markdown file
            title_override: Optional title to use instead of extracted

        Returns:
            IngestedPaper with parsed content

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file cannot be read
        """
        path = Path(source)

        if not path.exists():
            raise FileNotFoundError(f"Markdown file not found: {source}")

        if not path.is_file():
            raise ValueError(f"Source is not a file: {source}")

        # Read content
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Try with latin-1 as fallback
            content = path.read_text(encoding="latin-1")

        # Parse sections
        sections = parse_markdown_sections(content)

        # Extract metadata
        metadata = extract_metadata_from_markdown(content, source)
        if title_override:
            metadata.title = title_override

        # Extract figures and tables
        figure_captions = extract_figure_captions(content)
        table_captions = extract_table_captions(content)

        # Build result
        paper = IngestedPaper(
            id=IngestedPaper.generate_id(),
            source=str(path.absolute()),
            source_type=SourceType.MARKDOWN,
            raw_text=content,
            metadata=metadata,
            sections=sections,
            figure_captions=figure_captions,
            table_captions=table_captions,
            word_count=count_words(content),
            extraction_confidence=1.0,  # Markdown is lossless
            warnings=[],
        )

        return paper
