# HTML Content Reduction via Playwright innerText

**Date:** 2026-03-01
**Status:** Approved

## Problem

HTML fee schedule pages (e.g., NASDAQ ISE) contain 94K chars of extracted text via BeautifulSoup's `get_text()`, but only ~16K tokens of actual visible fee content. The bloat comes from navigation menus, hidden accordion/tab panels, sidebars, and repeated boilerplate that BeautifulSoup extracts but the browser doesn't display. This causes:

- AI extraction calls using 174K-239K input tokens per section group
- $1.58+ cost for just 2 extract_section calls
- Celery soft time limit (25 min) being hit

## Solution

Use Playwright to render HTML pages and extract `document.body.innerText` for the full text, while keeping BeautifulSoup for HTML table extraction.

### Why innerText

`innerText` only returns **visible text** — it respects CSS `display:none`, visibility, collapsed accordions, etc. This matches exactly what a user sees when copy-pasting from the browser (~16K tokens).

### Why not render to PDF

Converting HTML to PDF via `page.pdf()` would lose the well-structured HTML `<table>` elements. The HTML parser extracts tables perfectly from raw HTML — the bloat is in the surrounding text, not the tables.

## Architecture

```
Raw HTML (509KB)
  ├── BeautifulSoup: extract <table> elements → ExtractedTable[] (unchanged)
  └── Playwright render → page.evaluate('document.body.innerText') → full_text (~16K tokens)
```

## Changes

### 1. `HtmlParser.extract()` — accept optional `rendered_text`

Add an optional `rendered_text: str | None` parameter. If provided, use it as `full_text` instead of BeautifulSoup's `get_text()`. Tables are still parsed from raw HTML via BeautifulSoup (unchanged).

### 2. New utility: `render_html_text(html_bytes) -> str`

In `exnot/parser/html_renderer.py`:
- Launch Playwright, load HTML content via `page.set_content()` (no network request needed — HTML already fetched)
- Extract `document.body.innerText` via `page.evaluate()`
- Manage browser lifecycle efficiently (context manager pattern)
- Timeout: 15 seconds max

### 3. Pipeline integration

In `pipelines.py` or the parsing step: if the document is HTML, render it to get visible text before passing to HtmlParser.

### 4. Fallback

If Playwright rendering fails (browser not available, timeout), fall back to current BeautifulSoup `get_text()` with a warning log. This ensures the pipeline never breaks — it just uses more tokens in the degraded case.

## Expected Impact

- HTML full_text: 94K chars → ~16K tokens (~6x reduction)
- Per-group extract_section cost: ~$0.50 → ~$0.08
- Total NASDAQ ISE extraction: ~$2.00+ → ~$0.50
- Time: within Celery soft limit (25 min) easily
