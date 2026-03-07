# Claude Agent SDK Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace PydanticAI + LiteLLM/OpenRouter with Claude Agent SDK for agentic pipeline orchestration.

**Architecture:** Tool-heavy orchestrator (Haiku) with 3 specialized subagents (extractor=Sonnet, validator=Haiku, discovery=Haiku). Deterministic pipeline steps as custom MCP tools. SSE streaming for dashboard. Auth via ~/.claude/ subscription.

**Tech Stack:** claude-agent-sdk, sse-starlette, FastAPI, SQLAlchemy, Celery, Redis

**Design doc:** `docs/plans/2026-03-07-claude-agent-sdk-migration-design.md`

---

## Phase 1: Foundation — Dependencies & Config

### Task 1: Update dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Update pyproject.toml**

Remove `pydantic-ai` and `litellm` from dependencies. Add `claude-agent-sdk` and `sse-starlette`.

```toml
# REMOVE these lines:
# "pydantic-ai>=1.0.0",
# "litellm>=1.80.0",

# ADD these lines:
"claude-agent-sdk",
"sse-starlette>=2.0.0",
```

**Step 2: Install new dependencies**

Run: `pip install -e ".[dev]"` or `uv sync`

**Step 3: Verify installation**

Run: `python -c "from claude_agent_sdk import query, ClaudeAgentOptions; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: replace pydantic-ai/litellm with claude-agent-sdk"
```

---

### Task 2: Simplify config.py

**Files:**
- Modify: `src/exnot/config.py` (lines 17-79)

**Step 1: Read current config**

Read `src/exnot/config.py` to see the full Settings class.

**Step 2: Remove old AI settings, add new Claude model settings**

Remove these fields (lines 17-19, 22, 58-79):
- `openrouter_api_key`, `openrouter_base_url`
- `dashscope_api_key`
- `ai_model`, `ai_max_tokens`, `ai_confidence_threshold`, `ai_max_retries`, `ai_section_char_budget`
- All `ai_model_*` fields (table_classification, orchestrator, fee_extraction, etc.)
- `ai_budget_per_exchange_usd`, `ai_budget_daily_usd`

Add new fields:
```python
# Claude Agent SDK model settings
claude_orchestrator_model: str = "haiku"
claude_extractor_model: str = "sonnet"
claude_validator_model: str = "haiku"
claude_discovery_model: str = "haiku"
```

Keep: `serpapi_api_key`, `discovery_max_candidates`, `discovery_fetch_timeout`, `discovery_include_protocol_specs`, `doc_auto_approve_threshold`.

**Step 3: Run linter**

Run: `ruff check src/exnot/config.py --fix`

**Step 4: Commit**

```bash
git add src/exnot/config.py
git commit -m "config: replace AI model/budget settings with Claude SDK models"
```

---

## Phase 2: Custom Tools (MCP Server)

### Task 3: Create tools directory structure and server setup

**Files:**
- Create: `src/exnot/agents/__init__.py`
- Create: `src/exnot/agents/tools/__init__.py`
- Create: `src/exnot/agents/tools/server.py`

**Step 1: Create directory structure**

Run: `mkdir -p src/exnot/agents/tools src/exnot/agents/subagents`

**Step 2: Create `src/exnot/agents/__init__.py`**

```python
```

**Step 3: Create `src/exnot/agents/tools/__init__.py`**

```python
from exnot.agents.tools.server import create_tools_server

__all__ = ["create_tools_server"]
```

**Step 4: Create `src/exnot/agents/tools/server.py`**

This is the central MCP server that bundles all tools.

```python
from claude_agent_sdk import create_sdk_mcp_server

from exnot.agents.tools.diffing import detect_changes
from exnot.agents.tools.discovery import search_fee_urls
from exnot.agents.tools.exchange import load_exchange, load_exchange_prompt
from exnot.agents.tools.normalization import normalize_fees
from exnot.agents.tools.notifications import send_notifications
from exnot.agents.tools.parsing import parse_document
from exnot.agents.tools.persistence import save_scraped_document, save_snapshot
from exnot.agents.tools.profiles import save_profile, try_profile_extract
from exnot.agents.tools.scraping import check_document_changed, scrape_document


def create_tools_server():
    return create_sdk_mcp_server(
        name="exnot",
        tools=[
            load_exchange,
            load_exchange_prompt,
            search_fee_urls,
            scrape_document,
            check_document_changed,
            parse_document,
            try_profile_extract,
            save_profile,
            normalize_fees,
            detect_changes,
            save_snapshot,
            save_scraped_document,
            send_notifications,
        ],
    )
```

**Step 5: Commit**

```bash
git add src/exnot/agents/
git commit -m "feat: scaffold agents directory with tools server"
```

---

### Task 4: Exchange loading tools

**Files:**
- Create: `src/exnot/agents/tools/exchange.py`

**Step 1: Create exchange tools**

These tools wrap existing exchange registry and prompt lookup. Read `src/exnot/exchanges/registry.py` and `src/exnot/ai/prompts/registry.py` first to understand the interfaces.

