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

### AI / Claude Agent SDK

The pipeline uses the Claude Agent SDK, which bundles the Claude Code CLI as a subprocess. Authentication is handled via the Claude SDK auth file (`~/.claude/.claude.json`).

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_ORCHESTRATOR_MODEL` | `claude-sonnet-4-20250514` | Model for the orchestrator agent |
| `CLAUDE_EXTRACTOR_MODEL` | `claude-sonnet-4-20250514` | Model for the extractor subagent |
| `CLAUDE_VALIDATOR_MODEL` | `claude-sonnet-4-20250514` | Model for the validator subagent |
| `CLAUDE_DISCOVERY_MODEL` | `claude-sonnet-4-20250514` | Model for the discovery subagent |

**Docker requirements**:
- Both `web` and `worker` containers need `~/.claude:/root/.claude:ro` volume mount
- Worker needs Node.js (SDK bundles Claude Code CLI as subprocess)
- `/root/.claude.json` must exist — restore from backup if missing

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

## Claude Agent SDK Architecture

```mermaid
graph LR
    subgraph "Orchestrator"
        O[Orchestrator Agent]
    end

    subgraph "Subagents"
        E[Extractor]
        V[Validator]
        D[Discovery]
    end

    O --> Claude[Claude AI]
    E --> Claude
    V --> Claude
    D --> Claude
```

All agents use Claude models via the Agent SDK. Models are configurable per-agent via environment variables (`CLAUDE_ORCHESTRATOR_MODEL`, `CLAUDE_EXTRACTOR_MODEL`, etc.).

### Tuning Budgets

For high-value exchanges that need more extraction budget:
```bash
AI_BUDGET_PER_EXCHANGE_USD=5.00
```

Cost tracking is automatic via `ResultMessage.total_cost_usd` from the SDK.

## Example `.env` File

```bash
# Database
DATABASE_URL=postgresql+asyncpg://exnot:password@localhost:5432/exnot
DATABASE_URL_SYNC=postgresql+psycopg2://exnot:password@localhost:5432/exnot

# Redis
REDIS_URL=redis://localhost:6379/0

# AI (Claude Agent SDK)
# Auth via ~/.claude/.claude.json (mounted in Docker)
# No API key env var needed — SDK uses Claude Code CLI auth

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

- [AI Agent System](AI-Agent-System.md) — Claude Agent SDK architecture
- [Worker Architecture](Worker-Architecture.md) — Celery configuration
- [Development Guide](Development-Guide.md) — local setup instructions
