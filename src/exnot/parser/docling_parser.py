"""Extract text and tables from PDF documents using IBM Docling (deep learning).

Docling provides superior table structure recognition via TableFormer and
produces clean markdown with tables inline — better input for Claude extraction.

Requires optional dependency: pip install exnot[docling]
"""

import logging
from io import BytesIO

from exnot.parser.base import AbstractParser, ExtractedDocument, ExtractedTable

logger = logging.getLogger(__name__)

# Module-level singleton — DocumentConverter loads ML models (~5-15s on first call).
# Reused across all tasks within the same Celery worker process.
_converter_instance = None


def _get_converter():
    """Return a singleton DocumentConverter with fee-schedule-optimized settings."""
    global _converter_instance
    if _converter_instance is not None:
        return _converter_instance

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
        TableStructureOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False  # Fee schedules are programmatic PDFs
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options = TableStructureOptions(
        do_cell_matching=True,
        mode=TableFormerMode.ACCURATE,
    )
    # Disable enrichments not needed for fee schedules
    pipeline_options.do_code_enrichment = False
    pipeline_options.do_formula_enrichment = False
    pipeline_options.do_picture_classification = False

    _converter_instance = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
    logger.info("Docling DocumentConverter initialized (TableFormerMode.ACCURATE)")
    return _converter_instance


class DoclingPdfParser(AbstractParser):
    """Extract text and tables from PDFs using IBM Docling (deep learning).

    Produces the same ExtractedDocument interface as PdfParser, plus stores
    the raw Docling markdown in metadata["markdown"] for downstream use.
    """

    def __init__(self):
        # Trigger lazy import + singleton init to fail fast if docling not installed
        self._converter = _get_converter()

    def extract(self, content: bytes) -> ExtractedDocument:
        """Extract text and tables from PDF bytes using Docling."""
        from docling.datamodel.base_models import DocumentStream

        buf = BytesIO(content)
        source = DocumentStream(name="fee_schedule.pdf", stream=buf)
        result = self._converter.convert(source)
        doc = result.document

        # 1. Full markdown (the primary win — tables inline with text)
        markdown = doc.export_to_markdown()

        # 2. Page-marked text for section_splitter compatibility
        full_text = self._build_page_marked_text(doc)

        # 3. ExtractedTable objects for profile/classifier systems
        tables = self._extract_tables(doc)

        # 4. Page count
        page_count = doc.num_pages() if hasattr(doc, "num_pages") else len(doc.pages)

        return ExtractedDocument(
            full_text=full_text,
            tables=tables,
            page_count=page_count,
            metadata={
                "parser": "docling",
                "tools": ["docling"],
                "markdown": markdown,
            },
        )

    def _build_page_marked_text(self, doc) -> str:
        """Build page-marked text from Docling document items.

        Produces the same ``--- Page N ---`` format as PdfParser for
        section_splitter compatibility.
        """
        from docling_core.types.doc import TableItem, TextItem

        pages: dict[int, list[str]] = {}

        for item, _level in doc.iterate_items():
            page_no = self._get_page_no(item)
            pages.setdefault(page_no, [])

            if isinstance(item, TextItem):
                pages[page_no].append(item.text)
            elif isinstance(item, TableItem):
                # Include table as text for section splitter context
                try:
                    df = item.export_to_dataframe(doc=doc)
                    pages[page_no].append(df.to_string(index=False))
                except Exception:
                    pages[page_no].append("[Table]")

        # Build output with page markers
        parts = []
        for page_no in sorted(pages.keys()):
            if page_no > 0:
                parts.append(f"--- Page {page_no} ---")
            parts.append("\n".join(pages[page_no]))

        return "\n\n".join(parts)

    def _extract_tables(self, doc) -> list[ExtractedTable]:
        """Extract ExtractedTable objects from Docling document."""
        tables = []

        for table_item in doc.tables:
            try:
                df = table_item.export_to_dataframe(doc=doc)
            except Exception:
                logger.debug("Failed to export Docling table to DataFrame, skipping")
                continue

            if df.empty or len(df) < 1:
                continue

            # Flatten any multi-level column headers
            headers = [str(col).strip() for col in df.columns]
            rows = []
            for _, row in df.iterrows():
                cleaned = [str(val).strip() for val in row]
                if any(cleaned):
                    rows.append(cleaned)

            if not headers or not rows:
                continue

            page_no = self._get_page_no(table_item)

            # Try to get table caption/title
            title = ""
            if hasattr(table_item, "caption_text"):
                try:
                    title = table_item.caption_text(doc=doc) or ""
                except Exception:
                    pass

            tables.append(
                ExtractedTable(
                    headers=headers,
                    rows=rows,
                    title=title,
                    page_number=page_no if page_no > 0 else None,
                )
            )

        return tables

    @staticmethod
    def _get_page_no(item) -> int:
        """Get the page number from an item's provenance, or 0 if unavailable."""
        if hasattr(item, "prov") and item.prov:
            return item.prov[0].page_no
        return 0
