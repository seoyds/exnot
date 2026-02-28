"""Profile builder - learns table mappings from AI extraction output."""
import logging
import re
from dataclasses import dataclass, field

from exnot.parser.base import ExtractedTable
from exnot.parser.table_classifier import classify_tables
from exnot.profiles.extractor import parse_amount
from exnot.profiles.fingerprint import fingerprint_table

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Result of profile building."""
    table_mappings: list[dict] = field(default_factory=list)
    table_fingerprints: dict = field(default_factory=dict)
    extraction_stats: dict = field(default_factory=dict)
    match_ratio: float = 0.0
    matched_fees: int = 0
    total_fees: int = 0


class ProfileBuilder:
    """Learns table column mappings from AI extraction output."""

    def build(
        self,
        tables: list[ExtractedTable],
        ai_fees: list[dict],
    ) -> BuildResult:
        """Build a profile by matching AI-extracted fees to source table cells.

        Args:
            tables: Parsed tables from the document
            ai_fees: Fee dicts returned by AI extraction
        """
        result = BuildResult(total_fees=len(ai_fees))
        if not ai_fees or not tables:
            return result

        # Classify and fingerprint tables
        classifications = classify_tables(tables)
        fingerprints = {}
        for i, table in enumerate(tables):
            fp = fingerprint_table(table)
            is_fee = classifications[i].is_fee_table
            fingerprints[fp] = {
                "table_index": i,
                "title": table.title,
                "is_fee_table": is_fee,
            }
        result.table_fingerprints = fingerprints

        # Build amount->(table_idx, row_idx, col_idx) index for fee tables
        cell_index: dict[float, list[tuple[int, int, int]]] = {}
        for tbl_idx, table in enumerate(tables):
            if not classifications[tbl_idx].is_fee_table:
                continue
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row):
                    amt = parse_amount(str(cell))
                    if amt is not None:
                        cell_index.setdefault(amt, []).append((tbl_idx, row_idx, col_idx))

        # Match each AI fee to a source cell
        table_matches: dict[int, dict] = {}
        matched = 0

        for fee in ai_fees:
            amount = fee.get("amount")
            if amount is None:
                continue
            # Normalize: AI sometimes returns int for 0
            amount = float(amount)

            candidates = cell_index.get(amount, [])
            if not candidates:
                continue

            # Pick best candidate - prefer tables that already have matches
            best = None
            for tbl_idx, row_idx, col_idx in candidates:
                if tbl_idx in table_matches:
                    best = (tbl_idx, row_idx, col_idx)
                    break
            if best is None:
                best = candidates[0]

            tbl_idx, row_idx, col_idx = best
            table = tables[tbl_idx]
            row = table.rows[row_idx]

            if tbl_idx not in table_matches:
                table_matches[tbl_idx] = {"columns": {}, "row_labels": {}, "fees": []}

            # Record row label mapping
            row_label = str(row[0]).strip()
            row_label = re.sub(r"\s+", " ", row_label)
            participant = fee.get("participant_type")
            if participant and row_label:
                table_matches[tbl_idx]["row_labels"][row_label] = {
                    "participant_type": participant
                }

            # Record column mapping
            col_key = col_idx
            if col_key not in table_matches[tbl_idx]["columns"]:
                header = table.headers[col_idx] if col_idx < len(table.headers) else ""
                table_matches[tbl_idx]["columns"][col_key] = {
                    "header": re.sub(r"\s+", " ", header).strip(),
                    "fee_type": fee.get("fee_type", "TRANSACTION"),
                    "col_index": col_idx,
                    "security_class": fee.get("security_class", "ALL"),
                }

            table_matches[tbl_idx]["fees"].append(fee)
            matched += 1

        result.matched_fees = matched
        result.match_ratio = matched / len(ai_fees) if ai_fees else 0.0

        # Build table_mappings from matches
        for tbl_idx, match_data in table_matches.items():
            table = tables[tbl_idx]

            # Group columns by security_class
            col_groups: dict[str, list[dict]] = {}
            for col_info in match_data["columns"].values():
                sc = col_info["security_class"]
                col_groups.setdefault(sc, []).append(col_info)

            column_groups = []
            for sc, cols in col_groups.items():
                column_groups.append({
                    "label": sc,
                    "security_class": sc,
                    "columns": [
                        {"header": c["header"], "fee_type": c["fee_type"], "col_index": c["col_index"]}
                        for c in sorted(cols, key=lambda x: x["col_index"])
                    ],
                })

            # Detect contra-party column
            has_contra = False
            contra_col = None
            sample_fee = match_data["fees"][0] if match_data["fees"] else {}
            if sample_fee.get("contra_party_type"):
                for ci, h in enumerate(table.headers):
                    if "contra" in h.lower():
                        has_contra = True
                        contra_col = ci
                        break

            mapping = {
                "table_index": tbl_idx,
                "fingerprint": fingerprint_table(table),
                "table_title": table.title or f"Table {tbl_idx + 1}",
                "is_fee_table": True,
                "layout": "GRID",
                "row_axis_col": 0,
                "has_contra_party_column": has_contra,
                "contra_party_col_index": contra_col,
                "column_groups": column_groups,
                "row_mappings": match_data["row_labels"],
                "section_ref": sample_fee.get("section_ref", ""),
                "order_type": sample_fee.get("order_type", "SIMPLE"),
            }
            result.table_mappings.append(mapping)

        # Also add non-fee table entries (so we know to skip them)
        for i, cls in enumerate(classifications):
            if i not in table_matches:
                fp = fingerprint_table(tables[i])
                result.table_mappings.append({
                    "table_index": i,
                    "fingerprint": fp,
                    "table_title": tables[i].title or f"Table {i + 1}",
                    "is_fee_table": False,
                })

        # Extraction stats
        participant_types = sorted(set(f.get("participant_type", "") for f in ai_fees if f.get("participant_type")))
        order_types = sorted(set(f.get("order_type", "") for f in ai_fees if f.get("order_type")))
        fee_types = sorted(set(f.get("fee_type", "") for f in ai_fees if f.get("fee_type")))

        result.extraction_stats = {
            "expected_fee_count": len(ai_fees),
            "participant_types": participant_types,
            "order_types": order_types,
            "fee_types": fee_types,
            "has_tiers": any(f.get("tier_group") for f in ai_fees),
            "tier_groups": sorted(set(f.get("tier_group", "") for f in ai_fees if f.get("tier_group"))),
        }

        logger.info(
            f"Profile built: {matched}/{len(ai_fees)} fees matched to table cells "
            f"({result.match_ratio:.0%}), {len(table_matches)} fee tables identified"
        )
        return result
