from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.db.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# SQLite default busy_timeout is 0 → instant "database is locked" under concurrent jobs.
_SQLITE_BUSY_TIMEOUT_MS = 30_000


def _build_url(database_path: Path) -> str:
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    cursor.close()


async def init_db(database_path: Path) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    database_path.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_async_engine(_build_url(database_path), echo=False)
    event.listen(_engine.sync_engine, "connect", _configure_sqlite)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database is not initialized")
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
