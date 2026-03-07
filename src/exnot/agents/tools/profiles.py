"""Profile extraction tools — try rules-based extraction and save profiles."""

import json
import logging

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)


@tool(
    "try_profile_extract",
    "Attempt rules-based fee extraction using a stored profile for the exchange. "
    "If a profile exists and the document structure matches, extracts fees with "
    "zero AI cost. Returns extracted fees or indicates no matching profile found.",
    {"exchange_code": str},
)
async def try_profile_extract(args):
    try:
        from exnot.agents.tools.scraping import get_cached_document
        from exnot.db.engine import AsyncSessionLocal
        from exnot.db.repositories import ExchangeProfileRepository, ExchangeRepository
        from exnot.profiles.extractor import extract_all_from_profile
        from exnot.profiles.fingerprint import compare_fingerprints, fingerprint_all_tables

        exchange_code = args["exchange_code"]

        # Get cached document
        cached = get_cached_document(exchange_code)
        if not cached:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"matched": False, "reason": "No cached document available"}
                        ),
                    }
                ]
            }

        # Parse the document to get tables
        content_bytes = cached["content_bytes"]
        content_type = cached.get("content_type", "text/html")

        if "pdf" in content_type:
            from exnot.parser.pdf_parser import PdfParser

            parser = PdfParser()
        elif "csv" in content_type:
            from exnot.parser.csv_parser import CsvParser

            parser = CsvParser()
        else:
            from exnot.parser.html_parser import HtmlParser

            parser = HtmlParser()

        document = parser.extract(content_bytes)

        # Look up stored profile
        async with AsyncSessionLocal() as session:
            exchange_repo = ExchangeRepository(session)
            exchange = await exchange_repo.get_by_code(exchange_code)
            if not exchange:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"matched": False, "reason": "Exchange not found in DB"}
                            ),
                        }
                    ]
                }

            profile_repo = ExchangeProfileRepository(session)
            profile = await profile_repo.get_by_exchange_id(exchange.id)

            if not profile or not profile.table_mappings:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"matched": False, "reason": "No stored profile found"}
                            ),
                        }
                    ]
                }

            # Compare fingerprints
            stored_fps = profile.table_fingerprints or {}
            current_fps = fingerprint_all_tables(document.tables)
            comparison = compare_fingerprints(stored_fps, current_fps)

            if not comparison.all_match:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "matched": False,
                                    "reason": "Document structure has changed",
                                    "changed_ratio": comparison.changed_ratio,
                                    "changed_indices": comparison.changed_indices,
                                    "new_indices": comparison.new_indices,
                                }
                            ),
                        }
                    ]
                }

            # Extract using profile mappings
            fees = extract_all_from_profile(document.tables, profile.table_mappings)

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "matched": True,
                                "fee_count": len(fees),
                                "fees": fees,
                            },
                            default=str,
                        ),
                    }
                ]
            }
    except Exception as e:
        logger.error(f"try_profile_extract failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }


@tool(
    "save_profile",
    "Save an extraction profile for the exchange, built from AI extraction results. "
    "The profile enables zero-cost rules-based extraction on subsequent runs if the "
    "document structure is unchanged. Pass the AI-extracted fees as a JSON string.",
    {"exchange_code": str, "fees_json": str},
)
async def save_profile(args):
    try:
        from exnot.agents.tools.scraping import get_cached_document
        from exnot.db.engine import AsyncSessionLocal
        from exnot.db.models import ExchangeProfile, ProfileStatus
        from exnot.db.repositories import ExchangeProfileRepository, ExchangeRepository
        from exnot.profiles.builder import ProfileBuilder

        exchange_code = args["exchange_code"]
        fees = json.loads(args["fees_json"])

        # Get cached document and parse it
        cached = get_cached_document(exchange_code)
        if not cached:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"error": "No cached document available for profile building"}
                        ),
                    }
                ]
            }

        content_bytes = cached["content_bytes"]
        content_type = cached.get("content_type", "text/html")

        if "pdf" in content_type:
            from exnot.parser.pdf_parser import PdfParser

            parser = PdfParser()
        elif "csv" in content_type:
            from exnot.parser.csv_parser import CsvParser

            parser = CsvParser()
        else:
            from exnot.parser.html_parser import HtmlParser

            parser = HtmlParser()

        document = parser.extract(content_bytes)

        # Build profile from AI fees
        builder = ProfileBuilder()
        build_result = builder.build(document.tables, fees)

        if build_result.match_ratio < 0.3:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "saved": False,
                                "reason": "Match ratio too low for reliable profile",
                                "match_ratio": build_result.match_ratio,
                                "matched_fees": build_result.matched_fees,
                                "total_fees": build_result.total_fees,
                            }
                        ),
                    }
                ]
            }

        # Save to DB
        async with AsyncSessionLocal() as session:
            exchange_repo = ExchangeRepository(session)
            exchange = await exchange_repo.get_by_code(exchange_code)
            if not exchange:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": "Exchange not found in DB"}),
                        }
                    ]
                }

            profile_repo = ExchangeProfileRepository(session)
            existing = await profile_repo.get_by_exchange_id(exchange.id)

            if existing:
                existing.table_mappings = build_result.table_mappings
                existing.table_fingerprints = build_result.table_fingerprints
                existing.extraction_stats = build_result.extraction_stats
                existing.match_confidence = build_result.match_ratio
                existing.status = ProfileStatus.ACTIVE
                await profile_repo.update(existing)
            else:
                profile = ExchangeProfile(
                    exchange_id=exchange.id,
                    table_mappings=build_result.table_mappings,
                    table_fingerprints=build_result.table_fingerprints,
                    extraction_stats=build_result.extraction_stats,
                    match_confidence=build_result.match_ratio,
                    status=ProfileStatus.ACTIVE,
                )
                await profile_repo.create(profile)

            await session.commit()

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "saved": True,
                            "match_ratio": build_result.match_ratio,
                            "matched_fees": build_result.matched_fees,
                            "total_fees": build_result.total_fees,
                            "table_mappings_count": len(build_result.table_mappings),
                        }
                    ),
                }
            ]
        }
    except Exception as e:
        logger.error(f"save_profile failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }
