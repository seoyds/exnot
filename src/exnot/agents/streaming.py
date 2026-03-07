"""SSE streaming module for broadcasting pipeline messages to the dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from claude_agent_sdk import AssistantMessage, ResultMessage
from claude_agent_sdk.types import TextBlock, ThinkingBlock, ToolUseBlock
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["streaming"])

# Active SSE streams keyed by exchange_code -> asyncio.Queue
active_streams: dict[str, asyncio.Queue] = {}


def serialize_sdk_message(message: object) -> dict[str, Any]:
    """Convert an SDK message to a JSON-safe dict for the dashboard.

    Handles AssistantMessage (text/tool_use blocks), ResultMessage,
    and falls back to a system-level representation for other types.
    """
    if isinstance(message, AssistantMessage):
        blocks: list[dict[str, Any]] = []
        if message.content:
            for block in message.content:
                if isinstance(block, ThinkingBlock):
                    blocks.append({"type": "reasoning", "text": block.thinking})
                elif isinstance(block, TextBlock):
                    blocks.append({"type": "reasoning", "text": block.text})
                elif isinstance(block, ToolUseBlock):
                    # Truncate large tool inputs for the dashboard
                    input_str = json.dumps(block.input, default=str)
                    if len(input_str) > 2000:
                        input_str = input_str[:2000] + "..."
                    blocks.append({
                        "type": "tool_call",
                        "name": block.name,
                        "input": input_str,
                    })
        return {
            "type": "assistant",
            "blocks": blocks,
            "is_subagent": message.parent_tool_use_id is not None,
            "model": message.model,
        }

    if isinstance(message, ResultMessage):
        return {
            "type": "result",
            "subtype": message.subtype,
            "stop_reason": message.stop_reason,
            "total_cost_usd": message.total_cost_usd,
            "num_turns": message.num_turns,
            "is_error": message.is_error,
            "result": (message.result[:500] if message.result else None),
        }

    # SystemMessage, UserMessage, or unknown
    return {
        "type": "system",
        "raw": str(message)[:500],
    }


async def broadcast_to_dashboard(exchange_code: str, message: object) -> None:
    """Push a serialized message to the SSE queue for an exchange.

    If no dashboard client is listening for this exchange, the message
    is silently dropped.
    """
    queue = active_streams.get(exchange_code)
    if queue is None:
        return

    try:
        serialized = serialize_sdk_message(message)
        serialized["exchange_code"] = exchange_code
        queue.put_nowait(json.dumps(serialized, default=str))
    except asyncio.QueueFull:
        logger.warning("SSE queue full for %s, dropping message", exchange_code)
    except Exception:
        logger.exception("Error broadcasting to dashboard for %s", exchange_code)


@router.get("/dashboard/pipeline/{exchange_code}/stream")
async def stream_pipeline(exchange_code: str):
    """SSE endpoint that yields pipeline messages for a given exchange.

    Creates a queue in active_streams and yields events until the client
    disconnects or a 5-minute timeout is reached.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    active_streams[exchange_code] = queue

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=300.0)
                    yield {"event": "message", "data": data}
                except TimeoutError:
                    # 5-minute timeout reached, close the stream
                    yield {"event": "timeout", "data": json.dumps({"reason": "5min timeout"})}
                    break
        finally:
            # Clean up the queue when the client disconnects
            active_streams.pop(exchange_code, None)

    return EventSourceResponse(event_generator())
