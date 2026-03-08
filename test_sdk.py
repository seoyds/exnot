"""Simple test script for claude-agent-sdk."""

import asyncio
import os

# Prevent nested session error
os.environ.pop("CLAUDECODE", None)

from claude_agent_sdk import ClaudeAgentOptions, query


async def main():
    options = ClaudeAgentOptions(
        model="haiku",
    )

    print("Sending prompt to Claude via SDK...")
    async for message in query(prompt="Say hello in one sentence.", options=options):
        msg_type = type(message).__name__
        print(f"[{msg_type}] {message}")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
