# Claude Agent SDK Migration Design

**Date**: 2026-03-07
**Status**: Approved
**Goal**: Replace PydanticAI + LiteLLM/OpenRouter with Claude Agent SDK for agentic pipeline orchestration

## Context

ExNot currently uses PydanticAI agents with LiteLLM for fee schedule extraction, routed through OpenRouter to multiple models (DeepSeek, Qwen, Mistral). This design replaces that with the Claude Agent SDK, which provides the same agent loop, tools, and context management that power Claude Code, as a programmable Python library.

### Trade-offs Accepted

- **Claude-only models** — lose multi-model routing (DeepSeek, Qwen, Mistral) in favor of Claude (Opus, Sonnet, Haiku)
- **Higher per-call cost** — offset by simplified infrastructure, no OpenRouter/LiteLLM overhead
- **Drop fine-grained cost tracking** — rely on Anthropic subscription limits instead of per-exchange budgets
- **Auth via `~/.claude/` subscription** — no API key management, runs on machines with Claude subscription

## Architecture Overview

Tool-heavy orchestrator with 3 specialized subagents. Deterministic pipeline steps are tools; AI-intensive reasoning is subagents.

```
+-----------------------------------------------------+
|                  Pipeline Runner                     |
|            (Celery task / manual trigger)            |
+------------------------+----------------------------+
                         |
                         v
+-----------------------------------------------------+
|              Orchestrator Agent (Haiku)               |
|                                                       |
|  TOOLS (deterministic):                               |
|  +-- load_exchange        (DB lookup)                 |
|  +-- load_exchange_prompt  (per-exchange prompts)     |
|  +-- search_fee_urls      (SerpAPI search)            |
|  +-- scrape_document      (HTTP/Playwright download)  |
|  +-- check_document_changed (hash comparison)         |
|  +-- parse_document       (PDF/HTML/CSV + splitter)   |
|  +-- try_profile_extract  (fingerprint + rules)       |
|  +-- save_profile         (persist profile)           |
|  +-- normalize_fees       (canonical schema mapping)  |
|  +-- detect_changes       (diff old vs new)           |
|  +-- save_snapshot        (DB persist)                |
|  +-- save_scraped_document (MinIO storage)            |
|  +-- send_notifications   (email delivery)            |
|                                                       |
|  SUBAGENTS (AI-intensive):                            |
|  +-- extractor   (Sonnet) fee extraction from text    |
|  +-- validator   (Haiku)  completeness checks         |
|  +-- discovery   (Haiku)  URL evaluation              |
+-----------------------------------------------------+
```

### Key Principles

1. Deterministic steps as **tools** — fast, predictable, no AI needed
2. AI reasoning as **subagents** — isolated context, specialized prompts
3. Orchestrator (Haiku) decides flow, handles retries, coordinates everything
4. Raw SDK message stream exposed via SSE for dashboard live view
5. No correction subagent — orchestrator re-invokes extractor with validator's issues

## Custom Tools

Each tool is a Python function decorated with `@tool`, exposed via an in-process MCP server.

### Tool Definitions

```python
# Data Loading
load_exchange(exchange_code) -> {name, urls, config, yaml_definition}
load_exchange_prompt(exchange_code) -> {system_prompt, extraction_hints}

# Discovery
search_fee_urls(exchange_name, operator) -> {search_results[]}

# Scraping
scrape_document(url, method="http"|"browser") -> {content_hash, raw_bytes, format}
check_document_changed(exchange_code, content_hash) -> {changed: bool, previous_snapshot_id}

# Parsing
parse_document(raw_bytes, format) -> {text, tables[], sections[], section_groups[]}

# Profiles
try_profile_extract(exchange_code, tables, sections) -> {matched: bool, fees[]?}
save_profile(exchange_code, tables, column_mappings) -> {profile_id}

# Normalization & Diffing
normalize_fees(raw_fees[], exchange_code) -> {normalized_fees[], warnings[]}
detect_changes(exchange_code, normalized_fees[]) -> {changes[], summary}

# Persistence
save_snapshot(exchange_code, normalized_fees[], changes[], doc_hash) -> {snapshot_id}
save_scraped_document(exchange_code, raw_bytes, format, snapshot_id) -> {doc_id}

# Notifications
send_notifications(exchange_code, changes[], summary) -> {sent_count}
```

### Design Choices

- Tools return structured dicts (JSON) — Claude sees data and decides next steps
- `parse_document` bundles parsing + section splitting + rule-based table classification
- Profile extraction is a tool because it's entirely rules-based
- Each tool is self-contained — no shared mutable state between tools

## Subagents

### Extractor (Sonnet)

Core value task — extracts structured fee data from document sections.

```python
AgentDefinition(
    description="Extract structured fee data from exchange fee schedule text.",
    prompt="""You are a specialist in US options exchange fee schedules.
    Given document sections, extract every fee entry into structured format:
    participant_type, security_class, order_type, fee_type, amount_cents,
    is_rebate, tier info, origin_code, product_type, liquidity_role.
    {exchange_specific_prompt}""",
    tools=["Read"],
    model="sonnet",
)
```

- Dynamic prompt — exchange-specific instructions injected via factory function
- Data passed in Task prompt, not via file system
- Returns structured fee list as text for orchestrator to parse

### Validator (Haiku)

Checks extraction completeness and quality.

```python
AgentDefinition(
    description="Validate extracted fee data for completeness and correctness.",
    prompt="""Check: CUSTOMER/MM/PROFESSIONAL coverage, MAKER+TAKER presence,
    amount reasonableness, sign/rebate consistency, tier completeness.
    Return: is_valid, confidence (0-1), issues[], suggested_corrections[]""",
    tools=[],
    model="haiku",
)
```

- Pure reasoning — no tools needed
- Orchestrator uses validation result to decide if re-extraction needed

### Discovery (Haiku)

Evaluates search results to find official fee schedule URLs.

```python
AgentDefinition(
    description="Evaluate search results to find official fee schedule URLs.",
    prompt="""Identify official fee schedule document URL from search results.
    Prefer: direct PDF/HTML from exchange > regulatory filings.
    Return: primary_url, alternate_urls[], recommended_format, confidence""",
    tools=[],
    model="haiku",
)
```

## Orchestrator

Runs per-exchange via `ClaudeSDKClient`. Uses Haiku model for cheap coordination.

```python
options = ClaudeAgentOptions(
    system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
    allowed_tools=["mcp__exnot__*", "Task"],
    mcp_servers={"exnot": tools_server},
    agents={...},
    permission_mode="bypassPermissions",
    model="haiku",
)
```

### Pipeline Flow

1. `load_exchange` — get exchange config
2. If URLs need discovery: `search_fee_urls` -> `discovery` subagent
3. `scrape_document` — download document
4. `check_document_changed` — skip if unchanged (unless forced)
5. `parse_document` — PDF/HTML/CSV + section splitting
6. `try_profile_extract` — rules-based extraction attempt
7. If no profile match: `extractor` subagent per section group
8. `validator` subagent — check quality
9. If confidence < 0.8: re-invoke `extractor` with correction context (max 1 retry)
10. `normalize_fees` — canonical schema mapping
11. `detect_changes` — diff vs previous snapshot
12. `save_snapshot` + `save_scraped_document` — persist results
13. `send_notifications` — email subscribers if changes detected

## Dashboard Integration

Replace Redis pub/sub EventEmitter with SSE streaming of raw SDK messages.

### SSE Endpoint

```python
@router.get("/pipeline/{exchange_code}/stream")
async def stream_pipeline(exchange_code: str):
    # Returns EventSourceResponse streaming SDK messages
```

### Message Types

- **reasoning** — Claude's thinking text (why it's doing each step)
- **tool_call** — which tool, what arguments
- **subagent** — flagged via `parent_tool_use_id`
- **result** — completion/error events

### What's Removed

- `EventEmitter` class
- `AgentRun` / `AgentEvent` DB models
- Redis pub/sub for agent monitoring

