"""Split parsed documents into logical sections for chunked AI extraction.

Detects section boundaries from page markers and headings, classifies
context sections (definitions, footnotes, appendix), and groups fee-bearing
sections into chunks that fit within an AI token budget.
"""

import re
from dataclasses import dataclass, field

from exnot.parser.base import ExtractedDocument, ExtractedTable

# Heading patterns in fee schedule PDFs
# All-caps lines with 3+ words (e.g., "TRANSACTION FEES FOR OPTIONS")
ALL_CAPS_HEADING = re.compile(r"^[A-Z][A-Z\s,&\-/()]{10,}$")
# Numbered sections: "Section 3:", "1. Regular Orders", "1: Transaction Fees"
NUMBERED_SECTION = re.compile(r"^(?:Section\s+)?\d+[.:]\s+\S.+", re.IGNORECASE)
# Roman numeral sections: "I. Transaction Fees", "IV. Complex Orders"
ROMAN_SECTION = re.compile(r"^[IVX]+\.\s+\S.+")
# Lettered sections: "A. Fee Schedule", "B. Rebates"
LETTER_SECTION = re.compile(r"^[A-Z]\.\s+\S.{3,}")

# Page marker from PdfParser: "--- Page 5 ---"
PAGE_MARKER = re.compile(r"^---\s*Page\s+(\d+)\s*---$")
# CSV section marker: "--- Section 1: Title ---"
CSV_SECTION_MARKER = re.compile(r"^---\s*Section\s+\d+:\s*(.+?)\s*---$")

# Keywords that identify context sections (definitions, footnotes, appendix)
CONTEXT_KEYWORDS = [
    "definition", "glossary", "footnote", "endnote",
    "appendix", "exhibit", "abbreviation",
    "explanation of terms", "general notes",
    "important notice", "preamble", "table of contents",
]

# Dollar amount pattern for context classification
DOLLAR_PATTERN = re.compile(r"\$\d+\.\d{2}")


@dataclass
class DocumentSection:
    """A logical section of a parsed document."""

    heading: str
    text: str
    tables: list[ExtractedTable] = field(default_factory=list)
    page_range: tuple[int, int] | None = None
    is_context: bool = False

    @property
    def char_count(self) -> int:
        table_chars = sum(
            len(str(t.headers)) + sum(len(str(r)) for r in t.rows)
            for t in self.tables
        )
        return len(self.text) + table_chars


@dataclass
class SectionGroup:
    """A group of sections bundled for a single AI call."""

    sections: list[DocumentSection] = field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return sum(s.char_count for s in self.sections)


def should_use_sectioned_extraction(document: ExtractedDocument) -> bool:
    """Decide if sectioned extraction is needed based on document size."""
    return len(document.full_text) > 20000 or len(document.tables) > 8


def split_document(
    document: ExtractedDocument, format_hint: str = "pdf"
) -> list[DocumentSection]:
    """Split an ExtractedDocument into logical sections.

    Args:
        document: The parsed document.
        format_hint: One of "pdf", "html", "csv".

    Returns:
        List of DocumentSection objects.
    """
    fmt = format_hint.lower()
    if fmt == "csv":
        sections = _split_csv_text(document)
    elif fmt == "html":
        sections = _split_html_text(document)
    else:
        sections = _split_pdf_text(document)

    # Fallback: if splitting produced 0 or 1 section, chunk by char count
    if len(sections) <= 1 and len(document.full_text) > 20000:
        sections = _chunk_by_size(document, target_chars=12000)

    return sections


def _split_pdf_text(document: ExtractedDocument) -> list[DocumentSection]:
    """Split PDF text on page markers, then detect headings within pages."""
    pages = _extract_pages(document.full_text)
    if not pages:
        return [DocumentSection(
            heading="Full Document",
            text=document.full_text,
            tables=list(document.tables),
        )]

    # Build table lookup by page number
    tables_by_page: dict[int, list[ExtractedTable]] = {}
    for table in document.tables:
        pg = table.page_number or 0
        tables_by_page.setdefault(pg, []).append(table)

    # Detect heading lines within each page and create sections
    sections: list[DocumentSection] = []
    current_heading = ""
    current_text_parts: list[str] = []
    current_tables: list[ExtractedTable] = []
    current_start_page: int | None = None

    for page_num, page_text in pages:
        lines = page_text.split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped:
                current_text_parts.append("")
                continue

            if _is_heading(stripped):
                # Flush previous section
                if current_text_parts and current_heading:
                    sections.append(DocumentSection(
                        heading=current_heading,
                        text="\n".join(current_text_parts),
                        tables=current_tables,
                        page_range=(current_start_page or page_num, page_num),
                    ))
                    current_text_parts = []
                    current_tables = []

                current_heading = stripped
                current_start_page = page_num

            current_text_parts.append(line)

        # Assign tables for this page to current section
        if page_num in tables_by_page:
            current_tables.extend(tables_by_page[page_num])

    # Flush last section
    if current_text_parts:
        last_page = pages[-1][0] if pages else 1
        sections.append(DocumentSection(
            heading=current_heading or f"Pages {current_start_page or 1}-{last_page}",
            text="\n".join(current_text_parts),
            tables=current_tables,
            page_range=(current_start_page or 1, last_page),
        ))

    # Assign any unassigned tables (page_number=None) to first section
    assigned_tables = {id(t) for s in sections for t in s.tables}
    unassigned = [t for t in document.tables if id(t) not in assigned_tables]
    if unassigned and sections:
        sections[0].tables.extend(unassigned)

    return sections