```python
import json

from claude_agent_sdk import tool

from exnot.exchanges.registry import load_exchange_definitions


@tool(
    "load_exchange",
    "Load exchange configuration by code. Returns name, URLs, operator, and YAML definition.",
    {"exchange_code": str},
)
async def load_exchange(args):
    exchange_code = args["exchange_code"]
    definitions = load_exchange_definitions()
    defn = definitions.get(exchange_code)
    if not defn:
        return {"content": [{"type": "text", "text": f"Exchange '{exchange_code}' not found"}]}
    return {"content": [{"type": "text", "text": json.dumps(defn, default=str)}]}


@tool(
    "load_exchange_prompt",
    "Load exchange-specific extraction prompt for guiding fee extraction.",
    {"exchange_code": str},
)
async def load_exchange_prompt(args):
    from exnot.ai.prompts.registry import get_extraction_prompt

    exchange_code = args["exchange_code"]
    prompt = get_extraction_prompt(exchange_code)
    return {"content": [{"type": "text", "text": prompt}]}
```

Note: `load_exchange_prompt` still imports from `ai/prompts/` — we'll move prompts in Task 12.

**Step 2: Commit**

```bash
git add src/exnot/agents/tools/exchange.py
git commit -m "feat: add exchange loading tools"
```

---

### Task 5: Discovery tool

**Files:**
- Create: `src/exnot/agents/tools/discovery.py`

**Step 1: Read `src/exnot/discovery/search.py`** to understand SerpAPI interface.

**Step 2: Create discovery tool**

```python
import json

from claude_agent_sdk import tool

from exnot.config import get_settings


@tool(
    "search_fee_urls",
    "Search for fee schedule URLs for an exchange using SerpAPI. Returns raw search results for evaluation.",
    {"exchange_name": str, "operator": str},
)
async def search_fee_urls(args):
    from exnot.discovery.search import search_fee_schedule_urls

    settings = get_settings()
    results = await search_fee_schedule_urls(
        exchange_name=args["exchange_name"],
        operator=args.get("operator", ""),
        api_key=settings.serpapi_api_key,
        max_results=settings.discovery_max_candidates,
    )
    return {"content": [{"type": "text", "text": json.dumps(results, default=str)}]}
```

**Step 3: Commit**

```bash
git add src/exnot/agents/tools/discovery.py
git commit -m "feat: add fee URL search tool"
```

---

### Task 6: Scraping tools

**Files:**
- Create: `src/exnot/agents/tools/scraping.py`

**Step 1: Read `src/exnot/scraper/http_scraper.py` and `src/exnot/scraper/browser_scraper.py`** for scraping interfaces.

**Step 2: Create scraping tools**

```python
import base64
import json

from claude_agent_sdk import tool


@tool(
    "scrape_document",
    "Download a document from a URL. Returns content hash, base64-encoded bytes, and detected format (pdf/html/csv).",
    {"url": str, "method": str},
)
async def scrape_document(args):
    from exnot.scraper.http_scraper import HttpScraper
    from exnot.scraper.browser_scraper import BrowserScraper

    url = args["url"]
    method = args.get("method", "http")

    if method == "browser":
        scraper = BrowserScraper()
    else:
        scraper = HttpScraper()

    doc = await scraper.scrape(url)
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "content_hash": doc.content_hash,
                    "format": doc.format,
                    "size_bytes": len(doc.content),
                    "url": url,
                }),
            }
        ]
    }


@tool(
    "check_document_changed",
    "Check if a document has changed by comparing content hash against the latest snapshot.",
    {"exchange_code": str, "content_hash": str},
)
async def check_document_changed(args):
    from exnot.db.engine import async_session_factory
    from exnot.db.repositories import FeeScheduleSnapshotRepository

    async with async_session_factory() as session:
        repo = FeeScheduleSnapshotRepository(session)
        latest = await repo.get_latest_by_exchange_code(args["exchange_code"])
        changed = latest is None or latest.document_hash != args["content_hash"]
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "changed": changed,
                        "previous_snapshot_id": str(latest.id) if latest else None,
                    }),
                }
            ]
        }
```

Note: The actual implementation will need to adapt to the exact scraper interfaces — read those files during implementation.

**Step 3: Commit**

```bash
git add src/exnot/agents/tools/scraping.py
git commit -m "feat: add scraping tools"
```

---

### Task 7: Parsing tool

**Files:**
- Create: `src/exnot/agents/tools/parsing.py`

**Step 1: Read `src/exnot/parser/pdf_parser.py`, `src/exnot/parser/html_parser.py`, `src/exnot/parser/section_splitter.py`, and `src/exnot/parser/table_classifier.py`** for interfaces.

**Step 2: Create parsing tool**

This tool bundles: parser selection + parsing + section splitting + rule-based table classification.

