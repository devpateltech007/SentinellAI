from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

import sys
from sqlalchemy.pool import NullPool

pool_args = {"poolclass": NullPool} if "celery" in sys.argv[0] else {"pool_size": 20, "max_overflow": 10}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    **pool_args
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
