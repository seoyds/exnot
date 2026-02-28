# ExNot - US Options Exchange Fee Schedule Normalizer

ExNot (Exchange Notifications) automatically collects, parses, normalizes, and monitors fee schedules from all 18+ US options exchanges. It detects changes and sends email notifications to subscribers.

## Features

- **Automated scraping** of fee schedule PDFs, HTML pages, and CSVs from all major US options exchanges
- **AI-powered extraction** using Anthropic Claude to parse complex fee schedule documents into structured data
- **Section-by-section extraction** for large documents — splits into logical sections, always includes definitions/footnotes as context
- **Extraction profiles** — after the first AI run, document structure is fingerprinted and subsequent runs use rules-based extraction with zero AI cost
- **Change detection** — diffs fee schedules against previous versions and highlights additions, removals, and modifications
- **Email notifications** — subscribers receive alerts when fees change, plus daily digests and weekly summaries
- **REST API** with OpenAPI documentation at `/api/docs`
- **Web dashboard** for browsing exchanges, viewing fee schedules, and comparing fees across exchanges
- **Document storage** via MinIO for archiving scraped documents
- **URL discovery** via SerpAPI to find fee schedule URLs for new exchanges

## Tech Stack

- **Python 3.12+** / **FastAPI** / **SQLAlchemy 2.x** (async)
- **PostgreSQL 16** / **Redis** / **MinIO**
- **Celery 5.x** for task orchestration
- **Anthropic Claude** for AI extraction
- **PyMuPDF + pdfplumber** for PDF processing
- **Playwright + httpx** for web scraping
- **Jinja2 + HTMX + Tailwind CSS** for the dashboard

## Quick Start

### Prerequisites

- Docker and Docker Compose
- An Anthropic API key

### Setup

1. Clone the repository:
   ```bash
   git clone <repo-url> exnot
   cd exnot
   ```

2. Copy the environment file and configure:
   ```bash
   cp .env.example .env
   # Edit .env with your ANTHROPIC_API_KEY and other settings
   ```

3. Start the services:
   ```bash
   docker compose up
   ```

4. Access the application:
   - Dashboard: http://localhost:8000/dashboard/
   - API docs: http://localhost:8000/api/docs
   - Health check: http://localhost:8000/health

### Default Credentials

The admin user is created on first run from `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`.

## Architecture

### Pipeline

```
Scrape → Parse (AI) → Normalize → Diff → Notify
```

Each exchange's fee schedule goes through: document download, hash-based change detection, AI-powered extraction, normalization to a canonical schema, diff against the previous version, and email notification to subscribers.

### AI Extraction

The system uses two extraction strategies based on document size:

- **Single-call extraction** for small documents (< 20K chars, < 8 tables) — sends the entire document to Claude in one API call
- **Sectioned extraction** for large documents — splits into logical sections using heading detection, classifies context sections (definitions, footnotes, appendix), groups fee-bearing sections by character budget, and makes separate AI calls per group with shared context

### Extraction Profiles

After the first successful AI extraction for an exchange, a profile is built that maps document columns to schema fields. On subsequent runs, if the document structure matches the saved fingerprint, fees are extracted using rules-based logic with zero AI API calls.

### Fee Taxonomy

All fees are normalized into a canonical schema with these dimensions:

| Dimension | Values |
|-----------|--------|
| Participant | Customer, Professional, Market Maker, Firm, Broker-Dealer |
| Security Class | Penny, Non-Penny, Index, ETF, Equity, Mini |
| Order Type | Simple, Complex, Auction, Directed, QCC |
| Fee Type | Maker, Taker, Routing, ORF, Transaction, Comparison, Connectivity |

Amounts are stored as hundredths of a cent (integer) for precision.

## Development

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# With verbose output
pytest -v
```

### Linting

```bash
ruff check src/ tests/
ruff format src/ tests/
```

### Database Migrations

```bash
alembic upgrade head
alembic revision --autogenerate -m "description"
```

### Running Without Docker

```bash
# Start the API server
uvicorn exnot.api.app:app --host 0.0.0.0 --port 8000 --reload

# Start the Celery worker
celery -A exnot.workers.celery_app worker -l info

# Start the Celery beat scheduler
celery -A exnot.workers.celery_app beat -l info
```

## Configuration

Key environment variables (see `.env.example` for the full list):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL async connection string | Required |
| `REDIS_URL` | Redis connection string | Required |
| `ANTHROPIC_API_KEY` | Claude API key for AI extraction | Required |
| `SECRET_KEY` | JWT signing key | Required |
| `ADMIN_EMAIL` | Default admin email | `admin@example.com` |
| `ADMIN_PASSWORD` | Default admin password | `changeme` |
| `APP_URL` | Base URL for email links | `https://exnot.thepram.dev` |
| `AI_SECTION_CHAR_BUDGET` | Char budget per section group | `15000` |
| `SERPAPI_API_KEY` | SerpAPI key for URL discovery | Optional |

## Project Structure

See [CLAUDE.md](CLAUDE.md) for a detailed file-by-file breakdown of the codebase.
