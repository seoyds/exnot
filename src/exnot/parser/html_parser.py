import logging
import re

from bs4 import BeautifulSoup, Tag

from exnot.parser.base import AbstractParser, ExtractedDocument, ExtractedTable

logger = logging.getLogger(__name__)


class HtmlParser(AbstractParser):
    """Extract text and tables from HTML fee schedule pages."""

    def extract(self, content: bytes, rendered_text: str | None = None) -> ExtractedDocument:
        html_str = content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html_str, "lxml")

        # Remove script/style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Use Playwright-rendered visible text if provided, else fallback to get_text()
        if rendered_text is not None:
            full_text = rendered_text
        else:
            full_text = soup.get_text(separator="\n", strip=True)

        tables = self._extract_tables(soup)

        return ExtractedDocument(
            full_text=full_text,
            tables=tables,
            metadata={"parser": "html"},
        )

    def _extract_tables(self, soup: BeautifulSoup) -> list[ExtractedTable]:
        tables = []
        for table_el in soup.find_all("table"):
            extracted = self._parse_table(table_el)
            if extracted:
                tables.append(extracted)
        return tables

    def _parse_table(self, table: Tag) -> ExtractedTable | None:
        """Parse an HTML table element into an ExtractedTable."""
        rows_data: list[list[str]] = []

        # Try to find a caption or preceding heading as title
        title = ""
        caption = table.find("caption")
        if caption:
            title = caption.get_text(strip=True)
        else:
            prev = table.find_previous_sibling(["h1", "h2", "h3", "h4", "h5", "h6", "p", "b"])
            if prev:
                title = prev.get_text(strip=True)

        # Extract all rows (thead + tbody + tfoot)
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            row = []
            for cell in cells:
                text = cell.get_text(separator=" ", strip=True)
                text = re.sub(r"\s+", " ", text)
                row.append(text)
            if row:
                rows_data.append(row)

        if len(rows_data) < 2:
            return None

        # First row as headers
        headers = rows_data[0]
        rows = rows_data[1:]

        # Skip layout/navigation tables: too many columns or cells with huge text
        if len(headers) > 20:
            logger.debug(f"Skipping table with {len(headers)} columns (likely layout table)")
            return None

        max_cell_len = max(
            (len(cell) for row in rows_data for cell in row),
            default=0,
        )
        if max_cell_len > 5000:
            logger.debug(f"Skipping table with cell of {max_cell_len} chars (likely layout table)")
            return None

        # Collect footnotes from the table's container
        footnotes = []
        parent = table.parent
        if parent:
            for fn in parent.find_all(["sup", "small"]):
                fn_text = fn.get_text(strip=True)
                if fn_text and len(fn_text) > 2:
                    footnotes.append(fn_text)

        return ExtractedTable(
            headers=headers,
            rows=rows,
            title=title,
            footnotes=footnotes[:10],  # Limit footnotes
        )
