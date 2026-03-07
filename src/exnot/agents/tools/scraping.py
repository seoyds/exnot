"""Document scraping tools — download documents and check for changes."""

import json
import logging

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)

# Module-level cache for passing document bytes between tool calls within a pipeline run.
# Keyed by exchange_code -> DocumentResult-like dict with content_bytes.
_document_cache: dict[str, dict] = {}


def get_cached_document(exchange_code: str) -> dict | None:
    """Retrieve a cached document for an exchange code."""
    return _document_cache.get(exchange_code)


def clear_cached_document(exchange_code: str) -> None:
    """Clear cached document for an exchange code."""
    _document_cache.pop(exchange_code, None)


@tool(
    "scrape_document",
    "Download a document from a URL using HTTP or browser scraping. "
    "Caches the downloaded bytes internally for subsequent parse_document calls. "
    "Returns content_type, content_hash, source_url, and content size.",
    {"url": str, "method": str, "exchange_code": str},
)
async def scrape_document(args):
    try:
        url = args["url"]
        method = args.get("method", "http").lower()
        exchange_code = args["exchange_code"]

        if method == "browser":
            from exnot.scraper.browser_scraper import BrowserScraper

            scraper = BrowserScraper()
            try:
                doc_result = await scraper.fetch(url)
            finally:
                await scraper.close()
        else:
            from exnot.scraper.http_scraper import HttpScraper

            scraper = HttpScraper()
            try:
                doc_result = await scraper.fetch(url)
            finally:
                await scraper.close()

        # Cache the document for later use by parse_document
        _document_cache[exchange_code] = {
            "content_bytes": doc_result.content_bytes,
            "content_type": doc_result.content_type.value,
            "content_hash": doc_result.content_hash,
            "source_url": doc_result.source_url,
            "status_code": doc_result.status_code,
        }

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "content_type": doc_result.content_type.value,
                            "content_hash": doc_result.content_hash,
                            "source_url": doc_result.source_url,
                            "content_size_bytes": len(doc_result.content_bytes),
                            "status_code": doc_result.status_code,
                        }
                    ),
                }
            ]
        }
    except Exception as e:
        logger.error(f"scrape_document failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }


@tool(
    "check_document_changed",
    "Check if a document has changed by comparing its content hash against "
    "the latest stored snapshot for the exchange. Returns whether the document "
    "is new/changed or unchanged.",
    {"exchange_code": str, "content_hash": str},
)
async def check_document_changed(args):
    try:
        from exnot.db.engine import AsyncSessionLocal
        from exnot.db.repositories import ExchangeRepository, SnapshotRepository

        exchange_code = args["exchange_code"]
        content_hash = args["content_hash"]

        async with AsyncSessionLocal() as session:
            exchange_repo = ExchangeRepository(session)
            exchange = await exchange_repo.get_by_code(exchange_code)

            if not exchange:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "changed": True,
                                    "reason": f"Exchange {exchange_code} not found in DB (first run)",
                                }
                            ),
                        }
                    ]
                }

            snapshot_repo = SnapshotRepository(session)
            latest_hash = await snapshot_repo.get_latest_hash(exchange.id)

            if latest_hash is None:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "changed": True,
                                    "reason": "No previous snapshot exists",
                                }
                            ),
                        }
                    ]
                }

            changed = content_hash != latest_hash
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "changed": changed,
                                "reason": "Content hash differs"
                                if changed
                                else "Content hash matches latest snapshot",
                                "current_hash": content_hash,
                                "stored_hash": latest_hash,
                            }
                        ),
                    }
                ]
            }
    except Exception as e:
        logger.error(f"check_document_changed failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }
