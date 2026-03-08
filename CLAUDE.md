# ExNot - US Options Exchange Fee Schedule Normalizer

## Project Overview

ExNot (Exchange Notifications) is an AI-agentic system that automatically collects, parses, normalizes, and monitors fee schedules from all 18+ US options exchanges. It uses Claude Agent SDK for intelligent PDF/HTML parsing, Celery for task orchestration, PostgreSQL for storage, Redis for caching/brokering and real-time event streaming, and provides both a REST API and web dashboard.

## Tech Stack

- **Language**: Python 3.12+
- **Framework**: FastAPI (API + Dashboard)
- **Database**: PostgreSQL 16 via SQLAlchemy 2.x (async with asyncpg)
- **Migrations**: Alembic
- **Task Queue**: Celery 5.x with Redis broker
- **AI/LLM**: Claude Agent SDK (`claude-agent-sdk`) — orchestrator + subagents via Claude Code CLI subprocess
- **PDF Processing**: PyMuPDF (fitz) + pdfplumber
- **Web Scraping**: httpx + BeautifulSoup4 + Playwright
- **Dashboard**: Jinja2 + HTMX + Tailwind CSS (CDN)
- **Email**: aiosmtplib
- **Auth**: JWT (python-jose) + passlib/bcrypt
- **Config**: pydantic-settings (`.env` file)
- **Testing**: pytest + pytest-asyncio
- **Linting**: ruff
- **Containerization**: Docker + Docker Compose
- **Real-time**: SSE via sse-starlette + Redis pub/sub (worker→web bridge)

## Project Structure

```
src/exnot/
├── config.py              # pydantic-settings (Settings class, model config)
├── agents/                # Claude Agent SDK pipeline layer
│   ├── pipeline.py        # Orchestrator pipeline (entry point, run_exchange_pipeline)
│   ├── streaming.py       # SSE streaming via Redis pub/sub (worker→web bridge)
│   ├── tools/             # MCP tool definitions (11 tools + server.py)
│   │   ├── server.py      # create_tools_server() — registers all MCP tools
│   │   ├── exchange.py    # load_exchange, load_exchange_prompt
│   │   ├── scraper.py     # scrape_document, check_document_changed
│   │   ├── parser.py      # parse_document
│   │   ├── profile.py     # try_profile_extract, save_profile
│   │   ├── normalizer.py  # normalize_fees
│   │   ├── differ.py      # detect_changes
│   │   ├── storage.py     # save_snapshot, save_scraped_document
│   │   ├── discovery.py   # search_fee_urls
│   │   └── notifications.py # send_notifications
│   ├── subagents/         # AgentDefinition configs
│   │   ├── extractor.py   # Fee extraction specialist (per-exchange prompts)
│   │   ├── validator.py   # Fee data validation specialist
│   │   └── discovery.py   # URL discovery specialist
│   └── prompts/           # 18 exchange-specific prompt files + registry.py
├── api/
│   ├── app.py             # FastAPI application (mounts API + dashboard + static + SSE)
│   ├── deps.py            # Dependency injection (get_db, auth helpers)
│   ├── schemas.py         # Pydantic request/response models
│   └── routes/
│       ├── admin.py       # Admin endpoints (scrape triggers, logs)
│       ├── auth.py        # Auth endpoints (login, token)
│       ├── changes.py     # Fee change history endpoints
│       ├── comparisons.py # Cross-exchange comparison
│       ├── exchanges.py   # Exchange CRUD
│       ├── fees.py        # Fee schedule endpoints
│       └── subscriptions.py
├── dashboard/
│   ├── routes.py          # Server-rendered dashboard routes (monitor, admin, SDK test)
│   ├── templates/         # Jinja2 templates (base, dashboard, exchange, monitor, etc.)
│   └── static/            # CSS/JS assets
├── db/
│   ├── engine.py          # SQLAlchemy async engine + session factory
│   ├── models.py          # ORM models (Exchange, ScrapeLog, NormalizedFee, etc.)
│   └── repositories.py   # Data access layer (repository pattern)
├── discovery/
│   ├── search.py          # SerpAPI-based URL search
│   ├── discoverer.py      # Fee schedule URL discovery
│   └── pipeline.py        # Discovery pipeline orchestration
├── exchanges/
│   ├── registry.py        # Exchange registry loader
│   └── definitions/       # 19 YAML files (one per exchange)
├── parser/
│   ├── base.py            # Abstract parser + ExtractedDocument/ExtractedTable
│   ├── factory.py         # PDF parser factory (pymupdf/docling backend selection)
│   ├── pdf_parser.py      # PDF text/table extraction (PyMuPDF + pdfplumber)
│   ├── docling_parser.py  # PDF extraction via Docling deep learning (optional)
│   ├── html_parser.py     # HTML fee schedule parser
│   ├── csv_parser.py      # CSV fee schedule parser
│   ├── ai_extractor.py    # Thin adapter → orchestrator agent (same extract() interface)
│   ├── section_splitter.py # Document section detection, context classification, grouping
│   ├── extraction_hints.py # Extraction hint generation for AI prompts
│   └── table_classifier.py # Rule-based table type classification
├── profiles/
│   ├── builder.py         # Profile builder (column→schema mappings from AI output)
│   ├── extractor.py       # Rules-based extraction using saved profiles (zero AI cost)
│   └── fingerprint.py     # Document fingerprinting for profile matching
├── normalizer/
│   ├── schema.py          # Canonical fee schema (Pydantic enums + models)
│   ├── engine.py          # Normalization pipeline
│   └── validators.py      # Fee data validation rules
├── differ/
│   ├── detector.py        # Change detection logic
│   ├── comparator.py      # Fee comparison engine
│   └── reporter.py        # Change report generation
├── notifications/
│   ├── email_sender.py    # Async SMTP delivery
│   └── templates/         # Email templates (fee_change.html, daily_digest.html)
├── scraper/
│   ├── base.py            # Abstract scraper
│   ├── http_scraper.py    # httpx-based
│   ├── browser_scraper.py # Playwright-based
│   └── document.py        # Downloaded document model
├── storage/
│   └── minio_client.py    # MinIO object storage for scraped documents
└── workers/
    ├── celery_app.py      # Celery configuration (queues, routing, time limits)
    ├── tasks.py            # Task definitions (scrape_and_process_exchange lifecycle)
    ├── schedules.py        # Beat schedule (cron)
    └── pipelines.py        # Orchestration pipelines
```

