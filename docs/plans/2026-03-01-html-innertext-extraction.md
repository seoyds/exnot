# HTML innerText Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace BeautifulSoup `get_text()` with Playwright `innerText` for HTML documents to reduce token bloat from 94K to ~16K chars.

**Architecture:** Add a `render_html_text()` utility that uses Playwright's sync API to render HTML and extract only visible text. HtmlParser gains an optional `rendered_text` parameter — when provided, it uses that as `full_text` instead of `get_text()`. The pipeline calls the renderer before parsing HTML documents.

**Tech Stack:** Playwright (already installed), sync_playwright API, existing HtmlParser and pipelines.py

---

### Task 1: Create HTML renderer utility

**Files:**
- Create: `src/exnot/parser/html_renderer.py`
- Test: `tests/unit/test_html_renderer.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_html_renderer.py
"""Tests for Playwright-based HTML text renderer."""

from exnot.parser.html_renderer import render_html_text


class TestRenderHtmlText:
    def test_extracts_visible_text_only(self):
        html = b"""
        <html><body>
        <div style="display:none">HIDDEN CONTENT</div>
        <h1>Fee Schedule</h1>
        <p>Effective January 2026</p>
        </body></html>
        """
        text = render_html_text(html)
        assert "Fee Schedule" in text
        assert "Effective January 2026" in text
        assert "HIDDEN CONTENT" not in text

    def test_strips_nav_and_chrome(self):
        html = b"""
        <html><body>
        <nav><ul><li>Home</li><li>About</li></ul></nav>
        <div id="content">
            <h2>Transaction Fees</h2>
            <table><tr><th>A</th></tr><tr><td>1</td></tr></table>
        </div>
        <footer>Copyright 2026</footer>
        </body></html>
        """
        text = render_html_text(html)
        # innerText includes nav/footer since they are visible,
        # but the key point is it's much smaller than get_text() on bloated pages
        assert "Transaction Fees" in text

    def test_returns_fallback_on_empty_html(self):
        html = b"<html><body></body></html>"
        text = render_html_text(html)
        assert text == "" or text.strip() == ""

    def test_handles_unicode(self):
        html = "<html><body><p>Fee: $0.25 per contract</p></body></html>".encode("utf-8")
        text = render_html_text(html)
        assert "$0.25" in text
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_html_renderer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'exnot.parser.html_renderer'`

**Step 3: Write the implementation**

```python
# src/exnot/parser/html_renderer.py
"""Render HTML via Playwright and extract only visible text (innerText).

Used to reduce HTML token bloat — BeautifulSoup's get_text() extracts all
text including hidden elements, navs, and collapsed accordion panels.
Playwright's innerText returns only what a user sees in the browser.
"""

import logging

logger = logging.getLogger(__name__)

# Timeout for rendering a single page (seconds)
_RENDER_TIMEOUT = 15


def render_html_text(html_bytes: bytes) -> str:
    """Render HTML content and return only visible text via innerText.

    Args:
        html_bytes: Raw HTML content.

    Returns:
        Visible text extracted via document.body.innerText.
        Falls back to empty string on failure.
    """
    try:
        from playwright.sync_api import sync_playwright

        html_str = html_bytes.decode("utf-8", errors="replace")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content(html_str, timeout=_RENDER_TIMEOUT * 1000)
                text = page.evaluate("document.body.innerText")
                return text or ""
            finally:
                browser.close()

    except Exception as e:
        logger.warning(f"Playwright rendering failed, returning empty text: {e}")
        return ""
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_html_renderer.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/exnot/parser/html_renderer.py tests/unit/test_html_renderer.py
git commit -m "feat: add Playwright-based HTML innerText renderer"
```

---

### Task 2: Add `rendered_text` parameter to HtmlParser

**Files:**
- Modify: `src/exnot/parser/html_parser.py:14-29`
- Modify: `tests/unit/test_parsers.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_parsers.py`:

