"""부가세구분(과세/불공) 분류 — 2패스 저장(증빙유형 01=과세 / 02=법인카드(불공))을 구동한다.

과세 거래라도 **매입세액 불공제** 대상이면 '불공'으로 분류한다. 규칙(우선순위):
  1. 예산계정이 불공 계정이면 불공(결정적) — 복리후생비-업무·여비교통비-해외출장·차량유지비-유류·접대비류.
  2. 가맹점 기반 불공(통행료·우체국·유류 등)은 AI(recommend)가 판정해 전달 → 그 값이 '불공'이면 불공.
  3. VAT_TP 가 '과세'가 아니면(빈칸·간이미발급 등) 불공(기존 2패스 규칙).
  4. 그 외 과세.
사용자가 그리드에서 최종값을 덮어쓸 수 있으며(예외 대비), 저장 파티션은 그 최종값을 쓴다.
"""

from __future__ import annotations

from .nodes.catalog import _acct_norm

TAXABLE = "과세"
NONDEDUCTIBLE = "불공"

# 예산계정명이 이 목록(정확일치)이면 과세여도 불공. (판)/(제)/공백/하이픈은 _acct_norm 이 흡수.
# 특정 세부계정이라 정확일치(복리후생비-'업무'만 불공, '석식'은 아님).
_NONDEDUCTIBLE_ACCTS = (
    "복리후생비-업무",
    "여비교통비-해외출장",
    "차량유지비-유류",
)
_NONDEDUCTIBLE_NORM = frozenset(_acct_norm(a) for a in _NONDEDUCTIBLE_ACCTS)
# 접대비 계열은 명칭 형태가 다양(접대비·접대비-국내/해외·해외접대비 등, 어순도 다름) → 부분일치로 전부 불공.
_NONDEDUCTIBLE_CONTAINS = ("접대비",)


def is_nondeductible_account(bgacct_nm: str | None) -> bool:
    """예산계정명이 불공(매입세액 불공제) 계정인지 — (판)/(제)·공백·하이픈 무시. 접대비 계열은 부분일치."""
    norm = _acct_norm(bgacct_nm)
    if not norm:
        return False
    if any(sub in norm for sub in _NONDEDUCTIBLE_CONTAINS):
        return True
    return norm in _NONDEDUCTIBLE_NORM


def classify_vat(vat_tp: str | None, bgacct_nm: str | None, ai_vat: str | None = None) -> str:
    """부가세구분 자동 분류 → '과세' 또는 '불공'.

    ai_vat: recommend AI 의 가맹점 기반 판정('불공'이면 강제 불공, 그 외 무시). 계정 불공이 최우선.
    """
    if is_nondeductible_account(bgacct_nm):
        return NONDEDUCTIBLE
    if (ai_vat or "").strip() == NONDEDUCTIBLE:
        return NONDEDUCTIBLE
    if (vat_tp or "").strip() == TAXABLE:
        return TAXABLE
    return NONDEDUCTIBLE