def _split_html_text(document: ExtractedDocument) -> list[DocumentSection]:
    """Split HTML text on heading-like lines."""
    lines = document.full_text.split("\n")
    sections: list[DocumentSection] = []
    current_heading = ""
    current_parts: list[str] = []

    for line in lines:
        stripped = line.strip()
        if _is_heading(stripped):
            if current_parts:
                sections.append(DocumentSection(
                    heading=current_heading or "Introduction",
                    text="\n".join(current_parts),
                ))
                current_parts = []
            current_heading = stripped
        current_parts.append(line)

    if current_parts:
        sections.append(DocumentSection(
            heading=current_heading or "Full Document",
            text="\n".join(current_parts),
        ))

    # Assign tables to sections by title proximity
    _assign_tables_to_sections(sections, document.tables)

    return sections


def _split_csv_text(document: ExtractedDocument) -> list[DocumentSection]:
    """Split CSV text on section markers already present from CsvParser."""
    parts = re.split(r"(?=^---\s*Section\s+\d+:)", document.full_text, flags=re.MULTILINE)
    sections: list[DocumentSection] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        match = CSV_SECTION_MARKER.match(part.split("\n")[0])
        heading = match.group(1) if match else "CSV Section"
        sections.append(DocumentSection(heading=heading, text=part))

    # Assign tables to sections by index
    for i, table in enumerate(document.tables):
        if i < len(sections):
            sections[i].tables.append(table)
        elif sections:
            sections[-1].tables.append(table)

    return sections


def _chunk_by_size(
    document: ExtractedDocument, target_chars: int = 12000
) -> list[DocumentSection]:
    """Fallback: chunk the document by character count."""
    text = document.full_text
    sections: list[DocumentSection] = []
    start = 0
    chunk_num = 0

    while start < len(text):
        end = min(start + target_chars, len(text))
        # Try to break at a line boundary
        if end < len(text):
            newline_pos = text.rfind("\n", start, end)
            if newline_pos > start:
                end = newline_pos + 1

        chunk_text = text[start:end]
        chunk_num += 1
        sections.append(DocumentSection(
            heading=f"Chunk {chunk_num}",
            text=chunk_text,
        ))
        start = end

    # Distribute tables evenly
    if sections and document.tables:
        tables_per = max(1, len(document.tables) // len(sections))
        for i, table in enumerate(document.tables):
            section_idx = min(i // tables_per, len(sections) - 1)
            sections[section_idx].tables.append(table)

    return sections


def classify_context_sections(
    sections: list[DocumentSection],
) -> list[DocumentSection]:
    """Mark sections as context (definitions/footnotes/appendix) vs fee-bearing.

    Only keyword-matched sections are marked as context. Sections without
    dollar amounts are left as fee sections — they may contain text that
    describes fees without explicit amounts, which the AI should still see.
    """
    for section in sections:
        heading_lower = section.heading.lower()
        text_preview = section.text[:500].lower()
        combined = heading_lower + " " + text_preview

        # Only mark as context if heading/text explicitly matches context keywords
        if any(kw in combined for kw in CONTEXT_KEYWORDS):
            section.is_context = True

    return sections


def group_sections(
    fee_sections: list[DocumentSection], char_budget: int = 15000
) -> list[SectionGroup]:
    """Group fee-bearing sections into chunks that fit the character budget."""
    if not fee_sections:
        return []

    groups: list[SectionGroup] = []
    current = SectionGroup()

    for section in fee_sections:
        # If adding this section would exceed budget and group is non-empty, flush
        if current.sections and current.total_chars + section.char_count > char_budget:
            groups.append(current)
            current = SectionGroup()

        current.sections.append(section)

    # Flush final group
    if current.sections:
        groups.append(current)

    return groups


# --- Internal helpers ---


def _extract_pages(text: str) -> list[tuple[int, str]]:
    """Extract (page_number, page_text) tuples from PDF text with page markers."""
    pages: list[tuple[int, str]] = []
    current_page = 0
    current_lines: list[str] = []

    for line in text.split("\n"):
        match = PAGE_MARKER.match(line.strip())
        if match:
            if current_lines and current_page > 0:
                pages.append((current_page, "\n".join(current_lines)))
            current_page = int(match.group(1))
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines and current_page > 0:
        pages.append((current_page, "\n".join(current_lines)))

    return pages


def _is_heading(line: str) -> bool:
    """Check if a text line is a section heading."""
    if not line or len(line) > 120:
        return False

    # Skip lines that are obviously data rows (contain $ amounts)
    if "$" in line and re.search(r"\$\d+\.\d{2}", line):
        return False

    return bool(
        ALL_CAPS_HEADING.match(line)
        or NUMBERED_SECTION.match(line)
        or ROMAN_SECTION.match(line)
        or LETTER_SECTION.match(line)
    )


def _assign_tables_to_sections(
    sections: list[DocumentSection], tables: list[ExtractedTable]
) -> None:
    """Assign tables to sections by matching table titles against section text."""
    for table in tables:
        best_idx = len(sections) - 1  # Default to last section
        title_lower = table.title.lower() if table.title else ""

        for i, section in enumerate(sections):
            if title_lower and title_lower in section.text.lower():
                best_idx = i
                break

        if 0 <= best_idx < len(sections):
            sections[best_idx].tables.append(table)
