import logging

from exnot.config import get_settings
from exnot.scraper.base import AbstractScraper, ContentType, DocumentResult

logger = logging.getLogger(__name__)


class BrowserScraper(AbstractScraper):
    """Playwright-based scraper for JS-rendered pages."""

    def __init__(self):
        self._browser = None
        self._playwright = None

    async def _ensure_browser(self):
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)

    async def fetch(self, url: str) -> DocumentResult:
        await self._ensure_browser()
        settings = get_settings()

        page = await self._browser.new_page(
            user_agent=settings.user_agent,
        )
        try:
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            content = await page.content()
            content_bytes = content.encode("utf-8")

            return DocumentResult(
                content_bytes=content_bytes,
                content_type=ContentType.HTML,
                source_url=url,
                status_code=response.status if response else 200,
            )
        finally:
            await page.close()

    async def fetch_pdf_link(self, url: str, link_pattern: str = "*.pdf") -> str | None:
        """Navigate to a page and extract a PDF download link matching pattern."""
        await self._ensure_browser()
        settings = get_settings()

        page = await self._browser.new_page(user_agent=settings.user_agent)
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            links = await page.query_selector_all("a[href*='.pdf']")
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    return href
            return None
        finally:
            await page.close()

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
