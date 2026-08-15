from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


settings = get_settings()
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Keep the development footprint below Supabase pooler limits.
    pool_size=2,
    max_overflow=0,
    pool_timeout=15,
    connect_args={"server_settings": {"application_name": "karunya-sparsham-api"}},
)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
