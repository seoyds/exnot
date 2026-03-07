"""URL discovery tool — search for fee schedule URLs via SerpAPI."""

import json
import logging

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)


@tool(
    "search_fee_urls",
    "Search for fee schedule URLs for an exchange using SerpAPI. "
    "Returns a list of search results with title, url, snippet, and position.",
    {"exchange_name": str, "operator": str},
)
async def search_fee_urls(args):
    try:
        from exnot.discovery.search import get_search_provider

        exchange_name = args["exchange_name"]
        operator = args["operator"]

        query = f"{operator} {exchange_name} options exchange fee schedule"

        provider = get_search_provider()
        try:
            response = await provider.search(query, num_results=10)
        finally:
            await provider.close()

        if response.error:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"error": response.error, "query": response.query}
                        ),
                    }
                ]
            }

        results = [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "position": r.position,
            }
            for r in response.results
        ]

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "query": response.query,
                            "result_count": len(results),
                            "results": results,
                        }
                    ),
                }
            ]
        }
    except Exception as e:
        logger.error(f"search_fee_urls failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }
