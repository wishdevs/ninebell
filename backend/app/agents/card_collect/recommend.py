"""카드 승인내역 그리드 프리필용 AI 추천 — 행별 예산단위·프로젝트 1회 배치 추천.

collect_rows 가 카드내역을 가져오면, 행마다 어떤 예산단위 조합·프로젝트가 가장 적합한지
Gemini 에게 한 번(배치)에 물어 confidence 와 함께 받는다. confidence 가 높으면 그 추천을,
낮으면 호출부가 기본지정(즐겨찾기) 폴백으로 프리필한다.

이 모듈은 gemini(common)만 재사용하며 브라우저·DB 를 건드리지 않는다. 키가 없거나 후보가
비면 즉시 {} 를 돌려주고, 어떤 예외도 로깅 후 {} 로 흡수한다(런을 죽이지 않는다).
"""

from __future__ import annotations

import asyncio

import logging
from typing import Any

from app.agents.common.llm import chat_decide, llm_ready

logger = logging.getLogger("app.agents.card_collect.recommend")

# 이 이상이면 AI 추천을 프리셀렉트로 채택, 미만이면 호출부가 기본지정 폴백.
# 0.7→0.6 완화(2026-07-23): AI 가 방향은 맞혔는데(예: Agoda→여비교통비-해외출장, conf 0.6)
# 임계값 미달로 버려져 엉뚱한 기본값(소모품비)으로 폴백되던 문제. 애매한 가맹점(PG 토큰
# 노이즈)에서도 AI 의 근거 있는 추천이 blind 기본값보다 낫다. ETRIBE(GLM)는 confidence 를
# 보수적으로 매겨(0.6~0.9) 0.7 에선 대부분 탈락하던 것도 함께 완화.
RECOMMEND_CONFIDENCE_THRESHOLD = 0.6

# 프롬프트/컨텍스트 비대 방지 캡(nodes 후보 캡과 별개, 여기서 한 번 더 조인다).
# ── 배치 분할(2026-07-27 사용자 리포트: 400행에서 추천이 통째로 실패) ─────────────
# 근본원인은 "LLM 이 헷갈린다"가 아니라 **출력 토큰 상한 초과**다:
#   결정 호출 상한 _DECIDE_MAX_TOKENS=4096(사고 토큰과 공유, 헤드룸 1024) 인데
#   행당 추천 JSON 이 약 45~60 토큰 → 400행이면 약 20,000 토큰이 필요하다.
#   응답이 잘리면(finish_reason=length) 툴콜 JSON 이 깨져 파싱 실패 → 전 행이 추천 없이 진행.
# 사고를 빼면 실제 가용 출력이 2,000~3,000 토큰이므로 30행(≈1,650 토큰)이 안전 마진을 포함한
# 적정값이다(사용자 확정). 25~40 사이면 무난하다.
RECOMMEND_CHUNK_SIZE = 30
# 청크 동시 실행 수 — 400행이면 14청크라 순차 처리 시 지연이 14배가 된다. 후보 목록은 청크마다
# 재전송되므로 입력 토큰은 늘지만(후보 180건 ≈ 3~4K) 정확도·복원력 대비 감수한다.
RECOMMEND_CHUNK_CONCURRENCY = 3

_MAX_BUDGET_CANDIDATES = 120
_MAX_PROJECT_CANDIDATES = 60

