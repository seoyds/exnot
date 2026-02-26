"""Seed the database with all exchange definitions from YAML files."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from exnot.db.engine import AsyncSessionLocal
from exnot.db.repositories import ExchangeRepository
from exnot.exchanges.registry import get_all_exchanges


async def seed():
    print("Seeding exchanges from YAML definitions...")
    exchanges = get_all_exchanges()
    print(f"Found {len(exchanges)} exchange definitions")

    async with AsyncSessionLocal() as session:
        repo = ExchangeRepository(session)
        for exchange in exchanges:
            result = await repo.upsert(exchange)
            status = "updated" if result.id else "created"
            active = "ACTIVE" if exchange.is_active else "INACTIVE"
            print(f"  [{active}] {exchange.code}: {exchange.name} ({exchange.operator})")

        await session.commit()

    print(f"\nDone! {len(exchanges)} exchanges seeded.")


if __name__ == "__main__":
    asyncio.run(seed())
