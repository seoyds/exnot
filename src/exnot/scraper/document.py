"""Document collection orchestration: discovers and fetches all available
formats (HTML, PDF, CSV) for a given exchange fee schedule."""

import asyncio
import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from exnot.db.models import Exchange, FeeScheduleFormat, ScraperType
from exnot.scraper.base import (
    FORMAT_PRIORITY,
    CollectionResult,
    ContentType,
    DocumentResult,
)
from exnot.scraper.browser_scraper import BrowserScraper
from exnot.scraper.http_scraper import HttpScraper

# Maps exchange-declared format to scraper content type.
_FORMAT_TO_CONTENT_TYPE: dict[FeeScheduleFormat, ContentType] = {
    FeeScheduleFormat.PDF: ContentType.PDF,
    FeeScheduleFormat.HTML: ContentType.HTML,
    FeeScheduleFormat.CSV: ContentType.CSV,
    FeeScheduleFormat.EXCEL: ContentType.EXCEL,
}

logger = logging.getLogger(__name__)


class DocumentCollector:
    """Orchestrates multi-format document collection for any exchange."""

    def __init__(self) -> None:
        self.http_scraper = HttpScraper()
        self._browser_scraper: BrowserScraper | None = None

    @property
    def browser_scraper(self) -> BrowserScraper:
        if self._browser_scraper is None:
            self._browser_scraper = BrowserScraper()
        return self._browser_scraper

    async def collect(self, exchange: Exchange) -> CollectionResult:
        """Collect ALL available fee schedule documents for the exchange.

        Flow:
          1. Fetch the main HTML page (always captured as baseline).
          2. Scan HTML for PDF/CSV links.
          3. Fetch all alternate_urls from the YAML definition.
          4. Deduplicate by content_hash.
          5. Select the primary document by format priority (CSV > PDF > HTML).
        """
        logger.info(f"[{exchange.code}] Starting multi-format collection from {exchange.fee_schedule_url}")

        # --- 1. Fetch main page ---
        if exchange.scraper_type == ScraperType.BROWSER:
            main_doc = await self.browser_scraper.fetch(exchange.fee_schedule_url)
        else:
            main_doc = await self.http_scraper.fetch(exchange.fee_schedule_url)

        collected: list[DocumentResult] = [main_doc]

        # --- 2. Discover linked documents from HTML ---
        if main_doc.content_type == ContentType.HTML:
            discovered = await self._discover_linked_documents(exchange, main_doc)
            collected.extend(discovered)

        # --- 3. Fetch alternate_urls from YAML ---
        if exchange.alternate_urls:
            alt_results = await self._fetch_alternate_urls(exchange.alternate_urls)
            collected.extend(alt_results)

        # --- 4. Deduplicate by content_hash ---
        seen_hashes: set[str] = set()
        unique: list[DocumentResult] = []
        for doc in collected:
            if doc.content_hash not in seen_hashes:
                seen_hashes.add(doc.content_hash)
                unique.append(doc)

        # --- 5. Select primary by format priority ---
        # When the exchange declares a specific format (e.g. HTML), prefer
        # documents matching that format.  Only fall back to generic priority
        # when no matching document is found.
        preferred_ct = _FORMAT_TO_CONTENT_TYPE.get(exchange.fee_schedule_format)
        if preferred_ct:
            preferred_docs = [d for d in unique if d.content_type == preferred_ct]
            if preferred_docs:
                primary = preferred_docs[0]
            else:
                primary = max(unique, key=lambda d: FORMAT_PRIORITY.get(d.content_type, 0))
        else:
            primary = max(unique, key=lambda d: FORMAT_PRIORITY.get(d.content_type, 0))

        logger.info(
            f"[{exchange.code}] Collected {len(unique)} unique document(s). "
            f"Primary: {primary.content_type.value} from {primary.source_url}"
        )

        return CollectionResult(documents=tuple(unique), primary=primary)

    async def _discover_linked_documents(self, exchange: Exchange, html_doc: DocumentResult) -> list[DocumentResult]:
        """Scan an HTML page for PDF and CSV links and fetch them."""
        discovered_urls: list[str] = []

        try:
            soup = BeautifulSoup(html_doc.content_bytes, "lxml")

            # Find PDF links
            for link in soup.find_all("a", href=lambda h: h and ".pdf" in h.lower()):
                href = link.get("href", "")
                discovered_urls.append(urljoin(exchange.fee_schedule_url, href))

            # Find CSV links
            for link in soup.find_all("a", href=lambda h: h and (".csv" in h.lower() or "csv=true" in h.lower())):
                href = link.get("href", "")
                discovered_urls.append(urljoin(exchange.fee_schedule_url, href))

        except Exception as e:
            logger.warning(f"[{exchange.code}] Failed to parse HTML for document links: {e}")
            return []

        if not discovered_urls:
            return []

        logger.info(f"[{exchange.code}] Discovered {len(discovered_urls)} linked document URL(s)")
        tasks = [self._safe_fetch(url) for url in discovered_urls]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def _fetch_alternate_urls(self, urls: list[str]) -> list[DocumentResult]:
        """Fetch all alternate URLs in parallel, ignoring individual failures."""
        tasks = [self._safe_fetch(url) for url in urls]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def _safe_fetch(self, url: str) -> DocumentResult | None:
        """Fetch a single URL, returning None on failure instead of raising."""
        try:
            return await self.http_scraper.fetch(url)
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    async def close(self) -> None:
        await self.http_scraper.close()
        if self._browser_scraper:
            await self._browser_scraper.close()
