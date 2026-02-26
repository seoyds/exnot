"""Run initial scrape for all active exchanges."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from exnot.db.engine import AsyncSessionLocal
from exnot.db.repositories import ExchangeRepository


async def run():
    print("Starting initial scrape for all active exchanges...")
    print("NOTE: This requires Celery workers to be running.\n")

    async with AsyncSessionLocal() as session:
        repo = ExchangeRepository(session)
        exchanges = await repo.get_all(active_only=True)

        print(f"Found {len(exchanges)} active exchanges to scrape:\n")
        for ex in exchanges:
            print(f"  {ex.code}: {ex.name}")

    print("\nDispatching scrape tasks to Celery...")
    from exnot.workers.tasks import scrape_and_process_exchange

    for ex in exchanges:
        result = scrape_and_process_exchange.delay(ex.code)
        print(f"  Dispatched {ex.code} -> task_id={result.id}")

    print("\nAll tasks dispatched. Monitor progress in Celery Flower at http://localhost:5555")


if __name__ == "__main__":
    asyncio.run(run())
