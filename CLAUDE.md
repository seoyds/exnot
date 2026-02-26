# ExNot - US Options Exchange Fee Schedule Normalizer

## Project Overview

ExNot (Exchange Notifications) is an AI-agentic system that automatically collects, parses, normalizes, and monitors fee schedules from all 18+ US options exchanges. It uses Anthropic Claude for intelligent PDF/HTML parsing, Celery for task orchestration, PostgreSQL for storage, Redis for caching/brokering, and provides both a REST API and web dashboard.

## Tech Stack

- **Language**: Python 3.12+
- **Framework**: FastAPI (API + Dashboard)
- **Database**: PostgreSQL 16 via SQLAlchemy 2.x (async with asyncpg)
- **Migrations**: Alembic
- **Task Queue**: Celery 5.x with Redis broker
- **AI/LLM**: Anthropic Claude API
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
├── config.py              # pydantic-settings (Settings class)
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
├── exchanges/
│   ├── registry.py        # Exchange registry loader
│   └── definitions/       # 19 YAML files (one per exchange)
├── scraper/
│   ├── base.py            # Abstract scraper
│   ├── http_scraper.py    # httpx-based
│   ├── browser_scraper.py # Playwright-based
│   └── document.py        # Downloaded document model
├── parser/
│   ├── base.py            # Abstract parser
│   ├── pdf_parser.py      # PDF text/table extraction
│   ├── html_parser.py     # HTML fee schedule parser
│   └── ai_extractor.py    # Claude-powered extraction pipeline
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
└── workers/
    ├── celery_app.py      # Celery configuration
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
- `ANTHROPIC_API_KEY` - Claude API key
- `SECRET_KEY` - JWT signing key
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` - Email config
- `ADMIN_EMAIL`, `ADMIN_PASSWORD` - Default admin credentials
- `APP_URL` - Base URL for links in emails

## Conventions

- Repository pattern for all database access (`db/repositories.py`)
- Async throughout (asyncpg, aiosmtplib, httpx)
- Exchange definitions are YAML-driven (`exchanges/definitions/`)
- Dashboard uses Tailwind CSS via CDN and HTMX for dynamic updates
- ruff for linting with rules: E, F, I, N, W, UP (line length 120)
