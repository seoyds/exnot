# ExNot - US Options Exchange Fee Schedule Normalizer

## Project Overview

ExNot (Exchange Notifications) is an AI-agentic system that automatically collects, parses, normalizes, and monitors fee schedules from all 18+ US options exchanges. It uses PydanticAI agents with LiteLLM for intelligent PDF/HTML parsing (routed via OpenRouter), Celery for task orchestration, PostgreSQL for storage, Redis for caching/brokering, and provides both a REST API and web dashboard.

## Tech Stack

- **Language**: Python 3.12+
- **Framework**: FastAPI (API + Dashboard)
- **Database**: PostgreSQL 16 via SQLAlchemy 2.x (async with asyncpg)
- **Migrations**: Alembic
- **Task Queue**: Celery 5.x with Redis broker
- **AI/LLM**: PydanticAI + LiteLLM via OpenRouter (per-task model routing)
- **PDF Processing**: PyMuPDF (fitz) + pdfplumber
- **Web Scraping**: httpx + BeautifulSoup4 + Playwright
- **Dashboard**: Jinja2 + HTMX + Tailwind CSS (CDN)
- **Email**: aiosmtplib
- **Auth**: JWT (python-jose) + passlib/bcrypt
- **Config**: pydantic-settings (`.env` file)
- **Testing**: pytest + pytest-asyncio
- **Linting**: ruff
- **Containerization**: Docker + Docker Compose

## Project Structure

```
src/exnot/
├── config.py              # pydantic-settings (Settings class, per-task model routing)
├── ai/                    # AI foundation layer
│   ├── models.py          # LiteLLM model registry, TaskType → PydanticAI model routing
│   ├── cost.py            # Per-run cost tracking via LiteLLM completion_cost()
│   ├── deps.py            # Shared PydanticAI dependency dataclasses
│   ├── types.py           # Pydantic output models for all agent stages
│   └── agents/            # PydanticAI agent definitions
│       ├── orchestrator.py      # Extraction orchestrator (CHEAP tier, plans + coordinates)
│       ├── section_extractor.py # Per-section fee extraction (EXPENSIVE tier)
│       ├── fee_validator.py     # Structured validation (MEDIUM tier)
│       ├── correction.py        # Targeted correction (EXPENSIVE tier, budget-gated)
│       ├── table_classifier.py  # Hybrid rule-based + AI classification (CHEAP tier)
│       ├── discovery.py         # URL evaluation (CHEAP tier)
│       └── summarizer.py        # Change summary (CHEAP tier)
├── api/
│   ├── app.py             # FastAPI application (mounts API + dashboard + static)
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
│   ├── routes.py          # Server-rendered dashboard routes
│   ├── templates/         # Jinja2 templates (base, dashboard, exchange, comparison, changes, etc.)
│   └── static/            # CSS/JS assets
├── db/
│   ├── engine.py          # SQLAlchemy async engine + session factory
│   ├── models.py          # ORM models (Exchange, FeeScheduleSnapshot, NormalizedFee, FeeChange, Subscriber, etc.)
│   └── repositories.py   # Data access layer (repository pattern)
├── discovery/
│   ├── search.py          # SerpAPI-based URL search
│   ├── discoverer.py      # Fee schedule URL discovery (uses discovery agent)
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
│   └── reporter.py        # Change report generation (uses summarizer agent)
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
    ├── tasks.py            # Task definitions
    ├── schedules.py        # Beat schedule (cron)
    └── pipelines.py        # Orchestration pipelines
```

## Key Commands

```bash
# Run the app
uvicorn exnot.api.app:app --host 0.0.0.0 --port 8000 --reload

# Run with Docker
docker compose up

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

### Agentic AI Extraction

The extraction pipeline uses PydanticAI agents with per-task model routing via LiteLLM/OpenRouter. `AIExtractor` (`parser/ai_extractor.py`) is a thin adapter that delegates to the orchestrator agent.

**Agent graph:**
```
Orchestrator (CHEAP) — plans strategy, coordinates tools
  ├── classify_tables    → Table Classifier (rule-based + CHEAP AI fallback)
  ├── get_document_sections → section_splitter.py (no AI cost)
  ├── extract_section    → Section Extractor (EXPENSIVE) — core fee extraction
  ├── validate_extraction → Fee Validator (MEDIUM) — completeness checks
  └── correct_extraction → Correction Agent (EXPENSIVE, budget-gated)
