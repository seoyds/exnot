# ExNot - US Options Exchange Fee Schedule Normalizer & Change Notifier

## Grand Plan

---

## Executive Summary

**ExNot** (Exchange Notifications) is an AI-agentic system that automatically collects, parses, normalizes, and monitors fee schedules from all 18 US options exchanges. It uses Anthropic Claude for intelligent PDF/HTML parsing, Python Celery for task orchestration, PostgreSQL for persistent storage with versioning, Redis for caching and message brokering, and provides both a REST API and web dashboard for consuming normalized fee data. Email notifications alert subscribers to any fee schedule changes.

---

## Target Exchanges (18 Total)

### Cboe Global Markets (4 exchanges)
| Exchange | Fee Schedule URL | Format |
|----------|-----------------|--------|
| Cboe Options Exchange (C1) | https://www.cboe.com/us/options/membership/fee_schedule/cone/ | HTML + embedded PDF |
| Cboe BZX Options | https://www.cboe.com/us/options/membership/fee_schedule/bzx/ | HTML + embedded PDF |
| Cboe C2 Options | https://www.cboe.com/us/options/membership/fee_schedule/ctwo/ | HTML + embedded PDF |
| Cboe EDGX Options | https://www.cboe.com/us/options/membership/fee_schedule/edgx/ | HTML + embedded PDF |

### Nasdaq, Inc. (6 exchanges)
| Exchange | Fee Schedule URL | Format |
|----------|-----------------|--------|
| Nasdaq PHLX | https://listingcenter.nasdaq.com/rulebook/phlx/rules/phlx-options-7 | HTML (rulebook) |
| Nasdaq Options Market (NOM) | https://listingcenter.nasdaq.com/rulebook/nasdaq/rules/nasdaq-options-7 | HTML (rulebook) |
| Nasdaq ISE | https://listingcenter.nasdaq.com/rulebook/ise/rules/ise-options-7 | HTML (rulebook) |
| Nasdaq GEMX | https://listingcenter.nasdaq.com/rulebook/gemx/rules/gemx-options-7 | HTML (rulebook) |
| Nasdaq MRX | https://listingcenter.nasdaq.com/rulebook/mrx/rules/mrx-options-7 | HTML (rulebook) |
| Nasdaq BX Options | https://listingcenter.nasdaq.com/rulebook/bx/rules/bx-options-7 | HTML (rulebook) |

### NYSE / ICE (2 exchanges)
| Exchange | Fee Schedule URL | Format |
|----------|-----------------|--------|
| NYSE Arca Options | https://www.nyse.com/publicdocs/nyse/markets/arca-options/NYSE_Arca_Options_Fee_Schedule.pdf | PDF |
| NYSE American Options | https://www.nyse.com/publicdocs/nyse/markets/american-options/NYSE_American_Options_Fee_Schedule.pdf | PDF |

### MIAX Exchange Group (4 exchanges)
| Exchange | Fee Schedule URL | Format |
|----------|-----------------|--------|
| MIAX Options | https://www.miaxglobal.com/markets/us-options/all-options-exchanges/fees | HTML + PDF |
| MIAX PEARL | https://www.miaxglobal.com/markets/us-options/pearl-options/fees | HTML + PDF |
| MIAX Emerald | https://www.miaxglobal.com/markets/us-options/emerald-options/fees | HTML + PDF |
| MIAX Sapphire | https://www.miaxglobal.com/markets/us-options/all-options-exchanges/fees | HTML + PDF |

### BOX Exchange (1 exchange)
| Exchange | Fee Schedule URL | Format |
|----------|-----------------|--------|
| BOX Options | https://boxexchange.com/regulatory/fees/ | PDF |

### MEMX (1 exchange)
| Exchange | Fee Schedule URL | Format |
|----------|-----------------|--------|
| MEMX Options | https://info.memxtrading.com/us-options-trading-resources/us-options-fee-schedule/ | HTML |

---

## Normalized Fee Taxonomy (Universal Schema)

All exchange fee schedules will be normalized into these canonical categories:

### Participant Types (rows)
- **Customer** - Retail/non-professional individual
- **Professional Customer** - Individual meeting professional thresholds
- **Market Maker** - Registered market maker on that exchange
- **Away Market Maker** - Market maker registered on another exchange
- **Firm/Proprietary** - Broker-dealer trading for own account
- **Broker-Dealer** - Non-market-maker broker-dealer

### Fee Dimensions (columns)
- **Maker Fee/Rebate** - Fee (positive) or rebate (negative) for adding liquidity
- **Taker Fee/Rebate** - Fee (positive) or rebate (negative) for removing liquidity
- **Routing Fee** - Fee for orders routed to other exchanges

### Security Classifications
- **Penny Pilot** - Securities in the penny increment pilot program
- **Non-Penny** - Securities NOT in penny pilot
- **Index Options** - SPX, VIX, and other index options (select exchanges)
- **ETF Options** - Options on ETFs
- **Equity Options** - Standard equity options
- **Mini Options** - Mini-sized option contracts

### Order Types
- **Simple Orders** - Standard single-leg orders
- **Complex/Multi-leg Orders** - Spreads, straddles, etc.
- **Auction Orders** - PRICE improvement auction mechanisms
- **Directed Orders** - Orders directed to specific market makers
- **QCC (Qualified Contingent Cross)** - Qualified contingent crosses

### Additional Fee Categories
- **Options Regulatory Fee (ORF)** - Per-contract regulatory fee
- **Transaction Fee** - Section 31 / TAF fees
- **Comparison/Clearing Fee** - OCC-related clearing fees
- **Connectivity/Port Fees** - Physical/logical port charges
- **Market Data Fees** - Top of book / depth of book feeds
- **Membership/Permit Fees** - Trading permit/membership costs

### Volume Tiers
- Tier thresholds (expressed as % of OCV or absolute contracts)
- Tier qualifications per participant type
- ADAV (Average Daily Added Volume) requirements
- ADV (Average Daily Volume) requirements

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Language | Python 3.12+ | Core application |
| Task Queue | Celery 5.x | Distributed task processing & scheduling |
| Message Broker | Redis 7.x | Celery broker + caching |
| Database | PostgreSQL 16 | Persistent storage with JSONB |
| ORM | SQLAlchemy 2.x + Alembic | Database models & migrations |
| AI/LLM | Anthropic Claude API (claude-sonnet-4-20250514) | PDF parsing & data extraction |
| PDF Processing | PyMuPDF (fitz) + pdfplumber | PDF text/table extraction |
| Web Scraping | httpx + BeautifulSoup4 + Playwright | HTTP requests & HTML parsing |
| REST API | FastAPI | API framework |
| Dashboard | FastAPI + Jinja2 + HTMX + Tailwind | Server-side rendered dashboard |
| Email | SMTP (via `aiosmtplib`) | Change notifications |
| Containerization | Docker + Docker Compose | Deployment |
| Testing | pytest + pytest-asyncio + factory-boy | Test framework |
| Linting | ruff | Code quality |

---

## Phase 1: Project Scaffolding & Infrastructure

### 1.1 Project Structure
```
exnot/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
├── alembic/
│   └── versions/
├── src/
│   └── exnot/
│       ├── __init__.py
│       ├── config.py              # Settings via pydantic-settings
│       ├── db/
│       │   ├── __init__.py
│       │   ├── engine.py          # SQLAlchemy engine/session
│       │   ├── models.py          # All ORM models
│       │   └── repositories.py    # Data access layer
│       ├── exchanges/
│       │   ├── __init__.py
│       │   ├── registry.py        # Exchange registry with URLs
│       │   └── definitions/       # Per-exchange config YAML files
│       │       ├── cboe_c1.yml
│       │       ├── cboe_bzx.yml
│       │       ├── ...
│       │       └── memx.yml
│       ├── scraper/
│       │   ├── __init__.py
│       │   ├── base.py            # Abstract scraper
│       │   ├── http_scraper.py    # httpx-based scraper
│       │   ├── browser_scraper.py # Playwright-based scraper
│       │   └── document.py        # Downloaded document model
│       ├── parser/
│       │   ├── __init__.py
│       │   ├── base.py            # Abstract parser
│       │   ├── pdf_parser.py      # PDF text/table extraction
│       │   ├── html_parser.py     # HTML fee schedule parser
│       │   └── ai_extractor.py    # Claude-powered extraction
│       ├── normalizer/
│       │   ├── __init__.py
│       │   ├── schema.py          # Canonical fee schema (Pydantic)
│       │   ├── engine.py          # Normalization pipeline
│       │   └── validators.py      # Fee data validation
│       ├── differ/
│       │   ├── __init__.py
│       │   ├── detector.py        # Change detection logic
│       │   ├── comparator.py      # Fee comparison engine
│       │   └── reporter.py        # Change report generation
│       ├── notifications/
│       │   ├── __init__.py
│       │   ├── email_sender.py    # SMTP email delivery
│       │   └── templates/         # Jinja2 email templates
│       │       ├── fee_change.html
│       │       └── daily_digest.html
│       ├── api/
│       │   ├── __init__.py
│       │   ├── app.py             # FastAPI application
│       │   ├── routes/
│       │   │   ├── exchanges.py   # Exchange CRUD endpoints
│       │   │   ├── fees.py        # Fee schedule endpoints
│       │   │   ├── comparisons.py # Cross-exchange comparison
│       │   │   ├── changes.py     # Change history endpoints
│       │   │   └── subscriptions.py # Alert subscription mgmt
│       │   ├── schemas.py         # API request/response models
│       │   └── deps.py            # Dependency injection
│       ├── dashboard/
│       │   ├── __init__.py
│       │   ├── routes.py          # Dashboard page routes
│       │   ├── templates/         # Jinja2 HTML templates
│       │   │   ├── base.html
│       │   │   ├── dashboard.html
│       │   │   ├── exchange.html
│       │   │   ├── comparison.html
│       │   │   └── changes.html
│       │   └── static/            # CSS/JS assets
│       └── workers/
│           ├── __init__.py
│           ├── celery_app.py      # Celery configuration
│           ├── tasks.py           # Task definitions
│           ├── schedules.py       # Beat schedule (cron)
│           └── pipelines.py       # Orchestration pipelines
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── fixtures/                  # Sample PDFs, HTML for testing
└── scripts/
    ├── seed_exchanges.py          # Initial exchange data loader
    └── run_initial_scrape.py      # First-time full scrape
```

### 1.2 Docker Compose Services
- `web` - FastAPI app (API + Dashboard)
- `worker` - Celery worker (scraping, parsing, diffing)
- `beat` - Celery beat (scheduler)
- `db` - PostgreSQL 16
- `redis` - Redis 7
- `playwright` - Browser for JS-heavy pages (optional sidecar)

### 1.3 Configuration Management
- `pydantic-settings` for environment-based config
- `.env` file for secrets (API keys, SMTP credentials)
- YAML files for exchange definitions (URLs, scraper type, parser hints)

### 1.4 Deliverables
- [ ] `pyproject.toml` with all dependencies
- [ ] `Dockerfile` multi-stage build
- [ ] `docker-compose.yml` with all services
- [ ] `src/exnot/config.py` with pydantic settings
- [ ] Alembic setup with initial migration
- [ ] CI-ready project structure

---

## Phase 2: Database Models & Exchange Registry

### 2.1 Core Database Models

```
Exchange
├── id (UUID PK)
├── code (unique, e.g., "CBOE_C1", "NASDAQ_PHLX")
├── name (display name)
├── operator (parent company)
├── fee_schedule_url (primary URL)
├── fee_schedule_format (PDF | HTML | EXCEL)
├── scraper_type (HTTP | BROWSER)
├── parser_hints (JSONB - exchange-specific parsing config)
├── is_active (boolean)
├── created_at / updated_at

FeeScheduleSnapshot
├── id (UUID PK)
├── exchange_id (FK → Exchange)
├── version (integer, auto-increment per exchange)
├── effective_date (date)
├── source_url (URL scraped)
├── source_hash (SHA-256 of raw document)
├── raw_document (bytea - original PDF/HTML)
├── raw_text (text - extracted text)
├── ai_extraction (JSONB - Claude's structured output)
├── normalized_fees (JSONB - canonical schema)
├── parsing_confidence (float 0-1)
├── status (PENDING | PARSED | NORMALIZED | VERIFIED | FAILED)
├── error_log (text)
├── milestone_tag (e.g., "2026-Q1", version label)
├── created_at

NormalizedFee
├── id (UUID PK)
├── snapshot_id (FK → FeeScheduleSnapshot)
├── exchange_id (FK → Exchange)
├── participant_type (ENUM: customer, professional, market_maker, etc.)
├── security_class (ENUM: penny, non_penny, index, etf, etc.)
├── order_type (ENUM: simple, complex, auction, directed, qcc)
├── fee_type (ENUM: maker, taker, routing, orf, transaction, etc.)
├── amount_cents (integer - fee in hundredths of a cent for precision)
├── is_rebate (boolean)
├── volume_tier (nullable - tier name/number)
├── tier_threshold_pct (nullable - % of OCV)
├── tier_threshold_contracts (nullable - absolute contracts)
├── effective_date (date)
├── notes (text - any qualifiers/footnotes)
├── created_at

FeeChange
├── id (UUID PK)
├── exchange_id (FK → Exchange)
├── old_snapshot_id (FK → FeeScheduleSnapshot, nullable for new)
├── new_snapshot_id (FK → FeeScheduleSnapshot)
├── change_type (ENUM: new, modified, removed)
├── participant_type
├── security_class
├── order_type
├── fee_type
├── old_amount_cents (nullable)
├── new_amount_cents (nullable)
├── change_description (text - AI-generated summary)
├── detected_at (timestamp)
├── notified (boolean)

Subscriber
├── id (UUID PK)
├── email (unique)
├── name
├── is_active (boolean)
├── exchanges_filter (JSONB - null = all, or list of exchange codes)
├── notification_frequency (ENUM: immediate, daily_digest, weekly)
├── created_at

NotificationLog
├── id (UUID PK)
├── subscriber_id (FK → Subscriber)
├── fee_change_ids (JSONB - array of FeeChange IDs)
├── email_subject
├── sent_at
├── delivery_status (SENT | FAILED | BOUNCED)

ScrapeLog
├── id (UUID PK)
├── exchange_id (FK → Exchange)
├── started_at
├── completed_at
├── status (SUCCESS | FAILED | NO_CHANGE)
├── document_hash (SHA-256)
├── has_changes (boolean)
├── error_message (text, nullable)
```

### 2.2 Exchange Registry (YAML-driven)
Each exchange gets a YAML definition file:
```yaml
# definitions/cboe_c1.yml
code: CBOE_C1
name: "Cboe Options Exchange"
operator: "Cboe Global Markets"
fee_schedule_url: "https://www.cboe.com/us/options/membership/fee_schedule/cone/"
alternate_urls:
  - "https://cdn.cboe.com/resources/membership/Cboe_FeeSchedule.pdf"
fee_schedule_format: HTML
scraper_type: HTTP
parser_hints:
  has_volume_tiers: true
  has_index_options: true
  table_css_selector: "table.fee-table"
  pdf_fallback_url: "https://cdn.cboe.com/resources/membership/Cboe_FeeSchedule.pdf"
```

