# Agent Monitor Dashboard — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a real-time agent monitoring dashboard that streams pipeline events via SSE, shows full AI trace details, and allows stopping running tasks.

**Architecture:** New `AgentRun` and `AgentEvent` DB tables capture every pipeline step. An `EventEmitter` service writes events to both PostgreSQL (persistence) and Redis pub/sub (real-time). SSE endpoints stream events to a Jinja2+Tailwind dashboard page. Cancellation uses Redis flags + Celery revocation.

**Tech Stack:** SQLAlchemy 2.x (existing), Redis pub/sub, FastAPI SSE (StreamingResponse), Jinja2 + Tailwind + vanilla JS EventSource.

---

### Task 1: Database Models — AgentRun and AgentEvent

**Files:**
- Modify: `src/exnot/db/models.py:137-154` (add enums after existing enums)
- Modify: `src/exnot/db/models.py:453` (add new models at end)

**Step 1: Add enums and models to `db/models.py`**

After `DiscoveryStatus` enum (line 154), add:

```python
class AgentRunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentEventType(str, enum.Enum):
    PIPELINE_START = "PIPELINE_START"
    PIPELINE_STEP = "PIPELINE_STEP"
    AI_CALL_START = "AI_CALL_START"
    AI_CALL_COMPLETE = "AI_CALL_COMPLETE"
    AI_CALL_RETRY = "AI_CALL_RETRY"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    BUDGET_WARNING = "BUDGET_WARNING"
    PIPELINE_COMPLETE = "PIPELINE_COMPLETE"
    PIPELINE_ERROR = "PIPELINE_ERROR"
    CANCELLED = "CANCELLED"
```

After `ExchangeProfile` model (end of file), add:

```python
class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchanges.id"), nullable=False, index=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus), default=AgentRunStatus.RUNNING
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    exchange: Mapped["Exchange"] = relationship()
    events: Mapped[list["AgentEvent"]] = relationship(back_populates="run", order_by="AgentEvent.seq")


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[AgentEventType] = mapped_column(Enum(AgentEventType), nullable=False)
    step_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped["AgentRun"] = relationship(back_populates="events")
```

**Step 2: Generate Alembic migration**

Run: `alembic revision --autogenerate -m "add agent_runs and agent_events tables"`

**Step 3: Apply migration**

Run: `alembic upgrade head`

**Step 4: Commit**

```bash
git add src/exnot/db/models.py alembic/versions/
git commit -m "feat: add AgentRun and AgentEvent database models"
```

---

### Task 2: Repository Layer — AgentRunRepository and AgentEventRepository

**Files:**
- Modify: `src/exnot/db/repositories.py` (add at end)

**Step 1: Add repositories**

At the end of `repositories.py`, add:

```python
from exnot.db.models import AgentEvent, AgentRun, AgentRunStatus


class AgentRunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, run: AgentRun) -> AgentRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> AgentRun | None:
        stmt = select(AgentRun).where(AgentRun.id == run_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active(self) -> list[AgentRun]:
        stmt = (
            select(AgentRun)
            .where(AgentRun.status == AgentRunStatus.RUNNING)
            .options(selectinload(AgentRun.exchange))
            .order_by(AgentRun.started_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent(self, limit: int = 50) -> list[AgentRun]:
        stmt = (
            select(AgentRun)
            .options(selectinload(AgentRun.exchange))
            .order_by(AgentRun.started_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class AgentEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, event: AgentEvent) -> AgentEvent:
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_for_run(self, run_id: uuid.UUID) -> list[AgentEvent]:
        stmt = (
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id)
            .order_by(AgentEvent.seq)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
```

Also add imports at top of file:
```python
from exnot.db.models import AgentEvent, AgentRun, AgentRunStatus
```

**Step 2: Commit**

```bash
git add src/exnot/db/repositories.py
git commit -m "feat: add AgentRun and AgentEvent repositories"
```

---

### Task 3: EventEmitter Service

**Files:**
- Create: `src/exnot/ai/event_emitter.py`

**Step 1: Create the EventEmitter**

```python
"""Event emitter for agent monitoring — writes to PostgreSQL + Redis pub/sub."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime

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
            "created_at": datetime.utcnow().isoformat(),
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
        self._run.completed_at = datetime.utcnow()
        self._run.total_cost_usd = total_cost_usd
        self._run.total_input_tokens = total_input_tokens
        self._run.total_output_tokens = total_output_tokens
        self._session.commit()

        self.emit(AgentEventType.PIPELINE_COMPLETE, "pipeline_complete")
        self._cleanup()

    def fail(self, error_message: str) -> None:
        """Mark the run as failed."""
        self._run.status = AgentRunStatus.FAILED
        self._run.completed_at = datetime.utcnow()
        self._run.error_message = error_message[:2000]
        self._session.commit()

        self.emit(AgentEventType.PIPELINE_ERROR, "pipeline_error", metadata={"error": error_message[:2000]})
        self._cleanup()

    def cancel(self) -> None:
        """Mark the run as cancelled."""
        self._run.status = AgentRunStatus.CANCELLED
        self._run.completed_at = datetime.utcnow()
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
```

**Step 2: Commit**

```bash
git add src/exnot/ai/event_emitter.py
git commit -m "feat: add EventEmitter service for agent monitoring"
```

---

### Task 4: Instrument Pipeline with EventEmitter

**Files:**
- Modify: `src/exnot/workers/pipelines.py:46-229` (wrap run_scrape_pipeline)
- Modify: `src/exnot/parser/ai_extractor.py:40-56` (pass emitter, add extract params)
- Modify: `src/exnot/parser/ai_extractor.py:58-209` (_extract_async)
- Modify: `src/exnot/ai/deps.py:17-31` (add emitter field)

**Step 1: Add emitter to ExtractionDeps**

In `src/exnot/ai/deps.py`, add after the existing imports:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from exnot.ai.event_emitter import EventEmitter
```

Add field to `ExtractionDeps`:

```python
    event_emitter: EventEmitter | None = None
```

**Step 2: Instrument `run_scrape_pipeline` in `pipelines.py`**

Add import at top:
```python
from exnot.ai.event_emitter import EventEmitter
from exnot.db.models import AgentEventType
```

Wrap the pipeline function body. At the start of `run_scrape_pipeline`, after loading the exchange (line 60), create emitter:

```python
    # Create event emitter for monitoring
    emitter: EventEmitter | None = None
    try:
        emitter = EventEmitter(exchange_id=exchange.id)
        emitter.emit(AgentEventType.PIPELINE_START, "pipeline_start")
    except Exception:
        logger.warning(f"[{exchange_code}] Failed to create EventEmitter, proceeding without monitoring")
```

Add `emitter.emit(AgentEventType.PIPELINE_STEP, ...)` calls at each key step:
- After step (a2) discovery: `emitter.emit(AgentEventType.PIPELINE_STEP, "discovery")`
- After step (b) collect: `emitter.emit(AgentEventType.PIPELINE_STEP, "document_collection")`
- After step (c) hash check (NO_CHANGE): `emitter.emit(AgentEventType.PIPELINE_STEP, "no_change")`
- After step (d) snapshot created: `emitter.emit(AgentEventType.PIPELINE_STEP, "snapshot_created")`
- After step (e) parsed: `emitter.emit(AgentEventType.PIPELINE_STEP, "document_parsed")`
- Before step (f) extraction: `emitter.emit(AgentEventType.PIPELINE_STEP, "extraction_start")`
- After step (f): `emitter.emit(AgentEventType.PIPELINE_STEP, "extraction_complete")`
- After step (h) normalized: `emitter.emit(AgentEventType.PIPELINE_STEP, "normalization_complete")`
- After step (i) diff: `emitter.emit(AgentEventType.PIPELINE_STEP, "diff_complete")`
- At the end: call `emitter.complete(cost_tracker data)` or `emitter.fail(error)` in except block

Pass `emitter` to `AIExtractor.extract()`:
```python
    extraction_result = ai_extractor.extract(extracted, exchange_code, event_emitter=emitter)
```

Wrap entire pipeline body in try/except to call `emitter.fail()` on error.

**Step 3: Instrument `AIExtractor` in `ai_extractor.py`**

Update `extract()` signature:
```python
    def extract(self, document: ExtractedDocument, exchange_code: str, event_emitter=None) -> ExtractionResult:
