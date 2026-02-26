from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from exnot.config import get_settings


def get_async_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)


def get_sync_engine():
    settings = get_settings()
    return create_engine(settings.database_url_sync, echo=False, pool_pre_ping=True)


async_engine = get_async_engine()
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


def get_sync_session() -> Session:
    engine = get_sync_engine()
    session_factory = sessionmaker(bind=engine)
    return session_factory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
