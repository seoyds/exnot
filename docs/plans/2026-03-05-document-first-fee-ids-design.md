# Document-First Architecture + Canonical Fee IDs + Billing Codes

**Date:** 2026-03-05
**Status:** Approved
**Approach:** B — Document-First Architecture

## Problem Statement

ExNot currently treats fee schedule URLs as simple configuration — one primary URL per exchange, discovered once and used forever. This creates several gaps:

1. **No document classification** — discovered URLs are assumed to be fee schedules without verification
2. **No admin review** — AI picks the URL with no human oversight
3. **No billing code capture** — FIX/binary protocol specs contain billing codes that aren't collected
4. **Fee identity is implicit** — fees lack unique identifiers across exchanges, making cross-exchange comparison imprecise
5. **No document lifecycle** — documents can't be pinned, rejected, or tracked over time

## Design

### 1. ExchangeDocument Model & Lifecycle

New `ExchangeDocument` model replaces the current `ScrapedDocument` as the primary document tracking entity.

**Table: `exchange_documents`**

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | |
| exchange_id | FK → Exchange | |
| source_url | String(500) | Document URL |
| url_pattern | String(500), nullable | Derived regex/glob for pattern matching |
| title | String(200), nullable | From page title or filename |
| content_type | Enum(ContentType) | PDF/HTML/CSV/EXCEL |
| doc_category | Enum(DocumentCategory) | See below |
| status | Enum(DocumentStatus) | DISCOVERED → CLASSIFIED → APPROVED → REJECTED → STALE |
| is_pinned | Boolean, default false | Admin-pinned for future runs |
| is_primary | Boolean, default false | Primary fee schedule doc |
| classification_confidence | Float, nullable | AI classification confidence |
| classification_reasoning | Text, nullable | AI reasoning |
| admin_notes | Text, nullable | Admin notes |
| last_seen_at | DateTime | Updated each run |
| last_fetched_hash | String(64) | SHA-256 of last fetch |
| discovered_at | DateTime | |
| approved_at | DateTime, nullable | |
| approved_by | FK → User, nullable | |
| created_at / updated_at | DateTime | |

**DocumentCategory enum:**
- `FEE_SCHEDULE` — Primary fee schedule document
- `PROTOCOL_SPEC` — FIX/binary protocol specifications
- `REGULATORY_FILING` — SEC filings, rule changes
- `MEMBERSHIP_AGREEMENT` — Membership/connectivity agreements
- `CIRCULAR_NOTICE` — Exchange circulars, fee change notices
- `OTHER` — Unclassified/irrelevant

**DocumentStatus enum:**
- `DISCOVERED` — URL found, not yet classified
- `CLASSIFIED` — AI has categorized it
- `APPROVED` — Admin confirmed, enters processing pipeline
- `REJECTED` — Admin rejected, skipped in future runs
- `STALE` — Previously approved but URL now returns 404/error

**Lifecycle:**
```
Discovery → DISCOVERED → Classification Agent → CLASSIFIED → Admin Review → APPROVED/REJECTED
                                                                              ↓
                                                              APPROVED → enters extraction pipeline
                                                                              ↓
                                                              If URL fails → STALE (admin alerted)
```

Auto-approve: Documents classified as `FEE_SCHEDULE` with confidence ≥ 0.9 automatically advance to `APPROVED`. Configurable via `DOC_AUTO_APPROVE_THRESHOLD` setting.

**Relationship to existing ScrapedDocument:** `ScrapedDocument` continues to track per-snapshot document artifacts (stored in MinIO). `ExchangeDocument` is the long-lived record. A new FK `exchange_document_id` on `ScrapedDocument` links them.

### 2. Canonical Fee IDs

**Table: `canonical_fees`**

| Column | Type | Description |
|--------|------|-------------|
| id | Integer PK | |
| canonical_code | String(50), unique | e.g., "MAKER_REBATE", "TAKER_FEE" |
| display_name | String(100) | e.g., "Maker Rebate" |
| fee_type | Enum(FeeType) | Links to existing taxonomy |
| description | Text | |
| category | String(50) | Grouping: "transaction", "connectivity", etc. |

~30-50 curated entries. Seeded from a YAML file. AI suggests canonical codes during extraction; new codes proposed by AI are flagged for admin confirmation.

**NormalizedFee extensions:**

| New Column | Type | Description |
|------------|------|-------------|
| canonical_fee_id | FK → CanonicalFee, nullable | Maps to universal fee concept |
| exchange_fee_code | String(50), nullable | Exchange's own code (e.g., "OB") |
| exchange_fee_name | String(200), nullable | Exchange's own name for this fee |

Existing `fee_code` and `fee_name` columns are migrated to `exchange_fee_code` / `exchange_fee_name`, then deprecated and removed.

