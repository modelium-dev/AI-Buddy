"""Подключение к БД. PostgreSQL в Docker, SQLite в тестах."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Наивное UTC-время: одинаково ведёт себя в SQLite и PostgreSQL."""
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return uuid4().hex


class Database:
    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.sessionmaker: async_sessionmaker[AsyncSession] | None = None

    def init(self, url: str) -> None:
        kwargs: dict = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite+aiosqlite://", "sqlite+aiosqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool
        self.engine = create_async_engine(url, **kwargs)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        from app import models  # noqa: F401  (регистрирует таблицы)

        assert self.engine is not None
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        assert self.engine is not None
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()

    def session(self) -> AsyncSession:
        if self.sessionmaker is None:
            raise RuntimeError("База данных не инициализирована")
        return self.sessionmaker()


database = Database()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session
