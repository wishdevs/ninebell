"""공용 pydantic 베이스 — camelCase 직렬화(프론트 TS 타입과 1:1) + 리스트 envelope 표준."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


ItemT = TypeVar("ItemT")


class ListOut(CamelModel, Generic[ItemT]):
    """전량 목록 표준 — 페이지네이션 없는 소규모 목록(즐겨찾기·조직구분·유저 등)."""

    items: list[ItemT]
    total: int  # len(items) — FE 가 배지 카운트 등에 사용.


class ListPage(ListOut[ItemT], Generic[ItemT]):
    """페이지 목록 표준 — {items,total,limit,offset}. me_codes.py:352 형태의 공식화."""

    limit: int
    offset: int
