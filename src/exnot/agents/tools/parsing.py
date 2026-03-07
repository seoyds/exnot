"""Document parsing tool — parse documents, split sections, classify tables."""

import json
import logging

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)


@tool(
    "parse_document",
    "Parse a previously scraped document for an exchange. Extracts text and tables, "
    "splits into sections, classifies tables as fee-relevant or not, and groups "
    "sections for AI extraction. Uses the cached document from scrape_document. "
    "The 'format' parameter should be one of: pdf, html, csv.",
    {"exchange_code": str, "format": str},
)
async def parse_document(args):
    try:
        from exnot.agents.tools.scraping import get_cached_document
        from exnot.parser.section_splitter import (
            classify_context_sections,
            group_sections,
            should_use_sectioned_extraction,
            split_document,
        )
        from exnot.parser.table_classifier import classify_tables

        exchange_code = args["exchange_code"]
        doc_format = args.get("format", "html").lower()

        # Get cached document bytes
        cached = get_cached_document(exchange_code)
        if not cached:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "error": f"No cached document for {exchange_code}. "
                                "Call scrape_document first."
                            }
                        ),
                    }
                ]
            }

        content_bytes = cached["content_bytes"]

        # Select parser based on format
        if doc_format == "pdf":
            from exnot.parser.pdf_parser import PdfParser

            parser = PdfParser()
        elif doc_format == "csv":
            from exnot.parser.csv_parser import CsvParser

            parser = CsvParser()
        else:
            from exnot.parser.html_parser import HtmlParser

            parser = HtmlParser()

        # Parse the document
        document = parser.extract(content_bytes)

        # Classify tables
        table_classifications = classify_tables(document.tables)

        # Split into sections
        sections = split_document(document, format_hint=doc_format)
        sections = classify_context_sections(sections)

        # Determine if sectioned extraction is needed
        use_sectioned = should_use_sectioned_extraction(document)

        # Group fee-bearing sections
        from exnot.config import get_settings

        settings = get_settings()
        fee_sections = [s for s in sections if not s.is_context]
        context_sections = [s for s in sections if s.is_context]
        section_groups = group_sections(
            fee_sections, char_budget=settings.ai_section_char_budget
        )

        # Build serializable result
        tables_info = []
        for i, table in enumerate(document.tables):
            cls = table_classifications[i] if i < len(table_classifications) else None
            tables_info.append(
                {
                    "index": i,
                    "title": table.title,
                    "headers": table.headers,
                    "row_count": len(table.rows),
                    "page_number": table.page_number,
                    "is_fee_table": cls.is_fee_table if cls else None,
                    "classification_score": cls.score if cls else None,
                    "classification_reason": cls.reason if cls else None,
                }
            )

        sections_info = []
        for i, section in enumerate(sections):
            sections_info.append(
                {
                    "index": i,
                    "heading": section.heading,
                    "char_count": section.char_count,
                    "is_context": section.is_context,
                    "table_count": len(section.tables),
                    "page_range": section.page_range,
                }
            )

        groups_info = []
        for gi, group in enumerate(section_groups):
            group_section_indices = []
            for gs in group.sections:
                for si, s in enumerate(sections):
                    if s is gs:
                        group_section_indices.append(si)
                        break
            groups_info.append(
                {
                    "group_index": gi,
                    "section_indices": group_section_indices,
                    "total_chars": group.total_chars,
                    "section_headings": [s.heading for s in group.sections],
                }
            )

        # Build the full text + table data for each group (for AI extraction)
        group_contents = []
        for gi, group in enumerate(section_groups):
            text_parts = []
            table_parts = []

            for section in group.sections:
                text_parts.append(f"--- {section.heading} ---")
                text_parts.append(section.text)

                for table in section.tables:
                    # Only include fee-relevant tables
                    table_idx = None
                    for ti, dt in enumerate(document.tables):
                        if dt is table:
                            table_idx = ti
                            break
                    if table_idx is not None:
                        cls = (
                            table_classifications[table_idx]
                            if table_idx < len(table_classifications)
                            else None
                        )
                        if cls and not cls.is_fee_table:
                            continue

                    table_parts.append(f"\n--- Table: {table.title} ---")
                    table_parts.append(f"Headers: {table.headers}")
                    for row in table.rows[:50]:
                        table_parts.append(f"  {row}")
                    if len(table.rows) > 50:
                        table_parts.append(
                            f"  ... ({len(table.rows)} rows total)"
                        )
                    if table.footnotes:
                        table_parts.append(f"Footnotes: {table.footnotes}")

            group_contents.append(
                {
                    "group_index": gi,
                    "section_text": "\n".join(text_parts),
                    "table_text": "\n".join(table_parts),
                }
            )

        # Build context text from context sections
        context_parts = []
        for s in context_sections:
            context_parts.append(f"--- {s.heading} ---")
            context_parts.append(s.text[:3000])
        context_text = "\n".join(context_parts)[:8000]

        result = {
            "exchange_code": exchange_code,
            "format": doc_format,
            "full_text_length": len(document.full_text),
            "page_count": document.page_count,
            "table_count": len(document.tables),
            "tables": tables_info,
            "section_count": len(sections),
            "sections": sections_info,
            "use_sectioned_extraction": use_sectioned,
            "fee_section_count": len(fee_sections),
            "context_section_count": len(context_sections),
            "group_count": len(section_groups),
            "groups": groups_info,
            "group_contents": group_contents,
            "context_text": context_text,
        }

        return {
            "content": [{"type": "text", "text": json.dumps(result, default=str)}]
        }
    except Exception as e:
        logger.error(f"parse_document failed: {e}", exc_info=True)
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }
