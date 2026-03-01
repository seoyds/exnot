# Agent Monitor Dashboard — Design

## Overview

A real-time, authenticated dashboard page for monitoring AI agent pipeline runs. Provides full trace visibility (prompts, responses, tokens, costs, retries), persistent event history, and the ability to stop running tasks.

## Requirements

- Auth-required, admin-only page at `/dashboard/monitor`
- SSE-based real-time streaming of agent events
- Full trace detail: prompts, responses, tokens, costs, latency, retries, validation errors
- Event persistence in PostgreSQL, real-time delivery via Redis pub/sub
- Per-exchange stop + global "Stop All" cancellation

## Data Model

### `AgentRun` table

One row per pipeline execution.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | |
| `exchange_id` | UUID FK → Exchange | |
| `celery_task_id` | varchar | Celery task ID for revocation |
| `status` | enum(`RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`) | |
| `started_at` | timestamp | |
| `completed_at` | timestamp? | |
| `total_cost_usd` | float? | Final cost from CostTracker |
| `total_input_tokens` | int? | |
| `total_output_tokens` | int? | |
| `error_message` | text? | If failed |

### `AgentEvent` table

Append-only log of every event in a run.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | |
| `run_id` | UUID FK → AgentRun | |
| `seq` | int | Ordering within run |
| `event_type` | enum | See below |
| `step_name` | varchar | e.g. "extract_section", "validate", "scrape" |
| `model` | varchar? | LLM model used |
| `prompt_text` | text? | Full prompt sent to LLM |
| `response_text` | text? | Full response from LLM |
| `input_tokens` | int? | |
| `output_tokens` | int? | |
| `cost_usd` | float? | |
| `latency_ms` | int? | |
| `metadata` | JSONB? | Retries, validation errors, tool calls, etc. |
| `created_at` | timestamp | |

**Event types**: `PIPELINE_START`, `PIPELINE_STEP`, `AI_CALL_START`, `AI_CALL_COMPLETE`, `AI_CALL_RETRY`, `VALIDATION_ERROR`, `BUDGET_WARNING`, `PIPELINE_COMPLETE`, `PIPELINE_ERROR`, `CANCELLED`

## Event Emission & Streaming

### EventEmitter service

A thin service class that writes to both PostgreSQL and Redis pub/sub:

```python
class EventEmitter:
    def __init__(self, run_id, db_session, redis_client):
        self._run_id = run_id
        self._seq = 0

    async def emit(self, event_type, step_name, **kwargs):
        self._seq += 1
        # 1. INSERT into agent_events table
        # 2. PUBLISH to Redis channel "agent_run:{run_id}"
```

Created at the start of `run_scrape_pipeline()`, passed through to `AIExtractor` via `ExtractionDeps`.

Emission points:
- **pipelines.py**: PIPELINE_START, PIPELINE_STEP (scraping, hashing, parsing, normalizing, diffing), PIPELINE_COMPLETE/PIPELINE_ERROR
- **ai_extractor.py**: AI_CALL_START/AI_CALL_COMPLETE around each agent.run(), AI_CALL_RETRY on ModelRetry, BUDGET_WARNING when over budget

### SSE endpoints

```
GET /dashboard/monitor/stream?run_id={id}   — single run events
GET /dashboard/monitor/stream               — all active runs (summary only)
```

On connect, replays existing events from DB, then streams new events from Redis pub/sub.

### Redis channels

- Per-run: `agent_run:{run_id}` — full events for detail view
- Global: `agent_runs:all` — lightweight summaries for overview

## Cancellation

### Two-layer approach

1. **Redis cancellation flag**: `agent_run:cancel:{run_id}` key with 1800s TTL
2. **Celery revocation**: `celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')`

The AI extraction loop checks the cancellation flag before each section group. Current LLM call finishes, then the loop breaks. Already-extracted fees are preserved.

### Endpoints

```
POST /dashboard/monitor/{run_id}/stop   — stop single run (admin-only)
POST /dashboard/monitor/stop-all        — stop all running (admin-only)
```

## Dashboard UI

### Page: `/dashboard/monitor`

**Top bar**: "Stop All" button (red, count badge). Hidden when nothing running.

**Left panel — Active Runs list**:
- Cards per AgentRun, sorted by started_at desc
- Shows: exchange name, status badge, elapsed time, cost, tokens
- Running cards have "Stop" button
- Click to view detail in right panel
- Live updates via SSE from `agent_runs:all`

**Right panel — Run Detail**:
- Header: exchange, status, total cost, tokens, elapsed time
- Live event log: scrollable feed, auto-scrolling, newest at bottom
- Each event row: timestamp, step name, event type badge
- AI_CALL_COMPLETE rows: model, tokens in/out, cost, latency
- Expandable `<details>` for prompt and response text
- AI_CALL_RETRY/VALIDATION_ERROR: error details in metadata
- Live updates via SSE from `agent_run:{run_id}`

**Navigation**: "Monitor" link in nav bar, visible only to logged-in admins.

### Tech stack

- Jinja2 + Tailwind CSS (CDN) + HTMX (consistent with existing dashboard)
- Native `EventSource` JS for SSE
- Client-side DOM append for event log rendering
- `<details>` elements for prompt/response expand/collapse
