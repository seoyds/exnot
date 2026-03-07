"""Orchestrator pipeline — coordinates the full exchange fee schedule processing flow."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    UserMessage,
    query,
)
from claude_agent_sdk.types import PermissionResultAllow, ToolPermissionContext

from exnot.agents.subagents import (
    create_discovery_agent,
    create_extractor_agent,
    create_validator_agent,
)
from exnot.agents.tools.server import create_tools_server
from exnot.config import get_settings

logger = logging.getLogger(__name__)


async def _auto_approve_tool(
    tool_name: str, tool_input: dict, context: ToolPermissionContext
) -> PermissionResultAllow:
    """Auto-approve all tool calls — required for headless execution in Docker."""
    return PermissionResultAllow()

ORCHESTRATOR_SYSTEM_PROMPT = """\
You are ExNot, an automated pipeline coordinator for US options exchange fee schedule processing.

Your job is to execute the full fee schedule pipeline for a given exchange: scrape the document, \
extract fees, normalize them, detect changes, and send notifications.

## Available Tools (MCP server: exnot)

- **load_exchange**: Load exchange configuration (name, URLs, metadata) by exchange code.
- **load_exchange_prompt**: Load exchange-specific extraction prompt/hints for AI extraction.
- **search_fee_urls**: Search the web for fee schedule URLs for an exchange (uses SerpAPI).
- **scrape_document**: Download a fee schedule document from a URL. Returns document content and metadata.
- **check_document_changed**: Check if a document has changed since last scrape (hash-based comparison).
- **parse_document**: Parse a downloaded document (PDF/HTML/CSV) into structured text and tables.
- **try_profile_extract**: Attempt profile-based extraction (zero AI cost) using a saved extraction profile.
- **save_profile**: Save an extraction profile for future zero-cost re-extraction.
- **normalize_fees**: Normalize extracted fee data into the canonical schema.
- **detect_changes**: Compare normalized fees against the previous snapshot to find changes.
- **save_snapshot**: Save a new fee schedule snapshot and its normalized fees to the database.
- **save_scraped_document**: Persist the scraped document to object storage for audit trail.
- **send_notifications**: Send email notifications to subscribers about detected fee changes.

## Available Subagents (via Task tool)

- **extractor**: Fee schedule extraction specialist. Pass it document text/sections and it returns \
structured JSON fee data. Tailored to the specific exchange.
- **validator**: Fee data validation specialist. Pass it extracted fees JSON and it checks \
completeness, correctness, sign/rebate consistency, tier completeness, and duplicate detection.
- **discovery**: URL discovery specialist. Pass it web search results and it identifies the best \
fee schedule URL for an exchange.

## Execution Rules

1. **Always load exchange config first** using load_exchange. This gives you the exchange name, \
configured fee schedule URLs, and metadata.

2. **Use the discovery subagent only if the exchange has no configured URLs.** Call search_fee_urls \
to get search results, then delegate to the discovery subagent to pick the best URL.

3. **Check if the document has changed** before processing using check_document_changed. \
Skip processing if unchanged — unless force mode is enabled.

4. **Try profile-based extraction first** using try_profile_extract — it is free (zero AI cost). \
If it succeeds with adequate confidence, use those results instead of AI extraction.

5. **For AI extraction**, load the exchange prompt with load_exchange_prompt, then pass the full \
parsed document text to the extractor subagent. Include the exchange prompt as context.

6. **Process section groups sequentially**, accumulate all extracted fees into a single list.

7. **After extraction, use the validator subagent** to check quality. Pass it the full extracted \
fees JSON and the exchange code.

8. **If validation confidence < 0.8**, re-invoke the extractor subagent with the validator's \
correction suggestions as additional context. Allow at most 1 retry.

9. **Always save results** even if confidence is imperfect. Use save_snapshot to persist, and \
save_profile to store the extraction profile for future runs.

10. **Send notifications only if changes were detected.** Use detect_changes first, then \
send_notifications only if there are actual changes.

## Final Output

