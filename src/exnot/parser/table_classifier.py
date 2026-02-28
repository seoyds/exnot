"""Classify parsed tables as fee-relevant or non-fee."""
import re
from dataclasses import dataclass

from exnot.parser.base import ExtractedTable

# Headers that indicate per-contract fee tables
FEE_INDICATORS = [
    "maker", "taker", "rebate", "per contract", "fee per",
    "customer", "professional", "market maker", "broker",
    "penny", "non-penny", "account type", "contra",
]

# Headers that indicate non-fee tables (connectivity, membership, etc.)
NON_FEE_INDICATORS = [
    "port", "connection", "subscription", "permit",
    "membership", "market data", "monthly fee", "per month",
    "per port", "report", "card submission",
]

# Dollar amounts in cells: $0.50, ($0.20), -$0.05
DOLLAR_PATTERN = re.compile(r"^[\s]*[\-]?\$?\(?\d+\.\d{2}\)?[\s]*$")


@dataclass
class TableClassification:
    table_index: int
    is_fee_table: bool
    score: int
    reason: str


def classify_table(table: ExtractedTable, table_index: int = 0) -> TableClassification:
    """Classify a single table as fee-relevant or not."""
    headers_lower = " ".join(h.lower() for h in table.headers)
    score = 0
    reasons = []

    # Check headers for fee indicators
    for indicator in FEE_INDICATORS:
        if indicator in headers_lower:
            score += 1
            reasons.append(f"+header:{indicator}")

    # Check headers for non-fee indicators
    for indicator in NON_FEE_INDICATORS:
        if indicator in headers_lower:
            score -= 2
            reasons.append(f"-header:{indicator}")

    # Check if cells contain dollar amounts (per-contract format: $0.XX)
    dollar_cells = 0
    total_cells = 0
    for row in table.rows[:5]:  # Sample first 5 rows
        for cell in row:
            total_cells += 1
            if DOLLAR_PATTERN.match(str(cell).strip()):
                dollar_cells += 1

    if dollar_cells >= 1:
        score += 1
        reasons.append(f"+dollar_cells:{dollar_cells}")

    # Empty/title-page tables (all headers blank or single giant cell)
    non_empty_headers = [h for h in table.headers if h.strip()]
    if len(non_empty_headers) <= 1 and len(table.rows) <= 2:
        score -= 3
        reasons.append("-title_page")

    # Very few rows with "per month" in cells → non-fee
    all_cells_text = " ".join(
        str(cell).lower() for row in table.rows[:5] for cell in row
    )
    if "per month" in all_cells_text or "per port" in all_cells_text:
        score -= 2
        reasons.append("-monthly_flat")

    return TableClassification(
        table_index=table_index,
        is_fee_table=score >= 1,
        score=score,
        reason="; ".join(reasons),
    )


def classify_tables(tables: list[ExtractedTable]) -> list[TableClassification]:
    """Classify all tables in a document."""
    return [classify_table(table, i) for i, table in enumerate(tables)]
