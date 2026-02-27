# Smart Extraction Pipeline — Design Document

## Goal

Replace the current AI-every-run extraction with a profile-based system where the first run uses AI to learn each exchange's table structure, and all subsequent runs extract fees via rules-based column mappings — zero AI cost for ~95% of weekly runs.

## Problem

The current pipeline sends the full document text + tables to Claude on every extraction. For large PDFs like BOX (22 pages, 52K chars), this means:
- 21K+ input tokens, 32K+ output tokens per run
- Response truncation losing entire sections (PIP, QCC, Complex)
- ~$0.50+ per exchange per run × 19 exchanges × 52 weeks = ~$500/year in AI costs
- 2-4 minute extraction time per exchange

Most weekly runs find zero fee changes — the document is identical or has only date/footnote updates.

## Architecture

### Core Concept: Table Fingerprint Profiles

Each exchange's fee schedule consists of structured tables. The first AI run extracts fees and simultaneously builds a **profile** — a JSON mapping of each table's column-to-schema-field assignments. Subsequent runs parse the document, compute table header fingerprints, and if they match the profile, extract fees via direct column mapping with no AI.

### Pipeline Modes

```
Document arrives
    │
    ├─ Hash unchanged → NO_CHANGE (done, ~1s)
    │
    ├─ Hash changed, profile ACTIVE, all fingerprints match
    │   → Rules-based extraction (no AI, ~3s)
    │   → Diff against previous → notify if material changes
    │
    ├─ Hash changed, profile ACTIVE, some fingerprints changed
    │   → Rules-based for matched tables
    │   → AI extraction for changed tables only
    │   → Update profile with new mappings
    │
    └─ No profile (LEARNING) or major table changes (>50% new)
        → Full AI extraction (current behavior + pre-filtering)
        → Profile Builder learns mappings from AI output
        → Store profile as ACTIVE
```

## Data Model

### `exchange_profiles` table

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| exchange_id | UUID FK | Links to exchanges table |
| profile_version | int | Increments when profile changes |
| table_mappings | JSONB | Per-table column→schema mappings |
| table_fingerprints | JSONB | Header hashes for change detection |
| section_metadata | JSONB | Which sections exist, which are fee-relevant |
| extraction_stats | JSONB | Expected fee count, participant types, etc. |
| status | Enum | LEARNING, ACTIVE, NEEDS_UPDATE |
| created_at | DateTime | |
| updated_at | DateTime | |

### Table Mapping Schema (JSONB)

```json
[{
  "table_index": 8,
  "fingerprint": "sha256_of_normalized_headers",
  "table_title": "Transaction Fees",
  "is_fee_table": true,
  "layout": "GRID",
  "row_axis_col": 0,
  "column_groups": [
    {
      "label": "Penny Interval Classes",
      "security_class": "PENNY",
      "columns": [
        {"header": "Maker", "fee_type": "MAKER", "col_index": 2},
        {"header": "Taker", "fee_type": "TAKER", "col_index": 3}
      ]
    }
  ],
  "row_mappings": {
    "Public Customer": {"participant_type": "CUSTOMER"},
    "Professional": {"participant_type": "PROFESSIONAL"},
    "Market Maker": {"participant_type": "MARKET_MAKER"}
  },
  "section_ref": "Section IV.A",
  "order_type": "SIMPLE",
  "has_contra_party_column": true,
  "contra_party_col_index": 1
}]
```

### Table Fingerprint Schema (JSONB)

```json
{
  "fingerprints": {
    "sha256_hash_1": {"table_index": 8, "title": "Transaction Fees", "is_fee_table": true},
    "sha256_hash_2": {"table_index": 9, "title": "MM Volume Rebate Tiers", "is_fee_table": true},
    "sha256_hash_3": {"table_index": 4, "title": "Connectivity Fees", "is_fee_table": false}
  },
  "fee_table_count": 12,
  "non_fee_table_count": 10
}
```

### Extraction Stats Schema (JSONB)

```json
{
  "expected_fee_count": 125,
  "participant_types": ["CUSTOMER", "PROFESSIONAL", "MARKET_MAKER", "FIRM", "BROKER_DEALER"],
  "order_types": ["SIMPLE", "PIM", "COMPLEX", "QCC"],
  "fee_types": ["MAKER", "TAKER", "PIM_FEE", "BREAK_UP_REBATE", "TRANSACTION", "ORF"],
  "has_tiers": true,
  "tier_count": 21,
  "last_ai_extraction_tokens": 54315,
  "last_rules_extraction_ms": 150
}
```

## Components

### 1. Table Classifier (`parser/table_classifier.py`)

Classifies tables as fee-relevant or not based on header heuristics:

**Fee indicators** (score +1 each): headers containing "$", "fee", "rebate", "per contract", "maker", "taker", "customer", "professional", "market maker"; cells matching dollar amount pattern `\$?\(?\d+\.\d{2}\)?`

**Non-fee indicators** (score -1 each): headers containing "port", "connection", "subscription", "monthly", "membership", "market data"

Tables scoring >= 2 are classified as fee-relevant.

