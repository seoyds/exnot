# Architecture Overview

[← Home](Home.md)

## System Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        Browser[Web Browser]
        APIClient[API Clients]
    end

    subgraph "Application Layer"
        Web[FastAPI Web Server<br/>:8000]
        Dashboard[Dashboard<br/>Jinja2 + HTMX]
        API[REST API<br/>/api/v1/]
    end

    subgraph "Task Processing Layer"
        Worker[Celery Workers<br/>4 concurrent]
        Beat[Celery Beat<br/>Scheduler]
        Flower[Flower<br/>:5555]
    end

    subgraph "AI Layer"
        AIExtractor[AI Extractor]
        Orchestrator[Orchestrator Agent]
        SectionExtractor[Section Extractor]
        Validator[Fee Validator]
        Correction[Correction Agent]
        TableClassifier[Table Classifier]
    end

    subgraph "Data Layer"
        PG[(PostgreSQL 16)]
        Redis[(Redis 7)]
        MinIO[(MinIO<br/>Object Storage)]
    end

    subgraph "External Services"
        OpenRouter[OpenRouter / DashScope<br/>LLM API]
        Exchanges[18+ Exchange<br/>Websites]
        SerpAPI[SerpAPI<br/>URL Discovery]
        SMTP[SMTP Server<br/>Gmail]
    end

    Browser --> Dashboard
    APIClient --> API
    Web --> Dashboard
    Web --> API
    Dashboard -.->|SSE| Browser

    API --> PG
    Dashboard --> PG
    Worker --> PG
    Worker --> Redis
    Worker --> MinIO
    Beat --> Redis

    Worker --> AIExtractor
    AIExtractor --> Orchestrator
    AIExtractor --> SectionExtractor
    AIExtractor --> Validator
    AIExtractor --> Correction
    AIExtractor --> TableClassifier

    SectionExtractor --> OpenRouter
    Validator --> OpenRouter
    Correction --> OpenRouter
    TableClassifier --> OpenRouter

    Worker --> Exchanges
    Worker --> SerpAPI
    Worker --> SMTP
```

## Service Topology (Docker Compose)

ExNot runs as 7 containers orchestrated by Docker Compose:

| Service | Image / Command | Port | Purpose |
|---------|----------------|------|---------|
| **web** | `uvicorn exnot.api.app:app` | 8000 | FastAPI app serving API + Dashboard |
| **worker** | `celery worker -c 4` | — | Processes scraping, parsing, notification tasks |
| **beat** | `celery beat` | — | Cron-like periodic task scheduler |
| **flower** | `celery flower` | 5555 | Celery task monitoring UI |
| **db** | `postgres:16-alpine` | 5432 | Primary data store |
| **redis** | `redis:7-alpine` | 6379 | Celery broker + result backend + pub/sub |
| **cloudflared** | Cloudflare tunnel | — | Production TLS ingress |

```mermaid
graph LR
    subgraph "Docker Compose"
        web[web :8000]
        worker[worker]
        beat[beat]
        flower[flower :5555]
        db[(db :5432)]
        redis[(redis :6379)]
        cloudflared[cloudflared]
    end

    cloudflared -->|proxy| web
    web --> db
    web --> redis
    worker --> db
    worker --> redis
    beat --> redis
    flower --> redis
    worker -.->|MinIO| minio[(MinIO)]
```

## Module Map

```
src/exnot/
├── config.py              # Central configuration (pydantic-settings)
├── ai/                    # AI foundation: agents, models, cost tracking
│   ├── models.py          # LiteLLM model registry + TaskType routing
│   ├── cost.py            # Per-run cost tracking
│   ├── deps.py            # Shared PydanticAI dependencies
│   ├── types.py           # Pydantic output models for all agents
│   ├── prompts/           # Per-exchange extraction prompts (19 files)
│   └── agents/            # PydanticAI agent definitions (7 agents)
├── api/                   # FastAPI routes + schemas
├── dashboard/             # Jinja2 templates + static assets
├── db/                    # SQLAlchemy models + repository layer
├── discovery/             # Fee schedule URL discovery (SerpAPI)
├── exchanges/             # Exchange registry + YAML definitions
├── parser/                # PDF/HTML/CSV parsing + AI extraction
├── profiles/              # Zero-cost re-extraction profiles
├── normalizer/            # Canonical fee schema + mapping engine
├── differ/                # Change detection + comparison + reporting
├── notifications/         # Email delivery + templates
├── scraper/               # HTTP + Playwright document fetching
├── storage/               # MinIO client for raw document storage
└── workers/               # Celery app, tasks, schedules, pipelines
```

## Layer Architecture

```mermaid
graph TB
    subgraph "Presentation"
        REST[REST API]
        DASH[Dashboard]
    end

    subgraph "Application"
        Pipelines[Pipeline Orchestration]
        Tasks[Celery Tasks]
    end

    subgraph "Domain"
        Scraping[Document Collection]
        Parsing[Parsing & AI Extraction]
        Normalization[Normalization]
        Diffing[Change Detection]
        Notifications[Notification Delivery]
        Discovery[URL Discovery]
    end

    subgraph "Infrastructure"
        DB[Database / Repository]
        Storage[MinIO Storage]
        Cache[Redis Cache/Broker]
        LLM[LLM Provider]
        Email[SMTP]
    end

    REST --> DB
    DASH --> DB
    DASH -.->|SSE via Redis| Cache

    Tasks --> Pipelines
    Pipelines --> Scraping
    Pipelines --> Parsing
    Pipelines --> Normalization
    Pipelines --> Diffing
    Pipelines --> Notifications
    Pipelines --> Discovery

    Scraping --> Storage
    Parsing --> LLM
    Normalization --> DB
    Diffing --> DB
    Notifications --> Email
    Discovery --> LLM
```

## Key Design Decisions

### Async/Sync Bridge

The web server is fully async (asyncpg, httpx). Celery workers are synchronous — they use `asyncio.run()` to bridge into async scraping and email code. This gives Celery's reliable task execution model without sacrificing async I/O for network-heavy operations.

### Repository Pattern

All database access goes through `db/repositories.py`. Route handlers and pipeline code never construct raw queries. Each entity type has a dedicated repository class with typed async methods.

### Per-Exchange Configuration

Each exchange is defined in a YAML file (`exchanges/definitions/`) specifying its URL, document format, scraper type, and parser hints. Exchange-specific AI prompts live in `ai/prompts/`. This separation means adding a new exchange requires only a YAML file and an optional prompt — no code changes.

### Budget-Aware AI

Every AI call is cost-tracked via `CostTracker`. Per-exchange and daily budgets prevent runaway costs. The correction agent is entirely skipped when over budget.

## Related Pages

- [Pipeline Deep Dive](Pipeline-Deep-Dive.md) — detailed flow of each pipeline stage
- [AI Agent System](AI-Agent-System.md) — how the agents coordinate
- [Worker Architecture](Worker-Architecture.md) — Celery task design
- [Database Schema](Database-Schema.md) — data model