```python
    def test_extract_with_rendered_text(self):
        """When rendered_text is provided, use it as full_text instead of get_text()."""
        html = b"""
        <html><body>
        <nav>Navigation Menu Item 1 Item 2 Item 3</nav>
        <h2>Transaction Fees</h2>
        <table>
            <tr><th>Participant</th><th>Fee</th></tr>
            <tr><td>Customer</td><td>$0.50</td></tr>
        </table>
        <footer>Copyright 2026 All Rights Reserved</footer>
        </body></html>
        """
        rendered = "Transaction Fees\nParticipant\tFee\nCustomer\t$0.50"
        doc = self.parser.extract(html, rendered_text=rendered)

        # full_text should be the rendered text, not BeautifulSoup's get_text()
        assert doc.full_text == rendered
        assert "Navigation Menu" not in doc.full_text
        # Tables should still be parsed from raw HTML
        assert len(doc.tables) == 1
        assert doc.tables[0].headers == ["Participant", "Fee"]

    def test_extract_without_rendered_text_unchanged(self):
        """Without rendered_text, behavior is unchanged (uses get_text())."""
        html = b"""
        <html><body>
        <h1>Fee Schedule</h1>
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        </body></html>
        """
        doc = self.parser.extract(html)
        assert "Fee Schedule" in doc.full_text
        assert len(doc.tables) == 1
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_parsers.py::TestHtmlParser::test_extract_with_rendered_text -v`
Expected: FAIL with `TypeError: extract() got an unexpected keyword argument 'rendered_text'`

**Step 3: Modify HtmlParser.extract()**

In `src/exnot/parser/html_parser.py`, change the `extract` method signature and body:

```python
    def extract(self, content: bytes, rendered_text: str | None = None) -> ExtractedDocument:
        html_str = content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html_str, "lxml")

        # Remove script/style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Use rendered_text (Playwright innerText) if provided, else fallback to get_text()
        if rendered_text is not None:
            full_text = rendered_text
        else:
            full_text = soup.get_text(separator="\n", strip=True)

        tables = self._extract_tables(soup)

        return ExtractedDocument(
            full_text=full_text,
            tables=tables,
            metadata={"parser": "html"},
        )
```

Note: The `AbstractParser.extract()` base method has signature `extract(self, content: bytes)`. The `rendered_text` parameter is HTML-specific and optional, so it's fine to extend the signature — Python allows subclasses to add optional parameters.

**Step 4: Run all tests to verify**

Run: `.venv/bin/pytest tests/unit/test_parsers.py -v`
Expected: All tests PASS (existing + 2 new)

**Step 5: Commit**

```bash
git add src/exnot/parser/html_parser.py tests/unit/test_parsers.py
git commit -m "feat: add rendered_text parameter to HtmlParser"
```

---

### Task 3: Integrate renderer into pipeline

**Files:**
- Modify: `src/exnot/workers/pipelines.py:392-404` (`_parse_document` function)

**Step 1: Write the failing test**

Add to `tests/unit/test_parsers.py` (or a new test file if preferred):

```python
# This is more of an integration check — test that HtmlParser with rendered_text
# produces smaller output than without it. Use the renderer directly.
class TestHtmlRendererIntegration:
    def test_rendered_text_is_smaller(self):
        """Rendered text should be significantly smaller than get_text() for bloated pages."""
        from exnot.parser.html_parser import HtmlParser
        from exnot.parser.html_renderer import render_html_text

        # Simulate a page with hidden content
        html = b"""
        <html><body>
        <div style="display:none">""" + b"HIDDEN " * 1000 + b"""</div>
        <h1>Visible Fee Schedule</h1>
        <p>Only this should appear.</p>
        </body></html>
        """
        parser = HtmlParser()

        # Without rendering
        doc_raw = parser.extract(html)
        # With rendering
        rendered = render_html_text(html)
        doc_rendered = parser.extract(html, rendered_text=rendered)

        assert len(doc_raw.full_text) > len(doc_rendered.full_text)
        assert "HIDDEN" in doc_raw.full_text
        assert "HIDDEN" not in doc_rendered.full_text
        assert "Visible Fee Schedule" in doc_rendered.full_text
```

**Step 2: Run test to verify it passes** (this should pass already since Task 1 and 2 are done)

Run: `.venv/bin/pytest tests/unit/test_parsers.py::TestHtmlRendererIntegration -v`
Expected: PASS

**Step 3: Modify `_parse_document` in pipelines.py**

In `src/exnot/workers/pipelines.py`, modify the `_parse_document` function (lines 392-404):