### 2.3 Deliverables
- [ ] SQLAlchemy models for all tables
- [ ] Alembic migration for initial schema
- [ ] 18 YAML exchange definition files
- [ ] Exchange registry loader (`registry.py`)
- [ ] Repository pattern for data access
- [ ] Database seed script

---

## Phase 3: Web Scraping & Document Collection

### 3.1 Scraper Architecture
```
AbstractScraper
├── HttpScraper (httpx + retries)
│   └── handles: direct PDF downloads, simple HTML pages
├── BrowserScraper (Playwright)
│   └── handles: JS-rendered pages, dynamic content
└── DocumentResult
    ├── content_bytes (raw bytes)
    ├── content_type (PDF, HTML)
    ├── content_hash (SHA-256)
    ├── response_headers
    └── fetched_at
```

### 3.2 Scraping Strategy Per Exchange Family

**Cboe (4 exchanges):**
- Primary: HTTP GET the HTML fee schedule page
- Fallback: Download PDF from `cdn.cboe.com`
- Challenge: Fee tables embedded in HTML with complex styling
- Strategy: Fetch HTML page, also download PDF as backup

**Nasdaq (6 exchanges):**
- Primary: HTTP GET the rulebook HTML pages
- Challenge: Multi-page rulebook format, content spread across sections
- Strategy: Crawl all sub-sections of "Options 7 Pricing Schedule"

**NYSE (2 exchanges):**
- Primary: Direct PDF download
- Challenge: PDFs have complex table layouts
- Strategy: Download PDF, use content hash for change detection

**MIAX (4 exchanges):**
- Primary: Scrape fees landing page for PDF link
- Challenge: PDF URLs change with each update (date in filename)
- Strategy: Parse landing page for current PDF link, then download

**BOX (1 exchange):**
- Primary: Scrape fees page for current PDF link
- Challenge: Similar to MIAX, dated PDF filenames
- Strategy: Parse landing page, extract latest PDF URL

**MEMX (1 exchange):**
- Primary: HTTP GET the HTML fee schedule page
- Challenge: Fee schedule is inline HTML
- Strategy: Direct HTML parsing

### 3.3 Change Detection (Pre-Parse)
- Compute SHA-256 hash of downloaded document
- Compare with last stored `source_hash` in `FeeScheduleSnapshot`
- If hash matches → no change → skip parsing (save AI costs)
- If hash differs → new version → proceed to parsing pipeline
- Also check HTTP `Last-Modified` / `ETag` headers for early exit

### 3.4 Rate Limiting & Politeness
- Respect `robots.txt` (though fee schedules are public)
- 2-5 second delay between requests to same domain
- User-Agent header identifying the bot
- Retry with exponential backoff on 429/503 responses
- Maximum 3 retries per exchange per run

### 3.5 Deliverables
- [ ] `HttpScraper` with httpx, retries, rate limiting
- [ ] `BrowserScraper` with Playwright for JS pages
- [ ] Per-exchange scraping configuration
- [ ] Document download & storage pipeline
- [ ] Hash-based change detection
- [ ] `ScrapeLog` recording

---

## Phase 4: AI-Powered Fee Schedule Parsing

### 4.1 Multi-Stage Parsing Pipeline
```
Raw Document → Stage 1: Text/Table Extraction
             → Stage 2: AI Structural Analysis
             → Stage 3: AI Fee Data Extraction
             → Stage 4: Validation & Confidence Scoring
```

### 4.2 Stage 1: Text & Table Extraction

**For PDFs:**
- Use `pdfplumber` for table detection and extraction
- Use `PyMuPDF (fitz)` for full text extraction
- Extract page-by-page text with layout preservation
- Identify table regions and extract as structured data
- Handle multi-page tables that span page breaks

**For HTML:**
- Use `BeautifulSoup4` for DOM parsing
- Extract `<table>` elements with headers
- Handle nested tables, `colspan`/`rowspan`
- Preserve footnotes and qualifier text

### 4.3 Stage 2: AI Structural Analysis (Claude)
Send extracted text/tables to Claude with a structured prompt:

```
System: You are a financial document analyst specializing in US options
exchange fee schedules. Analyze the provided fee schedule and identify:

1. All fee tables present in the document
2. The participant categories used (Customer, Market Maker, etc.)
3. The security classifications (Penny, Non-Penny, Index, etc.)
4. Volume tier structures
5. Effective dates
6. Any footnotes or qualifiers that modify fee amounts

Return a structured JSON describing the document layout.
```

This stage produces a "document map" that guides Stage 3.

### 4.4 Stage 3: AI Fee Data Extraction (Claude)
For each identified fee table, send to Claude with extraction prompt:

