"""유형별 전표조회 승인(voucher-by-type) 실행 전 파라미터 — 최소 스키마.

이 화면의 조회 조건은 대부분 고정(회계단위=나인벨·전표상태=미결·전자결재상태=저장)이고,
사용자 입력은 네 가지다:
  max_rows                  한 실행에서 처리할 행 수.
  period_from / period_to   회계일 조회기간(실행 전 폼 입력, 기본값 = 당월 1일~말일).
  docu_types                전표유형 다중 선택(ERP 전체 62종 중 — 미지정 시 기본 3종).
  menu_filters              메뉴(MENU_NM) 필터 라벨 목록(미지정/빈 목록 = 필터 없음).

사용자 결정 2026-07-21: **기본 전체 진행**(조회된 전 건을 순회). `max_rows` 를 명시(양수)하면
그 수만큼만 처리한다(테스트/부분처리용). 이전의 단건/3건 게이트·`allow_batch` 는 제거했다.
⚠ 상신은 allow_submit 게이트 뒤에서만 실클릭한다(정책 전환 2026-08-07) — 보관은 절대 미클릭.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, ValidationError, field_validator

from app.agents.common.voucher_period import VoucherPeriodParams

from .steps import DOCU_TYPE_CHOICES

# 메뉴 필터 상한 — 관리자 설정 메뉴 목록(MAX_MENU_ITEMS)과 동일한 20.
MAX_MENU_FILTERS = 20


class VoucherReceivableParams(VoucherPeriodParams):
    """`params["voucher"]`(또는 flat params) — 처리 행 수 + 회계일 기간(상속) + 유형/메뉴 선택.

    max_rows      한 실행에서 순회할 최대 행 수. **None(기본) = 전체**(조회된 전 건).
                  양수를 주면 그 수만큼만(부분 처리·테스트용). 0 이하는 거부.
    docu_types    전표유형 라벨 목록(DOCU_TYPE_CHOICES 62종의 부분집합, 중복 제거·순서 유지).
                  None(기본) = 그래프 빌드 기본값(전체 3종). 빈 목록은 거부.
    menu_filters  메뉴(MENU_NM) 라벨 목록 — 이 중 하나와 일치하는 행만 결재 대상.
                  None/빈 목록 = 필터 없음(전 행 대상). 항목 공백 제거·중복 제거·최대 20개.
    """

    max_rows: int | None = Field(default=None, ge=1)
    docu_types: list[str] | None = None
    menu_filters: list[str] | None = None

    @field_validator("docu_types", mode="before")
    @classmethod
    def _validate_docu_types(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("전표유형은 목록이어야 합니다.")
        out: list[str] = []
        seen: set[str] = set()
        for item in v:
            label = str(item or "").strip()
            if label not in DOCU_TYPE_CHOICES:
                # 허용값이 62종이라 전량 나열은 메시지를 못 읽게 만든다 — 앞 몇 개 + 총수만.
                head = "·".join(DOCU_TYPE_CHOICES[:6])
                raise ValueError(
                    f"지원하지 않는 전표유형입니다: {item!r} "
                    f"(허용 {len(DOCU_TYPE_CHOICES)}종 — {head} 등)"
                )
            if label not in seen:
                seen.add(label)
                out.append(label)
        if not out:
            raise ValueError("전표유형을 1개 이상 선택하세요.")
        return out

    @field_validator("menu_filters", mode="before")
    @classmethod
    def _validate_menu_filters(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("메뉴 필터는 목록이어야 합니다.")
        out: list[str] = []
        seen: set[str] = set()
        for item in v:
            label = str(item or "").strip()
            if not label:
                raise ValueError("메뉴 필터에 빈 항목이 있습니다.")
            if label not in seen:
                seen.add(label)
                out.append(label)
        if len(out) > MAX_MENU_FILTERS:
            raise ValueError(f"메뉴 필터는 최대 {MAX_MENU_FILTERS}개까지 지정할 수 있습니다.")
        # 빈 목록 = 필터 없음(계약: absent OR empty → 미필터) — None 으로 정규화.
        return out or None


def parse_voucher_params(params: dict | None) -> VoucherReceivableParams:
    """실행 전 폼 params → VoucherReceivableParams(검증).

    ``params["voucher"]`` 중첩 dict 를 우선 읽고, 없으면 top-level 에서 읽는다. 아무것도 없으면
    max_rows=None(전체)·기간 미지정(화면 기본 당월)·전표유형/메뉴 미지정. 실패는 한국어
    ValueError(그래프 진입 노드가 단락). (구 allow_batch 등 다른 키는 무시된다.)
    """
    raw = params or {}
    src: Any = raw.get("voucher") if isinstance(raw.get("voucher"), dict) else raw
    keys = ("max_rows", "period_from", "period_to", "docu_types", "menu_filters")
    fields = {k: src[k] for k in keys if isinstance(src, dict) and k in src}
    # debug 는 runs.py 가 **최상위** 에 정규화해 넣는 권위 키 — 중첩(voucher)이 아니라 raw 에서 읽는다.
    fields["debug"] = raw.get("debug") is True
    try:
        return VoucherReceivableParams.model_validate(fields)
    except ValidationError as exc:  # pydantic ValidationError 는 ValueError 서브클래스.
        raise ValueError(f"전표조회승인 실행 파라미터가 올바르지 않습니다: {exc}") from exc