### 2. Table Fingerprinter (`profiles/fingerprint.py`)

Computes a stable hash from a table's header structure:

```python
def fingerprint(table: ExtractedTable) -> str:
    # Normalize: lowercase, strip whitespace/footnote refs, sort
    normalized = [re.sub(r'\d+F\d+|\d+$', '', h).strip().lower() for h in table.headers]
    return hashlib.sha256("|".join(normalized).encode()).hexdigest()[:16]
```

Fingerprints are stable across runs when the table structure is unchanged, even if data values or footnote numbers change.

### 3. Profile Builder (`profiles/builder.py`)

After AI extraction, reverse-engineers table mappings:

1. For each AI-extracted fee, search fee tables for a cell matching the amount
2. Use row label + column header to confirm the match
3. Group confirmed matches by table to build column_groups and row_mappings
4. Detect tier tables by "Tier" column or sequential numbering
5. If >= 70% of fees matched to source cells, profile is ACTIVE; otherwise stays LEARNING

### 4. Profile Extractor (`profiles/extractor.py`)

Rules-based extraction using stored mappings:

1. For each fee table mapping, iterate rows
2. Map row labels to participant_type via row_mappings
3. Map columns to fee_type + security_class via column_groups
4. Parse dollar amounts from cells (handles `$0.15`, `($0.20)`, `$0.00`, `-$0.05`)
5. Resolve contra_party from dedicated column if present
6. Return list of fee dicts in the same format as AI extraction

### 5. AI Extractor Changes (`parser/ai_extractor.py`)

**Pre-filtering**: Skip non-fee tables in `_build_document_context()`. Use TableClassifier to include only fee-relevant tables. This alone cuts input tokens ~30-50%.

**Compact format**: Flatten multi-column tables into CSV-like rows before sending to AI. A 20-row × 8-column table becomes simple tuples instead of verbose cell text.

### 6. Pipeline Integration (`workers/pipelines.py`)

New routing logic after document parsing:

```python
profile = get_exchange_profile(exchange, session)

if profile and profile.status == ProfileStatus.ACTIVE:
    new_fingerprints = compute_fingerprints(document.tables)
    match_result = compare_fingerprints(profile, new_fingerprints)

    if match_result.all_match:
        # Rules-based extraction — zero AI
        raw_fees = extract_from_profile(document, profile)
    elif match_result.changed_ratio < 0.5:
        # Partial: rules for matched, AI for changed
        rules_fees = extract_matched_from_profile(document, profile, match_result)
        ai_fees = extract_changed_with_ai(document, match_result.changed_tables)
        raw_fees = rules_fees + ai_fees
        update_profile(profile, match_result.changed_tables, ai_fees)
    else:
        # Major change: full AI extraction + rebuild profile
        raw_fees = full_ai_extraction(document, exchange_code)
        rebuild_profile(profile, document, raw_fees)
else:
    # First run: full AI extraction + build profile
    raw_fees = full_ai_extraction(document, exchange_code)
    build_new_profile(exchange, document, raw_fees, session)
```

## Weekly Run Cost Model

| Scenario | AI Calls | Input Tokens | Output Tokens | Time | Cost |
|----------|----------|-------------|---------------|------|------|
| No change (hash match) | 0 | 0 | 0 | ~1s | $0 |
| Changed doc, profile match | 0 | 0 | 0 | ~3s | $0 |
| Changed doc, 1 table changed | 1 | ~2K | ~2K | ~15s | ~$0.02 |
| First run (no profile) | 1 | ~20K | ~30K | ~4min | ~$0.50 |

**Annual cost projection**: ~$20 (first run for 19 exchanges = ~$10, plus ~10 table-change events/year × $0.02 = ~$10 for incremental updates).

## File Changes Summary

**New files:**
- `src/exnot/profiles/__init__.py`
- `src/exnot/profiles/models.py` — ExchangeProfile SQLAlchemy model + ProfileStatus enum
- `src/exnot/profiles/builder.py` — ProfileBuilder: learns mappings from AI extraction
- `src/exnot/profiles/extractor.py` — ProfileExtractor: rules-based extraction
- `src/exnot/profiles/fingerprint.py` — Table fingerprinting + comparison
- `src/exnot/parser/table_classifier.py` — Fee table classifier
- Alembic migration for `exchange_profiles` table

**Modified files:**
- `src/exnot/parser/ai_extractor.py` — Pre-filter tables, compact format
- `src/exnot/workers/pipelines.py` — Profile-aware routing
- `src/exnot/db/models.py` — Add ExchangeProfile model
- `src/exnot/db/repositories.py` — Add ExchangeProfileRepository

## Verification Plan

1. Run full AI extraction for CBOE_BZX (already has profile-worthy data)
2. Verify ProfileBuilder creates correct table_mappings
3. Delete snapshot, re-run — verify ProfileExtractor produces identical fees with zero AI calls
4. Modify one amount in a test fixture — verify diff detects the change
5. Run for BOX_OPTIONS — verify PIP/QCC/Complex tables all get profiled
6. Simulate a table header change — verify partial AI re-extraction + profile update