```python
def _parse_document(exchange: Exchange, doc_result: DocumentResult) -> ExtractedDocument:
    """Choose the right parser based on content type and run extraction."""
    if doc_result.is_csv or exchange.fee_schedule_format == FeeScheduleFormat.CSV:
        logger.info(f"[{exchange.code}] Parsing as CSV")
        parser = CsvParser()
        return parser.extract(doc_result.content_bytes)
    elif doc_result.is_pdf or exchange.fee_schedule_format == FeeScheduleFormat.PDF:
        logger.info(f"[{exchange.code}] Parsing as PDF")
        parser = get_pdf_parser()
        return parser.extract(doc_result.content_bytes)
    else:
        logger.info(f"[{exchange.code}] Parsing as HTML")
        parser = HtmlParser()

        # Render HTML with Playwright to get only visible text
        rendered_text = _render_html_visible_text(exchange.code, doc_result.content_bytes)
        return parser.extract(doc_result.content_bytes, rendered_text=rendered_text)
```

Add the helper function right below `_parse_document`:

```python
def _render_html_visible_text(exchange_code: str, html_bytes: bytes) -> str | None:
    """Render HTML with Playwright to extract only visible text.

    Returns the rendered text, or None to fall back to BeautifulSoup get_text().
    """
    from exnot.parser.html_renderer import render_html_text

    try:
        rendered = render_html_text(html_bytes)
        if rendered:
            raw_len = len(html_bytes)
            rendered_len = len(rendered)
            logger.info(
                f"[{exchange_code}] Playwright rendered HTML: "
                f"{raw_len} bytes -> {rendered_len} chars visible text"
            )
            return rendered
        else:
            logger.warning(f"[{exchange_code}] Playwright returned empty text, falling back to get_text()")
            return None
    except Exception as e:
        logger.warning(f"[{exchange_code}] Playwright rendering failed: {e}, falling back to get_text()")
        return None
```

Also update `_parse_supplementary_html` (lines 407-420) to use rendering too:

```python
def _parse_supplementary_html(
    exchange: Exchange, collection: CollectionResult
) -> ExtractedDocument | None:
    """Find and parse an HTML document from the collection to supplement CSV data."""
    from exnot.scraper.base import ContentType

    for doc in collection.documents:
        if doc.content_type == ContentType.HTML and doc.content_hash != collection.primary.content_hash:
            logger.info(f"[{exchange.code}] Parsing supplementary HTML from {doc.source_url}")
            parser = HtmlParser()
            rendered_text = _render_html_visible_text(exchange.code, doc.content_bytes)
            return parser.extract(doc.content_bytes, rendered_text=rendered_text)

    logger.info(f"[{exchange.code}] No supplementary HTML document found in collection")
    return None
```

**Step 4: Run all tests**

Run: `.venv/bin/pytest tests/ -x -q`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/exnot/workers/pipelines.py
git commit -m "feat: integrate Playwright HTML rendering into pipeline"
```

---

### Task 4: Run full test suite and lint

**Step 1: Run linter**

Run: `.venv/bin/ruff check src/exnot/parser/html_renderer.py src/exnot/parser/html_parser.py src/exnot/workers/pipelines.py`
Expected: No errors

**Step 2: Run full test suite**

Run: `.venv/bin/pytest tests/ -x -q`
Expected: All tests PASS

**Step 3: Fix any issues found**

Address any linting or test failures.

**Step 4: Commit fixes if needed**

---

### Task 5: Deploy and verify with NASDAQ ISE

**Step 1: Push changes**

```bash
git push origin qa
```

**Step 2: Rebuild Docker**

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

**Step 3: Trigger NASDAQ ISE scrape**

```bash
docker compose exec web python -c "
from exnot.workers.tasks import scrape_and_process_exchange
result = scrape_and_process_exchange.delay('NASDAQ_ISE')
print(f'Task ID: {result.id}')
"
```

**Step 4: Monitor logs for token reduction**

```bash
docker compose logs worker --follow
```

Expected output should show:
- `Playwright rendered HTML: 508965 bytes -> ~16000 chars visible text`
- `Pre-split: X sections, Y fee-bearing, Z groups` (fewer/smaller groups)
- extract_section calls with much lower token counts
- Total cost well under $2.00
- Completion within Celery time limit

**Step 5: Verify on website**

Check `exnot.thepram.dev` for NASDAQ ISE data populated correctly.
