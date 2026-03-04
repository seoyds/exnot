# Dashboard & Monitoring

[← Home](Home.md) | [API Reference](API-Reference.md)

## Overview

ExNot provides a server-rendered web dashboard at `/dashboard/` using Jinja2 templates, HTMX for dynamic updates, and Tailwind CSS (CDN) for styling. The dashboard includes a real-time agent monitoring system using Server-Sent Events (SSE).

## Dashboard Pages

```mermaid
graph TD
    Login[/dashboard/login] --> Dashboard[/dashboard]
    Dashboard --> ExchangeDetail[/dashboard/exchanges/:code]
    Dashboard --> Compare[/dashboard/compare]
    Dashboard --> Changes[/dashboard/changes]
    Dashboard --> Monitor[/dashboard/monitor<br/>Admin only]
    Dashboard --> Subscribe[/dashboard/subscribe]

    Monitor --> Events[/dashboard/monitor/events/:run_id<br/>HTMX fragment]
    Monitor -.->|SSE| Stream[/dashboard/monitor/stream]

    ExchangeDetail --> Download[/dashboard/exchanges/:code/<br/>documents/:doc_id/download]

    style Monitor fill:#E91E63,color:white
    style Stream fill:#E91E63,color:white
```

### Main Dashboard (`/dashboard`)

Overview page showing:
- All exchanges with status indicators (last scrape time, latest version)
- Recent fee changes across all exchanges
- Quick links to trigger scrapes (admin)

### Exchange Detail (`/dashboard/exchanges/{code}`)

Detailed view of a single exchange:
- Current normalized fees table (filterable by participant type, fee type, etc.)
- Version history with confidence scores and AI costs
- Scraped documents with download links
- V3 dimension filters (origin code, liquidity role, product type)

### Fee Comparison (`/dashboard/compare`)

Side-by-side fee comparison across multiple exchanges:
- Multi-select exchange picker
- Filter by participant type, security class, order type, fee type
- V3 dimension filters
- Results displayed in a comparison grid

### Change History (`/dashboard/changes`)

Filterable change log:
- Filter by exchange, change type (NEW/MODIFIED/REMOVED), date range
- Shows old vs. new amounts for modified fees
- Links to affected exchange detail pages

### Subscription Management (`/dashboard/subscribe`, `/dashboard/unsubscribe`)

Public pages for email subscription signup and removal:
- Frequency selection (Immediate, Daily Digest, Weekly)
- Exchange filter (all or specific exchanges)
- Email-based unsubscribe

## Real-Time Agent Monitoring

The monitoring system provides live visibility into AI extraction pipelines. **Admin-only access**.

### Architecture

```mermaid
sequenceDiagram
    participant Worker as Celery Worker
    participant Redis as Redis Pub/Sub
    participant DB as PostgreSQL
    participant SSE as SSE Endpoint
    participant Browser

    Worker->>DB: Save AgentEvent
    Worker->>Redis: Publish to exnot:events:{run_id}

    Browser->>SSE: Connect to /dashboard/monitor/stream
    SSE->>DB: Replay existing events (catch-up)
    SSE-->>Browser: Historical events

    loop Real-time stream
        Redis-->>SSE: New event published
        SSE-->>Browser: SSE event
        Browser->>Browser: HTMX update DOM
    end

    Note over Browser: Admin clicks "Cancel"
    Browser->>SSE: POST /dashboard/monitor/{run_id}/stop
    SSE->>Redis: Set cancel flag
    SSE->>Worker: Revoke Celery task (SIGTERM)
```

### Event Flow

1. **Worker** saves `AgentEvent` records to PostgreSQL and publishes to Redis pub/sub
2. **SSE endpoint** (`/dashboard/monitor/stream`) first replays existing events from DB (catch-up for late-joining clients)
3. Then subscribes to Redis channels (`exnot:events:{run_id}` or `exnot:events:all`)
4. Events are streamed as JSON to the browser via SSE
5. HTMX processes events and updates the DOM in real-time

### Event Types Displayed

| Event | Display |
|-------|---------|
| `PIPELINE_START` | Run card appears with exchange name, model info |
| `PIPELINE_STEP` | Progress update (e.g., "Extracting group 2/5") |
| `AI_CALL_START` | Spinner, prompt preview |
| `AI_CALL_COMPLETE` | Token count, cost, latency |
| `BUDGET_WARNING` | Yellow warning badge |
| `PIPELINE_COMPLETE` | Green checkmark, total cost summary |
| `PIPELINE_ERROR` | Red error with message |

### Run Events Detail View

Clicking a run expands to show all events via HTMX fragment:
```
GET /dashboard/monitor/events/{run_id}
```
Returns an HTML fragment (not a full page) that HTMX inserts into the run card.

### Cancellation

Admins can cancel runs:
- **Single run**: `POST /dashboard/monitor/{run_id}/stop`
- **All runs**: `POST /dashboard/monitor/stop-all`

Cancellation:
1. Sets a Redis flag `exnot:cancel:{run_id}`
2. Revokes the Celery task with `SIGTERM`
3. `AIExtractor` checks the cancel flag before each section group

## HTMX Patterns

The dashboard uses HTMX for dynamic interactions without a JavaScript framework:

```html
<!-- Example: Filter fees table -->
<select hx-get="/dashboard/exchanges/CBOE_BZX"
        hx-target="#fees-table"
        hx-include="[name='participant_type'],[name='fee_type']"
        name="participant_type">
    <option value="">All</option>
    <option value="CUSTOMER">Customer</option>
</select>

<!-- Example: HTMX SSE for monitoring -->
<div hx-ext="sse"
     sse-connect="/dashboard/monitor/stream"
     sse-swap="message">
</div>
```

## Template Structure

```
dashboard/templates/
├── base.html              # Base layout (nav, Tailwind CDN, HTMX)
├── dashboard.html         # Main overview page
├── exchange.html          # Exchange detail view
├── comparison.html        # Cross-exchange comparison
├── changes.html           # Change history
├── subscribe.html         # Subscription signup
├── unsubscribe.html       # Email unsubscribe
├── login.html             # Admin login form
├── monitor.html           # Real-time monitoring (admin)
└── monitor_events.html    # HTMX fragment for run events
```

## Document Downloads

Raw scraped documents (PDFs, HTML snapshots) stored in MinIO can be downloaded:

```
GET /dashboard/exchanges/{code}/documents/{doc_id}/download
```

Streams the file from MinIO as an attachment with the original filename.

## Related Pages

- [API Reference](API-Reference.md) — REST endpoints the dashboard calls
- [AI Agent System](AI-Agent-System.md) — what the monitor displays
- [Worker Architecture](Worker-Architecture.md) — task execution model
