# Pipeline Deep Dive

[← Home](Home.md) | [Architecture Overview](Architecture-Overview.md)

## Pipeline Overview

The core pipeline transforms raw exchange documents into normalized, comparable fee data and detects changes between versions.

```mermaid
graph LR
    A[Scrape] --> B[Parse]
    B --> C[Extract]
    C --> D[Normalize]
    D --> E[Diff]
    E --> F[Notify]

    style A fill:#4CAF50,color:white
    style B fill:#2196F3,color:white
    style C fill:#9C27B0,color:white
    style D fill:#FF9800,color:white
    style E fill:#F44336,color:white
    style F fill:#607D8B,color:white
```

## Complete Pipeline Sequence

```mermaid
sequenceDiagram
    participant Celery as Celery Worker
    participant DB as PostgreSQL
    participant Redis
    participant Scraper as Document Collector
    participant Exchange as Exchange Website
    participant MinIO
    participant Parser as PDF/HTML Parser
    participant AI as AI Extractor
    participant LLM as LLM Provider
    participant Normalizer
    participant Differ as Change Detector
    participant SMTP as Email Server

    Celery->>Redis: Acquire lock (exchange_code)
    alt Lock acquired
        Celery->>DB: Load Exchange record

        Note over Celery,Exchange: Stage 1: Document Collection
        Celery->>Scraper: Collect documents
        Scraper->>Exchange: Fetch main page (HTTP/Playwright)
        Exchange-->>Scraper: HTML/PDF response
        Scraper->>Exchange: Fetch linked PDFs/CSVs
        Exchange-->>Scraper: Additional documents
        Scraper-->>Celery: DocumentCollection (primary + supplements)

        Note over Celery,DB: Stage 2: Change Detection (Hash)
        Celery->>DB: Get latest snapshot hash
        alt Hash unchanged
            Celery-->>Celery: Skip (no changes)
        else Hash changed or first run
            Celery->>DB: Create FeeScheduleSnapshot (version++)
            Celery->>MinIO: Store raw documents

            Note over Celery,LLM: Stage 3: Parsing + AI Extraction
            Celery->>Parser: Parse primary document
            Parser-->>Celery: ExtractedDocument (text + tables)

            alt Profile exists and matches
                Celery->>Celery: Profile-based extraction (zero AI cost)
            else No profile or structure changed
                Celery->>AI: AI extraction pipeline
                loop For each section group
                    AI->>LLM: Extract fees from section
                    LLM-->>AI: Structured fee data
                end
                AI->>LLM: Validate extraction
                LLM-->>AI: ValidationResult
                AI-->>Celery: ExtractionResult (fees + confidence)
                Celery->>Celery: Build/update extraction profile
            end

            Note over Celery,DB: Stage 4: Normalization
            Celery->>Normalizer: Normalize raw fees
            Normalizer-->>Celery: NormalizedFeeSchedule
            Celery->>DB: Save NormalizedFee + FeeTier records

            Note over Celery,SMTP: Stage 5: Diff + Notify
            Celery->>DB: Load previous snapshot fees
            Celery->>Differ: Detect changes
            Differ-->>Celery: ChangeReport (new/modified/removed)
            Celery->>DB: Save FeeChange records

            alt Changes detected
                Celery->>DB: Find IMMEDIATE subscribers
                Celery->>SMTP: Send change alerts
            end
        end
        Celery->>Redis: Release lock
    else Lock held by another worker
        Celery-->>Celery: Skip (already in progress)
    end
```

## Stage 1: Document Collection

**Entry point**: `scraper/document.py: DocumentCollector`

The collector gathers all fee-related documents from an exchange:

1. **Fetch main page** — HTTP (httpx) or Browser (Playwright) based on `scraper_type` in YAML
2. **Discover linked documents** — Scans HTML for PDF/CSV links via BeautifulSoup
3. **Fetch alternate URLs** — Additional URLs from exchange YAML definition, fetched in parallel
4. **Deduplicate** — By `content_hash` (SHA-256)
5. **Select primary** — By format priority

```mermaid
graph TD
    A[Exchange YAML] -->|fee_schedule_url| B[Fetch Main Page]
    A -->|alternate_urls| C[Fetch Alternates]
    B --> D{HTML Response?}
    D -->|Yes| E[Scan for PDF/CSV Links]
    D -->|No| F[Use as Primary]
    E --> G[Fetch Linked Documents]
    C --> H[Deduplicate by Hash]
    G --> H
    F --> H
    B --> H
    H --> I[Select Primary Document]
    I --> J[DocumentCollection]
```