```python
import json

from claude_agent_sdk import tool


@tool(
    "parse_document",
    "Parse a scraped document into text, tables, sections, and section groups. "
    "Handles PDF, HTML, and CSV formats. Includes rule-based table classification.",
    {"exchange_code": str, "format": str},
)
async def parse_document(args):
    from exnot.parser.factory import get_parser
    from exnot.parser.section_splitter import classify_context_sections, group_sections, split_document
    from exnot.parser.table_classifier import classify_table

    exchange_code = args["exchange_code"]
    fmt = args["format"]

    # Get the scraped document from the pipeline context
    # Implementation: retrieve from MinIO or in-memory cache
    parser = get_parser(fmt)
    document = await parser.parse(exchange_code)

    # Split into sections
    sections = split_document(document, format_hint=fmt)
    classify_context_sections(sections)

    # Group fee-bearing sections
    fee_sections = [s for s in sections if not s.is_context]
    section_groups = group_sections(fee_sections, char_budget=15000)

    # Classify tables (rules-based only)
    table_classifications = []
    for i, table in enumerate(document.tables):
        tc = classify_table(table, table_index=i)
        table_classifications.append({"index": i, "is_fee_table": tc.score > 0, "reason": tc.reason})

    result = {
        "full_text_chars": len(document.text),
        "table_count": len(document.tables),
        "section_count": len(sections),
        "fee_section_count": len(fee_sections),
        "group_count": len(section_groups),
        "table_classifications": table_classifications,
        "sections": [
            {
                "heading": s.heading,
                "char_count": len(s.text),
                "is_context": s.is_context,
                "table_count": len(s.tables),
            }
            for s in sections
        ],
        "section_groups": [
            {
                "index": i,
                "section_indices": [sections.index(s) for s in sg.sections],
                "total_chars": sum(len(s.text) for s in sg.sections),
            }
            for i, sg in enumerate(section_groups)
        ],
    }
    return {"content": [{"type": "text", "text": json.dumps(result)}]}
```

Note: The actual document retrieval mechanism needs to be wired during implementation — the scraped bytes need to flow from `scrape_document` tool to `parse_document`. This may require a shared in-memory store keyed by exchange_code, or passing the data through the orchestrator prompt.

**Step 3: Commit**

```bash
git add src/exnot/agents/tools/parsing.py
git commit -m "feat: add document parsing tool"
```

---

### Task 8: Profile tools

**Files:**
- Create: `src/exnot/agents/tools/profiles.py`

**Step 1: Read `src/exnot/profiles/extractor.py` and `src/exnot/profiles/fingerprint.py`** for interfaces.

**Step 2: Create profile tools**

```python
import json

from claude_agent_sdk import tool


@tool(
    "try_profile_extract",
    "Attempt rules-based fee extraction using a saved profile. Returns matched=true with fees if profile matches, "
    "or matched=false if document structure has changed.",
    {"exchange_code": str},
)
async def try_profile_extract(args):
    from exnot.profiles.extractor import extract_all_from_profile
    from exnot.profiles.fingerprint import load_profile, match_fingerprints

    exchange_code = args["exchange_code"]
    profile = load_profile(exchange_code)
    if not profile:
        return {"content": [{"type": "text", "text": json.dumps({"matched": False, "reason": "no profile exists"})}]}

    # Match fingerprints against current document tables
    match = match_fingerprints(profile, exchange_code)
    if not match.matched:
        return {
            "content": [
                {"type": "text", "text": json.dumps({"matched": False, "reason": match.reason})}
            ]
        }

    fees = extract_all_from_profile(profile, exchange_code)
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"matched": True, "fee_count": len(fees), "fees": fees}, default=str),
            }
        ]
    }


@tool(
    "save_profile",
    "Save an extraction profile for an exchange based on AI extraction results and document tables.",
    {"exchange_code": str, "fees_json": str},
)
async def save_profile(args):
    from exnot.profiles.builder import ProfileBuilder

    exchange_code = args["exchange_code"]
    fees = json.loads(args["fees_json"])

    builder = ProfileBuilder()
    result = builder.build(exchange_code, fees)
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "profile_saved": True,
                    "match_ratio": result.match_ratio,
                    "matched_fees": result.matched_fees,
                }),
            }
        ]
    }
```

**Step 3: Commit**

```bash
git add src/exnot/agents/tools/profiles.py
git commit -m "feat: add profile extraction tools"
```

---

### Task 9: Normalization, diffing, persistence, and notification tools

**Files:**
- Create: `src/exnot/agents/tools/normalization.py`
- Create: `src/exnot/agents/tools/diffing.py`
- Create: `src/exnot/agents/tools/persistence.py`
- Create: `src/exnot/agents/tools/notifications.py`

**Step 1: Read existing interfaces**

Read these files to understand the APIs being wrapped:
- `src/exnot/normalizer/engine.py`
- `src/exnot/differ/detector.py`
- `src/exnot/db/repositories.py`
- `src/exnot/notifications/email_sender.py`

**Step 2: Create all four tool files**

Each follows the same pattern: wrap existing logic in a `@tool` decorated async function that returns `{"content": [{"type": "text", "text": json.dumps(result)}]}`.

`normalization.py`:
```python
import json
from claude_agent_sdk import tool


@tool(
    "normalize_fees",
    "Normalize raw extracted fees to the canonical schema. Maps participant types, security classes, "
    "order types, and fee types. Returns normalized fees and any warnings.",
    {"exchange_code": str, "raw_fees_json": str},
)
async def normalize_fees(args):
    from exnot.normalizer.engine import NormalizationEngine

    exchange_code = args["exchange_code"]
    raw_fees = json.loads(args["raw_fees_json"])
    engine = NormalizationEngine()
    result = engine.normalize(raw_fees, exchange_code)
    return {
        "content": [
            {"type": "text", "text": json.dumps({"fee_count": len(result.fees), "warnings": result.warnings, "fees": [f.model_dump() for f in result.fees]}, default=str)}
        ]
    }
```

