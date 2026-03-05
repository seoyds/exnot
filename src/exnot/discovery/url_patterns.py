"""URL pattern derivation and matching for pinned document URLs."""

import re
from urllib.parse import urlparse


def derive_url_pattern(url: str) -> str | None:
    """Derive a regex pattern from a URL that matches structurally similar URLs.

    Replaces date-like segments (2020-2030) and version numbers with wildcards.
    Keeps domain, path structure, and file extension stable.
    """
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None

    # Use domain as-is for readability and easy substring matching.
    # The unescaped dots will match any character in regex, which is
    # acceptable for URL matching (domains won't have unusual chars).
    domain_pattern = parsed.netloc

    # Process path: replace year-like numbers with wildcards BEFORE escaping,
    # using a placeholder that won't be affected by re.escape
    path = parsed.path
    # Replace 4-digit years (2020-2039 range) with a placeholder
    placeholder = "__YEAR_PATTERN__"
    path_with_placeholders = re.sub(r"20[2-3]\d", placeholder, path)

    # Now escape the path for regex safety
    path_pattern = re.escape(path_with_placeholders)

    # Replace the escaped placeholder with the actual regex pattern
    escaped_placeholder = re.escape(placeholder)
    path_pattern = path_pattern.replace(escaped_placeholder, r"20[2-3]\d")

    return f"^https?://{domain_pattern}{path_pattern}$"


def match_url_pattern(pattern: str | None, url: str) -> bool:
    """Check if a URL matches a derived pattern."""
    if not pattern:
        return False
    try:
        return bool(re.match(pattern, url))
    except re.error:
        return False