### What's Kept

- `ScrapeLog` DB records (pipeline outcomes persisted)
- Dashboard templates updated with HTMX + EventSource

## Project Structure Changes

### New: `src/exnot/agents/`

```
agents/
+-- tools/
|   +-- __init__.py
|   +-- server.py          # create_sdk_mcp_server setup
|   +-- exchange.py        # load_exchange, load_exchange_prompt
|   +-- discovery.py       # search_fee_urls
|   +-- scraping.py        # scrape_document, check_document_changed
|   +-- parsing.py         # parse_document
|   +-- profiles.py        # try_profile_extract, save_profile
|   +-- normalization.py   # normalize_fees
|   +-- diffing.py         # detect_changes
|   +-- persistence.py     # save_snapshot, save_scraped_document
|   +-- notifications.py   # send_notifications
+-- subagents/
|   +-- __init__.py
|   +-- extractor.py       # create_extractor_agent() factory
|   +-- validator.py       # VALIDATOR_AGENT definition
|   +-- discovery.py       # DISCOVERY_AGENT definition
+-- prompts/               # MOVED from ai/prompts/
|   +-- registry.py
|   +-- base.py
+-- pipeline.py            # Orchestrator: run_exchange_pipeline()
+-- streaming.py           # SSE broadcast + serialize_sdk_message
```

### Removed

- `src/exnot/ai/` — entire directory
  - `models.py` (LiteLLM model registry)
  - `cost.py` (CostTracker)
  - `deps.py` (dependency injection dataclasses)
  - `types.py` (Pydantic output models)
  - `agents/` (all PydanticAI agent definitions)
  - `event_emitter.py`
- `src/exnot/workers/pipelines.py` — replaced by `agents/pipeline.py`

### Changed

- `src/exnot/workers/tasks.py` — calls `agents/pipeline.py` instead of `workers/pipelines.py`
- `src/exnot/parser/table_classifier.py` — rules-based only, AI fallback removed
- `src/exnot/profiles/builder.py` — simplified, no AI profile building
- `src/exnot/config.py` — remove AI_MODEL_* and budget vars, add CLAUDE_*_MODEL vars
- `src/exnot/dashboard/templates/` — updated for SSE streaming
- `src/exnot/dashboard/routes.py` — add SSE endpoint

### Unchanged

- `src/exnot/parser/` (pdf_parser, html_parser, csv_parser, section_splitter)
- `src/exnot/normalizer/`
- `src/exnot/differ/`
- `src/exnot/scraper/`
- `src/exnot/storage/`
- `src/exnot/db/`
- `src/exnot/api/`
- `src/exnot/exchanges/definitions/`
- `src/exnot/notifications/`

## Configuration Changes

### Removed from `config.py`

```python
AI_MODEL: str
AI_MODEL_TABLE_CLASSIFICATION: str
AI_MODEL_ORCHESTRATOR: str
AI_MODEL_FEE_EXTRACTION: str
AI_MODEL_FEE_VALIDATION: str
AI_MODEL_CORRECTION: str
AI_MODEL_URL_DISCOVERY: str
AI_MODEL_CHANGE_SUMMARY: str
AI_BUDGET_PER_EXCHANGE_USD: float
AI_BUDGET_DAILY_USD: float
AI_SECTION_CHAR_BUDGET: int
OPENROUTER_API_KEY: str
OPENROUTER_BASE_URL: str
```

### Added to `config.py`

```python
CLAUDE_ORCHESTRATOR_MODEL: str = "haiku"
CLAUDE_EXTRACTOR_MODEL: str = "sonnet"
CLAUDE_VALIDATOR_MODEL: str = "haiku"
CLAUDE_DISCOVERY_MODEL: str = "haiku"
# Auth: uses ~/.claude/ subscription — no key config needed
```

## Dependencies

### Remove

- `pydantic-ai`
- `litellm`
- (OpenRouter dependency implicit via litellm)

### Add

- `claude-agent-sdk`
- `sse-starlette` (for SSE streaming endpoint)
