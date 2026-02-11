"""Base ingester interface and common utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import re

from guideai.research_contracts import (
    IngestedPaper,
    PaperMetadata,
    ParsedSection,
    SourceType,
)


class BaseIngester(ABC):
    """Abstract base class for research paper ingesters."""

    @abstractmethod
    def can_handle(self, source: str) -> bool:
        """Check if this ingester can handle the given source."""
        pass

    @abstractmethod
    def ingest(self, source: str, title_override: Optional[str] = None) -> IngestedPaper:
        """Ingest a research paper from the source."""
        pass

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """Return the source type this ingester handles."""
        pass


def parse_markdown_sections(content: str) -> list[ParsedSection]:
    """Parse markdown content into sections based on headings.

    Args:
        content: Raw markdown text

    Returns:
        List of ParsedSection objects
    """
    sections: list[ParsedSection] = []
    lines = content.split("\n")

    current_section_name = "Introduction"
    current_section_level = 1
    current_section_lines: list[str] = []

    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

    for line in lines:
        match = heading_pattern.match(line)
        if match:
            # Save previous section if it has content
            if current_section_lines:
                section_content = "\n".join(current_section_lines).strip()
                if section_content:
                    sections.append(ParsedSection(
                        name=current_section_name,
                        content=section_content,
                        level=current_section_level,
                    ))

            # Start new section
            current_section_level = len(match.group(1))
            current_section_name = match.group(2).strip()
            current_section_lines = []
        else:
            current_section_lines.append(line)

    # Don't forget the last section
    if current_section_lines:
        section_content = "\n".join(current_section_lines).strip()
        if section_content:
            sections.append(ParsedSection(
                name=current_section_name,
                content=section_content,
                level=current_section_level,
            ))

    return sections


def extract_metadata_from_markdown(content: str, source: str) -> PaperMetadata:
    """Extract metadata from markdown content.

    Looks for common patterns like YAML frontmatter, title headings, etc.
    """
    title = "Untitled"
    authors: list[str] = []
    abstract: Optional[str] = None

    lines = content.split("\n")

    # Try to find title from first H1
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Try to find abstract section
    in_abstract = False
    abstract_lines: list[str] = []
    for line in lines:
        lower_line = line.lower()
        if "abstract" in lower_line and line.startswith("#"):
            in_abstract = True
            continue
        elif in_abstract:
            if line.startswith("#"):
                break
            abstract_lines.append(line)

    if abstract_lines:
        abstract = "\n".join(abstract_lines).strip()

    # Try to extract authors (common patterns)
    for line in lines:
        if "author" in line.lower() or "by " in line.lower():
            # Simple extraction - could be improved
            potential_authors = re.findall(r"[A-Z][a-z]+ [A-Z][a-z]+", line)
            authors.extend(potential_authors[:5])  # Limit to 5
            break

    return PaperMetadata(
        title=title,
        authors=authors,
        source_url=source if source.startswith("http") else None,
        abstract=abstract,
    )


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def extract_figure_captions(content: str) -> list[str]:
    """Extract figure captions from markdown.

    Looks for patterns like:
    - ![Figure 1: Caption](...)
    - **Figure 1**: Caption
    - Figure 1. Caption
    """
    captions: list[str] = []

    # Pattern for markdown image with caption
    img_pattern = re.compile(r"!\[([^\]]*[Ff]igure[^\]]*)\]")
    for match in img_pattern.finditer(content):
        captions.append(match.group(1))

    # Pattern for bold figure references
    bold_pattern = re.compile(r"\*\*[Ff]igure\s+\d+[^*]*\*\*:?\s*([^\n]+)")
    for match in bold_pattern.finditer(content):
        captions.append(f"Figure: {match.group(1)}")

    return captions


def extract_table_captions(content: str) -> list[str]:
    """Extract table captions from markdown."""
    captions: list[str] = []

    # Pattern for table references
    table_pattern = re.compile(r"\*\*[Tt]able\s+\d+[^*]*\*\*:?\s*([^\n]+)")
    for match in table_pattern.finditer(content):
        captions.append(f"Table: {match.group(1)}")

    return captions
