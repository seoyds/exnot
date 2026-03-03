"""Table fingerprinting for change detection."""

import hashlib
import re
from dataclasses import dataclass, field

from exnot.parser.base import ExtractedTable

# Patterns to strip from headers before fingerprinting
FOOTNOTE_REF_PATTERN = re.compile(r"\d+F\d+|\d+f\d+")
TRAILING_NUMBERS = re.compile(r"\d+$")


def _normalize_header(header: str) -> str:
    """Normalize a header for stable fingerprinting."""
    h = header.strip().lower()
    h = FOOTNOTE_REF_PATTERN.sub("", h)
    h = TRAILING_NUMBERS.sub("", h)
    h = re.sub(r"\s+", " ", h).strip()
    return h


def fingerprint_table(table: ExtractedTable) -> str:
    """Compute a stable fingerprint from a table's header structure."""
    normalized = [_normalize_header(h) for h in table.headers]
    raw = "|".join(normalized)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def fingerprint_all_tables(
    tables: list[ExtractedTable],
) -> dict[str, int]:
    """Compute fingerprints for all tables. Returns {fingerprint: table_index}."""
    result = {}
    for i, table in enumerate(tables):
        fp = fingerprint_table(table)
        result[fp] = i
    return result


@dataclass
class FingerprintComparison:
    """Result of comparing current fingerprints against stored profile."""

    all_match: bool
    matched_indices: list[int] = field(default_factory=list)
    changed_indices: list[int] = field(default_factory=list)
    new_indices: list[int] = field(default_factory=list)
    removed_fingerprints: list[str] = field(default_factory=list)

    @property
    def changed_ratio(self) -> float:
        total = len(self.matched_indices) + len(self.changed_indices) + len(self.new_indices)
        if total == 0:
            return 1.0
        return (len(self.changed_indices) + len(self.new_indices)) / total


def compare_fingerprints(
    stored: dict[str, dict],
    current: dict[str, int],
) -> FingerprintComparison:
    """Compare current table fingerprints against a stored profile.

    Args:
        stored: {fingerprint: {"table_index": N, ...}} from profile
        current: {fingerprint: table_index} from current document
    """
    stored_fps = set(stored.keys())
    current_fps = set(current.keys())

    matched_fps = stored_fps & current_fps
    removed_fps = stored_fps - current_fps
    new_fps = current_fps - stored_fps

    matched_indices = [current[fp] for fp in matched_fps]
    new_indices = [current[fp] for fp in new_fps]

    # Changed = stored fee tables whose fingerprint disappeared
    # (the table at that index now has a different fingerprint)
    changed_indices = []
    for fp in removed_fps:
        old_idx = stored[fp].get("table_index")
        if old_idx is not None and stored[fp].get("is_fee_table", True):
            changed_indices.append(old_idx)

    all_match = len(removed_fps) == 0 and len(new_fps) == 0

    return FingerprintComparison(
        all_match=all_match,
        matched_indices=sorted(matched_indices),
        changed_indices=sorted(changed_indices),
        new_indices=sorted(new_indices),
        removed_fingerprints=sorted(removed_fps),
    )