```

Pass `event_emitter` through to `_extract_async()`:
```python
    async def _extract_async(self, document, exchange_code, event_emitter=None):
```

Set emitter on deps:
```python
    deps = ExtractionDeps(
        ...
        event_emitter=event_emitter,
    )
```

In the extraction loop (lines 120-182), add events around each `agent.run()` call:

```python
        for gi, group in enumerate(section_groups):
            if cost_tracker.is_over_budget:
                if event_emitter:
                    event_emitter.emit(AgentEventType.BUDGET_WARNING, f"group_{gi}",
                                       metadata={"budget_remaining": cost_tracker.budget_remaining})
                break

            # Check cancellation
            if event_emitter and event_emitter.is_cancelled():
                logger.info(f"[{exchange_code}] Cancelled at group {gi}")
                event_emitter.cancel()
                break

            # Emit AI_CALL_START
            if event_emitter:
                event_emitter.emit(AgentEventType.AI_CALL_START, f"extract_section:{section_info[:50]}",
                                   model=extraction_model_name, prompt_text=prompt)

            start_time = time.time()
            result = await section_extractor_agent.run(...)
            elapsed_ms = int((time.time() - start_time) * 1000)

            usage = result.usage()
            cost = cost_tracker.record(...)

            # Emit AI_CALL_COMPLETE
            if event_emitter:
                event_emitter.emit(
                    AgentEventType.AI_CALL_COMPLETE,
                    f"extract_section:{section_info[:50]}",
                    model=extraction_model_name,
                    response_text=str([f.model_dump() for f in result.output.fees]),
                    input_tokens=usage.input_tokens or 0,
                    output_tokens=usage.output_tokens or 0,
                    cost_usd=cost,
                    latency_ms=elapsed_ms,
                )
```

Similarly instrument the validation call in `_run_validation()`.

Add `import time` at top of ai_extractor.py.

**Step 4: Commit**

```bash
git add src/exnot/ai/deps.py src/exnot/workers/pipelines.py src/exnot/parser/ai_extractor.py
git commit -m "feat: instrument pipeline and AI extractor with event emission"
```

---

### Task 5: Cancellation Mechanism

**Files:**
- Modify: `src/exnot/workers/tasks.py:137-202` (store task ID on emitter)

**Step 1: Pass Celery task ID to pipeline**

In `scrape_and_process_exchange` task (line 163), pass `self.request.id`:

```python
    change_report = run_scrape_pipeline(exchange_code, session, celery_task_id=self.request.id)
```

Update `run_scrape_pipeline` signature in `pipelines.py`:
```python
def run_scrape_pipeline(exchange_code: str, session: Session, celery_task_id: str | None = None) -> ChangeReport | None:
```

Pass to EventEmitter:
```python
    emitter = EventEmitter(exchange_id=exchange.id, celery_task_id=celery_task_id)
```

**Step 2: Commit**

```bash
git add src/exnot/workers/tasks.py src/exnot/workers/pipelines.py
git commit -m "feat: pass Celery task ID through to EventEmitter for cancellation"
```

---

### Task 6: SSE Streaming Endpoints

**Files:**
- Modify: `src/exnot/dashboard/routes.py` (add monitor routes at end)

**Step 1: Add SSE stream endpoint and monitor page route**

Add at end of `routes.py`:

```python
import asyncio
import json
import uuid as _uuid

from exnot.db.models import AgentEventType, AgentRunStatus


# ---------------------------------------------------------------------------
# Agent Monitor
# ---------------------------------------------------------------------------


@router.get("/dashboard/monitor", response_class=HTMLResponse)
async def monitor_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Agent monitoring dashboard — admin only."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/dashboard/login?error=Admin+login+required", status_code=303)

    from exnot.db.repositories import AgentRunRepository

    run_repo = AgentRunRepository(db)
    runs = await run_repo.get_recent(limit=50)

    return templates.TemplateResponse(
        "monitor.html",
        {
            "request": request,
            "runs": runs,
            "user": user,
        },
    )