`diffing.py`:
```python
import json
from claude_agent_sdk import tool


@tool(
    "detect_changes",
    "Compare normalized fees against the previous snapshot for an exchange. Returns list of changes.",
    {"exchange_code": str, "normalized_fees_json": str},
)
async def detect_changes(args):
    from exnot.db.engine import async_session_factory
    from exnot.differ.detector import ChangeDetector

    exchange_code = args["exchange_code"]
    fees = json.loads(args["normalized_fees_json"])

    async with async_session_factory() as session:
        detector = ChangeDetector(session)
        changes = await detector.detect(exchange_code, fees)
        return {
            "content": [
                {"type": "text", "text": json.dumps({"change_count": len(changes), "changes": changes}, default=str)}
            ]
        }
```

`persistence.py`:
```python
import json
from claude_agent_sdk import tool


@tool(
    "save_snapshot",
    "Save a fee schedule snapshot with normalized fees and detected changes to the database.",
    {"exchange_code": str, "normalized_fees_json": str, "changes_json": str, "document_hash": str},
)
async def save_snapshot(args):
    from exnot.db.engine import async_session_factory
    from exnot.db.repositories import FeeScheduleSnapshotRepository

    async with async_session_factory() as session:
        repo = FeeScheduleSnapshotRepository(session)
        snapshot = await repo.create_with_fees(
            exchange_code=args["exchange_code"],
            fees=json.loads(args["normalized_fees_json"]),
            changes=json.loads(args["changes_json"]),
            document_hash=args["document_hash"],
        )
        await session.commit()
        return {
            "content": [
                {"type": "text", "text": json.dumps({"snapshot_id": str(snapshot.id)})}
            ]
        }


@tool(
    "save_scraped_document",
    "Store a scraped document in MinIO object storage.",
    {"exchange_code": str, "format": str, "snapshot_id": str},
)
async def save_scraped_document(args):
    from exnot.storage.minio_client import store_document

    doc_id = await store_document(
        exchange_code=args["exchange_code"],
        fmt=args["format"],
        snapshot_id=args["snapshot_id"],
    )
    return {"content": [{"type": "text", "text": json.dumps({"doc_id": str(doc_id)})}]}
```

`notifications.py`:
```python
import json
from claude_agent_sdk import tool


@tool(
    "send_notifications",
    "Send email notifications to subscribers about fee schedule changes.",
    {"exchange_code": str, "changes_json": str, "summary": str},
)
async def send_notifications(args):
    from exnot.db.engine import async_session_factory
    from exnot.db.repositories import SubscriberRepository
    from exnot.notifications.email_sender import send_change_notification

    exchange_code = args["exchange_code"]
    changes = json.loads(args["changes_json"])
    summary = args["summary"]

    if not changes:
        return {"content": [{"type": "text", "text": json.dumps({"sent_count": 0, "reason": "no changes"})}]}

    async with async_session_factory() as session:
        sub_repo = SubscriberRepository(session)
        subscribers = await sub_repo.get_for_exchange(exchange_code)
        sent = 0
        for sub in subscribers:
            await send_change_notification(sub.email, exchange_code, changes, summary)
            sent += 1
        return {"content": [{"type": "text", "text": json.dumps({"sent_count": sent})}]}
```

Note: All tool implementations are approximations. During implementation, read the actual interfaces in the wrapped modules and adapt the tool to match their exact signatures.

**Step 3: Commit**

```bash
git add src/exnot/agents/tools/normalization.py src/exnot/agents/tools/diffing.py src/exnot/agents/tools/persistence.py src/exnot/agents/tools/notifications.py
git commit -m "feat: add normalization, diffing, persistence, and notification tools"
```

---

## Phase 3: Subagents

### Task 10: Extractor subagent

**Files:**
- Create: `src/exnot/agents/subagents/__init__.py`
- Create: `src/exnot/agents/subagents/extractor.py`

**Step 1: Read `src/exnot/ai/prompts/registry.py` and `src/exnot/ai/prompts/base.py`** to understand prompt structure.

**Step 2: Create extractor subagent factory**

```python
from claude_agent_sdk import AgentDefinition

from exnot.config import get_settings

EXTRACTOR_BASE_PROMPT = """You are a specialist in US options exchange fee schedules.

Given document sections with text and tables, extract EVERY fee entry into this structured JSON format:

```json
[
  {
    "participant_type": "CUSTOMER|PROFESSIONAL|MARKET_MAKER|FIRM|BROKER_DEALER",
    "security_class": "PENNY|NON_PENNY|INDEX|ETF|EQUITY|MINI",
    "order_type": "SIMPLE|COMPLEX|AUCTION|DIRECTED|QCC",
    "fee_type": "MAKER|TAKER|ROUTING|ORF|TRANSACTION|COMPARISON|CONNECTIVITY|MARKET_DATA|MEMBERSHIP",
    "amount_cents": 2500,
    "is_rebate": false,
    "origin_code": "...",
    "product_type": "...",
    "liquidity_role": "...",
    "tier_level": null,
    "tier_threshold": null,
    "tier_unit": null,
    "confidence": 0.95,
    "source_context": "brief quote from source"
  }
]
```

Rules:
- Extract ALL fees, not just examples or a sample
- amount_cents is in hundredths of a cent (e.g., $0.25 per contract = 2500)
- Rebates have negative amount_cents and is_rebate=true
- Include tier info when fees are volume-tiered
- When uncertain, include the fee with lower confidence
- Return ONLY the JSON array, no other text
"""


def create_extractor_agent(exchange_code: str) -> AgentDefinition:
    """Factory that creates an extractor subagent with exchange-specific prompt."""
    from exnot.ai.prompts.registry import get_extraction_prompt

    exchange_prompt = get_extraction_prompt(exchange_code)
    settings = get_settings()

    return AgentDefinition(
        description=(
            "Extract structured fee data from exchange fee schedule text. "
            "Use when profile-based extraction fails or isn't available."
        ),
        prompt=f"{EXTRACTOR_BASE_PROMPT}\n\n## Exchange-Specific Instructions\n\n{exchange_prompt}",
        tools=["Read"],
        model=settings.claude_extractor_model,
    )
```

