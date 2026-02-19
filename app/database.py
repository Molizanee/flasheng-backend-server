import ssl

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


_engine = None
_async_session = None


def get_engine():
    global _engine
    if _engine is None:
        from app.config import get_settings

        settings = get_settings()

        # Supabase (and most cloud PostgreSQL) requires SSL.
        # Create a permissive SSL context so asyncpg can connect.
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=280,
            connect_args={"ssl": ssl_context},
        )
    return _engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session


async def get_db() -> AsyncSession:
    session_factory = get_async_session()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
