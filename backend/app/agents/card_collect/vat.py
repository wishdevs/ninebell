"""부가세구분(과세/불공) 분류 — 2패스 저장(증빙유형 01=과세 / 02=법인카드(불공))을 구동한다.

과세 거래라도 **매입세액 불공제** 대상이면 '불공'으로 분류한다. 규칙(우선순위):
  1. 예산계정이 불공 계정이면 불공(결정적) — 복리후생비-업무·여비교통비-해외출장·여비교통비-기타·
     차량유지비-유류·차량유지비-관리·기부금·접대비류.
  2. 가맹점명이 통행료·우체국 등 불공 대상이면 불공 — **결정적 키워드**(is_nondeductible_merchant)로
     먼저 잡고, 놓친 변형은 AI(recommend)의 가맹점 판정('불공')이 보완한다.
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
    "여비교통비-기타",  # 사용자 지시 2026-09-02 — 기타(대리운전·하이패스 등)는 전부 불공.
    "차량유지비-유류",
    "차량유지비-관리",
    "기부금",
)
_NONDEDUCTIBLE_NORM = frozenset(_acct_norm(a) for a in _NONDEDUCTIBLE_ACCTS)
# 접대비 계열은 명칭 형태가 다양(접대비·접대비-국내/해외·해외접대비 등, 어순도 다름) → 부분일치로 전부 불공.
_NONDEDUCTIBLE_CONTAINS = ("접대비",)

# 가맹점명 기반 불공(결정적) — 통행료·우체국은 과세 표기여도 불공(사용자 규칙 2026-07-23).
# 통행료 사업자명이 다양(도로공사·하이패스·톨게이트·영업소 등)해 AI 판정으로 보완하되, 확실한
# 신호는 여기서 먼저 잡는다. 필요 시 이 목록을 조정한다(오검출은 substring 특성상 주의).
_NONDEDUCTIBLE_MERCHANT_KW = ("우체국", "통행료", "하이패스", "톨게이트", "도로공사")


def is_nondeductible_account(bgacct_nm: str | None) -> bool:
    """예산계정명이 불공(매입세액 불공제) 계정인지 — (판)/(제)·공백·하이픈 무시. 접대비 계열은 부분일치."""
    norm = _acct_norm(bgacct_nm)
    if not norm:
        return False
    if any(sub in norm for sub in _NONDEDUCTIBLE_CONTAINS):
        return True
    return norm in _NONDEDUCTIBLE_NORM


def is_nondeductible_merchant(merchant: str | None) -> bool:
    """가맹점명이 불공 대상(통행료·우체국 등)인지 — 결정적 키워드 부분일치."""
    m = str(merchant or "")
    return any(kw in m for kw in _NONDEDUCTIBLE_MERCHANT_KW)


def classify_vat(
    vat_tp: str | None,
    bgacct_nm: str | None,
    ai_vat: str | None = None,
    merchant: str | None = None,
) -> str:
    """부가세구분 자동 분류 → '과세' 또는 '불공'.

    merchant: 가맹점명 — 통행료·우체국 등이면 결정적 불공(규칙 2, AI 보다 우선·독립).
    ai_vat: recommend AI 의 가맹점 기반 판정('불공'이면 강제 불공, 그 외 무시) — 키워드가 놓친 변형 보완.
    계정 불공(규칙 1)이 최우선.
    """
    if is_nondeductible_account(bgacct_nm):
        return NONDEDUCTIBLE
    if is_nondeductible_merchant(merchant):
        return NONDEDUCTIBLE
    if (ai_vat or "").strip() == NONDEDUCTIBLE:
        return NONDEDUCTIBLE
    if (vat_tp or "").strip() == TAXABLE:
        return TAXABLE
    return NONDEDUCTIBLE
