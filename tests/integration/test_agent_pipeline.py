"""Integration test for the Claude Agent SDK pipeline.

These tests require a valid Claude subscription via ~/.claude/ auth.
Run with: pytest tests/integration/ -v -s -m integration
"""

import pytest


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pipeline_imports():
    """Verify all pipeline components import correctly."""
    from exnot.agents.subagents import create_discovery_agent, create_extractor_agent, create_validator_agent
    from exnot.agents.tools.server import create_tools_server

    # Verify tools server creates without error
    server = create_tools_server()
    assert server is not None

    # Verify subagent factories work
    extractor = create_extractor_agent("CBOE")
    assert extractor.model == "sonnet"

    validator = create_validator_agent()
    assert validator.model == "haiku"

    discovery = create_discovery_agent()
    assert discovery.model == "haiku"
