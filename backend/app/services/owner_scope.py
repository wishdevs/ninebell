"""소유자 스코프 단건 조회 공용 헬퍼 — uuid 파싱 → (id, user_id) where → 없으면 None.

me_codes 의 즐겨찾기 삭제·기본지정·개입학습 삭제 3중복(uuid 파싱 try/except → 소유자 where
→ 404)을 단일화. 라우터는 None 을 받아 자기 문구로 404 를 반환한다(무효 id·미존재·소유자
불일치 모두 같은 404 — 존재 자체를 숨긴다).
"""

from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")


async def get_owned_or_none(
    db: AsyncSession, model: type[ModelT], raw_id: str, user_id: uuid.UUID
) -> ModelT | None:
    """uuid PK `id` + `user_id` 컬럼을 가진 모델의 소유자 스코프 단건 조회.

    raw_id 가 uuid 형식이 아니거나, 행이 없거나, 소유자가 다르면 None.
    """
    try:
        parsed = uuid.UUID(raw_id)
    except ValueError:
        return None
    return (
        await db.execute(select(model).where(model.id == parsed, model.user_id == user_id))
    ).scalar_one_or_none()