_SYSTEM = (
    "당신은 법인카드 거래 내역을 회계 결의서에 정리하는 보조자입니다. "
    "각 거래 행마다 가장 적합한 예산단위 조합과 프로젝트를 아래 후보 목록에서 고르고, "
    "얼마나 확신하는지 confidence(0~1)로 매기세요. "
    "가맹점명·거래일시·금액·부가세구분·적요 초안을 근거로 판단합니다. "
    # ⚠ 2026-07-27 사고: 18:33 결제가 '복리후생비-중식'으로 추천됐다(시각 미전달이 근본원인).
    #   시각을 보내는 것만으로는 부족해 **판단 규칙**까지 명시한다.
    "행의 time 은 거래시각(HH:MM:SS)입니다. 후보 계정이 식사 시간대로 나뉘어 있으면"
    "(중식·석식·야식·조식 등) **반드시 이 시각으로 구분**하세요 — 대략 11~15시는 중식, "
    "17시 이후는 석식, 22시 이후는 야식, 11시 이전은 조식입니다. 가맹점명이나 과거 선택만 보고 "
    "시간대를 단정하지 마세요(예: 18:33 결제를 '중식'으로 고르면 안 됩니다). "
    # ⚠ 00:00:00 은 자정 결제가 아니라 카드사가 승인 시각을 안 넘겨준 것(사용자 확정 2026-07-29).
    #   시각을 근거로 쓰면 자정 결제로 오판한다(예: 시외버스 승차권을 야식/심야로 해석).
    "단, time 이 '00:00:00'(또는 00:00)이면 실제 자정 결제가 아니라 **카드사에서 승인 시각이 "
    "전달되지 않은 것**입니다. 이 경우 시각을 판단 근거로 쓰지 말고(야식·심야 등 시간대 단정 금지) "
    "가맹점명·merchantHint·priorChoice 등 나머지 근거로만 판단하세요. "
    "확신이 서지 않으면 낮은 confidence 를 매기고, 적당한 후보가 없으면 해당 코드를 null 로 두세요. "
    "budgetUnitCode·projectCode 는 반드시 제공된 후보의 code 값을 그대로 사용하고, 새로 만들지 마세요. "
    "행에 priorChoice(과거 사용자가 같은 가맹점에 확정했던 선택)가 있으면, 그 code 를 최우선으로 "
    "채택하고 confidence 를 높게 매기세요(사용자의 반복 판단이 가장 신뢰도 높은 근거입니다). "
    # ⚠ 단, 시간대가 다른 거래에까지 과거 선택을 그대로 물려주면 18:33 결제가 '중식'이 된다
    #   (2026-07-27 실제 사고). 시간대 구분 계정에서는 시각이 과거 선택보다 우선한다.
    "다만 priorChoice 가 **시간대로 나뉘는 계정**(중식/석식/야식 등)이고 이 거래의 time 이 그 "
    "시간대와 맞지 않으면, 과거 선택을 그대로 쓰지 말고 **같은 성격의 계정 중 시각에 맞는 것**을 "
    "고르세요(예: priorChoice 가 '복리후생비-중식'인데 time 이 18:33 이면 '복리후생비-석식'). "
    "행에 merchantHint(가맹점 유형: 카페·택시·해외 OTA 등)가 있으면 그 업종에 맞는 예산단위를 "
    "고르는 근거로 삼으세요(예: '해외 호텔/항공 예약(OTA)'→여비교통비-해외출장). "
    "주유·유류 가맹점은 예산단위를 '차량유지비-유류' 계정으로 고르세요. "
    # vatDeduction 은 가맹점 기반 신호만 — 계정·VAT_TP 기반 불공은 시스템(classify_vat)이 결정적으로
    # 처리하므로 AI 가 계정으로 판단하지 않는다(불필요한 오판·토큰 방지).
    "vatDeduction 은 가맹점명이 통행료·우체국·주유소(유류)처럼 매입세액 불공제가 확실한 경우에만 "
    "'불공'으로, 나머지는 모두 '과세'로 두세요(예산계정 기반 불공은 시스템이 자동 처리하니 계정으로 "
    "판단하지 마세요). "
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
                            "vatDeduction": {
                                "type": "string",
                                "enum": ["과세", "불공"],
                                "description": (
                                    "부가세구분 — 매입세액 불공제 대상 가맹점(통행료·우체국·"
                                    "주유소(유류) 등)이면 '불공', 그 외 '과세'"
                                ),
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


# 판/제 버킷 판정(prefill._PREFIX_PROJECT_NO 와 동일 소스 — 변경 시 동기화). 접속자 비용구분에
# 맞지 않는 반대 버킷 후보를 LLM 컨텍스트에서 제외해 토큰을 아낀다(제조 후보는 판관 사용자가
# 선택할 일이 없다 — 사용자 확정 2026-07-23).
_PREFIX_PJT_NO = {"(제)": "500", "(판)": "800"}
_BUCKET_PREFIXES = ("(판)", "(제)")


def _filter_budget_by_cost(candidates: list[dict], cost_prefix: str | None) -> list[dict]:
    """접속자 비용구분 접두(예: '(판)')와 반대 버킷의 예산단위를 제외. 접두 미상이면 원본 유지.

    bgacctNm 이 '(판)'/'(제)' 로 시작하는 것만 버킷 판정 대상 — 접두 없는 중립 계정(지급수수료
    (구매)·기부금 등)은 부서 무관이라 그대로 둔다.
    """
    if not cost_prefix:
        return candidates
    kept = []
    for c in candidates:
        nm = c.get("bgacctNm") or ""
        if nm.startswith(_BUCKET_PREFIXES) and not nm.startswith(cost_prefix):
            continue  # 반대 버킷((제) 등) — 제외.
        kept.append(c)
    return kept


# 직급별 추천 제외 계정 키워드(사용자 확정 2026-07-29): 최하위 '팀원'은 접대비·회식비 등을
# 쓸 일이 없다. 후보 목록에서 아예 제외해 LLM 이 추천 자체를 못 하게 한다(프롬프트 지시보다
# 결정적). '회식'은 '회식비'·'복리후생비-회식' 등 표기 변형을 포괄. 추후 직급·키워드 추가 예정
# (직급체계: app.erp.profile.JOB_TITLE_HIERARCHY).
_EXCLUDED_BUDGET_KEYWORDS_BY_JOB_TITLE: dict[str, tuple[str, ...]] = {
    "팀원": ("접대비", "회식"),
}


def _filter_budget_by_job_title(candidates: list[dict], job_title: str | None) -> list[dict]:
    """접속자 직급이 쓸 일 없는 계정(팀원→접대비·회식비)을 후보에서 제외. 직급 미상이면 원본."""
    keywords = _EXCLUDED_BUDGET_KEYWORDS_BY_JOB_TITLE.get((job_title or "").strip())
    if not keywords:
        return candidates
    return [
        c for c in candidates
        if not any(k in (c.get("bgacctNm") or "") for k in keywords)
    ]


def _filter_project_by_cost(candidates: list[dict], cost_prefix: str | None) -> list[dict]:
    """반대 버킷(제조원가 500 / 판관비 800) 프로젝트만 제외. 버킷 아닌 특정 프로젝트는 부서
    무관이라 유지. 접두 미상이면 원본."""
    want = _PREFIX_PJT_NO.get(cost_prefix or "")
    if not want:
        return candidates
    kept = []
    for c in candidates:
        pjt_no = _code(c.get("code")).split("|")[0]
        if pjt_no in ("500", "800") and pjt_no != want:
            continue  # 반대 버킷 — 제외.
        kept.append(c)
    return kept


async def recommend_selections(
    rows: list[dict],
    budget_candidates: list[dict],
    project_candidates: list[dict],
    *,
    http: Any,
    settings: Any,
    cost_prefix: str | None = None,
    user_job_title: str | None = None,
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
    if not llm_ready(settings):  # etribe 는 무인증(항상 가능) — gemini 만 키 필요.
        return {}

    # 접속자 비용구분(판/제)에 맞는 후보만 LLM 에 보낸다 — 반대 버킷은 선택 대상이 아니므로
    # 컨텍스트에서 빼 토큰을 아낀다. 검증(코드 화이트리스트)도 같은 필터본 기준으로 좁힌다.
    # 직급 필터(팀원→접대비·회식비 제외)도 같은 원리 — 후보에서 빠지면 검증에서도 걸러진다.
    budget_ctx = _filter_budget_by_job_title(
        _filter_budget_by_cost(budget_candidates, cost_prefix), user_job_title
    )[:_MAX_BUDGET_CANDIDATES]
    project_ctx = _filter_project_by_cost(project_candidates, cost_prefix)[:_MAX_PROJECT_CANDIDATES]

    chunks = [
        rows[i : i + RECOMMEND_CHUNK_SIZE] for i in range(0, len(rows), RECOMMEND_CHUNK_SIZE)
    ]
    if len(chunks) > 1:
        logger.info(
            "card-collect 추천 %d행 → %d청크(청크당 최대 %d행, 동시 %d)",
            len(rows), len(chunks), RECOMMEND_CHUNK_SIZE, RECOMMEND_CHUNK_CONCURRENCY,
        )

    sem = asyncio.Semaphore(RECOMMEND_CHUNK_CONCURRENCY)

    async def run_chunk(index: int, chunk: list[dict]) -> dict[int, dict]:
        # ⚠ 청크 단위 실패 격리: 한 청크가 잘리거나 예외가 나도 나머지 청크의 추천은 살린다
        #   (종전엔 1회 호출이라 실패하면 전 행이 추천 없이 기본지정으로 떨어졌다).
        async with sem:
            try:
                return await _recommend_chunk(
                    chunk, budget_ctx, project_ctx, http=http, settings=settings
                )
            except Exception:  # noqa: BLE001 — 추천 실패는 런을 죽이지 않는다.
                logger.exception("card-collect recommend chunk %d/%d 실패", index + 1, len(chunks))
                return {}

    results = await asyncio.gather(*(run_chunk(i, c) for i, c in enumerate(chunks)))
    out: dict[int, dict] = {}
    for part in results:
        for no, rec in part.items():
            out.setdefault(no, rec)  # 청크 간 no 는 겹치지 않지만 방어적으로 선착순.
    return out


async def _recommend_chunk(
    rows: list[dict],
    budget_ctx: list[dict],
    project_ctx: list[dict],
    *,
    http: Any,
    settings: Any,
) -> dict[int, dict]:
    """행 묶음 하나를 LLM 1회 호출로 추천받고 검증한다(호출·검증 단위).

    검증 화이트리스트(코드·no 범위)는 **이 청크 기준**이라, 다른 청크의 행 번호를 돌려주는
    응답은 자동으로 걸러진다(청크 간 오염 차단).
    """
    budget_codes = {_code(c.get("code")) for c in budget_ctx if _code(c.get("code"))}
    project_codes = {_code(c.get("code")) for c in project_ctx if _code(c.get("code"))}
    valid_nos = {r.get("no") for r in rows if isinstance(r.get("no"), int)}

    context = {
        "rows": [
            {
                "no": r.get("no"),
                "merchant": r.get("merchant") or "",
                "amount": r.get("amount") or "",
                "vatType": r.get("vatType") or "",
                # 거래일시 — 식대(중식/석식/야식) 같은 시간대별 계정 판단의 결정적 근거.
                "date": r.get("date") or "",
                "time": r.get("time") or "",
                "note": r.get("note") or "",
                # 과거 사용자가 이 가맹점에 확정했던 선택(개입 학습). 있으면 최우선 참고.
                **({"priorChoice": r["priorChoice"]} if r.get("priorChoice") else {}),
                # 가맹점 유형 힌트(분류 사전) — 카드 표기명으로 인식한 업종(카페·택시·OTA 등).
                **({"merchantHint": r["merchantHint"]} if r.get("merchantHint") else {}),
            }
            for r in rows
        ],
        # bgacctNm(계정명)만 남긴다 — name(팀명, 전 후보 동일)·bizplanNm(사업계획명)은 판단에
        # 불필요한 토큰 낭비라 제외(사용자 확정 2026-07-23).
        "budgetCandidates": [
            {"code": _code(c.get("code")), "bgacctNm": c.get("bgacctNm") or ""}
            for c in budget_ctx
        ],
        "projectCandidates": [
            {"code": _code(c.get("code")), "name": c.get("name") or "", "wbsNm": c.get("wbsNm") or ""}
            for c in project_ctx
        ],
    }

    name, args = await chat_decide(
        http,
        system=_SYSTEM,
        history="",  # 대화 기록 없음(단발 배치 판단).
        context=context,
        shot_b64=None,  # 스크린샷 불필요.
        tools=_TOOLS,
        settings=settings,
    )

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
        vat_ded = str(rec.get("vatDeduction") or "").strip()
        out[no] = {
            "budgetUnitCode": budget_code if budget_code in budget_codes else "",
            "projectCode": project_code if project_code in project_codes else "",
            "confidence": _clamp01(rec.get("confidence")),
            # 부가세구분(가맹점 기반) — '불공'만 유의미(계정/VAT_TP 와 함께 classify_vat 로 최종 결정).
            "vatDeduction": vat_ded if vat_ded in ("과세", "불공") else None,
        }
    return out