## Key Commands

```bash
# Run the app
uvicorn exnot.api.app:app --host 0.0.0.0 --port 8000 --reload

# Run with Docker
docker compose up

# Restart specific containers after code changes
docker compose restart web worker

# Run tests
pytest
pytest tests/unit/
pytest -m unit
pytest -m integration

# Lint
ruff check src/ tests/
ruff format src/ tests/

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Celery worker
celery -A exnot.workers.celery_app worker -l info
celery -A exnot.workers.celery_app beat -l info

# Check worker logs for pipeline errors
docker compose logs worker --tail=50
```

## Key Concepts

### Fee Taxonomy (Normalized Schema)

All fees are normalized into a canonical schema with these dimensions:
- **ParticipantType**: CUSTOMER, PROFESSIONAL, MARKET_MAKER, AWAY_MARKET_MAKER, FIRM, BROKER_DEALER
- **SecurityClass**: PENNY, NON_PENNY, INDEX, ETF, EQUITY, MINI
- **OrderType**: SIMPLE, COMPLEX, AUCTION, DIRECTED, QCC
- **FeeType**: MAKER, TAKER, ROUTING, ORF, TRANSACTION, COMPARISON, CONNECTIVITY, MARKET_DATA, MEMBERSHIP

Amounts are stored in `amount_cents` as hundredths of a cent (integer) for precision.

### Pipeline Flow

```
Scrape → Parse (AI) → Normalize → Diff → Notify
```

Each exchange's fee schedule goes through: document download, hash-based change detection, AI-powered extraction, normalization to canonical schema, diff against previous version, and email notification to subscribers.

### Claude Agent SDK Pipeline

The extraction pipeline uses Claude Agent SDK. The orchestrator (`agents/pipeline.py`) coordinates MCP tools and subagents via a Claude Code CLI subprocess.

**Architecture:**
```
Orchestrator (pipeline.py)
  ├── MCP Tools (agents/tools/) — 11 tools for scraping, parsing, normalizing, etc.
  ├── Subagent: extractor — fee extraction specialist (per-exchange prompts)
  ├── Subagent: validator — fee data validation
  └── Subagent: discovery — URL discovery
```