**Format priority**: CSV > PDF > HTML (overridden by exchange's declared `fee_schedule_format`)

**Scraper types**:
- `HTTP` — Fast httpx-based fetching for static pages
- `BROWSER` — Playwright headless browser for JavaScript-rendered pages

## Stage 2: Hash-Based Change Detection

Before parsing, the pipeline compares the `content_hash` of the new primary document against the latest snapshot. If the hash matches, the entire pipeline is skipped — avoiding unnecessary AI costs.

```python
# Simplified logic in pipelines.py
if latest_snapshot and latest_snapshot.content_hash == new_hash:
    log.info("No changes detected, skipping")
    return None  # No pipeline run needed
```

## Stage 3: Parsing and AI Extraction

### Document Parsing

Three parser backends, selected by document format:

| Format | Parser | Method |
|--------|--------|--------|
| PDF | `parser/pdf_parser.py` | PyMuPDF for text, pdfplumber for tables |
| HTML | `parser/html_parser.py` | BeautifulSoup + optional Playwright rendering |
| CSV | `parser/csv_parser.py` | Python csv module with section marker detection |

All parsers return `ExtractedDocument`:
```
ExtractedDocument
├── full_text: str          # Complete document text
├── tables: list[ExtractedTable]  # Structured table data
├── page_count: int
└── metadata: dict
```

### AI Extraction Pipeline

**Entry point**: `parser/ai_extractor.py: AIExtractor`

The AI extraction pipeline processes the parsed document through multiple stages:

```mermaid
graph TD
    A[ExtractedDocument] --> B[Section Splitter]
    B --> C[Classify Sections<br/>context vs. fee]
    C --> D[Group Fee Sections<br/>≤15,000 chars each]
    D --> E{For Each Group}
    E --> F[Build Prompt<br/>section text + tables +<br/>exchange prompt]
    F --> G[Section Extractor Agent<br/>EXPENSIVE tier]
    G --> H[Append to extracted_fees]
    H --> E
    E -->|All groups done| I[Fee Validator Agent<br/>MEDIUM tier]
    I --> J{Confidence OK?<br/>Budget remaining?}
    J -->|Low confidence +<br/>budget available| K[Correction Agent<br/>EXPENSIVE tier]
    J -->|Good confidence<br/>or over budget| L[ExtractionResult]
    K --> L
```

**Key behaviors**:
- Documents are split into sections, classified (context vs. fee-bearing), then grouped into chunks of ≤15,000 characters
- Context sections (footnotes, tier definitions) are included as reference material but not extracted from
- Each group gets its own AI call with the exchange-specific prompt
- Budget is checked before each group — extraction stops early if over budget
- Cancellation checkpoints exist before each group (for admin cancel from dashboard)

See [AI Agent System](AI-Agent-System.md) for full agent details.

### Profile-Based Extraction (Zero-Cost Path)

Before calling AI, the pipeline checks if an extraction profile exists and matches the current document structure:

```mermaid
graph TD
    A[Parsed Document] --> B{Profile exists?}
    B -->|No| C[AI Extraction]
    B -->|Yes| D[Fingerprint Tables]
    D --> E{Fingerprints match?}
    E -->|Yes| F[Profile Extraction<br/>Zero AI cost]
    E -->|>50% changed| G[Mark NEEDS_UPDATE]
    G --> C
    F --> H[ExtractionResult]
    C --> I[Build/Update Profile]
    I --> H
```

See [Extraction Profiles](Extraction-Profiles.md) for details.

## Stage 4: Normalization

**Entry point**: `normalizer/engine.py: NormalizationEngine`

Maps raw extracted fee dicts to the canonical schema:

```mermaid
graph LR
    A[Raw Fee Dict] --> B{V3 fields present?<br/>origin_code exists}
    B -->|Yes| C[V3 Mapping]
    B -->|No| D[V2 Mapping]
    C --> E[NormalizedFeeEntry]
    D --> E
    E --> F[NormalizedFeeSchedule]
```

**V3 field mappings**:
| Source Field | Target |
|-------------|--------|
| `origin_code` | `ParticipantType` |
| `listing_type` + `penny_class` | `SecurityClass` |
| `auction_type` + `exec_venue` + `product_type` | `OrderType` |
| `liquidity_role` / `exec_venue` | `FeeType` |
| `fee_value` | `amount` (Decimal) |

**Amount storage**: All amounts are stored as `amount_cents` — an integer representing hundredths of a cent (1/10,000th of a dollar). A fee of $0.45/contract is stored as `4500`.

See [Normalization Engine](Normalization-Engine.md) for the full taxonomy.

## Stage 5: Change Detection and Notification

### Change Detection

**Entry point**: `differ/detector.py: ChangeDetector`

Fees are compared using a composite key:

```
fee_key = (participant_type, security_class, order_type, fee_type,
           fee_code, contra_party_type, symbol, tier_number)
```

```mermaid
graph TD
    A[Previous Snapshot Fees] --> C[Build Key Sets]
    B[Current Snapshot Fees] --> C
    C --> D{Set Operations}
    D -->|In new only| E[NEW fees]
    D -->|In old only| F[REMOVED fees]
    D -->|In both,<br/>different amount| G[MODIFIED fees]
    E --> H[ChangeReport]
    F --> H
    G --> H
```

For the first snapshot of an exchange, all fees are marked as NEW.

### Notification

Three notification frequencies:

| Frequency | Trigger | Template |
|-----------|---------|----------|
| `IMMEDIATE` | After each pipeline run with changes | `fee_change.html` |
| `DAILY_DIGEST` | Celery Beat at 7:00 AM ET | `daily_digest.html` |
| `WEEKLY` | Celery Beat, Monday 8:00 AM ET | `daily_digest.html` |

Email delivery via `aiosmtplib`. Subscribers can filter by specific exchange codes.

## Error Handling and Resilience

- **Redis lock**: Prevents duplicate runs per exchange (30-min TTL)
- **Budget guardrails**: Per-exchange ($2.00) and daily ($15.00) caps prevent runaway AI costs
- **Retry with backoff**: Celery tasks retry on transient failures
- **Graceful degradation**: If AI extraction fails, the pipeline records the failure in `ScrapeLog` but doesn't crash other exchanges
- **Cancellation**: Admin can cancel in-flight runs via dashboard; checked at group boundaries

## Related Pages

- [AI Agent System](AI-Agent-System.md) — agent details, model routing
- [Extraction Profiles](Extraction-Profiles.md) — zero-cost path details
- [Normalization Engine](Normalization-Engine.md) — V2/V3 mapping rules
- [Worker Architecture](Worker-Architecture.md) — task definitions, scheduling