```
System: Extract all fee and rebate amounts from this options exchange
fee schedule table. For each fee entry, provide:

{
  "participant_type": "customer|professional|market_maker|...",
  "security_class": "penny|non_penny|index|...",
  "order_type": "simple|complex|auction|...",
  "fee_type": "maker|taker|routing|...",
  "amount": <decimal>,
  "is_rebate": <boolean>,
  "volume_tier": <string or null>,
  "tier_threshold": <string or null>,
  "notes": "<any qualifiers>"
}

Return as a JSON array. Use negative values for rebates.
Amounts should be in dollars per contract.
```

### 4.5 Stage 4: Validation & Confidence
- Validate extracted amounts are within reasonable ranges ($0.00 - $2.00 per contract)
- Cross-reference participant types against known categories
- Check for completeness (every exchange should have Customer + MM fees at minimum)
- Flag anomalies for human review
- Compute confidence score (0-1) based on:
  - Number of expected fields extracted
  - Consistency of amounts (maker < taker typically)
  - Presence of expected categories
  - AI self-reported confidence

### 4.6 Agentic Workflow: Self-Questioning Loop
If confidence < 0.8, the agent enters a self-questioning loop:
1. Identify what data is missing or uncertain
2. Re-query Claude with focused questions about specific sections
3. Try alternative extraction strategies (different table regions)
4. After 3 attempts, flag for human review

### 4.7 Deliverables
- [ ] PDF text/table extraction pipeline (`pdf_parser.py`)
- [ ] HTML table extraction pipeline (`html_parser.py`)
- [ ] Claude AI structural analysis prompts
- [ ] Claude AI data extraction prompts
- [ ] Validation rules and confidence scoring
- [ ] Self-questioning agentic loop
- [ ] `ai_extractor.py` orchestrating the pipeline
- [ ] Prompt templates stored as versioned files
- [ ] Cost tracking for API calls

---

## Phase 5: Fee Normalization Engine

### 5.1 Canonical Schema (Pydantic Models)

```python
class NormalizedFeeEntry(BaseModel):
    exchange_code: str
    participant_type: ParticipantType  # Enum
    security_class: SecurityClass      # Enum
    order_type: OrderType              # Enum
    fee_type: FeeType                  # Enum
    amount: Decimal                    # Per-contract amount in USD
    is_rebate: bool
    volume_tier: Optional[VolumeTier]
    effective_date: date
    notes: Optional[str]

class NormalizedFeeSchedule(BaseModel):
    exchange_code: str
    exchange_name: str
    effective_date: date
    fees: list[NormalizedFeeEntry]
    metadata: FeeScheduleMetadata
```

### 5.2 Normalization Rules

**Participant Type Mapping:**
Each exchange uses slightly different terminology. The normalizer maps:
- "Public Customer" / "Priority Customer" → `CUSTOMER`
- "Professional" / "Professional Customer" → `PROFESSIONAL`
- "Specialist" / "Lead Market Maker" / "DPM" → `MARKET_MAKER`
- "Away Market Maker" / "Non-Member Market Maker" → `AWAY_MARKET_MAKER`
- "Firm" / "Proprietary" / "Non-Customer" → `FIRM`
- "Broker-Dealer" / "BD" → `BROKER_DEALER`

**Amount Normalization:**
- All amounts stored as USD per contract
- Rebates stored as negative amounts with `is_rebate=True`
- Handle "per contract" vs "per executed equivalent share" conversions
- Round to 4 decimal places

**Tier Normalization:**
- Express all thresholds as both % of OCV and absolute contracts where available
- Map exchange-specific tier names to ordinal tier numbers

### 5.3 Exchange-Specific Adapters
Each exchange family may need custom normalization logic:
- Cboe: Handle SPX/VIX-specific fees, AIM auction fees
- Nasdaq: Handle pro-rata vs price-time model differences
- NYSE: Handle floor broker vs electronic execution distinctions
- MIAX: Handle their unique tier structures
- BOX: Handle PIP (Price Improvement Period) auction fees

### 5.4 Deliverables
- [ ] Pydantic models for canonical fee schema
- [ ] Participant type mapping rules
- [ ] Amount normalization logic
- [ ] Volume tier normalization
- [ ] Per-exchange-family adapters
- [ ] Validation rules ensuring schema compliance
- [ ] Unit tests with known fee amounts

---

## Phase 6: Change Detection & Versioning

### 6.1 Snapshot Versioning Strategy
- Each successful parse creates a new `FeeScheduleSnapshot` with incrementing version
- Snapshots are immutable once created
- Git-like milestoning: tag snapshots with labels (e.g., "2026-Q1-initial")
- Keep all historical snapshots (never delete)

### 6.2 Diff Algorithm
```
Previous NormalizedFee set  ──┐
                              ├──► Deep comparison ──► FeeChange records
Current NormalizedFee set   ──┘

Comparison key: (exchange_id, participant_type, security_class, order_type, fee_type, volume_tier)

For each key:
  - Present in OLD but not NEW → change_type = REMOVED
  - Present in NEW but not OLD → change_type = NEW
  - Present in both but amount differs → change_type = MODIFIED
  - Present in both and amounts same → NO CHANGE (skip)
```

