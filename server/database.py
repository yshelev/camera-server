import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
)

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, echo=False)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False, 
)

async def get_db():
    async with async_session() as session:
        yield session