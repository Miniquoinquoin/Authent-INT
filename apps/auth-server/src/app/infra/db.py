"""Async engine, sessionmaker, and the `get_db` dependency. Nothing else."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def ping() -> None:
    """Raise if Postgres is unreachable. Used by /health/ready."""
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text("select 1"))
