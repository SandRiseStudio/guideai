"""PDF file ingester for research papers using PyMuPDF."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import re

from guideai.research_contracts import (
    IngestedPaper,
    PaperMetadata,
    ParsedSection,
    SourceType,
)
from guideai.research.ingesters.base import (
    BaseIngester,
    count_words,
)


class PDFIngester(BaseIngester):
    """Ingester for PDF files using PyMuPDF (fitz)."""

    def can_handle(self, source: str) -> bool:
        """Check if this is a PDF file."""
        if source.startswith("http://") or source.startswith("https://"):
            return source.lower().endswith(".pdf")

        path = Path(source)
        return path.suffix.lower() == ".pdf"

    @property
    def source_type(self) -> SourceType:
        return SourceType.PDF

    def ingest(self, source: str, title_override: Optional[str] = None) -> IngestedPaper:
        """Ingest a PDF file.

        Args:
            source: Path to the PDF file
            title_override: Optional title to use instead of extracted

        Returns:
            IngestedPaper with parsed content

        Raises:
            FileNotFoundError: If file doesn't exist
            ImportError: If pymupdf is not installed
            ValueError: If PDF cannot be parsed
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError(
                "pymupdf is required for PDF ingestion. "
                "Install with: pip install pymupdf"
            )

        path = Path(source)

        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        warnings: list[str] = []

        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise ValueError(f"Failed to open PDF: {source}. Error: {e}")

        try:
            # Extract text from all pages
            all_text: list[str] = []
            for page_num, page in enumerate(doc):
                text = page.get_text("text")
                all_text.append(text)

            full_text = "\n\n".join(all_text)

            # Extract metadata from PDF
            pdf_metadata = doc.metadata

            # Build our metadata
            title = title_override or pdf_metadata.get("title") or "Untitled"
            if title == "Untitled" or not title.strip():
                # Try to extract from first page content
                first_lines = all_text[0].split("\n")[:10] if all_text else []
                for line in first_lines:
                    line = line.strip()
                    if len(line) > 10 and len(line) < 200:
                        title = line
                        break

            authors: list[str] = []
            if pdf_metadata.get("author"):
                # Split common author separators
                author_str = pdf_metadata["author"]
                authors = re.split(r"[,;&]|\band\b", author_str)
                authors = [a.strip() for a in authors if a.strip()]

            metadata = PaperMetadata(
                title=title,
                authors=authors,
                source_url=str(path.absolute()),
                publication_date=pdf_metadata.get("creationDate"),
            )

            # Parse sections (look for common heading patterns)
            sections = self._parse_sections(full_text)

            # Extract figure and table captions
            figure_captions = self._extract_captions(full_text, "figure")
            table_captions = self._extract_captions(full_text, "table")

            # Calculate confidence
            confidence = self._calculate_confidence(full_text, doc)

            if confidence < 0.7:
                warnings.append("Low extraction confidence - PDF may have complex layout")

            if len(full_text) < 1000:
                warnings.append("Extracted text is short - PDF may be image-based")

            return IngestedPaper(
                id=IngestedPaper.generate_id(),
                source=str(path.absolute()),
                source_type=SourceType.PDF,
                raw_text=full_text,
                metadata=metadata,
                sections=sections,
                figure_captions=figure_captions,
                table_captions=table_captions,
                word_count=count_words(full_text),
                extraction_confidence=confidence,
                warnings=warnings,
            )

        finally:
            doc.close()

    def _parse_sections(self, text: str) -> list[ParsedSection]:
        """Parse sections from PDF text.

        Looks for common academic paper section headings.
        """
        sections: list[ParsedSection] = []

        # Common section headings in academic papers
        section_patterns = [
            r"^(?:I+\.?\s+)?(Abstract)(?:\s|$)",
            r"^(?:\d+\.?\s+)?(Introduction)(?:\s|$)",
            r"^(?:\d+\.?\s+)?(Related Work|Background|Literature Review)(?:\s|$)",
            r"^(?:\d+\.?\s+)?(Method(?:s|ology)?|Approach)(?:\s|$)",
            r"^(?:\d+\.?\s+)?(Experiment(?:s)?|Evaluation)(?:\s|$)",
            r"^(?:\d+\.?\s+)?(Result(?:s)?)(?:\s|$)",
            r"^(?:\d+\.?\s+)?(Discussion)(?:\s|$)",
            r"^(?:\d+\.?\s+)?(Conclusion(?:s)?)(?:\s|$)",
            r"^(?:\d+\.?\s+)?(Reference(?:s)?|Bibliography)(?:\s|$)",
            r"^(?:\d+\.?\s+)?(Appendix|Appendices)(?:\s|$)",
        ]

        lines = text.split("\n")
        current_section_name = "Preamble"
        current_section_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            matched = False

            for pattern in section_patterns:
                match = re.match(pattern, stripped, re.IGNORECASE)
                if match:
                    # Save previous section
                    if current_section_lines:
                        content = "\n".join(current_section_lines).strip()
                        if content:
                            sections.append(ParsedSection(
                                name=current_section_name,
                                content=content,
                                level=1,
                            ))

                    current_section_name = match.group(1)
                    current_section_lines = []
                    matched = True
                    break

            if not matched:
                current_section_lines.append(line)

        # Don't forget last section
        if current_section_lines:
            content = "\n".join(current_section_lines).strip()
            if content:
                sections.append(ParsedSection(
                    name=current_section_name,
                    content=content,
                    level=1,
                ))

        return sections

    def _extract_captions(self, text: str, caption_type: str) -> list[str]:
        """Extract figure or table captions from text."""
        captions: list[str] = []

        # Pattern: "Figure 1: Caption text" or "Table 1. Caption text"
        pattern = rf"{caption_type}\s+\d+[.:]\s*([^\n]+)"

        for match in re.finditer(pattern, text, re.IGNORECASE):
            caption = match.group(1).strip()
            if caption:
                captions.append(f"{caption_type.title()}: {caption}")

        return captions

    def _calculate_confidence(self, text: str, doc) -> float:
        """Calculate extraction confidence."""
        confidence = 1.0

        # Penalize short text (might be image-based PDF)
        word_count = count_words(text)
        pages = len(doc)
        words_per_page = word_count / max(pages, 1)

        if words_per_page < 100:
            confidence -= 0.3
        elif words_per_page < 200:
            confidence -= 0.1

        # Check for garbled text (encoding issues)
        weird_char_ratio = sum(1 for c in text if ord(c) > 10000) / max(len(text), 1)
        if weird_char_ratio > 0.1:
            confidence -= 0.2

        # Check for excessive whitespace (layout issues)
        whitespace_ratio = sum(1 for c in text if c.isspace()) / max(len(text), 1)
        if whitespace_ratio > 0.5:
            confidence -= 0.1

        return max(0.1, min(1.0, confidence))
