"""Scraper orchestration: decides which scraper to use per exchange and manages the pipeline."""

import logging
from urllib.parse import urljoin

from exnot.db.models import Exchange, FeeScheduleFormat, ScraperType
from exnot.scraper.base import ContentType, DocumentResult
from exnot.scraper.browser_scraper import BrowserScraper
from exnot.scraper.http_scraper import HttpScraper

logger = logging.getLogger(__name__)


class DocumentCollector:
    """Orchestrates document collection for any exchange."""

    def __init__(self):
        self.http_scraper = HttpScraper()
        self._browser_scraper: BrowserScraper | None = None

    @property
    def browser_scraper(self) -> BrowserScraper:
        if self._browser_scraper is None:
            self._browser_scraper = BrowserScraper()
        return self._browser_scraper

    async def collect(self, exchange: Exchange) -> DocumentResult:
        """Collect the fee schedule document for the given exchange."""
        logger.info(f"Collecting fee schedule for {exchange.code} from {exchange.fee_schedule_url}")

        if exchange.scraper_type == ScraperType.BROWSER:
            result = await self.browser_scraper.fetch(exchange.fee_schedule_url)
        else:
            result = await self.http_scraper.fetch(exchange.fee_schedule_url)

        # If the exchange has a PDF format but we got HTML, try to find the PDF link
        if (
            exchange.fee_schedule_format == FeeScheduleFormat.PDF
            and result.content_type == ContentType.HTML
        ):
            result = await self._try_pdf_fallback(exchange, result)

        # If we got an HTML page that links to a PDF, and the exchange wants PDF
        if result.content_type == ContentType.HTML and exchange.alternate_urls:
            for alt_url in exchange.alternate_urls:
                if alt_url.endswith(".pdf"):
                    try:
                        pdf_result = await self.http_scraper.fetch(alt_url)
                        if pdf_result.is_pdf:
                            logger.info(f"Using alternate PDF URL for {exchange.code}: {alt_url}")
                            return pdf_result
                    except Exception as e:
                        logger.warning(f"Failed to fetch alternate URL {alt_url}: {e}")

        return result

    async def _try_pdf_fallback(
        self, exchange: Exchange, html_result: DocumentResult
    ) -> DocumentResult:
        """Try to extract a PDF link from the HTML page and download it."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html_result.content_bytes, "lxml")
            pdf_links = soup.find_all("a", href=lambda h: h and ".pdf" in h.lower())

            for link in pdf_links:
                href = link.get("href", "")
                full_url = urljoin(exchange.fee_schedule_url, href)
                try:
                    pdf_result = await self.http_scraper.fetch(full_url)
                    if pdf_result.is_pdf:
                        logger.info(f"Found PDF link for {exchange.code}: {full_url}")
                        return pdf_result
                except Exception as e:
                    logger.warning(f"Failed to fetch PDF at {full_url}: {e}")
                    continue
        except Exception as e:
            logger.warning(f"Failed to parse HTML for PDF links for {exchange.code}: {e}")

        return html_result

    async def close(self):
        await self.http_scraper.close()
        if self._browser_scraper:
            await self._browser_scraper.close()
