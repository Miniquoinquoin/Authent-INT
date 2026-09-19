import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    os.environ["DATABASE_URL"]
)
Session = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with Session() as s:
        yield s