### 6.3 AI-Powered Change Summarization
After detecting changes, send the diff to Claude for human-readable summary:
```
"CBOE C1: Customer maker rebate for penny pilot securities increased
from -$0.25 to -$0.28 per contract, effective February 1, 2026.
This makes CBOE C1 more competitive for customer liquidity providers
compared to the previous schedule."
```

### 6.4 Milestone Tagging
- Automatic milestone tag when fee changes are detected
- Format: `{exchange_code}_{YYYY-MM-DD}_v{version}`
- Manual milestone tagging via API/Dashboard for significant events
- Milestones enable easy rollback/comparison between versions

### 6.5 Deliverables
- [ ] Snapshot creation and versioning logic
- [ ] Deep diff comparison algorithm
- [ ] `FeeChange` record creation
- [ ] AI-powered change summarization
- [ ] Milestone tagging system
- [ ] Change history query APIs

---

## Phase 7: Email Notification System

### 7.1 Notification Triggers
- **Immediate**: When fee changes are detected, notify subscribers set to "immediate"
- **Daily Digest**: Aggregate all changes in the past 24 hours
- **Weekly Summary**: Weekly recap of all changes

### 7.2 Email Content
- HTML-formatted emails using Jinja2 templates
- Include:
  - Exchange name and effective date
  - Summary of changes (AI-generated natural language)
  - Table showing old vs new fees
  - Link to dashboard for full details
  - Unsubscribe link

### 7.3 Email Template Structure
```html
Subject: [ExNot] Fee Schedule Change: {exchange_name} - {date}

Body:
- Header with ExNot branding
- Change summary paragraph (AI-generated)
- Table: | Fee Category | Old Amount | New Amount | Change |
- "View Full Details" button → Dashboard link
- Footer with unsubscribe link
```

### 7.4 SMTP Configuration
- Support standard SMTP (Gmail, SendGrid, Amazon SES, etc.)
- TLS/STARTTLS support
- Rate limiting to avoid spam filters
- Bounce handling and delivery status tracking

### 7.5 Deliverables
- [ ] SMTP email sender with async support
- [ ] Jinja2 email templates (fee_change, daily_digest, weekly)
- [ ] Subscriber management (CRUD)
- [ ] Notification scheduling logic
- [ ] `NotificationLog` recording
- [ ] Unsubscribe mechanism
- [ ] Email preview endpoint (for testing)

---

## Phase 8: REST API

### 8.1 API Endpoints

```
Authentication: API key-based (simple, via header)

GET  /api/v1/exchanges
     → List all exchanges with latest snapshot info

GET  /api/v1/exchanges/{code}
     → Single exchange details + current fee summary

GET  /api/v1/exchanges/{code}/fees
     ?version=latest|{version_number}
     ?participant_type=customer,market_maker
     ?security_class=penny,non_penny
     ?fee_type=maker,taker
     → Normalized fees for an exchange (filterable)

GET  /api/v1/exchanges/{code}/fees/history
     ?from_date=2025-01-01&to_date=2026-01-01
     → Historical fee snapshots for an exchange

GET  /api/v1/exchanges/{code}/changes
     ?from_version=5&to_version=8
     → Fee changes between versions

GET  /api/v1/compare
     ?exchanges=CBOE_C1,NYSE_ARCA,NASDAQ_PHLX
     ?participant_type=customer
     ?security_class=penny
     ?fee_type=maker,taker
     → Cross-exchange fee comparison

GET  /api/v1/changes/recent
     ?days=7
     → All recent fee changes across all exchanges

GET  /api/v1/snapshots/{snapshot_id}
     → Detailed snapshot with raw + normalized data

POST /api/v1/subscribers
     → Create email subscription
PUT  /api/v1/subscribers/{id}
     → Update subscription preferences
DELETE /api/v1/subscribers/{id}
     → Unsubscribe

POST /api/v1/admin/scrape/{exchange_code}
     → Trigger manual scrape for an exchange
POST /api/v1/admin/scrape-all
     → Trigger manual scrape for all exchanges
GET  /api/v1/admin/scrape-logs
     → View scraping history and status
```

### 8.2 Response Format
```json
{
  "data": { ... },
  "meta": {
    "timestamp": "2026-02-26T10:00:00Z",
    "version": "1.0"
  }
}
```

### 8.3 Deliverables
- [ ] FastAPI application with router structure
- [ ] All API endpoints implemented
- [ ] Pydantic request/response schemas
- [ ] API key authentication middleware
- [ ] OpenAPI documentation (auto-generated)
- [ ] Pagination for list endpoints
- [ ] Rate limiting

---

## Phase 9: Web Dashboard

### 9.1 Dashboard Pages

**Home / Overview:**
- Status cards for each exchange (last updated, change indicator)
- Recent changes feed
- System health (last scrape times, failures)

**Exchange Detail Page:**
- Current fee schedule displayed as sortable/filterable table
- Historical versions with date picker
- Change timeline visualization
- Raw document viewer (PDF embed / HTML frame)

**Cross-Exchange Comparison:**
- Side-by-side fee comparison table
- Select exchanges, participant type, security class
- Highlight cheapest/most expensive per category
- Sortable by any fee column