@router.get("/dashboard/monitor/stream")
async def monitor_stream(
    request: Request,
    run_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for real-time agent events."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return HTMLResponse("Unauthorized", status_code=401)

    from exnot.ai.event_emitter import CHANNEL_ALL, EventEmitter, _channel_for_run

    async def event_generator():
        r = EventEmitter.get_redis_client()
        pubsub = r.pubsub()

        if run_id:
            channel = _channel_for_run(_uuid.UUID(run_id))
        else:
            channel = CHANNEL_ALL

        pubsub.subscribe(channel)

        # If run_id specified, replay existing events from DB
        if run_id:
            from exnot.db.repositories import AgentEventRepository

            async with AsyncSessionLocal() as replay_db:
                event_repo = AgentEventRepository(replay_db)
                events = await event_repo.get_for_run(_uuid.UUID(run_id))
                for ev in events:
                    msg = {
                        "run_id": str(ev.run_id),
                        "seq": ev.seq,
                        "event_type": ev.event_type.value,
                        "step_name": ev.step_name,
                        "model": ev.model,
                        "prompt_text": ev.prompt_text,
                        "response_text": ev.response_text,
                        "input_tokens": ev.input_tokens,
                        "output_tokens": ev.output_tokens,
                        "cost_usd": ev.cost_usd,
                        "latency_ms": ev.latency_ms,
                        "metadata": ev.metadata_json,
                        "created_at": ev.created_at.isoformat() if ev.created_at else None,
                    }
                    yield f"data: {json.dumps(msg)}\n\n"

        try:
            while True:
                message = pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    yield f"data: {message['data'].decode()}\n\n"
                else:
                    # Send keepalive
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)
        finally:
            pubsub.unsubscribe()
            pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/dashboard/monitor/events/{run_id}", response_class=HTMLResponse)
