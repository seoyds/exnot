"""Exchange loading tools — load YAML definitions and extraction prompts."""

import json
import logging

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)


@tool(
    "load_exchange",
    "Load an exchange YAML definition by exchange code. Returns exchange metadata "
    "including name, operator, fee_schedule_url, format, scraper_type, and parser_hints.",
    {"exchange_code": str},
)
async def load_exchange(args):
    try:

        from exnot.exchanges.registry import DEFINITIONS_DIR, load_exchange_definition

        exchange_code = args["exchange_code"]

        # Find the YAML file matching this exchange code
        for filepath in sorted(DEFINITIONS_DIR.glob("*.yml")):
            defn = load_exchange_definition(filepath)
            if defn.get("code") == exchange_code:
                return {
                    "content": [{"type": "text", "text": json.dumps(defn, default=str)}]
                }

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"error": f"Exchange {exchange_code} not found"}),
                }
            ]
        }
    except Exception as e:
        logger.error(f"load_exchange failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }


@tool(
    "load_exchange_prompt",
    "Load the extraction prompt for an exchange. Returns the combined base + "
    "exchange-specific prompt used for AI fee extraction.",
    {"exchange_code": str},
)
async def load_exchange_prompt(args):
    try:
        from exnot.agents.prompts.registry import get_extraction_prompt

        exchange_code = args["exchange_code"]
        prompt = get_extraction_prompt(exchange_code)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "exchange_code": exchange_code,
                            "prompt": prompt,
                            "char_count": len(prompt),
                        }
                    ),
                }
            ]
        }
    except Exception as e:
        logger.error(f"load_exchange_prompt failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }
