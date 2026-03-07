from claude_agent_sdk import create_sdk_mcp_server


def create_tools_server():
    """Create the ExNot MCP tools server with all pipeline tools."""
    return create_sdk_mcp_server(
        name="exnot",
        tools=[
            # Will be populated as tools are created:
            # load_exchange, load_exchange_prompt,
            # search_fee_urls,
            # scrape_document, check_document_changed,
            # parse_document,
            # try_profile_extract, save_profile,
            # normalize_fees,
            # detect_changes,
            # save_snapshot, save_scraped_document,
            # send_notifications,
        ],
    )