**Change History:**
- Filterable log of all fee changes
- Date range picker
- Exchange filter
- Change type filter (new, modified, removed)
- Each change expandable with AI summary

**Subscription Management:**
- Subscribe/unsubscribe with email
- Select exchanges to monitor
- Choose notification frequency
- View notification history

**Admin Panel:**
- Manual scrape triggers
- Scrape log viewer
- System configuration
- Exchange management (enable/disable, update URLs)

### 9.2 Technology Choices
- **HTMX** for dynamic updates without full SPA complexity
- **Tailwind CSS** for styling
- **Chart.js** or **Plotly** for fee trend visualizations
- **Jinja2** templates for server-side rendering

### 9.3 Deliverables
- [ ] Base template with navigation
- [ ] Overview/home page
- [ ] Exchange detail page with fee tables
- [ ] Cross-exchange comparison view
- [ ] Change history page
- [ ] Subscription management page
- [ ] Admin panel
- [ ] Responsive design (mobile-friendly)

---

## Phase 10: Celery Workers & Scheduling

### 10.1 Celery Task Definitions

```python
# High-level orchestration
@celery.task
def daily_fee_schedule_check():
    """Master task: runs daily, orchestrates full pipeline for all exchanges."""
    for exchange in get_active_exchanges():
        scrape_and_process_exchange.delay(exchange.code)

@celery.task
def scrape_and_process_exchange(exchange_code: str):
    """Full pipeline for a single exchange."""
    # 1. Scrape document
    # 2. Check for changes (hash comparison)
    # 3. If changed: parse → normalize → diff → notify
    chain(
        scrape_document.s(exchange_code),
        check_for_changes.s(),
        parse_document.s(),
        normalize_fees.s(),
        detect_changes.s(),
        send_notifications.s(),
    ).apply_async()

# Individual tasks
@celery.task
def scrape_document(exchange_code: str) -> dict
@celery.task
def check_for_changes(scrape_result: dict) -> dict
@celery.task
def parse_document(document: dict) -> dict
@celery.task
def normalize_fees(parsed_data: dict) -> dict
@celery.task
def detect_changes(normalized: dict) -> dict
@celery.task
def send_notifications(changes: dict) -> None

# Maintenance tasks
@celery.task
def send_daily_digest()
@celery.task
def send_weekly_summary()
@celery.task
def cleanup_old_scrape_logs(days: int = 90)
```

### 10.2 Celery Beat Schedule
```python
beat_schedule = {
    'daily-fee-check': {
        'task': 'exnot.workers.tasks.daily_fee_schedule_check',
        'schedule': crontab(hour=6, minute=0),  # 6 AM ET daily
    },
    'daily-digest': {
        'task': 'exnot.workers.tasks.send_daily_digest',
        'schedule': crontab(hour=7, minute=0),  # 7 AM ET daily
    },
    'weekly-summary': {
        'task': 'exnot.workers.tasks.send_weekly_summary',
        'schedule': crontab(hour=8, minute=0, day_of_week=1),  # Monday 8 AM
    },
    'cleanup-logs': {
        'task': 'exnot.workers.tasks.cleanup_old_scrape_logs',
        'schedule': crontab(hour=2, minute=0, day_of_week=0),  # Sunday 2 AM
    },
}
```

### 10.3 Error Handling & Retries
- Auto-retry on network failures (3 retries, exponential backoff)
- Dead letter queue for permanently failed tasks
- Alert admin on repeated failures
- Per-exchange circuit breaker (disable after 5 consecutive failures)

### 10.4 Deliverables
- [ ] Celery application configuration
- [ ] All task definitions
- [ ] Task chaining/orchestration pipelines
- [ ] Beat schedule configuration
- [ ] Error handling and retry logic
- [ ] Dead letter queue handling
- [ ] Task monitoring setup

---

## Phase 11: Testing Strategy

### 11.1 Unit Tests
- Fee normalization logic
- Change detection algorithm
- Participant type mapping
- Amount conversion utilities
- Validation rules

### 11.2 Integration Tests
- Database operations (CRUD, queries)
- Celery task execution
- Email sending (with test SMTP server)
- API endpoint responses

### 11.3 AI/Parser Tests
- Use fixture PDFs and HTML files from actual exchanges
- Snapshot-based testing: compare AI output against known-good extractions
- Test self-questioning loop with deliberately ambiguous inputs

### 11.4 End-to-End Tests
- Full pipeline: scrape → parse → normalize → diff → notify
- Use recorded HTTP responses (VCR/cassettes) for deterministic tests

### 11.5 Deliverables
- [ ] pytest configuration with markers
- [ ] Unit tests for all core logic
- [ ] Integration tests with test database
- [ ] Fixture files (sample PDFs, HTML)
- [ ] VCR cassettes for scraper tests
- [ ] CI pipeline configuration
- [ ] Minimum 80% code coverage target

---

## Phase 12: Deployment & Operations

