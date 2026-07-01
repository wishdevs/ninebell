"""Async SQLAlchemy 엔진/세션 관리.

엔진은 모듈 전역에 1회 초기화(`init_engine`)하고 `get_db` 의존성이 세션을 제공한다.
테스트는 `init_engine("sqlite+aiosqlite://...")` 로 인메모리 DB 를 주입할 수 있다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """엔진/세션메이커를 (재)생성하고 반환한다."""
    global _engine, _sessionmaker
    _engine = create_async_engine(database_url, echo=echo, pool_pre_ping=True, future=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("DB engine not initialized — call init_engine() first")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("DB engine not initialized — call init_engine() first")
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 의존성 — 요청 범위 세션."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
