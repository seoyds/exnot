"""CSV fee schedule parser.

Handles single- and multi-section CSVs (sections separated by blank lines).
Uses only the stdlib csv module — no extra dependencies.
"""

import csv
import io
import logging

from exnot.parser.base import AbstractParser, ExtractedDocument, ExtractedTable

logger = logging.getLogger(__name__)


class CsvParser(AbstractParser):
    """Extract text and tables from CSV fee schedule files."""

    def extract(self, content: bytes) -> ExtractedDocument:
        text = content.decode("utf-8", errors="replace")

        sections = self._split_sections(text)
        tables: list[ExtractedTable] = []
        text_lines: list[str] = []

        for idx, section in enumerate(sections):
            table = self._parse_section(section, section_index=idx)
            if table is not None:
                tables.append(table)
                # Build pipe-delimited text representation for AI extraction
                text_lines.append(f"--- Section {idx + 1}: {table.title or 'Untitled'} ---")
                text_lines.append(" | ".join(table.headers))
                for row in table.rows:
                    text_lines.append(" | ".join(row))
                text_lines.append("")

        full_text = "\n".join(text_lines) if text_lines else text

        logger.info(f"CSV parser extracted {len(tables)} table(s), {len(full_text)} chars")
        return ExtractedDocument(
            full_text=full_text,
            tables=tables,
            metadata={"parser": "csv", "section_count": len(sections)},
        )

    def _split_sections(self, text: str) -> list[str]:
        """Split a CSV on consecutive blank lines into independent sections."""
        sections: list[str] = []
        current: list[str] = []

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                if current:
                    sections.append("\n".join(current))
                    current = []
            else:
                current.append(line)

        if current:
            sections.append("\n".join(current))

        return sections

    def _parse_section(self, section_text: str, section_index: int = 0) -> ExtractedTable | None:
        """Parse a single CSV section into an ExtractedTable."""
        reader = csv.reader(io.StringIO(section_text))
        rows_data: list[list[str]] = []

        for row in reader:
            # Skip completely empty rows
            if not any(cell.strip() for cell in row):
                continue
            cleaned = [cell.strip() for cell in row]
            rows_data.append(cleaned)

        if len(rows_data) < 2:
            return None

        # Heuristic: if first row looks like a title (single non-empty cell),
        # use it as the title and advance to the header row.
        title = ""
        header_idx = 0
        first_non_empty = [c for c in rows_data[0] if c]
        if len(first_non_empty) == 1 and len(rows_data) >= 3:
            title = first_non_empty[0]
            header_idx = 1

        headers = rows_data[header_idx]
        data_rows = rows_data[header_idx + 1:]

        if not data_rows:
            return None

        return ExtractedTable(
            headers=headers,
            rows=data_rows,
            title=title,
        )
