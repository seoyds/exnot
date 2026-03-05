"""One-time migration: copy NormalizedFee.fee_code -> exchange_fee_code, fee_name -> exchange_fee_name."""

import asyncio

from sqlalchemy import update

from exnot.db.engine import AsyncSessionLocal as async_session
from exnot.db.models import NormalizedFee


async def migrate():
    async with async_session() as session:
        # Copy fee_code -> exchange_fee_code where exchange_fee_code is null
        stmt = (
            update(NormalizedFee)
            .where(NormalizedFee.exchange_fee_code.is_(None))
            .where(NormalizedFee.fee_code.isnot(None))
            .values(exchange_fee_code=NormalizedFee.fee_code)
        )
        result = await session.execute(stmt)
        print(f"Migrated {result.rowcount} fee_code -> exchange_fee_code")

        # Copy fee_name -> exchange_fee_name where exchange_fee_name is null
        stmt = (
            update(NormalizedFee)
            .where(NormalizedFee.exchange_fee_name.is_(None))
            .where(NormalizedFee.fee_name.isnot(None))
            .values(exchange_fee_name=NormalizedFee.fee_name)
        )
        result = await session.execute(stmt)
        print(f"Migrated {result.rowcount} fee_name -> exchange_fee_name")

        await session.commit()
        print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
