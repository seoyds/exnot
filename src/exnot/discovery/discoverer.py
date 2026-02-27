"""Fee schedule URL discovery using web search + AI validation."""

import asyncio
import json
import logging
from dataclasses import dataclass, field

import anthropic
import httpx

from exnot.config import get_settings
from exnot.discovery.search import SearchResult, get_search_provider

logger = logging.getLogger(__name__)


@dataclass
class CandidateUrl:
    """A candidate URL with metadata for AI evaluation."""

    url: str
    title: str
    snippet: str
    content_type: str | None = None
    content_preview: str | None = None
    is_pdf: bool = False
    is_csv: bool = False
    fetch_error: str | None = None


@dataclass
class DiscoveryResult:
    """Result of URL discovery for one exchange."""

    exchange_code: str
    exchange_name: str
    primary_url: str | None = None
    alternate_urls: list[str] = field(default_factory=list)
    recommended_format: str = "HTML"
    ai_reasoning: str = ""
    search_queries: list[str] = field(default_factory=list)
    all_candidates: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    error: str | None = None


URL_EVALUATION_PROMPT = """You are evaluating search results to find the official fee schedule for a US options exchange.

Exchange: {exchange_name} ({exchange_code})
Operator: {operator}

Below are candidate URLs found via web search. For each, I provide the URL, page title, search snippet, detected content type, and a preview of the content (if available).

CANDIDATES:
{candidates_text}

TASK: Identify which URL(s) contain the actual, current fee schedule for this OPTIONS exchange.

RULES:
- The fee schedule must be specifically for OPTIONS (not equities, listings, or market data).
- Prefer official exchange/operator websites (e.g., cboe.com, nasdaq.com, nyse.com, miaxglobal.com).
- Prefer direct links to the fee schedule document (PDF or CSV) over landing pages.
- If a landing page links to a downloadable fee schedule, select the landing page as primary.
- REJECT: regulatory filings (SEC), news articles, third-party sites, listing guides, market data fees.
- If multiple valid URLs exist, pick the best as primary and list others as alternates.

Return JSON:
{{
  "primary_url": "<best URL or null if none found>",
  "alternate_urls": ["<other valid fee schedule URLs>"],
  "recommended_format": "PDF" | "CSV" | "HTML",
  "confidence": <0.0 to 1.0>,
  "reasoning": "<explain your selection>"
}}"""