```

**Key design:**
- **Typed output**: All agents return Pydantic models (`ExtractedFee`, `SectionExtractionResult`, etc.) — no JSON parsing/salvage code needed
- **Per-task model routing**: Each task uses the cheapest model that works (e.g., Gemini Flash for classification, Claude Sonnet for extraction). Configured via `AI_MODEL_*` env vars.
- **Budget guardrails**: `CostTracker` tracks per-exchange cost using LiteLLM's `completion_cost()`. Correction agent is budget-gated — skipped if over budget.
- **Automatic retry**: PydanticAI handles structured retry via `ModelRetry` in output validators (e.g., sign/rebate consistency, missing CUSTOMER fees).
- **Hybrid classification**: Tables are classified by rules first; AI is only called for ambiguous tables (score near 0).

The orchestrator decides whether to use single or sectioned extraction based on document structure. Section splitting uses `section_splitter.py` as before. The `extract()` interface and `ExtractionResult` dataclass are unchanged — `pipelines.py` calls it identically.

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
- `ScrapeLog` - Scraping activity log
- `User` - Admin/dashboard users

### API Structure

- REST API at `/api/v1/` with OpenAPI docs at `/api/docs`
- Dashboard at `/dashboard/` (server-rendered with HTMX)
- Health checks at `/health` and `/ready`

### Authentication

- API: JWT bearer tokens via `/api/v1/auth/login`
- Dashboard: JWT stored in HTTP-only cookie (`access_token`)
- Admin user auto-created on startup from `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars

## Configuration

Settings are in `config.py` via pydantic-settings, loaded from environment or `.env`:

- `DATABASE_URL` - PostgreSQL async connection string
- `REDIS_URL` - Redis connection string
- `OPENROUTER_API_KEY` - OpenRouter API key
- `OPENROUTER_BASE_URL` - OpenRouter base URL (default: https://openrouter.ai/api/v1)
- `SECRET_KEY` - JWT signing key
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` - Email config
- `ADMIN_EMAIL`, `ADMIN_PASSWORD` - Default admin credentials
- `APP_URL` - Base URL for links in emails
- `AI_MODEL` - Default/fallback model (default: anthropic/claude-sonnet-4-20250514)
- `AI_MODEL_TABLE_CLASSIFICATION` - Table classifier model (default: google/gemini-2.5-flash)
- `AI_MODEL_ORCHESTRATOR` - Orchestrator model (default: google/gemini-2.5-flash)
- `AI_MODEL_FEE_EXTRACTION` - Fee extraction model (default: anthropic/claude-sonnet-4-20250514)
- `AI_MODEL_FEE_VALIDATION` - Validation model (default: openai/gpt-4o-mini)
- `AI_MODEL_CORRECTION` - Correction model (default: anthropic/claude-sonnet-4-20250514)
- `AI_MODEL_URL_DISCOVERY` - URL discovery model (default: google/gemini-2.5-flash)
- `AI_MODEL_CHANGE_SUMMARY` - Change summary model (default: google/gemini-2.5-flash)
- `AI_BUDGET_PER_EXCHANGE_USD` - Max cost per exchange per pipeline run (default: 2.00)
- `AI_BUDGET_DAILY_USD` - Daily total cap (default: 15.00)
- `AI_SECTION_CHAR_BUDGET` - Character budget per section group for sectioned AI extraction (default 15000)
- `SERPAPI_API_KEY` - SerpAPI key for fee schedule URL discovery
- `CLOUDFLARE_TUNNEL_TOKEN` - Cloudflare tunnel token for production deployment

## Conventions

- Repository pattern for all database access (`db/repositories.py`)
- Async throughout (asyncpg, aiosmtplib, httpx)
- Exchange definitions are YAML-driven (`exchanges/definitions/`)
- Dashboard uses Tailwind CSS via CDN and HTMX for dynamic updates
- ruff for linting with rules: E, F, I, N, W, UP (line length 120)