**Step 3: Create `__init__.py`**

```python
from exnot.agents.subagents.extractor import create_extractor_agent

__all__ = ["create_extractor_agent"]
```

**Step 4: Commit**

```bash
git add src/exnot/agents/subagents/
git commit -m "feat: add extractor subagent with exchange-specific prompts"
```

---

### Task 11: Validator and discovery subagents

**Files:**
- Create: `src/exnot/agents/subagents/validator.py`
- Create: `src/exnot/agents/subagents/discovery.py`

**Step 1: Create validator subagent**

```python
from claude_agent_sdk import AgentDefinition

from exnot.config import get_settings


def create_validator_agent() -> AgentDefinition:
    settings = get_settings()
    return AgentDefinition(
        description=(
            "Validate extracted fee data for completeness and correctness. "
            "Use after extraction to check quality."
        ),
        prompt="""You are a fee schedule validation specialist for US options exchanges.

Given a JSON array of extracted fees, validate:
1. Participant type coverage: CUSTOMER, MARKET_MAKER, PROFESSIONAL should be present
2. Fee type coverage: both MAKER and TAKER fees should be present
3. Amount reasonableness: flag any amount > $3.00/contract (300000 in amount_cents)
4. Sign/rebate consistency: is_rebate=true should have negative amount_cents
5. Tier group completeness: if tiers exist, check for gaps in tier levels

Return JSON:
```json
{
  "is_valid": true/false,
  "confidence": 0.0-1.0,
  "issues": [
    {"severity": "HIGH|MEDIUM|LOW", "category": "missing_participant|missing_fee_type|amount_outlier|sign_mismatch|tier_gap", "message": "description"}
  ],
  "suggested_corrections": ["specific correction instructions"]
}
```

Set is_valid=true if confidence >= 0.8. Return ONLY the JSON, no other text.""",
        tools=[],
        model=settings.claude_validator_model,
    )
```

**Step 2: Create discovery subagent**

```python
from claude_agent_sdk import AgentDefinition

from exnot.config import get_settings


def create_discovery_agent() -> AgentDefinition:
    settings = get_settings()
    return AgentDefinition(
        description=(
            "Evaluate search results to find official fee schedule URLs for US options exchanges. "
            "Use when discovering or updating exchange fee schedule URLs."
        ),
        prompt="""You are a URL discovery specialist for US options exchanges.

Given search results, identify the official fee schedule document URL.

Preferences (in order):
1. Direct PDF from official exchange website
2. HTML fee schedule page from official exchange website
3. CSV/Excel fee data from official exchange website
4. SEC/regulatory filing with fee schedule

Avoid:
- Third-party summaries or news articles
- Outdated versions (check year in URL/title)
- Generic exchange pages without fee data

Return JSON:
```json
{
  "primary_url": "https://...",
  "alternate_urls": ["https://..."],
  "recommended_format": "pdf|html|csv",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}
```

Return ONLY the JSON, no other text.""",
        tools=[],
        model=settings.claude_discovery_model,
    )
```

**Step 3: Update `__init__.py`**

```python
from exnot.agents.subagents.discovery import create_discovery_agent
from exnot.agents.subagents.extractor import create_extractor_agent
from exnot.agents.subagents.validator import create_validator_agent

__all__ = ["create_discovery_agent", "create_extractor_agent", "create_validator_agent"]
```

**Step 4: Commit**

```bash
git add src/exnot/agents/subagents/
git commit -m "feat: add validator and discovery subagents"
```

---

## Phase 4: Orchestrator Pipeline

### Task 12: Move prompts directory

**Files:**
- Move: `src/exnot/ai/prompts/` → `src/exnot/agents/prompts/`

**Step 1: Copy prompts directory**

Run: `cp -r src/exnot/ai/prompts src/exnot/agents/prompts`

**Step 2: Update all imports in prompt files**

Read each file in `src/exnot/agents/prompts/` and update any internal imports that reference `exnot.ai.prompts` to `exnot.agents.prompts`.

**Step 3: Update imports in extractor subagent**

In `src/exnot/agents/subagents/extractor.py`, change:
```python
# FROM:
from exnot.ai.prompts.registry import get_extraction_prompt
# TO:
from exnot.agents.prompts.registry import get_extraction_prompt
```

**Step 4: Update imports in exchange tool**

In `src/exnot/agents/tools/exchange.py`, change:
```python
# FROM:
from exnot.ai.prompts.registry import get_extraction_prompt
# TO:
from exnot.agents.prompts.registry import get_extraction_prompt
```

