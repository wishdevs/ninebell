"""SQLAlchemy 선언적 베이스 + 공용 믹스인/타입.

ax `db/base.py` 의 네이밍 컨벤션 이식. PostgreSQL 과 SQLite(테스트) 양쪽에서 동작하도록
이식성 있는 타입을 쓴다:
- UUID: `sqlalchemy.Uuid` (PG=native uuid, sqlite=CHAR(32))
- JSON: `JSON().with_variant(JSONB, "postgresql")` (PG=JSONB, sqlite=JSON)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, MetaData, func
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
