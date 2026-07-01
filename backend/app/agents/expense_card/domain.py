"""법인카드 지출 도메인 지식 — 예산단위/계정/적요 매핑(사용자 제공 규칙 이식).

ninebell-bak `erp/graph.py` 의 `_BUDGET_MAP`·`_REMARK_MAP`·정규화/역추론 헬퍼를 순수 함수로
분리 이식했다. 브라우저·네트워크 의존이 없어 단위테스트가 쉽다(page 없이 검증 가능).

⚠ 검증 수준: '야근식대'(석식) 경로만 라이브 확인됨. 나머지 매핑은 규칙 기반(미검증) —
   실패는 tools 계층에서 best-effort + ask 로 흡수한다.
"""

from __future__ import annotations

import re

# 사용항목 → (예산단위 팝업 검색어, 예산계정명 매칭 부분문자열). '야근식대'(석식)만 라이브 검증됨.
BUDGET_MAP: dict[str, tuple[str, str]] = {
    "야근식대": ("석식", "복리후생비-석식"),
    "휴일식대": ("석식", "복리후생비-석식"),
    "회식": ("회식", "복리후생비-회식"),
    "국내출장": ("국내출장", "여비교통비-국내출장"),
    "주차료": ("국내출장", "여비교통비-국내출장"),
    "출장식대": ("국내출장", "여비교통비-국내출장"),
    "해외출장": ("해외출장", "여비교통비-해외출장"),
    "유류": ("유류", "차량유지비-유류"),
    "업무추진비": ("업무", "복리후생비-업무"),
    "사무용품비": ("사무용품", "사무용품비"),
    "접대비": ("접대비", "접대비"),
    "해외접대비": ("해외접대", "해외접대비"),
    "대리운전비": ("기타", "여비교통비-기타"),
    "하이패스": ("기타", "여비교통비-기타"),
    "중식식대": ("중식", "복리후생비-중식"),
    "직원조식": ("조식", "복리후생비-조식"),
    "직원간식": ("간식", "복리후생비-간식"),
    "우편물발송": ("통신", "통신비"),
}

# 사용항목 → 적요(법인카드 접미사). 없으면 '{사용항목}(법인카드)' 폴백.
REMARK_MAP: dict[str, str] = {
    "야근식대": "직원 야근 식대(법인카드)",
    "휴일식대": "직원 휴일 식대(법인카드)",
    "회식": "직원 회식(법인카드)",
    "주차료": "국내출장 주차료(법인카드)",
    "업무추진비": "업무추진비(법인카드)",
}


def norm_item(s: object) -> str:
    """사용항목/부서/계정 매칭용 정규화 — 공백·_·-·/·괄호 제거 + 소문자."""
    return re.sub(r"[\s_\-/()]+", "", str(s or "").lower())


def budget_for(use_item: str) -> tuple[str, str] | None:
    """사용항목에 대응하는 (검색어, 예산계정 부분문자열). 정규화 매칭. 없으면 None."""
    return next((v for k, v in BUDGET_MAP.items() if norm_item(k) == norm_item(use_item)), None)


def remark_for(use_item: str) -> str:
    """사용항목 → 적요. 커스텀 매핑 우선, 없으면 '{사용항목}(법인카드)' 폴백."""
    for k, v in REMARK_MAP.items():
        if norm_item(k) == norm_item(use_item):
            return v
    return f"{use_item}(법인카드)"


def use_item_from_remark(remark: str) -> str | None:
    """적요에서 사용항목 역추론(옛 템플릿 보정용).

    예: '중식식대(법인카드)' → '중식식대'. REMARK_MAP 커스텀 적요도 역매핑.
    """
    r = (remark or "").strip()
    if not r:
        return None
    for k, v in REMARK_MAP.items():  # 커스텀 적요 역매핑
        if norm_item(v) == norm_item(r):
            return k
    if r.endswith("(법인카드)"):  # 기본 패턴 "{사용항목}(법인카드)"
        cand = r[: -len("(법인카드)")].strip()
        if any(norm_item(k) == norm_item(cand) for k in BUDGET_MAP):
            return cand
    return None