After completing the pipeline, report a JSON summary:
```json
{
  "exchange_code": "...",
  "status": "success" | "unchanged" | "error",
  "fees_extracted": <count>,
  "changes_detected": <count>,
  "notifications_sent": true | false,
  "validation_confidence": <float>,
  "error_message": null | "..."
}
```
"""


async def run_exchange_pipeline(exchange_code: str, force: bool = False) -> list:
    """Run the full fee schedule pipeline for a single exchange.

    Creates the orchestrator agent with MCP tools and subagents, then
    executes the pipeline end-to-end via Claude Agent SDK.

    Args:
        exchange_code: Exchange identifier (e.g., "CBOE_BZX", "NASDAQ_ISE").
        force: If True, re-process even if document hasn't changed.

    Returns:
        List of all messages from the agent conversation.
    """
    settings = get_settings()

    # Create MCP tools server
    tools_server = create_tools_server()

    # Create subagents tailored to this exchange
    extractor = create_extractor_agent(exchange_code)
    validator = create_validator_agent()
    discovery = create_discovery_agent()

    # Capture stderr for debugging
    def _log_stderr(line: str) -> None:
        logger.warning("SDK stderr [%s]: %s", exchange_code, line.rstrip())

    # Build agent options
    options = ClaudeAgentOptions(
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        allowed_tools=["mcp__exnot__*", "Task"],
        mcp_servers={"exnot": tools_server},
        agents={
            "extractor": extractor,
            "validator": validator,
            "discovery": discovery,
        },
        permission_mode="default",
        can_use_tool=_auto_approve_tool,
        model=settings.claude_orchestrator_model,
        stderr=_log_stderr,
    )

    # Build the user prompt as an async iterable (required for can_use_tool callback)
    prompt_text = (
        f"Process fee schedule for exchange: {exchange_code}\n"
        f"Force re-process: {force}\n\n"
        "Execute the full pipeline following the execution rules."
    )

    async def prompt_stream() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "user", "message": {"role": "user", "content": prompt_text}}

    messages: list = []

    logger.info("Starting pipeline for exchange=%s force=%s", exchange_code, force)

    async for message in query(prompt=prompt_stream(), options=options):
        messages.append(message)

        # Log based on message type
        if isinstance(message, ResultMessage):
            logger.info(
                "Pipeline complete for %s: cost=$%.4f turns=%d stop_reason=%s",
                exchange_code,
                message.total_cost_usd or 0.0,
                message.num_turns or 0,
                message.stop_reason,
            )
        elif isinstance(message, AssistantMessage):
            # Log assistant text content for debugging
            if message.content:
                for block in message.content:
                    if hasattr(block, "text"):
                        logger.debug("Assistant [%s]: %s", exchange_code, block.text[:200])
        elif isinstance(message, SystemMessage):
            logger.debug("System [%s]: subtype=%s", exchange_code, message.subtype)
        elif isinstance(message, UserMessage):
            logger.debug("User [%s]: tool result received", exchange_code)

        # Broadcast to dashboard if available (SSE streaming, implemented separately)
        await _broadcast_message(exchange_code, message)

    return messages


async def _broadcast_message(exchange_code: str, message: object) -> None:
    """Broadcast a pipeline message to connected dashboard clients via SSE.

    Args:
        exchange_code: Exchange being processed.
        message: Message from the agent conversation.
    """
    try:
        from exnot.agents.streaming import broadcast_to_dashboard

        await broadcast_to_dashboard(exchange_code, message)
    except ImportError:
        pass
    except Exception:
        logger.debug("Failed to broadcast message for %s", exchange_code, exc_info=True)


def run_exchange_pipeline_sync(exchange_code: str, force: bool = False) -> list:
    """Synchronous wrapper for run_exchange_pipeline.

    Intended for use in Celery tasks which require a sync entry point.

    Args:
        exchange_code: Exchange identifier (e.g., "CBOE_BZX", "NASDAQ_ISE").
        force: If True, re-process even if document hasn't changed.

    Returns:
        List of all messages from the agent conversation.
    """
    return asyncio.run(run_exchange_pipeline(exchange_code, force=force))
