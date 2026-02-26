import io
import logging

import fitz  # PyMuPDF
import pdfplumber

from exnot.parser.base import AbstractParser, ExtractedDocument, ExtractedTable

logger = logging.getLogger(__name__)


class PdfParser(AbstractParser):
    """Extract text and tables from PDF documents using PyMuPDF and pdfplumber."""

    def extract(self, content: bytes) -> ExtractedDocument:
        full_text = self._extract_text_pymupdf(content)
        tables = self._extract_tables_pdfplumber(content)
        page_count = self._get_page_count(content)

        return ExtractedDocument(
            full_text=full_text,
            tables=tables,
            page_count=page_count,
            metadata={"parser": "pdf", "tools": ["pymupdf", "pdfplumber"]},
        )

    def _extract_text_pymupdf(self, content: bytes) -> str:
        """Extract full text preserving layout using PyMuPDF."""
        doc = fitz.open(stream=content, filetype="pdf")
        pages = []
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text")
            pages.append(f"--- Page {page_num + 1} ---\n{text}")
        doc.close()
        return "\n\n".join(pages)

    def _extract_tables_pdfplumber(self, content: bytes) -> list[ExtractedTable]:
        """Extract tables using pdfplumber's table detection."""
        tables = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_tables = page.extract_tables()
                for table_data in page_tables:
                    if not table_data or len(table_data) < 2:
                        continue

                    # First row as headers
                    headers = [str(cell or "").strip() for cell in table_data[0]]
                    rows = []
                    for row in table_data[1:]:
                        cleaned = [str(cell or "").strip() for cell in row]
                        if any(cleaned):  # Skip entirely empty rows
                            rows.append(cleaned)

                    if headers and rows:
                        tables.append(
                            ExtractedTable(
                                headers=headers,
                                rows=rows,
                                page_number=page_num,
                            )
                        )
        return tables

    def _get_page_count(self, content: bytes) -> int:
        doc = fitz.open(stream=content, filetype="pdf")
        count = len(doc)
        doc.close()
        return count
