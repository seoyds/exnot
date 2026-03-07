"""Fee normalization tool — normalize raw fees to canonical schema."""

import json
import logging

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)


@tool(
    "normalize_fees",
    "Normalize raw AI-extracted fees into the canonical fee schema. Takes raw fees "
    "as a JSON string and returns normalized fee entries with canonical participant_type, "
    "security_class, order_type, fee_type, and amount_cents values.",
    {"exchange_code": str, "raw_fees_json": str},
)
async def normalize_fees(args):
    try:
        from exnot.normalizer.engine import NormalizationEngine
        from exnot.parser.ai_extractor import ExtractionResult

        exchange_code = args["exchange_code"]
        raw_fees = json.loads(args["raw_fees_json"])

        # Build an ExtractionResult from the raw fees
        extraction = ExtractionResult(
            raw_fees=raw_fees,
            confidence=0.0,
            exchange_name=exchange_code,
        )

        engine = NormalizationEngine()
        schedule = engine.normalize(extraction, exchange_code)

        # Serialize normalized fees
        normalized = []
        for fee in schedule.fees:
            entry = {
                "exchange_code": fee.exchange_code,
                "fee_code": fee.fee_code,
                "participant_type": fee.participant_type.value,
                "contra_party_type": fee.contra_party_type.value
                if fee.contra_party_type
                else None,
                "security_class": fee.security_class.value,
                "symbol": fee.symbol,
                "order_type": fee.order_type.value,
                "fee_type": fee.fee_type.value,
                "fee_unit": fee.fee_unit.value,
                "amount": str(fee.amount),
                "amount_cents": fee.amount_cents,
                "is_rebate": fee.is_rebate,
                "routing_destination": fee.routing_destination,
                "tier_group": fee.tier_group,
                "tier_number": fee.tier_number,
                "conditions": fee.conditions,
                "effective_date": str(fee.effective_date) if fee.effective_date else None,
                "section_ref": fee.section_ref,
                "notes": fee.notes,
                "volume_tier": fee.volume_tier,
                "exchange_fee_code": fee.exchange_fee_code,
                "exchange_fee_name": fee.exchange_fee_name,
            }
            normalized.append(entry)

        result = {
            "exchange_code": exchange_code,
            "fee_count": len(normalized),
            "effective_date": str(schedule.effective_date)
            if schedule.effective_date
            else None,
            "fees": normalized,
        }

        return {
            "content": [{"type": "text", "text": json.dumps(result, default=str)}]
        }
    except Exception as e:
        logger.error(f"normalize_fees failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }
