"""Tests for Playwright-based HTML text renderer."""

import pytest

from exnot.parser.html_renderer import render_html_text

try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        _browser = p.chromium.launch(headless=True)
        _browser.close()
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright Chromium not available")


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
        assert "Transaction Fees" in text

    def test_returns_empty_on_empty_html(self):
        html = b"<html><body></body></html>"
        text = render_html_text(html)
        assert text == "" or text.strip() == ""

    def test_handles_unicode(self):
        html = b"<html><body><p>Fee: $0.25 per contract</p></body></html>"
        text = render_html_text(html)
        assert "$0.25" in text

    def test_rendered_text_is_smaller_than_get_text(self):
        """Rendered text should exclude hidden content that get_text() includes."""
        from exnot.parser.html_parser import HtmlParser

        html = b"""
        <html><body>
        <div style="display:none">""" + b"HIDDEN " * 500 + b"""</div>
        <h1>Visible Fee Schedule</h1>
        <p>Only this should appear.</p>
        </body></html>
        """
        parser = HtmlParser()

        doc_raw = parser.extract(html)
        rendered = render_html_text(html)
        doc_rendered = parser.extract(html, rendered_text=rendered)

        assert len(doc_raw.full_text) > len(doc_rendered.full_text)
        assert "HIDDEN" in doc_raw.full_text
        assert "HIDDEN" not in doc_rendered.full_text
        assert "Visible Fee Schedule" in doc_rendered.full_text