**Key design:**
- **Headless execution**: Uses `can_use_tool` callback for auto-approval (Docker/root can't use `bypassPermissions`)
- **Streaming prompt**: `can_use_tool` requires `AsyncIterable[dict]` prompt format, not plain string
- **CLAUDECODE env var**: Must `os.environ.pop("CLAUDECODE", None)` before SDK calls to prevent nested session errors
- **Budget guardrails**: Per-exchange cost limits via `AI_BUDGET_PER_EXCHANGE_USD`
- **Hybrid classification**: Tables classified by rules first; AI only for ambiguous cases

### Real-time Event Streaming

Pipeline events are streamed from Celery worker to web dashboard via Redis pub/sub:

```
Worker (pipeline.py) → Redis pub/sub → Web (streaming.py SSE) → Browser (EventSource)
```

- Events are also **persisted** to Redis lists keyed by `scrape_log_id` (24h TTL)
- Monitor page shows inline expandable log panels per run (live for RUNNING, stored for completed)
- Channel pattern: `exnot:pipeline:events:{exchange_code}`
- Storage pattern: `exnot:pipeline:log:{scrape_log_id}`

### ScrapeLog Lifecycle

`ScrapeLog` tracks pipeline execution with status enum `RUNNING → SUCCESS | FAILED | NO_CHANGE`:

1. **Task start**: Creates ScrapeLog with `status=RUNNING`, `celery_task_id` set
2. **Success**: Updates to `SUCCESS` or `NO_CHANGE`, populates `total_cost_usd`, `total_tokens`, `num_turns`
3. **Failure**: Updates to `FAILED` with `error_message` (enriched with SDK stderr output)
4. **Kill**: Admin can revoke Celery task via monitor UI, sets `FAILED` with "Manually killed"

### Extraction Profiles

The profiles system (`profiles/`) enables zero-cost re-extraction of unchanged document formats:

1. **First run**: AI extracts fees and a profile is built mapping document columns to schema fields
2. **Subsequent runs**: If the document structure fingerprint matches, the profile applies rules-based extraction with zero AI API calls
3. Profiles are stored per-exchange and include column mappings, table structure fingerprints, and match confidence scores

### Database Models

Core models in `db/models.py`:
- `Exchange` - Exchange metadata + URLs
- `FeeScheduleSnapshot` - Versioned snapshots of fee schedules
- `NormalizedFee` - Individual normalized fee entries
- `FeeChange` - Detected changes between versions
- `Subscriber` - Email notification subscribers
- `NotificationLog` - Email delivery tracking
- `ScrapeLog` - Pipeline execution log (status, cost, tokens, turns, celery_task_id)
- `User` - Admin/dashboard users

### API Structure

- REST API at `/api/v1/` with OpenAPI docs at `/api/docs`
- Dashboard at `/dashboard/` (server-rendered with HTMX)
- Pipeline monitor at `/dashboard/monitor` (admin-only, real-time events)
- SDK test at `/dashboard/admin/sdk-test` (admin-only, connectivity check)
- SSE stream at `/dashboard/pipeline/{exchange_code}/stream`
- Health checks at `/health` and `/ready`

### Authentication

- API: JWT bearer tokens via `/api/v1/auth/login`
- Dashboard: JWT stored in HTTP-only cookie (`access_token`)
- Admin user auto-created on startup from `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars

## Docker Setup

**Critical: both `web` and `worker` containers need the Claude SDK auth mount:**
```yaml
volumes:
  - .:/app
  - ~/.claude:/root/.claude:ro
```

- Worker needs Node.js (SDK bundles Claude Code CLI as subprocess)
- `/root/.claude.json` must exist — if missing, restore from backup: `cp /root/.claude/backups/.claude.json.backup.* /root/.claude.json`
- After code changes, `docker compose restart web worker` picks up changes (bind-mounted volumes)
- PostgreSQL enum changes require both ALTER TYPE in DB and Python enum update + container restart

## Configuration

Settings are in `config.py` via pydantic-settings, loaded from environment or `.env`:

- `DATABASE_URL` - PostgreSQL async connection string
- `REDIS_URL` - Redis connection string
- `SECRET_KEY` - JWT signing key
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` - Email config
- `ADMIN_EMAIL`, `ADMIN_PASSWORD` - Default admin credentials
- `APP_URL` - Base URL for links in emails
- `AI_BUDGET_PER_EXCHANGE_USD` - Max cost per exchange per pipeline run (default: 2.00)
- `AI_BUDGET_DAILY_USD` - Daily total cap (default: 15.00)
- `SERPAPI_API_KEY` - SerpAPI key for fee schedule URL discovery
- `CLOUDFLARE_TUNNEL_TOKEN` - Cloudflare tunnel token for production deployment

## Conventions

- Repository pattern for all database access (`db/repositories.py`)
- Async throughout (asyncpg, aiosmtplib, httpx)
- Exchange definitions are YAML-driven (`exchanges/definitions/`)
- Dashboard uses Tailwind CSS via CDN and HTMX for dynamic updates
- ruff for linting with rules: E, F, I, N, W, UP (line length 120)
- DB schema changes: add column via `ALTER TABLE` directly, update ORM model, restart containers
- Pipeline events use Redis pub/sub for real-time + Redis lists for persistence (24h TTL)
