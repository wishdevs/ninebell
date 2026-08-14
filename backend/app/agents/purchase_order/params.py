"""구매발주(purchase-order) 실행 전 파라미터 — 프로젝트 사전 선택.

실행 전 폼(`src/components/live/pre-run/purchase-order-pre-run-form.tsx`)이 기존 프로젝트
카탈로그(GET /me/catalog?kind=project)로 고른 프로젝트를 넘긴다:

    params["purchase_order"] = {project_no, project_name, keyword}

  project_no    옴니솔 도움창 PJT_NO(카탈로그 code 'PJT_NO|WBS_NO' 의 앞부분).
                직접 입력 폼에선 생략 가능 — 검색 결과 1건일 때만 자동 특정(steps.apply_project).
  project_name  표시·검증용 전체 이름(적용 후 필드 반영 로그에 쓴다).
  keyword       ERP 도움창 검색어. 미지정이면 project_name 에서 유도하며, 지정/유도 모두
                **콤마·'#' 앞 토큰**으로 정화한다 — 진단 프로브 실측(2026-08-14):
                '#' 포함 검색('MISC-ESR3 #2')과 PJT_NO 숫자 검색은 **도움창 팝업을 죽인다**.
                'MISC-ESR3' 처럼 넓힌 검색 + PJT_NO 행 선택이 검증된 경로다.

keyword 가 없으면 pick_project 가 하드 실패한다 — 검색 개입 폴백은 제거됐다(2026-08-14
사용자 지시, 폼에서 이미 고른 것을 다시 고르게 하는 이중 입력 방지).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError, field_validator, model_validator

#: 도움창 검색어 상한 — pick_project.MAX_QUERY_LEN 과 같은 값(입력 경로가 둘이라 각자 자른다).
MAX_KEYWORD_LEN = 50


def sanitize_keyword(raw: str) -> str:
    """도움창 검색어 정화 — 콤마·'#' 앞 토큰 + 상한. '#' 은 팝업을 죽인다(프로브 실측)."""
    return raw.split(",")[0].split("#")[0].strip()[:MAX_KEYWORD_LEN]


class PurchaseOrderParams(BaseModel):
    """프로젝트 사전 선택 — keyword 필수(없으면 pick_project 하드 실패), project_no 권장."""

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
        """keyword 미지정 시 project_name 에서 유도 — 지정/유도 모두 sanitize_keyword 로 정화."""
        kw = self.keyword or self.project_name or ""
        object.__setattr__(self, "keyword", sanitize_keyword(kw) or None)
        return self

    @property
    def has_preselection(self) -> bool:
        """적용을 시작할 수 있는가 — 검색어만 있으면 된다(번호 없으면 단일 결과 자동 특정)."""
        return bool(self.keyword)


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
