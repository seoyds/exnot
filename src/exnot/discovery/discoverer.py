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
        """Classify each candidate URL into a document category using AI."""
        from exnot.ai.agents.doc_classifier import doc_classifier_agent
        from exnot.ai.cost import CostTracker
        from exnot.ai.models import ModelRegistry, TaskType

        settings = get_settings()
        registry = ModelRegistry(settings)
        cost_tracker = CostTracker(exchange_code="discovery", budget_usd=0.50)
        classified = []

        for candidate in candidates:
            try:
                from exnot.ai.deps import DiscoveryDeps

                prompt = (
                    f"URL: {candidate.url}\n"
                    f"Title: {candidate.title}\n"
                    f"Content Type: {candidate.content_type}\n"
                    f"Preview: {candidate.content_preview[:500] if candidate.content_preview else 'N/A'}\n"
                )
                deps = DiscoveryDeps(
                    model_registry=registry,
                    cost_tracker=cost_tracker,
                    exchange_code="",
                    exchange_name="",
                    operator="",
                )
                model = registry.get_model(TaskType.URL_DISCOVERY)
                result = await doc_classifier_agent.run(prompt, model=model, deps=deps)
                classified.append(
                    ClassifiedCandidate(
                        url=candidate.url,
                        title=candidate.title,
                        content_type=candidate.content_type or ("PDF" if candidate.is_pdf else "HTML"),
                        doc_category=result.output.doc_category,
                        classification_confidence=result.output.confidence,
                        classification_reasoning=result.output.reasoning,
                        content_preview=candidate.content_preview or "",
                        is_pdf=candidate.is_pdf,
                        is_csv=candidate.is_csv,
                    )
                )
            except Exception:
                classified.append(
                    ClassifiedCandidate(
                        url=candidate.url,
                        title=candidate.title,
                        content_type=candidate.content_type or "HTML",
                        doc_category="OTHER",
                        classification_confidence=0.0,
                        classification_reasoning="Classification failed",
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
        """Use the discovery agent to pick the best fee schedule URL from candidates."""
        from exnot.ai.agents.discovery import discovery_agent
        from exnot.ai.cost import CostTracker
        from exnot.ai.deps import DiscoveryDeps
        from exnot.ai.models import ModelRegistry, TaskType

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
                preview = c.content_preview[:200]
                candidates_text += f"Content Preview: {preview}\n"

        prompt = (
            f"Exchange: {exchange_name} ({exchange_code})\n"
            f"Operator: {operator}\n\n"
            f"CANDIDATES:\n{candidates_text}\n\n"
            f"Identify which URL(s) contain the actual, current fee schedule for this OPTIONS exchange."
        )

        try:
            settings = get_settings()
            registry = ModelRegistry(settings)
            cost_tracker = CostTracker(exchange_code=exchange_code, budget_usd=0.50)
            deps = DiscoveryDeps(
                model_registry=registry,
                cost_tracker=cost_tracker,
                exchange_code=exchange_code,
                exchange_name=exchange_name,
                operator=operator,
            )

            model = registry.get_model(TaskType.URL_DISCOVERY)
            result = await discovery_agent.run(prompt, deps=deps, model=model)

            model_name = registry.get_model_name(TaskType.URL_DISCOVERY)
            cost_tracker.record(
                task="url_discovery",
                model=model_name,
                usage=result.usage(),
            )

            logger.info(
                f"[{exchange_code}] AI discovery: cost=${cost_tracker.total_cost_usd:.4f}, "
                f"tokens={cost_tracker.total_tokens}"
            )

            return result.output.model_dump()
        except Exception as e:
            logger.error(f"[{exchange_code}] AI evaluation failed: {e}")
            return {}
