"""Database connection and async session management."""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import get_settings


import urllib.parse


def get_async_database_url(url: str) -> str:
    """Normalizes database URL to use async drivers and cleans asyncpg-incompatible query parameters."""
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)

    if "postgresql+asyncpg://" in url and "?" in url:
        base_url, query_str = url.split("?", 1)
        params = urllib.parse.parse_qs(query_str)
        # asyncpg does not accept psycopg2-specific parameters like 'sslmode' or 'channel_binding'
        new_params = {}
        for k, v in params.items():
            if k == "sslmode":
                new_params["ssl"] = v[0]
            elif k in ("channel_binding",):
                continue
            else:
                new_params[k] = v[0]
        if "ssl" not in new_params and "sslmode" in query_str:
            new_params["ssl"] = "require"
        new_query = urllib.parse.urlencode(new_params)
        url = f"{base_url}?{new_query}" if new_query else base_url

    return url


settings = get_settings()
db_url = get_async_database_url(settings.DATABASE_URL)

engine_kwargs = {"echo": settings.DEBUG}
if "sqlite" in db_url:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 10

engine: AsyncEngine = create_async_engine(db_url, **engine_kwargs)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for yielding an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
