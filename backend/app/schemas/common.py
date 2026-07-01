"""공용 pydantic 베이스 — camelCase 직렬화(프론트 TS 타입과 1:1)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