### 3. Billing Codes

**Table: `billing_codes`**

| Column | Type | Description |
|--------|------|-------------|
| id | Integer PK | |
| exchange_id | FK → Exchange | |
| code | String(50) | The billing/FIX code |
| protocol | Enum(BillingProtocol) | FIX, BINARY, SRO, OTHER |
| description | Text | |
| canonical_fee_id | FK → CanonicalFee, nullable | Maps to canonical fee |
| source_document_id | FK → ExchangeDocument, nullable | Where this was found |
| effective_date | Date, nullable | |
| tag_number | Integer, nullable | FIX tag number if applicable |

**BillingProtocol enum:** FIX, BINARY, SRO, OTHER

**Extraction sources:**
1. Fee schedule documents — inline billing code references extracted during normal AI pipeline
2. Protocol spec documents — dedicated lightweight agent extracts codes from approved PROTOCOL_SPEC documents

### 4. Documents Dashboard Page

**Route:** `GET /dashboard/exchanges/{code}/documents`

Grouped by status (Approved/Pinned → Pending Review → Rejected → Stale), showing:
- Document title/filename, content type, file size
- Source URL
- Category + classification confidence + AI reasoning
- Last seen date, content hash
- Action buttons: Approve, Approve & Pin, Reject, Recategorize, View/Download

**HTMX interactions:**
- Approve → POST, sets status=APPROVED, triggers processing if fee schedule or protocol spec
- Approve & Pin → same + sets is_pinned=true, derives url_pattern
- Reject → POST, sets status=REJECTED
- Recategorize → dropdown POST to change doc_category
- View → opens/downloads from MinIO

**Main dashboard integration:** Summary column on exchange table showing document counts (e.g., "3 docs, 1 pending").

### 5. Enhanced Discovery Pipeline

**Expanded search queries:**
- Existing fee schedule queries (unchanged)
- New: `"{exchange} FIX protocol specification"`, `"{exchange} binary order entry specification"`

**New classification phase:**
- After probing candidates, a document classification agent (CHEAP tier) categorizes each into DocumentCategory
- All candidates stored as ExchangeDocument records with status CLASSIFIED
- Auto-approve logic applied for high-confidence fee schedule matches

**New classification agent** (`ai/agents/doc_classifier.py`):
- Model: CHEAP tier (same as table classifier)
- Input: URL, title, content preview (2KB), content type
- Output: DocumentCategory, confidence, reasoning
- Config: `AI_MODEL_DOC_CLASSIFICATION` env var

### 6. Subsequent Run Logic (Pinned URL Priority)

```
For each exchange:
  1. Fetch pinned documents → verify hash
     - OK → proceed to extraction
     - 404/error → mark STALE, alert admin
  2. No valid pinned docs → pattern match
     - Scrape exchange site, find URLs matching stored url_pattern
     - If found → proceed, flag for admin review
  3. No pattern match → full rediscovery
     - Run complete discovery pipeline
     - All new docs need admin review before processing
```

### 7. Pipeline Integration

Changes to `run_scrape_pipeline`:
- Query `ExchangeDocument` for APPROVED docs instead of `Exchange.fee_schedule_url`
- `DocumentCollector` fetches all approved docs for the exchange
- Protocol spec documents processed by separate billing code extraction agent
- `Exchange.fee_schedule_url` becomes denormalized cache of pinned/primary document URL (backward compatible)

### 8. New Config Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `DOC_AUTO_APPROVE_THRESHOLD` | 0.9 | Auto-approve fee schedule docs above this confidence |
| `AI_MODEL_DOC_CLASSIFICATION` | (same as table classifier) | Model for document classification |
| `AI_MODEL_PROTOCOL_EXTRACTION` | (same as CHEAP tier) | Model for billing code extraction from protocol specs |
| `DISCOVERY_INCLUDE_PROTOCOL_SPECS` | true | Whether to search for protocol spec documents |

## Migration Strategy

1. Create new tables (`exchange_documents`, `canonical_fees`, `billing_codes`)
2. Migrate existing `ScrapedDocument` data → create corresponding `ExchangeDocument` records
3. Migrate `NormalizedFee.fee_code` → `exchange_fee_code`, `fee_name` → `exchange_fee_name`
4. Seed canonical fees from YAML
5. Existing `Exchange.fee_schedule_url` continues working — pipeline falls back to it if no approved ExchangeDocuments exist

## Testing Strategy

- Unit tests for document lifecycle state machine
- Unit tests for URL pattern derivation
- Unit tests for canonical fee mapping
- Integration tests for classification agent
- Integration tests for pinned URL → pattern match → rediscovery fallback chain
- Dashboard E2E tests for approve/reject/pin workflows
