import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from backend.config import Settings
from backend.database import Base, make_engine
from backend.safety import models


@pytest.fixture
def config(tmp_path):
    return Settings(_env_file=None, DATA_DIR=tmp_path, DATABASE_URL=f'sqlite+aiosqlite:///{tmp_path / "test.db"}', SAFETY_CALL_GRACE_SECONDS=1)


@pytest_asyncio.fixture
async def factory(config):
    engine = make_engine(config.DATABASE_URL)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
