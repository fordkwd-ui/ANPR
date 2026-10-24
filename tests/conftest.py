"""Global test fixtures and environment overrides."""
import os
import shutil
import tempfile
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force test configuration
os.environ["STORAGE_DRIVER"] = "local"
test_storage_dir = tempfile.mkdtemp(prefix="anpr_test_media_")
os.environ["STORAGE_LOCAL_DIR"] = test_storage_dir
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from app.config import get_settings
from app.db.base import Base
import app.models  # Register all models with Base.metadata
from app.db.session import get_db
from app.main import create_app
from app.services.storage import get_storage
from app.services.storage.local import LocalStorageDriver

from sqlalchemy.pool import StaticPool

test_engine = create_async_engine(
    "sqlite+aiosqlite:///file:testmem?mode=memory&cache=shared&uri=true",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="session", autouse=True)
def cleanup_temp_storage():
    yield
    shutil.rmtree(test_storage_dir, ignore_errors=True)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a fresh isolated database schema per test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Test client bound to app with test DB override."""
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
