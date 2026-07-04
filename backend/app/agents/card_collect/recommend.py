"""카드 승인내역 그리드 프리필용 AI 추천 — 행별 예산단위·프로젝트 1회 배치 추천.

collect_rows 가 카드내역을 가져오면, 행마다 어떤 예산단위 조합·프로젝트가 가장 적합한지
Gemini 에게 한 번(배치)에 물어 confidence 와 함께 받는다. confidence 가 높으면 그 추천을,
낮으면 호출부가 기본지정(즐겨찾기) 폴백으로 프리필한다.

이 모듈은 gemini(common)만 재사용하며 브라우저·DB 를 건드리지 않는다. 키가 없거나 후보가
비면 즉시 {} 를 돌려주고, 어떤 예외도 로깅 후 {} 로 흡수한다(런을 죽이지 않는다).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.common.gemini import gemini_chat_decide

logger = logging.getLogger("app.agents.card_collect.recommend")

# 이 이상이면 AI 추천을 프리셀렉트로 채택, 미만이면 호출부가 기본지정 폴백.
RECOMMEND_CONFIDENCE_THRESHOLD = 0.7

# 프롬프트/컨텍스트 비대 방지 캡(nodes 후보 캡과 별개, 여기서 한 번 더 조인다).
_MAX_BUDGET_CANDIDATES = 120
_MAX_PROJECT_CANDIDATES = 60

_SYSTEM = (
    "당신은 법인카드 거래 내역을 회계 결의서에 정리하는 보조자입니다. "
    "각 거래 행마다 가장 적합한 예산단위 조합과 프로젝트를 아래 후보 목록에서 고르고, "
    "얼마나 확신하는지 confidence(0~1)로 매기세요. "
    "가맹점명·금액·부가세구분·적요 초안을 근거로 판단합니다. "
    "확신이 서지 않으면 낮은 confidence 를 매기고, 적당한 후보가 없으면 해당 코드를 null 로 두세요. "
    "budgetUnitCode·projectCode 는 반드시 제공된 후보의 code 값을 그대로 사용하고, 새로 만들지 마세요. "
    "행에 priorChoice(과거 사용자가 같은 가맹점에 확정했던 선택)가 있으면, 그 code 를 최우선으로 "
    "채택하고 confidence 를 높게 매기세요(사용자의 반복 판단이 가장 신뢰도 높은 근거입니다). "
    "모든 행에 대해 submit_recommendations 를 정확히 한 번 호출하세요."
)

_TOOLS: list[dict] = [
    {
        "name": "submit_recommendations",
        "description": "행별 예산단위·프로젝트 추천과 confidence 를 제출한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "no": {"type": "integer", "description": "거래 행 번호(1-based)"},
                            "budgetUnitCode": {
                                "type": "string",
                                "description": "후보 예산단위 code(없으면 빈 문자열)",
                            },
                            "projectCode": {
                                "type": "string",
                                "description": "후보 프로젝트 code(없으면 빈 문자열)",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "0~1 확신도",
                            },
                        },
                        "required": ["no", "confidence"],
                    },
                }
            },
            "required": ["recommendations"],
        },
    }
]


def _clamp01(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _code(v: Any) -> str:
    return str(v).strip() if v is not None else ""


async def recommend_selections(
    rows: list[dict],
    budget_candidates: list[dict],
    project_candidates: list[dict],
    *,
    http: Any,
    settings: Any,
) -> dict[int, dict]:
    """행별 예산단위·프로젝트 프리셀렉트 추천을 Gemini 1회 배치 호출로 받는다.

    rows 항목은 {no, merchant, amount, vatType, note} 형태(호출부가 준비). budget/project
    candidates 는 {code, ...} 목록. 반환은 {no: {budgetUnitCode, projectCode, confidence}}
    — 후보에 실재하지 않는 code 는 제거하고 no 범위·confidence 를 검증한다. 후보가 모두
    비었거나 키가 없거나 예외가 나면 {}.
    """
    if not rows:
        return {}
    if not budget_candidates and not project_candidates:
        return {}
    if not getattr(settings, "gemini_api_key", ""):
        return {}

    budget_codes = {_code(c.get("code")) for c in budget_candidates if _code(c.get("code"))}
    project_codes = {_code(c.get("code")) for c in project_candidates if _code(c.get("code"))}
    valid_nos = {r.get("no") for r in rows if isinstance(r.get("no"), int)}

    context = {
        "rows": [
            {
                "no": r.get("no"),
                "merchant": r.get("merchant") or "",
                "amount": r.get("amount") or "",
                "vatType": r.get("vatType") or "",
                "note": r.get("note") or "",
                # 과거 사용자가 이 가맹점에 확정했던 선택(개입 학습). 있으면 최우선 참고.
                **({"priorChoice": r["priorChoice"]} if r.get("priorChoice") else {}),
            }
            for r in rows
        ],
        "budgetCandidates": [
            {
                "code": _code(c.get("code")),
                "name": c.get("name") or "",
                "bizplanNm": c.get("bizplanNm") or "",
                "bgacctNm": c.get("bgacctNm") or "",
            }
            for c in budget_candidates[:_MAX_BUDGET_CANDIDATES]
        ],
        "projectCandidates": [
            {
                "code": _code(c.get("code")),
                "name": c.get("name") or "",
                "wbsNm": c.get("wbsNm") or "",
            }
            for c in project_candidates[:_MAX_PROJECT_CANDIDATES]
        ],
    }

    try:
        name, args = await gemini_chat_decide(
            http,
            settings.gemini_api_key,
            settings.gemini_model,
            settings.gemini_base_url,
            _SYSTEM,
            "",  # 대화 기록 없음(단발 배치 판단).
            context,
            None,  # 스크린샷 불필요.
            _TOOLS,
        )
    except Exception:  # noqa: BLE001 — 추천 실패는 런을 죽이지 않는다.
        logger.exception("card-collect recommend_selections gemini call failed")
        return {}

    if name != "submit_recommendations":
        return {}
    recs = args.get("recommendations")
    if not isinstance(recs, list):
        return {}

    out: dict[int, dict] = {}
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        no = rec.get("no")
        if isinstance(no, float) and no.is_integer():
            no = int(no)
        if not isinstance(no, int) or no not in valid_nos or no in out:
            continue
        budget_code = _code(rec.get("budgetUnitCode"))
        project_code = _code(rec.get("projectCode"))
        out[no] = {
            "budgetUnitCode": budget_code if budget_code in budget_codes else "",
            "projectCode": project_code if project_code in project_codes else "",
            "confidence": _clamp01(rec.get("confidence")),
        }
    return out