class UrlDiscoverer:
    """Discovers fee schedule URLs for US options exchanges."""

    def __init__(self):
        settings = get_settings()
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.ai_model
        self.max_candidates = settings.discovery_max_candidates
        self.fetch_timeout = settings.discovery_fetch_timeout

    async def discover(
        self, exchange_code: str, exchange_name: str, operator: str
    ) -> DiscoveryResult:
        """Run the full discovery pipeline for one exchange."""
        result = DiscoveryResult(exchange_code=exchange_code, exchange_name=exchange_name)

        # Step 1: Build and execute search queries
        queries = self._build_search_queries(exchange_name, operator)
        result.search_queries = queries

        search_provider = get_search_provider()
        try:
            all_results: list[SearchResult] = []
            for query in queries:
                search_resp = await search_provider.search(query, num_results=10)
                if search_resp.error:
                    logger.warning(f"[{exchange_code}] Search failed for '{query}': {search_resp.error}")
                    continue
                all_results.extend(search_resp.results)
                await asyncio.sleep(1)  # Rate limit between searches
        finally:
            await search_provider.close()

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_results: list[SearchResult] = []
        for r in all_results:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                unique_results.append(r)

        if not unique_results:
            result.error = "No search results found"
            return result

        unique_results = unique_results[: self.max_candidates]
        logger.info(f"[{exchange_code}] {len(unique_results)} unique candidate URLs from {len(queries)} searches")

        # Step 2: Probe each candidate URL
        candidates = await self._probe_candidates(unique_results)
        result.all_candidates = [
            {"url": c.url, "title": c.title, "content_type": c.content_type} for c in candidates
        ]

        # Step 3: Use Claude to evaluate candidates
        evaluation = self._evaluate_with_ai(candidates, exchange_code, exchange_name, operator)

        result.primary_url = evaluation.get("primary_url")
        result.alternate_urls = evaluation.get("alternate_urls", [])
        result.recommended_format = evaluation.get("recommended_format", "HTML")
        result.ai_reasoning = evaluation.get("reasoning", "")
        result.confidence = evaluation.get("confidence", 0.0)

        return result

    def _build_search_queries(self, exchange_name: str, operator: str) -> list[str]:
        """Build 2-3 search queries targeting the fee schedule."""
        queries = [
            f"{exchange_name} options fee schedule",
            f"{exchange_name} options transaction fees rebates",
        ]
        if operator.lower() not in exchange_name.lower():
            queries.append(f"{operator} {exchange_name} fee schedule PDF")
        return queries

    async def _probe_candidates(self, search_results: list[SearchResult]) -> list[CandidateUrl]:
        """Fetch HEAD + first ~2KB of each candidate to determine content type."""
        settings = get_settings()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.fetch_timeout),
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            tasks = [self._probe_single(client, sr) for sr in search_results]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        candidates = []
        for r in results:
            if isinstance(r, CandidateUrl):
                candidates.append(r)
            elif isinstance(r, Exception):
                logger.debug(f"Probe failed: {r}")
        return candidates

    async def _probe_single(self, client: httpx.AsyncClient, sr: SearchResult) -> CandidateUrl:
        """Probe a single URL to get content type and preview."""
        candidate = CandidateUrl(url=sr.url, title=sr.title, snippet=sr.snippet)
        try:
            async with client.stream("GET", sr.url) as resp:
                ct = resp.headers.get("content-type", "").lower()
                candidate.content_type = ct

                if "pdf" in ct or sr.url.lower().endswith(".pdf"):
                    candidate.is_pdf = True
                    candidate.content_preview = "[PDF document]"
                elif "csv" in ct or sr.url.lower().endswith(".csv"):
                    candidate.is_csv = True
                    chunks = []
                    async for part in resp.aiter_bytes(1024):
                        chunks.append(part)
                        if sum(len(c) for c in chunks) >= 1024:
                            break
                    candidate.content_preview = b"".join(chunks)[:1024].decode("utf-8", errors="replace")
                else:
                    chunks = []
                    async for part in resp.aiter_bytes(2048):
                        chunks.append(part)
                        if sum(len(c) for c in chunks) >= 2048:
                            break
                    candidate.content_preview = b"".join(chunks)[:2048].decode("utf-8", errors="replace")
        except Exception as e:
            candidate.fetch_error = str(e)

        return candidate

    def _evaluate_with_ai(
        self,
        candidates: list[CandidateUrl],
        exchange_code: str,
        exchange_name: str,
        operator: str,
    ) -> dict:
        """Use Claude to pick the best fee schedule URL from candidates."""
        candidates_text = ""
        for i, c in enumerate(candidates, 1):
            candidates_text += f"\n--- Candidate {i} ---\n"
            candidates_text += f"URL: {c.url}\n"
            candidates_text += f"Title: {c.title}\n"
            candidates_text += f"Snippet: {c.snippet}\n"
            candidates_text += f"Content-Type: {c.content_type or 'unknown'}\n"
            if c.fetch_error:
                candidates_text += f"Fetch Error: {c.fetch_error}\n"
            elif c.content_preview:
                preview = c.content_preview[:500]
                candidates_text += f"Content Preview: {preview}\n"

        prompt = URL_EVALUATION_PROMPT.format(
            exchange_name=exchange_name,
            exchange_code=exchange_code,
            operator=operator,
            candidates_text=candidates_text,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip()
            logger.info(
                f"[{exchange_code}] AI evaluation: {response.usage.input_tokens} in, "
                f"{response.usage.output_tokens} out tokens"
            )
            return self._parse_json(text)
        except Exception as e:
            logger.error(f"[{exchange_code}] AI evaluation failed: {e}")
            return {}

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from Claude's response."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            return {}
