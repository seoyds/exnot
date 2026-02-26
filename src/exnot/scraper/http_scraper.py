import asyncio
import logging

import httpx

from exnot.config import get_settings
from exnot.scraper.base import AbstractScraper, ContentType, DocumentResult

logger = logging.getLogger(__name__)


class HttpScraper(AbstractScraper):
    def __init__(self):
        settings = get_settings()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.scrape_timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        )
        self.max_retries = settings.scrape_max_retries
        self.delay = settings.scrape_delay_seconds

    async def fetch(self, url: str) -> DocumentResult:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.get(url)
                response.raise_for_status()

                content_type = self._detect_content_type(response)

                return DocumentResult(
                    content_bytes=response.content,
                    content_type=content_type,
                    source_url=str(response.url),
                    response_headers=dict(response.headers),
                    status_code=response.status_code,
                )
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    wait = (2**attempt) * 2
                    logger.warning(f"Rate limited on {url}, waiting {wait}s (attempt {attempt+1})")
                    await asyncio.sleep(wait)
                elif e.response.status_code >= 500:
                    wait = 2**attempt
                    logger.warning(f"Server error on {url}, retrying in {wait}s (attempt {attempt+1})")
                    await asyncio.sleep(wait)
                else:
                    raise
            except httpx.RequestError as e:
                last_error = e
                wait = 2**attempt
                logger.warning(f"Request error on {url}: {e}, retrying in {wait}s (attempt {attempt+1})")
                await asyncio.sleep(wait)

        raise last_error  # type: ignore[misc]

    def _detect_content_type(self, response: httpx.Response) -> ContentType:
        ct = response.headers.get("content-type", "").lower()
        if "pdf" in ct or response.content[:5] == b"%PDF-":
            return ContentType.PDF
        if "html" in ct:
            return ContentType.HTML
        if "spreadsheet" in ct or "excel" in ct:
            return ContentType.EXCEL
        return ContentType.UNKNOWN

    async def close(self):
        await self.client.aclose()
