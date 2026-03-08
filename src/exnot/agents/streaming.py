"""SSE streaming module for broadcasting pipeline messages to the dashboard.

Uses Redis pub/sub to bridge between the Celery worker (publisher) and the
FastAPI web process (subscriber/SSE endpoint). This allows real-time event
streaming across container boundaries.

Events are also persisted to Redis lists keyed by scrape_log_id so they
can be retrieved after a pipeline run completes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from claude_agent_sdk import AssistantMessage, ResultMessage
from claude_agent_sdk.types import TextBlock, ThinkingBlock, ToolUseBlock
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from exnot.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["streaming"])

REDIS_CHANNEL_PREFIX = "exnot:pipeline:events:"
REDIS_LOG_PREFIX = "exnot:pipeline:log:"
LOG_TTL_SECONDS = 86400  # 24 hours


def serialize_sdk_message(message: object) -> dict[str, Any]:
    """Convert an SDK message to a JSON-safe dict for the dashboard."""
    if isinstance(message, AssistantMessage):
        blocks: list[dict[str, Any]] = []
        if message.content:
            for block in message.content:
                if isinstance(block, ThinkingBlock):
                    blocks.append({"type": "reasoning", "text": block.thinking})
                elif isinstance(block, TextBlock):
                    blocks.append({"type": "text", "text": block.text})
                elif isinstance(block, ToolUseBlock):
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


def _persist_event(r, scrape_log_id: str, event_json: str) -> None:
    """Append an event to the persistent Redis list for this run."""
    key = f"{REDIS_LOG_PREFIX}{scrape_log_id}"
    r.rpush(key, event_json)
    r.expire(key, LOG_TTL_SECONDS)


async def broadcast_to_dashboard(exchange_code: str, message: object, scrape_log_id: str | None = None) -> None:
    """Publish a serialized message to Redis pub/sub and persist it."""
    try:
        import redis

        settings = get_settings()
        r = redis.from_url(settings.redis_url)
        serialized = serialize_sdk_message(message)
        serialized["exchange_code"] = exchange_code
        event_json = json.dumps(serialized, default=str)

        # Publish for live SSE listeners
        channel = f"{REDIS_CHANNEL_PREFIX}{exchange_code}"
        r.publish(channel, event_json)

        # Persist for later retrieval
        if scrape_log_id:
            _persist_event(r, scrape_log_id, event_json)

        r.close()
    except Exception:
        logger.debug("Failed to broadcast to dashboard for %s", exchange_code, exc_info=True)


def broadcast_log_event(exchange_code: str, level: str, message: str, scrape_log_id: str | None = None) -> None:
    """Publish a plain log event (not an SDK message) to the dashboard."""
    try:
        import redis

        settings = get_settings()
        r = redis.from_url(settings.redis_url)
        event = {
            "type": "log",
            "exchange_code": exchange_code,
            "level": level,
            "message": message,
        }
        event_json = json.dumps(event, default=str)

        channel = f"{REDIS_CHANNEL_PREFIX}{exchange_code}"
        r.publish(channel, event_json)

        if scrape_log_id:
            _persist_event(r, scrape_log_id, event_json)

        r.close()
    except Exception:
        logger.debug("Failed to broadcast log event for %s", exchange_code, exc_info=True)


def get_stored_events(scrape_log_id: str) -> list[dict[str, Any]]:
    """Retrieve all persisted events for a given scrape log run."""
    import redis

    settings = get_settings()
    r = redis.from_url(settings.redis_url)
    key = f"{REDIS_LOG_PREFIX}{scrape_log_id}"
    raw_events = r.lrange(key, 0, -1)
    r.close()

    events = []
    for raw in raw_events:
        try:
            events.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            pass
    return events


@router.get("/dashboard/pipeline/{exchange_code}/stream")
async def stream_pipeline(exchange_code: str):
    """SSE endpoint that subscribes to Redis pub/sub and yields pipeline events."""
    import redis.asyncio as aioredis

    settings = get_settings()

    async def event_generator():
        r = aioredis.from_url(settings.redis_url)
        pubsub = r.pubsub()
        channel = f"{REDIS_CHANNEL_PREFIX}{exchange_code}"
        await pubsub.subscribe(channel)

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=300.0)
                    if msg and msg["type"] == "message":
                        yield {"event": "message", "data": msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]}
                    elif msg is None:
                        await asyncio.sleep(0.1)
                except TimeoutError:
                    yield {"event": "timeout", "data": json.dumps({"reason": "5min timeout"})}
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await r.close()

    return EventSourceResponse(event_generator())
