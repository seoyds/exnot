"""Parser factory — selects the PDF parser backend based on configuration."""

import logging

from exnot.parser.base import AbstractParser

logger = logging.getLogger(__name__)


def get_pdf_parser() -> AbstractParser:
    """Return the configured PDF parser instance.

    Controlled by the ``PDF_PARSER_BACKEND`` env var / ``pdf_parser_backend``
    config setting.  Defaults to ``"pymupdf"``; set to ``"docling"`` for
    deep-learning table extraction (requires ``pip install exnot[docling]``).
    """
    from exnot.config import get_settings

    settings = get_settings()
    backend = settings.pdf_parser_backend.lower()

    if backend == "docling":
        try:
            from exnot.parser.docling_parser import DoclingPdfParser

            return DoclingPdfParser()
        except ImportError:
            logger.error(
                "PDF_PARSER_BACKEND=docling but docling is not installed. "
                "Install with: pip install exnot[docling]. Falling back to pymupdf."
            )

    from exnot.parser.pdf_parser import PdfParser

    return PdfParser()
