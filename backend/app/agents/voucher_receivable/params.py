"""전표조회승인(voucher-receivable) 실행 전 파라미터 — 최소 스키마.

이 화면의 조회 조건은 대부분 고정(회계단위=나인벨·회계일=당월·전표상태=미결·전자결재상태=저장·
전표유형=국내/해외매출)이라 사용자 입력이 거의 없다. 유일한 파라미터는 **한 실행에서 처리할
행 수(max_rows)** 다.

사용자 결정 2026-07-21: **기본 전체 진행**(조회된 전 건을 순회). `max_rows` 를 명시(양수)하면
그 수만큼만 처리한다(테스트/부분처리용). 이전의 단건/3건 게이트·`allow_batch` 는 제거했다.
⚠ 절대 안전은 불변 — 이 에이전트는 결제창을 열어 **가상 상신 로그만** 남기고 닫으며, 실제
상신·보관은 어떤 경우에도 클릭하지 않는다(nodes/approvals.py).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError


class VoucherReceivableParams(BaseModel):
    """`params["voucher"]`(또는 flat params) — 처리 행 수.

    max_rows  한 실행에서 순회할 최대 행 수. **None(기본) = 전체**(조회된 전 건).
              양수를 주면 그 수만큼만(부분 처리·테스트용). 0 이하는 거부.
    """

    max_rows: int | None = Field(default=None, ge=1)


def parse_voucher_params(params: dict | None) -> VoucherReceivableParams:
    """실행 전 폼 params → VoucherReceivableParams(검증).

    ``params["voucher"]`` 중첩 dict 를 우선 읽고, 없으면 top-level 에서 max_rows 를 읽는다.
    아무것도 없으면 max_rows=None(전체). 실패는 한국어 ValueError(그래프 진입 노드가 단락).
    (구 allow_batch 등 다른 키는 무시된다.)
    """
    raw = params or {}
    src: Any = raw.get("voucher") if isinstance(raw.get("voucher"), dict) else raw
    fields = {k: src[k] for k in ("max_rows",) if isinstance(src, dict) and k in src}
    try:
        return VoucherReceivableParams.model_validate(fields)
    except ValidationError as exc:  # pydantic ValidationError 는 ValueError 서브클래스.
        raise ValueError(f"전표조회승인 실행 파라미터가 올바르지 않습니다: {exc}") from exc
