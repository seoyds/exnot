from claude_agent_sdk import create_sdk_mcp_server

from exnot.agents.tools.diffing import detect_changes
from exnot.agents.tools.discovery import search_fee_urls
from exnot.agents.tools.exchange import load_exchange, load_exchange_prompt
from exnot.agents.tools.normalization import normalize_fees
from exnot.agents.tools.notifications import send_notifications
from exnot.agents.tools.parsing import parse_document
from exnot.agents.tools.persistence import save_scraped_document, save_snapshot
from exnot.agents.tools.profiles import save_profile, try_profile_extract
from exnot.agents.tools.scraping import check_document_changed, scrape_document


def create_tools_server():
    """Create the ExNot MCP tools server with all pipeline tools."""
    return create_sdk_mcp_server(
        name="exnot",
        tools=[
            # Exchange loading
            load_exchange,
            load_exchange_prompt,
            # URL discovery
            search_fee_urls,
            # Document scraping
            scrape_document,
            check_document_changed,
            # Document parsing
            parse_document,
            # Profile extraction
            try_profile_extract,
            save_profile,
            # Fee normalization
            normalize_fees,
            # Change detection
            detect_changes,
            # DB persistence
            save_snapshot,
            save_scraped_document,
            # Notifications
            send_notifications,
        ],
    )
