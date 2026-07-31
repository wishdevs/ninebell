"""Async SQLAlchemy 엔진/세션 관리.

엔진은 모듈 전역에 1회 초기화(`init_engine`)하고 `get_db` 의존성이 세션을 제공한다.
테스트는 `init_engine("sqlite+aiosqlite://...")` 로 인메모리 DB 를 주입할 수 있다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
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
    if make_url(database_url).get_backend_name() == "sqlite":
        # SQLite(aiosqlite — 테스트/로컬): QueuePool 노브 미적용(기존 동작 불변).
        _engine = create_async_engine(database_url, echo=echo, pool_pre_ping=True, future=True)
    else:
        # PG: 풀을 settings 로 명시한다. 기본(5+10)은 SSE 장기 점유·동시 실행이 겹치면
        # 고갈되고, pool_timeout 초과 시 대기 요청이 TimeoutError 로 죽는다.
        s = _pool_settings()
        _engine = create_async_engine(
            database_url,
            echo=echo,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_timeout=s.db_pool_timeout,
            pool_pre_ping=s.db_pool_pre_ping,
            future=True,
        )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def _pool_settings():
    """풀 노브 지연 로드 — 모듈 임포트 시점의 config 순환/조기 평가를 피한다."""
    from app.config import get_settings

    return get_settings()


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