**Step 5: Verify no remaining references to old path**

Run: `grep -r "exnot.ai.prompts" src/exnot/agents/`
Expected: no output

**Step 6: Commit**

```bash
git add src/exnot/agents/prompts/ src/exnot/agents/subagents/extractor.py src/exnot/agents/tools/exchange.py
git commit -m "refactor: move prompts to agents/prompts"
```

---

### Task 13: Create orchestrator pipeline

**Files:**
- Create: `src/exnot/agents/pipeline.py`

**Step 1: Read `src/exnot/workers/pipelines.py`** thoroughly (904 lines) to understand the full pipeline flow, error handling, and edge cases.

**Step 2: Create pipeline module**

```python
import asyncio
import json
import logging

from claude_agent_sdk import ClaudeAgentOptions, query

from exnot.agents.subagents import create_discovery_agent, create_extractor_agent, create_validator_agent
from exnot.agents.tools.server import create_tools_server
from exnot.config import get_settings

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM_PROMPT = """You are ExNot, an automated pipeline coordinator for US options exchange fee schedule processing.

You have tools for each pipeline step and specialized subagents for AI-intensive tasks.

## Available Tools
- load_exchange: Get exchange configuration
- load_exchange_prompt: Get exchange-specific extraction instructions
- search_fee_urls: Search for fee schedule URLs via SerpAPI
- scrape_document: Download a document from URL
- check_document_changed: Compare document hash against latest snapshot
- parse_document: Parse PDF/HTML/CSV into sections and tables
- try_profile_extract: Attempt rules-based extraction using saved profile
- save_profile: Save extraction profile from AI results
- normalize_fees: Map extracted fees to canonical schema
- detect_changes: Diff against previous snapshot
- save_snapshot: Persist snapshot to database
- save_scraped_document: Store document in object storage
- send_notifications: Email subscribers about changes

## Available Subagents
- extractor: Extracts structured fee data from document text (use via Task tool)
- validator: Validates extraction completeness and quality (use via Task tool)
- discovery: Evaluates search results to find official URLs (use via Task tool)

## Execution Rules
1. Always load exchange config first
2. Use discovery subagent only if exchange has no configured URLs
3. Check if document changed before processing (unless forced)
4. Try profile-based extraction first — it's free
5. For AI extraction, pass full section text to the extractor subagent
6. Process section groups sequentially, accumulate all fees
7. After extraction, use validator subagent to check quality
8. If validation confidence < 0.8, re-invoke extractor with correction context (max 1 retry)
9. Always save results even if confidence is imperfect
10. Send notifications only if changes were detected

Report your final status as a JSON summary with: exchange_code, fees_extracted, changes_detected, notifications_sent, errors."""


async def run_exchange_pipeline(exchange_code: str, force: bool = False) -> list:
    """Run the full extraction pipeline for one exchange via Claude Agent SDK."""
    settings = get_settings()
    tools_server = create_tools_server()

    extractor_agent = create_extractor_agent(exchange_code)
    validator_agent = create_validator_agent()
    discovery_agent = create_discovery_agent()

    options = ClaudeAgentOptions(
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        allowed_tools=["mcp__exnot__*", "Task"],
        mcp_servers={"exnot": tools_server},
        agents={
            "extractor": extractor_agent,
            "validator": validator_agent,
            "discovery": discovery_agent,
        },
        permission_mode="bypassPermissions",
        model=settings.claude_orchestrator_model,
    )

    prompt = (
        f"Process fee schedule for exchange: {exchange_code}\n"
        f"Force re-process: {force}\n\n"
        "Execute the full pipeline following the execution rules in your instructions."
    )

    messages = []
    async for message in query(prompt=prompt, options=options):
        messages.append(message)
        # Broadcast to dashboard SSE (if streaming module is available)
        try:
            from exnot.agents.streaming import broadcast_to_dashboard
            await broadcast_to_dashboard(exchange_code, message)
        except Exception:
            pass

    return messages


def run_exchange_pipeline_sync(exchange_code: str, force: bool = False) -> list:
    """Sync wrapper for Celery task compatibility."""
    return asyncio.run(run_exchange_pipeline(exchange_code, force=force))
```

**Step 3: Commit**

```bash
git add src/exnot/agents/pipeline.py
git commit -m "feat: add orchestrator pipeline using Claude Agent SDK"
```

---

## Phase 5: SSE Streaming & Dashboard

### Task 14: Create SSE streaming module

**Files:**
- Create: `src/exnot/agents/streaming.py`

**Step 1: Create streaming module**

