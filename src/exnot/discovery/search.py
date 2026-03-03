"""Web search providers for fee schedule URL discovery."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from exnot.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    position: int


@dataclass
class SearchResponse:
    """Results from a web search query."""

    query: str
    results: list[SearchResult] = field(default_factory=list)
    error: str | None = None


class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, num_results: int = 10) -> SearchResponse: ...

    @abstractmethod
    async def close(self): ...


class SerpApiProvider(SearchProvider):
    """Search via SerpAPI (serpapi.com)."""

    BASE_URL = "https://serpapi.com/search"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.serpapi_api_key
        if not self.api_key:
            raise ValueError("SERPAPI_API_KEY is not configured")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(15))

    async def search(self, query: str, num_results: int = 10) -> SearchResponse:
        try:
            resp = await self.client.get(
                self.BASE_URL,
                params={
                    "q": query,
                    "api_key": self.api_key,
                    "num": num_results,
                    "engine": "google",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("organic_results", []):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                        position=item.get("position", 0),
                    )
                )

            logger.info(f"SerpAPI search '{query}': {len(results)} results")
            return SearchResponse(query=query, results=results)
        except Exception as e:
            logger.error(f"SerpAPI search failed for '{query}': {e}")
            return SearchResponse(query=query, error=str(e))

    async def close(self):
        await self.client.aclose()


def get_search_provider() -> SearchProvider:
    """Factory to get the configured search provider."""
    return SerpApiProvider()
