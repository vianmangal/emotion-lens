from typing import AsyncGenerator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from backend.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url):
    parsed = make_url(url)
    if parsed.drivername != 'sqlite+aiosqlite':
        raise ValueError('Local operation requires sqlite+aiosqlite; export legacy databases separately.')
    if parsed.database and parsed.database != ':memory:':
        try:
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Leave connection lazy: lifespan can expose a storage warning while
            # retaining health/local camera warnings when this path is unusable.
            pass
    engine = create_async_engine(url, connect_args={'timeout': 10})

    @event.listens_for(engine.sync_engine, 'connect')
    def sqlite_config(connection, _):
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.close()
    return engine


engine = make_engine(settings.DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
