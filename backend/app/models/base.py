"""SQLAlchemy 선언적 베이스 + 공용 믹스인/타입.

ax `db/base.py` 의 네이밍 컨벤션 이식. PostgreSQL 과 SQLite(테스트) 양쪽에서 동작하도록
이식성 있는 타입을 쓴다:
- UUID: `sqlalchemy.Uuid` (PG=native uuid, sqlite=CHAR(32))
- JSON: `JSON().with_variant(JSONB, "postgresql")` (PG=JSONB, sqlite=JSON)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, MetaData, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# PostgreSQL 에선 JSONB, 그 외(sqlite 테스트)에선 일반 JSON 으로 컴파일.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UuidPkMixin:
    """신규 도메인 테이블 기본 PK — 앱 생성 uuid4 surrogate 키(user.py 패턴의 공식화)."""

    # sort_order=-1: 믹스인 컬럼이 클래스 본문 컬럼 뒤로 밀리지 않고 기존 테이블처럼 첫 컬럼 유지.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, sort_order=-1
    )
