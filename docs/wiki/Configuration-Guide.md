# Configuration Guide

[← Home](Home.md) | [Architecture Overview](Architecture-Overview.md)

## Overview

All configuration is managed via `pydantic-settings` in `src/exnot/config.py`. Settings are loaded from environment variables or a `.env` file in the project root. The `Settings` object is cached as a singleton via `@lru_cache`.

## Environment Variables

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async PostgreSQL connection string |
| `DATABASE_URL_SYNC` | `postgresql+psycopg2://...` | Sync connection string (used by Celery) |

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection (broker + result backend + pub/sub) |

### AI / LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | OpenRouter API key (required) |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter base URL |
| `DASHSCOPE_API_KEY` | — | DashScope API key (optional, for direct Qwen routing) |
| `AI_MODEL` | `deepseek/deepseek-v3.2-20251201` | Default/fallback model |

### Per-Task Model Routing

Each AI task can use a different model for cost/quality optimization:

| Variable | Default | Task |
|----------|---------|------|
| `AI_MODEL_TABLE_CLASSIFICATION` | `qwen/qwen3.5-flash-02-23` | Table type classification |
| `AI_MODEL_ORCHESTRATOR` | `qwen/qwen3.5-flash-02-23` | Extraction orchestrator |
| `AI_MODEL_FEE_EXTRACTION` | `deepseek/deepseek-v3.2-20251201` | Core fee extraction |
| `AI_MODEL_FEE_VALIDATION` | `mistralai/mistral-small-3.1-24b-instruct` | Extraction validation |
| `AI_MODEL_CORRECTION` | `deepseek/deepseek-v3.2-20251201` | Targeted correction |
| `AI_MODEL_URL_DISCOVERY` | `qwen/qwen3.5-flash-02-23` | Fee schedule URL discovery |
| `AI_MODEL_CHANGE_SUMMARY` | `qwen/qwen3.5-flash-02-23` | Change summary generation |

**Provider routing**:
- Models starting with `qwen/` → DashScope (if `DASHSCOPE_API_KEY` set) → OpenRouter (fallback)
- All other models → OpenRouter

### Budget Guardrails

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_BUDGET_PER_EXCHANGE_USD` | `2.00` | Max AI cost per exchange per pipeline run |
| `AI_BUDGET_DAILY_USD` | `15.00` | Daily total AI cost cap |
| `AI_SECTION_CHAR_BUDGET` | `15000` | Character budget per section group for AI extraction |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | — | JWT signing key (required) |
| `ADMIN_EMAIL` | — | Default admin email (auto-created on startup) |
| `ADMIN_PASSWORD` | — | Default admin password |

### Email / SMTP

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP server port |
| `SMTP_USERNAME` | — | SMTP auth username |
| `SMTP_PASSWORD` | — | SMTP auth password (app password for Gmail) |
| `SMTP_FROM_EMAIL` | — | Sender email address |

### Scraping

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRAPE_DELAY_SECONDS` | `2` | Delay between requests to same domain |
| `SCRAPE_MAX_RETRIES` | `3` | Max retry attempts for failed scrapes |
| `SCRAPE_TIMEOUT_SECONDS` | `30` | HTTP request timeout |
| `SCRAPE_USER_AGENT` | (browser UA) | User-Agent header for requests |

### Object Storage (MinIO)

| Variable | Default | Description |
|----------|---------|-------------|
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO server endpoint |
| `MINIO_ACCESS_KEY` | — | MinIO access key |
| `MINIO_SECRET_KEY` | — | MinIO secret key |
| `MINIO_BUCKET` | `exnot-documents` | Bucket for scraped documents |
| `MINIO_SECURE` | `false` | Use HTTPS for MinIO |

### URL Discovery

| Variable | Default | Description |
|----------|---------|-------------|
| `SERPAPI_API_KEY` | — | SerpAPI key for Google search |

### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_URL` | `http://localhost:8000` | Base URL for links in emails |
| `CLOUDFLARE_TUNNEL_TOKEN` | — | Cloudflare tunnel token for production |

## Model Cost Tiers

```mermaid
graph LR
    subgraph "CHEAP ($)"
        TC[Table Classification]
        OR[Orchestrator]
        UD[URL Discovery]
        CS[Change Summary]
    end

    subgraph "MEDIUM ($$)"
        FV[Fee Validation]
    end

    subgraph "EXPENSIVE ($$$)"
        FE[Fee Extraction]
        CO[Correction]
    end

    TC --> Q[qwen3.5-flash]
    OR --> Q
    UD --> Q
    CS --> Q
    FV --> M[mistral-small]
    FE --> D[deepseek-v3.2]
    CO --> D
```

### Tuning Models

To use a different model for fee extraction:
```bash
AI_MODEL_FEE_EXTRACTION=anthropic/claude-3.5-sonnet
```

To use the same model for everything:
```bash
AI_MODEL=anthropic/claude-3.5-sonnet
# Individual overrides take precedence over AI_MODEL
```

### Tuning Budgets

For high-value exchanges that need more extraction budget:
```bash
AI_BUDGET_PER_EXCHANGE_USD=5.00
```

For reducing section sizes (more AI calls, but each sees less text):
```bash
AI_SECTION_CHAR_BUDGET=10000
```

## Example `.env` File

```bash
# Database
DATABASE_URL=postgresql+asyncpg://exnot:password@localhost:5432/exnot
DATABASE_URL_SYNC=postgresql+psycopg2://exnot:password@localhost:5432/exnot

# Redis
REDIS_URL=redis://localhost:6379/0

# AI
OPENROUTER_API_KEY=sk-or-v1-xxxxx
DASHSCOPE_API_KEY=sk-xxxxx  # Optional: direct Qwen routing

# Auth
SECRET_KEY=your-secret-key-here
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=changeme

# Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your@gmail.com
SMTP_PASSWORD=app-password-here

# Storage
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin

# Discovery
SERPAPI_API_KEY=xxxxx

# App
APP_URL=http://localhost:8000
```

## Related Pages

- [AI Agent System](AI-Agent-System.md) — model routing details
- [Worker Architecture](Worker-Architecture.md) — Celery configuration
- [Development Guide](Development-Guide.md) — local setup instructions