```python
import asyncio
import json
import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory channel per exchange pipeline run
active_streams: dict[str, asyncio.Queue] = {}


def serialize_sdk_message(message) -> dict:
    """Extract dashboard-relevant info from an SDK message."""
    if hasattr(message, "content") and message.content:
        blocks = []
        for block in message.content:
            if hasattr(block, "text"):
                blocks.append({"type": "reasoning", "text": block.text})
            elif hasattr(block, "name"):
                blocks.append({
                    "type": "tool_call",
                    "name": block.name,
                    "input": getattr(block, "input", {}),
                })
        return {
            "type": "assistant",
            "blocks": blocks,
            "is_subagent": bool(getattr(message, "parent_tool_use_id", None)),
        }
    elif hasattr(message, "result"):
        return {"type": "result", "subtype": getattr(message, "subtype", "unknown")}
    return {"type": "system", "raw": str(message)[:500]}


async def broadcast_to_dashboard(exchange_code: str, message):
    """Push SDK message to any listening dashboard clients."""
    queue = active_streams.get(exchange_code)
    if not queue:
        return
    event = serialize_sdk_message(message)
    await queue.put(event)


@router.get("/dashboard/pipeline/{exchange_code}/stream")
async def stream_pipeline(exchange_code: str):
    """SSE endpoint for live pipeline activity."""
    queue: asyncio.Queue = asyncio.Queue()
    active_streams[exchange_code] = queue

    async def event_generator():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=300)
                yield {"event": "message", "data": json.dumps(event)}
        except asyncio.TimeoutError:
            yield {"event": "timeout", "data": "{}"}
        except asyncio.CancelledError:
            pass
        finally:
            active_streams.pop(exchange_code, None)

    return EventSourceResponse(event_generator())
```

**Step 2: Commit**

```bash
git add src/exnot/agents/streaming.py
git commit -m "feat: add SSE streaming for pipeline dashboard"
```

---

### Task 15: Mount SSE routes and update dashboard

**Files:**
- Modify: `src/exnot/api/app.py` (line ~50)
- Modify: `src/exnot/dashboard/routes.py` (lines 694-909)

**Step 1: Mount SSE router in app.py**

Add after the dashboard router mount (~line 55):

```python
try:
    from exnot.agents.streaming import router as streaming_router
    app.include_router(streaming_router)
except ImportError:
    pass
```

**Step 2: Remove old agent monitoring routes from dashboard/routes.py**

Remove the following sections (lines 694-909):
- `/dashboard/monitor` route
- `/dashboard/monitor/stream` SSE route (Redis-based)
- `/dashboard/monitor/events/{run_id}` route
- `/dashboard/monitor/{run_id}/stop` route
- Any related stop-all routes

Also remove imports of `EventEmitter`, `AgentRunRepository`, `AgentEventRepository` from the top of the file.

**Step 3: Run linter**

Run: `ruff check src/exnot/api/app.py src/exnot/dashboard/routes.py --fix`

**Step 4: Commit**

```bash
git add src/exnot/api/app.py src/exnot/dashboard/routes.py
git commit -m "feat: mount SSE streaming, remove old agent monitor routes"
```

---

## Phase 6: Wire Up Workers

### Task 16: Update Celery tasks

**Files:**
- Modify: `src/exnot/workers/tasks.py` (line 30, line ~160)

**Step 1: Read `src/exnot/workers/tasks.py`** to understand the full task structure.

**Step 2: Replace pipeline import and calls**

Change the import at line 30:
```python
# FROM:
from exnot.workers.pipelines import run_scrape_pipeline
# TO:
from exnot.agents.pipeline import run_exchange_pipeline_sync
```

At line ~160, in the `scrape_and_process_exchange` task, replace:
```python
# FROM:
change_report = run_scrape_pipeline(exchange_code, session, celery_task_id=self.request.id, force=force)
# TO:
messages = run_exchange_pipeline_sync(exchange_code, force=force)
```

Note: The return type changes from `ChangeReport | None` to `list` of SDK messages. Adjust any downstream code that uses `change_report`. The pipeline now handles DB persistence internally via tools, so the Celery task just triggers the pipeline.

**Step 3: Remove any other imports of old AI modules**

Search for and remove imports of:
- `exnot.ai.event_emitter`
- `exnot.ai.cost`
- `exnot.ai.models`
- `exnot.ai.deps`

**Step 4: Run linter**

Run: `ruff check src/exnot/workers/tasks.py --fix`

**Step 5: Commit**

```bash
git add src/exnot/workers/tasks.py
git commit -m "feat: wire Celery tasks to Claude Agent SDK pipeline"
```

---

## Phase 7: Cleanup

### Task 17: Remove old AI directory

**Files:**
- Remove: `src/exnot/ai/` (entire directory except `prompts/` which was already moved)
- Remove: `src/exnot/workers/pipelines.py`

**Step 1: Verify prompts were moved**

Run: `ls src/exnot/agents/prompts/registry.py`
Expected: file exists

**Step 2: Check for any remaining imports of old modules**

Run: `grep -r "from exnot.ai\." src/exnot/ --include="*.py" | grep -v "exnot/ai/"` (excluding files in ai/ itself)

Fix any remaining imports found. Common places:
- `src/exnot/parser/ai_extractor.py` — this file should be deleted or gutted (its role is replaced by the extractor subagent)
- `src/exnot/dashboard/routes.py` — already cleaned in Task 15
- `src/exnot/workers/tasks.py` — already cleaned in Task 16

**Step 3: Remove old files**

```bash
rm -rf src/exnot/ai/models.py src/exnot/ai/cost.py src/exnot/ai/deps.py src/exnot/ai/types.py src/exnot/ai/event_emitter.py
rm -rf src/exnot/ai/agents/
rm -f src/exnot/ai/__init__.py
rm -f src/exnot/parser/ai_extractor.py
rm -f src/exnot/workers/pipelines.py
```

