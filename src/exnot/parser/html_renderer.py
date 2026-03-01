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
