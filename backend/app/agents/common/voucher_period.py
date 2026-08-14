"""회계일 조회기간(period_from~period_to) — 전표 3종 공용 파라미터 조각.

외상매출금·외상매입금·미지급금 법인카드는 조회 조건이 대부분 고정이고, 사용자가 고르는 값은
**회계일 기간** 하나다. 실행 전 폼이 시작일·종료일을 'YYYY-MM-DD'(또는 'YYYYMMDD')로 보내면
여기서 YYYYMMDD 로 정규화·검증해 각 에이전트 params 모델에 얹는다.

규칙:
  - 둘 다 None = 미지정 → 종전 동작(화면 기본값 당월) 그대로. 폼 없이 실행하던 경로 무영향.
  - 한쪽만 지정은 거부 — 반쪽 기간으로 의도와 다른 범위를 조회/결재하는 사고를 막는다.
  - 시작일 > 종료일 거부.
  - 월 전체가 아닌 부분 기간(예: 7/1~7/5)도 정상 입력이다.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from pydantic import BaseModel, field_validator, model_validator


def normalize_ymd(value: Any) -> str:
    """'YYYY-MM-DD' / 'YYYYMMDD' → 'YYYYMMDD'(실재 날짜 검증 포함). 실패는 한국어 ValueError."""
    digits = str(value).replace("-", "").strip()
    if len(digits) != 8 or not digits.isdigit():
        raise ValueError("회계일은 'YYYY-MM-DD' 형식이어야 합니다.")
    try:
        date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError as exc:  # 2026-02-30 같은 없는 날짜.
        raise ValueError(f"회계일 '{value}' 는 존재하지 않는 날짜입니다.") from exc
    return digits


def month_range(year: int, month: int) -> tuple[str, str]:
    """해당 월의 1일~말일 (YYYYMMDD, YYYYMMDD)."""
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}{month:02d}01", f"{year:04d}{month:02d}{last:02d}"


def current_month_range(today: date | None = None) -> tuple[str, str]:
    """당월 1일~말일 — 폼 기본값(서버 기준)과 '당월 여부' 판정에 쓴다."""
    d = today or date.today()
    return month_range(d.year, d.month)


def is_current_month_range(start: str, end: str, today: date | None = None) -> bool:
    """주어진 기간이 정확히 당월 1일~말일인가 — 맞으면 검증된 setMonth() 경로를 쓸 수 있다."""
    return (start, end) == current_month_range(today)


class VoucherPeriodParams(BaseModel):
    """회계일 기간(둘 다 None = 화면 기본값 당월). 전표 3종 params 모델이 상속한다.

    period_from  조회 시작일 'YYYYMMDD'(입력은 'YYYY-MM-DD' 도 수용).
    period_to    조회 종료일 'YYYYMMDD'.
    """

    period_from: str | None = None
    period_to: str | None = None
    # 디버그 모드(로그인 체크박스 → runs.py 가 params["debug"] 로 주입, 최상위 키).
    # True 면 voucher 계열 loop_approvals 가 상신 게이트를 런타임에 닫는다(가상 상신).
    debug: bool = False

    @field_validator("period_from", "period_to", mode="before")
    @classmethod
    def _normalize(cls, v: Any) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return normalize_ymd(v)

    @model_validator(mode="after")
    def _check_pair(self) -> VoucherPeriodParams:
        if (self.period_from is None) != (self.period_to is None):
            raise ValueError("회계일은 시작일·종료일을 함께 지정해야 합니다.")
        if self.period_from and self.period_to and self.period_from > self.period_to:
            raise ValueError("회계일 시작일이 종료일보다 늦을 수 없습니다.")
        return self

    @property
    def period_label(self) -> str:
        """로그용 표기 — 미지정이면 '당월', 아니면 'YYYY-MM-DD ~ YYYY-MM-DD'."""
        if not self.period_from or not self.period_to:
            return "당월"
        return f"{_dash(self.period_from)} ~ {_dash(self.period_to)}"


def _dash(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
