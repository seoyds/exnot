"""Fee schedule URL discovery using web search + AI validation."""

import asyncio
import logging
from dataclasses import dataclass, field

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
class ClassifiedCandidate:
    """A candidate URL classified into a document category."""

    url: str
    title: str
    content_type: str
    doc_category: str  # DocumentCategory value
    classification_confidence: float
    classification_reasoning: str
    content_preview: str = ""
    is_pdf: bool = False
    is_csv: bool = False


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
    classified_candidates: list[ClassifiedCandidate] = field(default_factory=list)
    confidence: float = 0.0
    error: str | None = None


class UrlDiscoverer:
    """Discovers fee schedule URLs for US options exchanges."""

    def __init__(self):
        settings = get_settings()
        self.max_candidates = settings.discovery_max_candidates
        self.fetch_timeout = settings.discovery_fetch_timeout

    async def discover(self, exchange_code: str, exchange_name: str, operator: str) -> DiscoveryResult:
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
        result.all_candidates = [{"url": c.url, "title": c.title, "content_type": c.content_type} for c in candidates]

        # Step 3: Classify all candidates into document categories
        classified = await self._classify_candidates(candidates)
        result.classified_candidates = classified

        # Step 4: Use AI agent to evaluate candidates
        evaluation = await self._evaluate_with_ai(candidates, exchange_code, exchange_name, operator)

        result.primary_url = evaluation.get("primary_url")
        result.alternate_urls = evaluation.get("alternate_urls", [])
        result.recommended_format = evaluation.get("recommended_format", "HTML")
        result.ai_reasoning = evaluation.get("reasoning", "")
        result.confidence = evaluation.get("confidence", 0.0)

        return result

    def _build_search_queries(self, exchange_name: str, operator: str) -> list[str]:
        """Build 2-3 search queries targeting the fee schedule."""
        settings = get_settings()
        queries = [
            f"{exchange_name} options fee schedule",
            f"{exchange_name} options transaction fees rebates",
        ]
        if operator.lower() not in exchange_name.lower():
            queries.append(f"{operator} {exchange_name} fee schedule PDF")
        if settings.discovery_include_protocol_specs:
            queries.append(f"{exchange_name} FIX protocol specification binary order entry")
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

    async def _classify_candidates(self, candidates: list[CandidateUrl]) -> list[ClassifiedCandidate]:
        """Classify each candidate URL into a document category.

        TODO: Re-implement via Agent SDK discovery subagent.
        Currently returns basic heuristic classifications.
        """
        classified = []
        for candidate in candidates:
            # Simple heuristic classification
            url_lower = candidate.url.lower()
            title_lower = (candidate.title or "").lower()
            if any(kw in url_lower or kw in title_lower for kw in ["fee", "pricing", "schedule"]):
                doc_category = "FEE_SCHEDULE"
                confidence = 0.7
                reasoning = "URL/title contains fee-related keywords"
            elif any(kw in url_lower or kw in title_lower for kw in ["protocol", "fix", "binary", "spec"]):
                doc_category = "PROTOCOL_SPEC"
                confidence = 0.5
                reasoning = "URL/title contains protocol-related keywords"
            else:
                doc_category = "OTHER"
                confidence = 0.3
                reasoning = "No strong signal detected"

            classified.append(
                ClassifiedCandidate(
                    url=candidate.url,
                    title=candidate.title,
                    content_type=candidate.content_type or ("PDF" if candidate.is_pdf else "HTML"),
                    doc_category=doc_category,
                    classification_confidence=confidence,
                    classification_reasoning=reasoning,
                    content_preview=candidate.content_preview or "",
                    is_pdf=candidate.is_pdf,
                    is_csv=candidate.is_csv,
                )
            )

        return classified

    async def _evaluate_with_ai(
        self,
        candidates: list[CandidateUrl],
        exchange_code: str,
        exchange_name: str,
        operator: str,
    ) -> dict:
        """Evaluate candidates to pick the best fee schedule URL.

        TODO: Re-implement via Agent SDK discovery subagent.
        Currently uses heuristic scoring based on URL patterns and content.
        """
        best_url = None
        best_score = -1
        alternates = []

        for c in candidates:
            if c.fetch_error:
                continue

            score = 0
            url_lower = c.url.lower()
            title_lower = c.title.lower()

            # Score based on URL/title content
            if "fee" in url_lower or "fee" in title_lower:
                score += 3
            if "schedule" in url_lower or "schedule" in title_lower:
                score += 2
            if "option" in url_lower or "option" in title_lower:
                score += 1
            if exchange_name.lower().split()[0] in url_lower:
                score += 2
            if c.is_pdf:
                score += 1

            if score > best_score:
                if best_url:
                    alternates.append(best_url)
                best_url = c.url
                best_score = score
            elif score > 0:
                alternates.append(c.url)

        recommended_format = "PDF" if best_url and best_url.lower().endswith(".pdf") else "HTML"
        confidence = min(best_score / 8.0, 1.0) if best_score > 0 else 0.0

        return {
            "primary_url": best_url,
            "alternate_urls": alternates[:3],
            "recommended_format": recommended_format,
            "reasoning": f"Heuristic scoring (best_score={best_score})",
            "confidence": confidence,
        }
