"""구매발주(purchase-order) 실행 전 파라미터 — 프로젝트 사전 선택.

실행 전 폼(`src/components/live/pre-run/purchase-order-pre-run-form.tsx`)이 기존 프로젝트
카탈로그(GET /me/catalog?kind=project)로 고른 프로젝트를 넘긴다:

    params["purchase_order"] = {project_no, project_name, keyword}

  project_no    옴니솔 도움창 PJT_NO(카탈로그 code 'PJT_NO|WBS_NO' 의 앞부분).
  project_name  표시·검증용 전체 이름(적용 후 필드 반영 로그에 쓴다).
  keyword       ERP 도움창 검색어. 미지정이면 project_name 의 **콤마 앞 토큰**으로 유도한다
                (프로브 검증 경로 — 전체 이름으로는 도움창이 0건을 돌려주는 사례가 있다).

셋 다 없으면(=폼 없이 실행) 종전대로 pick_project 가 HITL 검색 개입을 띄운다 — 사전 선택은
**개입을 건너뛰는 지름길**일 뿐이고, 적용에 실패하면 같은 개입으로 폴백한다(nodes/pick_project).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError, field_validator, model_validator

#: 도움창 검색어 상한 — pick_project.MAX_QUERY_LEN 과 같은 값(입력 경로가 둘이라 각자 자른다).
MAX_KEYWORD_LEN = 50


class PurchaseOrderParams(BaseModel):
    """프로젝트 사전 선택(전부 optional — 없으면 HITL 검색 개입)."""

    project_no: str | None = None
    project_name: str | None = None
    keyword: str | None = None

    @field_validator("project_no", "project_name", "keyword", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @model_validator(mode="after")
    def _derive_keyword(self) -> PurchaseOrderParams:
        """keyword 미지정 시 project_name 의 콤마 앞 토큰으로 유도하고, 상한으로 자른다."""
        kw = self.keyword
        if not kw and self.project_name:
            kw = self.project_name.split(",")[0].strip() or None
        if kw:
            kw = kw[:MAX_KEYWORD_LEN]
        object.__setattr__(self, "keyword", kw)
        return self

    @property
    def has_preselection(self) -> bool:
        """사전 선택으로 개입을 건너뛸 수 있는가 — 코드와 검색어가 모두 있어야 한다."""
        return bool(self.project_no and self.keyword)


def parse_purchase_order_params(params: dict | None) -> PurchaseOrderParams:
    """실행 전 폼 params → PurchaseOrderParams. 중첩(params["purchase_order"]) / flat 둘 다 수용.

    실패는 한국어 ValueError(호출 노드가 error 프레임으로 승격). 다른 키는 무시된다.
    """
    raw = params or {}
    src: Any = raw.get("purchase_order") if isinstance(raw.get("purchase_order"), dict) else raw
    keys = ("project_no", "project_name", "keyword")
    fields = {k: src[k] for k in keys if isinstance(src, dict) and k in src}
    try:
        return PurchaseOrderParams.model_validate(fields)
    except ValidationError as exc:  # pydantic ValidationError 는 ValueError 서브클래스.
        raise ValueError(f"구매발주 실행 파라미터가 올바르지 않습니다: {exc}") from exc
