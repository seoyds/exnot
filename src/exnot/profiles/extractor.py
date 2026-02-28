"""Rules-based fee extraction using stored table profiles."""
import logging
import re
from decimal import InvalidOperation

from exnot.parser.base import ExtractedTable

logger = logging.getLogger(__name__)

# Contra-party label normalization
CONTRA_MAPPINGS = {
    "non-customer": "NON_CUSTOMER",
    "customer": "CUSTOMER",
    "professional": "PROFESSIONAL",
    "market maker": "MARKET_MAKER",
    "mm": "MARKET_MAKER",
    "firm": "FIRM",
    "broker-dealer": "BROKER_DEALER",
    "bd": "BROKER_DEALER",
}


def parse_amount(raw: str) -> float | None:
    """Parse a dollar amount string. Returns None if unparseable."""
    if not raw or not raw.strip():
        return None

    s = raw.strip()
    # Remove dollar sign
    s = s.replace("$", "")

    # Handle parenthetical negatives: (0.20) -> -0.20
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    elif s.startswith("-"):
        negative = True
        s = s[1:]

    # Remove commas
    s = s.replace(",", "").strip()

    try:
        value = float(s)
    except (ValueError, InvalidOperation):
        return None

    return -value if negative else value


def _resolve_contra(raw: str | None) -> str | None:
    """Resolve a contra-party label to canonical enum."""
    if not raw:
        return None
    normalized = raw.strip().lower()
    for label, enum_val in CONTRA_MAPPINGS.items():
        if label in normalized:
            return enum_val
    return None


def extract_from_mapping(
    table: ExtractedTable,
    mapping: dict,
) -> list[dict]:
    """Extract fees from a table using a stored column mapping.

    Returns list of fee dicts in the same format as AI extraction output.
    """
    fees = []
    row_axis_col = mapping.get("row_axis_col", 0)
    has_contra = mapping.get("has_contra_party_column", False)
    contra_col = mapping.get("contra_party_col_index")
    row_mappings = mapping.get("row_mappings", {})
    section_ref = mapping.get("section_ref", "")
    order_type = mapping.get("order_type", "SIMPLE")

    for row in table.rows:
        if len(row) <= row_axis_col:
            continue

        row_label = str(row[row_axis_col]).strip()
        # Clean newlines from row labels
        row_label = re.sub(r"\s+", " ", row_label)

        participant_info = row_mappings.get(row_label)
        if not participant_info:
            # Try partial match for labels with extra text
            for known_label, info in row_mappings.items():
                if known_label.lower() in row_label.lower():
                    participant_info = info
                    break
        if not participant_info:
            continue

        contra_party = None
        if has_contra and contra_col is not None and contra_col < len(row):
            contra_party = _resolve_contra(str(row[contra_col]))

        for group in mapping.get("column_groups", []):
            security_class = group.get("security_class", "ALL")
            for col_def in group.get("columns", []):
                col_idx = col_def["col_index"]
                if col_idx >= len(row):
                    continue

                amount = parse_amount(str(row[col_idx]))
                if amount is None:
                    continue

                fees.append({
                    "participant_type": participant_info["participant_type"],
                    "contra_party_type": contra_party,
                    "security_class": security_class,
                    "fee_type": col_def["fee_type"],
                    "order_type": order_type,
                    "amount": amount,
                    "is_rebate": amount < 0,
                    "section_ref": section_ref,
                    "fee_code": None,
                    "symbol": None,
                    "fee_unit": "PER_CONTRACT",
                    "routing_destination": None,
                    "tier_group": None,
                    "tier_number": None,
                    "tier_conditions": None,
                    "conditions": None,
                    "notes": None,
                })

    return fees


def extract_all_from_profile(
    tables: list[ExtractedTable],
    table_mappings: list[dict],
) -> list[dict]:
    """Extract fees from all tables using stored profile mappings."""
    all_fees = []
    for mapping in table_mappings:
        if not mapping.get("is_fee_table", False):
            continue
        idx = mapping.get("table_index", -1)
        if idx < 0 or idx >= len(tables):
            logger.warning(f"Table index {idx} out of range (have {len(tables)} tables)")
            continue
        fees = extract_from_mapping(tables[idx], mapping)
        all_fees.extend(fees)
    return all_fees