### 12.1 Docker Compose Production Setup
```yaml
services:
  web:
    build: .
    command: uvicorn exnot.api.app:app --host 0.0.0.0 --port 8000
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [db, redis]

  worker:
    build: .
    command: celery -A exnot.workers.celery_app worker -l info -c 4
    env_file: .env
    depends_on: [db, redis]

  beat:
    build: .
    command: celery -A exnot.workers.celery_app beat -l info
    env_file: .env
    depends_on: [db, redis]

  db:
    image: postgres:16-alpine
    volumes: [postgres_data:/var/lib/postgresql/data]
    environment:
      POSTGRES_DB: exnot
      POSTGRES_USER: exnot
      POSTGRES_PASSWORD: ${DB_PASSWORD}

  redis:
    image: redis:7-alpine
    volumes: [redis_data:/data]
```

### 12.2 Monitoring & Observability
- Celery Flower for task monitoring
- Structured logging with `structlog`
- Health check endpoints (`/health`, `/ready`)
- Scrape status dashboard in admin panel

### 12.3 Backup Strategy
- PostgreSQL daily backups (pg_dump)
- Raw document storage backup
- Configuration backup (YAML files)

### 12.4 Deliverables
- [ ] Production Docker Compose configuration
- [ ] Health check endpoints
- [ ] Structured logging setup
- [ ] Celery Flower integration
- [ ] Backup scripts
- [ ] Environment template (`.env.example`)
- [ ] Deployment documentation

---

## Phase 13: Initial Data Load & Validation

### 13.1 First-Time Scrape
- Run initial scrape for all 18 exchanges
- Manually verify AI extraction quality for each exchange
- Adjust parser hints and prompts based on results
- Create baseline snapshots (version 1 for each exchange)

### 13.2 Cross-Exchange Validation
- Compare extracted fees against manually verified values
- Verify that comparison logic produces sensible results
- Test change detection with known fee updates

### 13.3 Deliverables
- [ ] Initial scrape script
- [ ] Verification report for each exchange
- [ ] Baseline snapshot data
- [ ] Tuned prompts per exchange family
- [ ] Known-good test fixtures from real data

---

## Phase 14: Advanced Features & Iteration

### 14.1 Future Enhancements (Post-MVP)
- **SEC Filing Monitoring**: Watch EDGAR for SR (Self-Regulatory) fee change filings
- **Predictive Alerts**: Detect SEC filings before fee changes take effect
- **PDF Annotation**: Highlight changes directly on the original PDF
- **Export**: CSV/Excel export of comparison data
- **API Webhooks**: Push notifications to external systems
- **Multi-tenancy**: Support multiple organizations with isolated data
- **Fee Calculator**: Input trade parameters, calculate fees across exchanges
- **Historical Trends**: Charts showing fee evolution over time
- **Slack/Teams Integration**: Optional future notification channels

### 14.2 AI Model Improvements
- Fine-tune extraction prompts based on error patterns
- Build exchange-specific prompt templates
- Implement RAG (Retrieval-Augmented Generation) for fee schedule context
- Cache and reuse AI responses for unchanged document sections

---

## Implementation Order & Dependencies

```
Phase 1  ──► Phase 2  ──► Phase 3  ──► Phase 4  ──► Phase 5
(Setup)     (Models)     (Scrape)     (Parse)      (Normalize)
                                                       │
Phase 10 ◄────────────────────────────────────────────┘
(Workers)
    │
    ├──► Phase 6 (Change Detection)
    │       │
    │       ├──► Phase 7 (Notifications)
    │       │
    │       └──► Phase 8 (API) ──► Phase 9 (Dashboard)
    │
    └──► Phase 11 (Testing) ─── runs continuously

Phase 12 (Deployment) ── after Phase 8
Phase 13 (Data Load) ── after Phase 12
Phase 14 (Advanced) ── ongoing
```

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Exchange changes website structure | Scraper breaks | Multiple scraper strategies per exchange; alert on failures; YAML-driven config allows quick URL updates |
| AI hallucination in fee extraction | Incorrect data | Multi-stage validation; confidence scoring; human review for low-confidence extractions |
| Exchange blocks scraping | No data collection | Respect rate limits; identify as legitimate tool; fall back to cached data; consider RSS/email subscription as backup |
| High Claude API costs | Budget overrun | Hash-based change detection skips unchanged docs; cache AI responses; use smaller models for validation |
| Complex PDF table layouts | Poor extraction | Combine multiple PDF tools; exchange-specific parser hints; manual fallback |
| Fee schedule format changes | Parser breaks | AI-based parsing adapts to new formats; alert on parsing failures; agentic self-correction |

---

## Cost Estimates (Monthly)

| Item | Estimate |
|------|----------|
| Claude API (18 exchanges, ~2 parses/month avg) | ~$5-15/month |
| VPS/Cloud (Docker Compose host) | $20-40/month |
| Email sending (SendGrid free tier) | $0 |
| Domain + SSL | $1/month |
| **Total** | **~$25-55/month** |

---

## Success Metrics

1. **Coverage**: Successfully scraping and normalizing all 18 exchanges
2. **Accuracy**: >95% fee extraction accuracy (validated against manual checks)
3. **Timeliness**: Fee changes detected within 24 hours of publication
4. **Reliability**: <1% scrape failure rate
5. **API Performance**: <200ms response time for fee queries