async def monitor_run_events(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return events for a specific run as HTML fragment (for initial load via HTMX)."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return HTMLResponse("Unauthorized", status_code=401)

    from exnot.db.repositories import AgentEventRepository, AgentRunRepository

    run_repo = AgentRunRepository(db)
    run = await run_repo.get_by_id(_uuid.UUID(run_id))
    if not run:
        return HTMLResponse("Run not found", status_code=404)

    event_repo = AgentEventRepository(db)
    events = await event_repo.get_for_run(_uuid.UUID(run_id))

    return templates.TemplateResponse(
        "monitor_events.html",
        {
            "request": request,
            "run": run,
            "events": events,
            "user": user,
        },
    )


@router.post("/dashboard/monitor/{run_id}/stop")
async def stop_run(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stop a single running agent run."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/dashboard/login?error=Admin+login+required", status_code=303)

    from exnot.ai.event_emitter import EventEmitter
    from exnot.db.repositories import AgentRunRepository
    from exnot.workers.celery_app import celery_app

    run_repo = AgentRunRepository(db)
    run = await run_repo.get_by_id(_uuid.UUID(run_id))
    if not run:
        return RedirectResponse(url="/dashboard/monitor?error=Run+not+found", status_code=303)

    # Set cancellation flag
    EventEmitter.request_cancel(run.id)

    # Revoke Celery task
    if run.celery_task_id:
        celery_app.control.revoke(run.celery_task_id, terminate=True, signal="SIGTERM")

    # Update run status
    run.status = AgentRunStatus.CANCELLED
    run.completed_at = datetime.utcnow()
    await db.commit()

    return RedirectResponse(url="/dashboard/monitor?success=Run+stopped", status_code=303)


@router.post("/dashboard/monitor/stop-all")
async def stop_all_runs(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stop all running agent runs."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/dashboard/login?error=Admin+login+required", status_code=303)

    from exnot.ai.event_emitter import EventEmitter
    from exnot.db.repositories import AgentRunRepository
    from exnot.workers.celery_app import celery_app

    run_repo = AgentRunRepository(db)
    active_runs = await run_repo.get_active()

    for run in active_runs:
        EventEmitter.request_cancel(run.id)
        if run.celery_task_id:
            celery_app.control.revoke(run.celery_task_id, terminate=True, signal="SIGTERM")
        run.status = AgentRunStatus.CANCELLED
        run.completed_at = datetime.utcnow()

    await db.commit()

    return RedirectResponse(
        url=f"/dashboard/monitor?success=Stopped+{len(active_runs)}+runs",
        status_code=303,
    )
```

Also add import at top of `routes.py`:
```python
from exnot.db.engine import AsyncSessionLocal
```

**Step 2: Commit**

```bash
git add src/exnot/dashboard/routes.py
git commit -m "feat: add monitor page, SSE stream, and stop endpoints"
```

---

### Task 7: Dashboard Template — Monitor Page

**Files:**
- Create: `src/exnot/dashboard/templates/monitor.html`
- Create: `src/exnot/dashboard/templates/monitor_events.html`
- Modify: `src/exnot/dashboard/templates/base.html:70-76` (add Monitor nav link)

**Step 1: Add Monitor link to base.html nav**

After the Admin nav link (line 75), add a Monitor link. Replace the admin block:

```html
                                {% if user and user.is_admin %}
                                <a href="/dashboard/monitor"
                                   class="rounded-md px-3 py-2 text-sm font-medium transition-colors
                                          {% if '/monitor' in request.url.path %}bg-slate-800 text-white{% else %}text-slate-300 hover:bg-slate-700 hover:text-white{% endif %}">
                                    Monitor
                                </a>
                                <a href="/dashboard/admin"
                                   class="rounded-md px-3 py-2 text-sm font-medium transition-colors
                                          {% if '/admin' in request.url.path and '/monitor' not in request.url.path %}bg-slate-800 text-white{% else %}text-slate-300 hover:bg-slate-700 hover:text-white{% endif %}">
                                    Admin
                                </a>
                                {% endif %}
```

**Step 2: Create `monitor.html`**

```html
{% extends "base.html" %}

{% block title %}Agent Monitor{% endblock %}

{% block header %}
<header class="bg-white shadow">
    <div class="mx-auto max-w-7xl px-4 py-4 sm:px-6 lg:px-8 flex items-center justify-between">
        <h1 class="text-2xl font-bold tracking-tight text-slate-900">Agent Monitor</h1>
        <div class="flex items-center gap-3">
            <span id="active-count" class="text-sm text-slate-500"></span>
            <form method="post" action="/dashboard/monitor/stop-all" id="stop-all-form" class="hidden">
                <button type="submit"
                        class="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 transition-colors"
                        onclick="return confirm('Stop all running agent tasks?')">
                    Stop All
                </button>
            </form>
        </div>
    </div>
</header>
{% endblock %}

{% block content %}
{% if success %}
<div class="mb-4 rounded-md bg-green-50 p-4"><p class="text-sm text-green-800">{{ success }}</p></div>
{% endif %}
{% if error %}
<div class="mb-4 rounded-md bg-red-50 p-4"><p class="text-sm text-red-800">{{ error }}</p></div>
{% endif %}

<div class="flex gap-6" style="height: calc(100vh - 240px);">
    <!-- Left panel: Run list -->
    <div class="w-80 flex-shrink-0 overflow-y-auto space-y-2" id="run-list">
        {% for run in runs %}
        <div class="run-card cursor-pointer rounded-lg border p-3 hover:bg-slate-50 transition-colors
                    {% if run.status.value == 'RUNNING' %}border-blue-300 bg-blue-50{% elif run.status.value == 'COMPLETED' %}border-green-200{% elif run.status.value == 'FAILED' %}border-red-200{% else %}border-slate-200{% endif %}"
             data-run-id="{{ run.id }}"
             onclick="selectRun('{{ run.id }}')">
            <div class="flex items-center justify-between">
                <span class="font-medium text-sm">{{ run.exchange.code if run.exchange else 'Unknown' }}</span>
                <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium
                    {% if run.status.value == 'RUNNING' %}bg-blue-100 text-blue-700
                    {% elif run.status.value == 'COMPLETED' %}bg-green-100 text-green-700
                    {% elif run.status.value == 'FAILED' %}bg-red-100 text-red-700
                    {% else %}bg-slate-100 text-slate-700{% endif %}">
                    {{ run.status.value }}
                </span>
            </div>
            <div class="mt-1 text-xs text-slate-500">
                {{ run.started_at.strftime('%H:%M:%S') if run.started_at else '' }}
                {% if run.total_cost_usd %} · ${{ "%.4f"|format(run.total_cost_usd) }}{% endif %}
                {% if run.total_input_tokens %} · {{ run.total_input_tokens + (run.total_output_tokens or 0) }} tok{% endif %}
            </div>
            {% if run.status.value == 'RUNNING' %}
            <form method="post" action="/dashboard/monitor/{{ run.id }}/stop" class="mt-2" onclick="event.stopPropagation()">
                <button type="submit" class="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200 transition-colors">
                    Stop
                </button>
            </form>
            {% endif %}
        </div>
        {% endfor %}
        {% if not runs %}
        <p class="text-sm text-slate-500 text-center py-8">No agent runs yet.</p>
        {% endif %}
    </div>

    <!-- Right panel: Event detail -->
    <div class="flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white flex flex-col">
        <div id="run-header" class="border-b border-slate-200 px-4 py-3 bg-slate-50">
            <p class="text-sm text-slate-500">Select a run to view details</p>
        </div>
        <div id="event-log" class="flex-1 overflow-y-auto p-4 space-y-2 font-mono text-xs">
        </div>
    </div>
</div>

<script>
let currentRunId = null;
let eventSource = null;

function selectRun(runId) {
    currentRunId = runId;

    // Highlight selected card
    document.querySelectorAll('.run-card').forEach(c => c.classList.remove('ring-2', 'ring-blue-500'));
    const card = document.querySelector(`[data-run-id="${runId}"]`);
    if (card) card.classList.add('ring-2', 'ring-blue-500');

    // Clear event log
    const log = document.getElementById('event-log');
    log.innerHTML = '<p class="text-slate-400">Loading events...</p>';

    // Close existing SSE
    if (eventSource) { eventSource.close(); }

    // Load existing events via fetch
    fetch(`/dashboard/monitor/events/${runId}`)
        .then(r => r.text())
        .then(html => {
            log.innerHTML = html;
            log.scrollTop = log.scrollHeight;
        });

    // Open SSE for new events
    eventSource = new EventSource(`/dashboard/monitor/stream?run_id=${runId}`);
    eventSource.onmessage = function(e) {
        const ev = JSON.parse(e.data);
        if (ev.run_id !== runId) return;
        appendEvent(ev);
    };
    eventSource.onerror = function() {
        // Reconnect will happen automatically
    };
}

function appendEvent(ev) {
    const log = document.getElementById('event-log');
    const div = document.createElement('div');
    div.className = 'border-l-2 pl-3 py-1 ' + eventBorderColor(ev.event_type);

    let content = `<div class="flex items-center gap-2">
        <span class="text-slate-400">${ev.created_at ? ev.created_at.split('T')[1]?.slice(0,8) : ''}</span>
        <span class="font-semibold ${eventTextColor(ev.event_type)}">${ev.event_type}</span>
        <span class="text-slate-600">${ev.step_name}</span>
    </div>`;

    if (ev.model) {
        content += `<div class="text-slate-500 mt-0.5">Model: ${ev.model}</div>`;
    }
    if (ev.input_tokens || ev.output_tokens) {
        content += `<div class="text-slate-500 mt-0.5">${ev.input_tokens || 0} in / ${ev.output_tokens || 0} out`;
        if (ev.cost_usd) content += ` · $${ev.cost_usd.toFixed(4)}`;
        if (ev.latency_ms) content += ` · ${ev.latency_ms}ms`;
        content += `</div>`;
    }

    if (ev.prompt_text) {
        content += `<details class="mt-1"><summary class="cursor-pointer text-blue-600 hover:text-blue-800">Prompt</summary>
            <pre class="mt-1 max-h-60 overflow-auto rounded bg-slate-50 p-2 text-xs whitespace-pre-wrap">${escapeHtml(ev.prompt_text)}</pre></details>`;
    }
    if (ev.response_text) {
        content += `<details class="mt-1"><summary class="cursor-pointer text-green-600 hover:text-green-800">Response</summary>
            <pre class="mt-1 max-h-60 overflow-auto rounded bg-slate-50 p-2 text-xs whitespace-pre-wrap">${escapeHtml(ev.response_text)}</pre></details>`;
    }
    if (ev.metadata) {
        content += `<details class="mt-1"><summary class="cursor-pointer text-slate-500 hover:text-slate-700">Metadata</summary>
            <pre class="mt-1 max-h-40 overflow-auto rounded bg-slate-50 p-2 text-xs whitespace-pre-wrap">${escapeHtml(JSON.stringify(ev.metadata, null, 2))}</pre></details>`;
    }

    div.innerHTML = content;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

function eventBorderColor(type) {
    const colors = {
        'PIPELINE_START': 'border-blue-400', 'PIPELINE_STEP': 'border-slate-300',
        'AI_CALL_START': 'border-yellow-300', 'AI_CALL_COMPLETE': 'border-green-400',
        'AI_CALL_RETRY': 'border-orange-400', 'VALIDATION_ERROR': 'border-red-400',
        'BUDGET_WARNING': 'border-amber-400', 'PIPELINE_COMPLETE': 'border-green-500',
        'PIPELINE_ERROR': 'border-red-500', 'CANCELLED': 'border-slate-500',
    };
    return colors[type] || 'border-slate-300';
}

function eventTextColor(type) {
    const colors = {
        'PIPELINE_START': 'text-blue-600', 'PIPELINE_STEP': 'text-slate-600',
        'AI_CALL_START': 'text-yellow-600', 'AI_CALL_COMPLETE': 'text-green-600',
        'AI_CALL_RETRY': 'text-orange-600', 'VALIDATION_ERROR': 'text-red-600',
        'BUDGET_WARNING': 'text-amber-600', 'PIPELINE_COMPLETE': 'text-green-700',
        'PIPELINE_ERROR': 'text-red-700', 'CANCELLED': 'text-slate-600',
    };
    return colors[type] || 'text-slate-600';
}

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

// Update active run count and show/hide Stop All
(function updateActiveCount() {
    const running = document.querySelectorAll('.run-card .bg-blue-100').length;
    const countEl = document.getElementById('active-count');
    const stopAll = document.getElementById('stop-all-form');
    if (running > 0) {
        countEl.textContent = `${running} running`;
        stopAll.classList.remove('hidden');
    } else {
        countEl.textContent = 'No active runs';
        stopAll.classList.add('hidden');
    }
})();
</script>
{% endblock %}
```

**Step 3: Create `monitor_events.html`**

This is a fragment template (no base extension) returned by the HTMX events endpoint:

```html
{% for ev in events %}
<div class="border-l-2 pl-3 py-1
    {% if ev.event_type.value == 'PIPELINE_START' %}border-blue-400
    {% elif ev.event_type.value == 'PIPELINE_STEP' %}border-slate-300
    {% elif ev.event_type.value == 'AI_CALL_START' %}border-yellow-300
    {% elif ev.event_type.value == 'AI_CALL_COMPLETE' %}border-green-400
    {% elif ev.event_type.value == 'AI_CALL_RETRY' %}border-orange-400
    {% elif ev.event_type.value == 'VALIDATION_ERROR' %}border-red-400
    {% elif ev.event_type.value == 'BUDGET_WARNING' %}border-amber-400
    {% elif ev.event_type.value == 'PIPELINE_COMPLETE' %}border-green-500
    {% elif ev.event_type.value == 'PIPELINE_ERROR' %}border-red-500
    {% elif ev.event_type.value == 'CANCELLED' %}border-slate-500
    {% else %}border-slate-300{% endif %}">
    <div class="flex items-center gap-2">
        <span class="text-slate-400">{{ ev.created_at.strftime('%H:%M:%S') if ev.created_at else '' }}</span>
        <span class="font-semibold
            {% if ev.event_type.value == 'AI_CALL_COMPLETE' %}text-green-600
            {% elif ev.event_type.value == 'PIPELINE_ERROR' %}text-red-700
            {% elif ev.event_type.value == 'PIPELINE_START' %}text-blue-600
            {% elif ev.event_type.value == 'AI_CALL_START' %}text-yellow-600
            {% elif ev.event_type.value == 'AI_CALL_RETRY' %}text-orange-600
            {% elif ev.event_type.value == 'BUDGET_WARNING' %}text-amber-600
            {% elif ev.event_type.value == 'PIPELINE_COMPLETE' %}text-green-700
            {% elif ev.event_type.value == 'CANCELLED' %}text-slate-600
            {% else %}text-slate-600{% endif %}">
            {{ ev.event_type.value }}
        </span>
        <span class="text-slate-600">{{ ev.step_name }}</span>
    </div>
    {% if ev.model %}
    <div class="text-slate-500 mt-0.5">Model: {{ ev.model }}</div>
    {% endif %}
    {% if ev.input_tokens or ev.output_tokens %}
    <div class="text-slate-500 mt-0.5">
        {{ ev.input_tokens or 0 }} in / {{ ev.output_tokens or 0 }} out
        {% if ev.cost_usd %} · ${{ "%.4f"|format(ev.cost_usd) }}{% endif %}
        {% if ev.latency_ms %} · {{ ev.latency_ms }}ms{% endif %}
    </div>
    {% endif %}
    {% if ev.prompt_text %}
    <details class="mt-1">
        <summary class="cursor-pointer text-blue-600 hover:text-blue-800">Prompt</summary>
        <pre class="mt-1 max-h-60 overflow-auto rounded bg-slate-50 p-2 text-xs whitespace-pre-wrap">{{ ev.prompt_text }}</pre>
    </details>
    {% endif %}
    {% if ev.response_text %}
    <details class="mt-1">
        <summary class="cursor-pointer text-green-600 hover:text-green-800">Response</summary>
        <pre class="mt-1 max-h-60 overflow-auto rounded bg-slate-50 p-2 text-xs whitespace-pre-wrap">{{ ev.response_text }}</pre>
    </details>
    {% endif %}
    {% if ev.metadata_json %}
    <details class="mt-1">
        <summary class="cursor-pointer text-slate-500 hover:text-slate-700">Metadata</summary>
        <pre class="mt-1 max-h-40 overflow-auto rounded bg-slate-50 p-2 text-xs whitespace-pre-wrap">{{ ev.metadata_json | tojson(indent=2) }}</pre>
    </details>
    {% endif %}
</div>
{% endfor %}
{% if not events %}
<p class="text-slate-400">No events recorded for this run.</p>
{% endif %}
```

**Step 4: Commit**

```bash
git add src/exnot/dashboard/templates/
git commit -m "feat: add monitor page template with SSE event streaming"
```

---

### Task 8: Lint and Verify

**Step 1: Run ruff check**

Run: `ruff check src/exnot/ai/event_emitter.py src/exnot/db/models.py src/exnot/db/repositories.py src/exnot/dashboard/routes.py src/exnot/workers/pipelines.py src/exnot/parser/ai_extractor.py src/exnot/ai/deps.py`

Fix any issues.

**Step 2: Run ruff format**

Run: `ruff format src/exnot/ai/event_emitter.py src/exnot/db/models.py src/exnot/db/repositories.py src/exnot/dashboard/routes.py src/exnot/workers/pipelines.py src/exnot/parser/ai_extractor.py src/exnot/ai/deps.py`

**Step 3: Run tests**

Run: `pytest tests/unit/ -x -v`

Fix any failures.

**Step 4: Commit fixes if any**

```bash
git add -u
git commit -m "fix: lint and test fixes for agent monitor feature"
```

---

### Task 9: Manual Smoke Test

**Step 1: Start services**

Run: `docker compose up -d` (or equivalent) to start PostgreSQL, Redis.

**Step 2: Apply migration**

Run: `alembic upgrade head`

**Step 3: Start the app**

Run: `uvicorn exnot.api.app:app --host 0.0.0.0 --port 8000 --reload`

**Step 4: Verify**

1. Login at `/dashboard/login`
2. Navigate to `/dashboard/monitor` — should see empty state
3. Trigger a scrape from the dashboard
4. Return to `/dashboard/monitor` — should see the run appear
5. Click the run card — should see events streaming in
6. Verify prompt/response expandable sections work
7. Test "Stop" button on a running task
8. Test "Stop All" button

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: agent monitor dashboard — complete implementation"
```
