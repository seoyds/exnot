"""Event emitter for agent monitoring — writes to PostgreSQL + Redis pub/sub."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

import redis

from exnot.config import get_settings
from exnot.db.engine import get_sync_session
from exnot.db.models import AgentEvent, AgentEventType, AgentRun, AgentRunStatus

logger = logging.getLogger(__name__)

# Redis channel names
CHANNEL_ALL = "agent_runs:all"


def _channel_for_run(run_id: uuid.UUID) -> str:
    return f"agent_run:{run_id}"


def _cancel_key(run_id: uuid.UUID) -> str:
    return f"agent_run:cancel:{run_id}"


class EventEmitter:
    """Emits agent pipeline events to PostgreSQL and Redis pub/sub.

    Designed to be used from synchronous Celery task context.
    """

    def __init__(self, exchange_id: uuid.UUID, celery_task_id: str | None = None):
        settings = get_settings()
        self._redis = redis.from_url(settings.redis_url)
        self._session = get_sync_session()
        self._seq = 0

        # Create the AgentRun record
        self._run = AgentRun(
            exchange_id=exchange_id,
            celery_task_id=celery_task_id,
            status=AgentRunStatus.RUNNING,
        )
        self._session.add(self._run)
        self._session.commit()
        self.run_id = self._run.id

    def emit(
        self,
        event_type: AgentEventType,
        step_name: str,
        *,
        model: str | None = None,
        prompt_text: str | None = None,
        response_text: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
        latency_ms: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Emit a single event to DB + Redis."""
        self._seq += 1

        event = AgentEvent(
            run_id=self.run_id,
            seq=self._seq,
            event_type=event_type,
            step_name=step_name,
            model=model,
            prompt_text=prompt_text,
            response_text=response_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            metadata_json=metadata,
        )
        self._session.add(event)
        self._session.commit()

        # Publish to Redis
        msg = {
            "run_id": str(self.run_id),
            "seq": self._seq,
            "event_type": event_type.value,
            "step_name": step_name,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 6) if cost_usd else None,
            "latency_ms": latency_ms,
            "created_at": datetime.now(tz=UTC).isoformat(),
        }
        msg_json = json.dumps(msg)
        self._redis.publish(_channel_for_run(self.run_id), msg_json)

        # Publish summary to global channel (no prompt/response text)
        self._redis.publish(CHANNEL_ALL, msg_json)

    def complete(
        self,
        total_cost_usd: float = 0.0,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
    ) -> None:
        """Mark the run as completed."""
        self._run.status = AgentRunStatus.COMPLETED
        self._run.completed_at = datetime.now(tz=UTC)
        self._run.total_cost_usd = total_cost_usd
        self._run.total_input_tokens = total_input_tokens
        self._run.total_output_tokens = total_output_tokens
        self._session.commit()

        self.emit(AgentEventType.PIPELINE_COMPLETE, "pipeline_complete")
        self._cleanup()

    def fail(self, error_message: str) -> None:
        """Mark the run as failed."""
        self._run.status = AgentRunStatus.FAILED
        self._run.completed_at = datetime.now(tz=UTC)
        self._run.error_message = error_message[:2000]
        self._session.commit()

        self.emit(AgentEventType.PIPELINE_ERROR, "pipeline_error", metadata={"error": error_message[:2000]})
        self._cleanup()

    def cancel(self) -> None:
        """Mark the run as cancelled."""
        self._run.status = AgentRunStatus.CANCELLED
        self._run.completed_at = datetime.now(tz=UTC)
        self._session.commit()

        self.emit(AgentEventType.CANCELLED, "cancelled")
        self._cleanup()

    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested via Redis."""
        return bool(self._redis.exists(_cancel_key(self.run_id)))

    def _cleanup(self) -> None:
        """Close DB session and Redis connection."""
        self._session.close()

    @staticmethod
    def request_cancel(run_id: uuid.UUID, redis_url: str | None = None) -> None:
        """Set the cancellation flag in Redis for a given run."""
        settings = get_settings()
        r = redis.from_url(redis_url or settings.redis_url)
        r.set(_cancel_key(run_id), "1", ex=1800)

    @staticmethod
    def get_redis_client():
        """Get a Redis client for SSE subscription."""
        settings = get_settings()
        return redis.from_url(settings.redis_url)