Keep `src/exnot/ai/prompts/` as a symlink or remove it if all references now point to `src/exnot/agents/prompts/`.

**Step 4: Remove AgentRun/AgentEvent DB models and repositories**

In `src/exnot/db/models.py`:
- Remove `AgentRunStatus` enum (lines 156-160)
- Remove `AgentEventType` enum (lines 163-173)
- Remove `AgentRun` model (lines 556-573)
- Remove `AgentEvent` model (lines 576-595)

In `src/exnot/db/repositories.py`:
- Remove `AgentRunRepository` (lines 324-353)
- Remove `AgentEventRepository` (lines 356-368)

**Step 5: Create Alembic migration to drop agent tables**

Run: `alembic revision --autogenerate -m "drop agent_runs and agent_events tables"`
Then: `alembic upgrade head`

**Step 6: Run full linter**

Run: `ruff check src/exnot/ --fix`

**Step 7: Commit**

```bash
git add -A
git commit -m "cleanup: remove PydanticAI agents, LiteLLM, old pipeline, agent monitoring tables"
```

---

### Task 18: Remove old parser/table_classifier AI fallback

**Files:**
- Modify: `src/exnot/parser/table_classifier.py` (if it has any AI imports)

**Step 1: Read `src/exnot/parser/table_classifier.py`**

This file should already be pure rules-based (106 lines). Verify no imports from `exnot.ai`.

The hybrid AI classifier was in `src/exnot/ai/agents/table_classifier.py` which was already deleted in Task 17.

**Step 2: If clean, just verify and commit**

Run: `grep -r "exnot.ai" src/exnot/parser/table_classifier.py`
Expected: no output

**Step 3: Commit (if any changes)**

```bash
git add src/exnot/parser/table_classifier.py
git commit -m "cleanup: verify table classifier is rules-only"
```

---

### Task 19: Simplify profiles/builder.py

**Files:**
- Modify: `src/exnot/profiles/builder.py`

**Step 1: Read `src/exnot/profiles/builder.py`** (206 lines)

**Step 2: Remove any AI-dependent logic**

The builder currently takes `ai_fees: list[dict]` as input and builds profiles from them. This stays — the orchestrator will pass extracted fees to the `save_profile` tool. But remove any imports from `exnot.ai.*`.

**Step 3: Verify**

Run: `grep -r "exnot.ai" src/exnot/profiles/`
Expected: no output

**Step 4: Commit**

```bash
git add src/exnot/profiles/
git commit -m "cleanup: remove AI imports from profiles module"
```

---

## Phase 8: Integration Testing

### Task 20: End-to-end pipeline test

**Files:**
- Create: `tests/integration/test_agent_pipeline.py`

**Step 1: Write integration test**

```python
import pytest

from exnot.agents.pipeline import run_exchange_pipeline


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pipeline_runs_for_known_exchange():
    """Smoke test: run pipeline for a known exchange and verify it completes."""
    messages = await run_exchange_pipeline("CBOE", force=True)
    assert len(messages) > 0
    # Check that we got a result message
    result_messages = [m for m in messages if hasattr(m, "result")]
    assert len(result_messages) > 0
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_agent_pipeline.py -v -s`

This will make real Claude API calls and test the full pipeline. Debug any issues.

**Step 3: Commit**

```bash
git add tests/integration/test_agent_pipeline.py
git commit -m "test: add agent pipeline integration test"
```

---

### Task 21: Verify tools work individually

**Files:**
- Create: `tests/integration/test_agent_tools.py`

**Step 1: Write tool tests**

```python
import pytest
import json
from claude_agent_sdk import query, ClaudeAgentOptions
from exnot.agents.tools.server import create_tools_server


@pytest.mark.asyncio
@pytest.mark.integration
async def test_load_exchange_tool():
    """Verify the load_exchange tool returns valid exchange data."""
    server = create_tools_server()
    messages = []
    async for msg in query(
        prompt="Use the load_exchange tool with exchange_code 'CBOE' and tell me the exchange name.",
        options=ClaudeAgentOptions(
            mcp_servers={"exnot": server},
            allowed_tools=["mcp__exnot__load_exchange"],
            permission_mode="bypassPermissions",
            model="haiku",
        ),
    ):
        messages.append(msg)
    # Should have completed successfully
    result_msgs = [m for m in messages if hasattr(m, "result")]
    assert len(result_msgs) > 0
```

**Step 2: Run tool tests**

Run: `pytest tests/integration/test_agent_tools.py -v -s`

**Step 3: Commit**

```bash
git add tests/integration/test_agent_tools.py
git commit -m "test: add agent tool integration tests"
```

---

### Task 22: Final cleanup and verification

**Step 1: Run full linter**

Run: `ruff check src/exnot/ tests/ --fix`

**Step 2: Check for dead imports**

Run: `grep -r "pydantic_ai\|pydantic-ai\|litellm\|openrouter" src/exnot/ --include="*.py"`
Expected: no output

Run: `grep -r "from exnot.ai\." src/exnot/ --include="*.py"`
Expected: no output (or only from `agents/prompts/` internal references)

**Step 3: Run all tests**

Run: `pytest tests/unit/ -v`

Fix any import errors from removed modules.

**Step 4: Commit**

```bash
git add -A
git commit -m "cleanup: final lint and dead import removal"
```
