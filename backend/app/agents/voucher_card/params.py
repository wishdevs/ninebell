"""미지급금 법인카드(voucher-card) 실행 전 파라미터 — 공유 스키마 + 회계일 기간.

공유(voucher_receivable)와 동일하게 조회 조건은 대부분 고정이라 사용자 입력이 거의 없다.
파라미터:
  max_rows                  한 실행에서 순회할 최대 행 수. None(기본) = 전체(사용자 결정).
  period_from / period_to   회계일 조회기간(상속). 미지정 = 화면 기본값(당월).
  accounting_ym             구 파라미터('YYYYMM'). 기간이 없을 때만 그 월의 1일~말일로
                            펼쳐 period_from/to 로 흡수한다(하위호환 — 신규 입력은 기간 사용).

⚠ 절대 안전은 불변 — 이 에이전트는 결제창을 열어 가상 상신 로그만 남기며, 참조문서 '확인'·
   실제 상신은 어떤 경우에도 클릭하지 않는다(기본 게이트).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, ValidationError, field_validator, model_validator

from app.agents.common.voucher_period import VoucherPeriodParams, month_range


class VoucherCardParams(VoucherPeriodParams):
    """`params["voucher"]`(또는 flat params) — 처리 행 수 + 회계일 기간(상속) + 구 월 override."""

    max_rows: int | None = Field(default=None, ge=1)
    accounting_ym: str | None = Field(default=None)

    @field_validator("accounting_ym")
    @classmethod
    def _normalize_ym(cls, v: str | None) -> str | None:
        if v is None:
            return None
        digits = str(v).replace("-", "").strip()
        if len(digits) != 6 or not digits.isdigit():
            raise ValueError("회계일(accounting_ym)은 'YYYYMM' 형식이어야 합니다.")
        month = int(digits[4:6])
        if not 1 <= month <= 12:
            raise ValueError("회계일(accounting_ym)의 월은 01~12 여야 합니다.")
        return digits

    @model_validator(mode="after")
    def _expand_ym(self) -> VoucherCardParams:
        """구 accounting_ym → 그 월의 1일~말일 기간으로 흡수(기간 미지정일 때만).

        하위 소비자는 period_from/period_to 한 경로만 본다 — 두 파라미터가 동시에 오면
        더 구체적인 기간을 남긴다(월 override 는 무시).
        """
        if self.accounting_ym and not self.period_from:
            start, end = month_range(int(self.accounting_ym[:4]), int(self.accounting_ym[4:6]))
            object.__setattr__(self, "period_from", start)
            object.__setattr__(self, "period_to", end)
        return self


def parse_voucher_card_params(params: dict | None) -> VoucherCardParams:
    """실행 전 폼 params → VoucherCardParams(검증). 중첩(params["voucher"]) / flat 둘 다 수용.

    실패는 한국어 ValueError(그래프 진입 노드가 단락). 구 allow_batch 등 다른 키는 무시된다.
    """
    raw = params or {}
    src: Any = raw.get("voucher") if isinstance(raw.get("voucher"), dict) else raw
    keys = ("max_rows", "accounting_ym", "period_from", "period_to")
    fields = {k: src[k] for k in keys if isinstance(src, dict) and k in src}
    try:
        return VoucherCardParams.model_validate(fields)
    except ValidationError as exc:  # pydantic ValidationError 는 ValueError 서브클래스.
        raise ValueError(f"미지급금 법인카드 실행 파라미터가 올바르지 않습니다: {exc}") from exc
