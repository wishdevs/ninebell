"""가맹점 분류 사전(하이브리드) — 미등록 가맹점을 위한 도메인 지식.

개입학습(learned)·전사 seed 에 이력이 있는 가맹점은 그 데이터로 결정된다. 이력이 없는
가맹점(예: 아고다)은 AI 가 판단해야 하는데, 카드 표기명이 브랜드명과 달라(Agoda_아고다_나이스)
근거가 약하다. 이 사전은 **카드 표기명에 나타나는 키워드**로 가맹점 유형을 인식해:
  - strong=True: 확실한 유형(주유소 등)은 계정을 **결정적**으로 해석(learned/seed 다음, AI 앞).
  - strong=False: 애매한 유형(카페·택시 등)은 AI 프롬프트에 **힌트**로만 주입.

재료: 내부 seed(card_seed_selections 1,048건) 마이닝 + 웹 브랜드 변형(OTA 등) + 수기 큐레이션.
키워드는 소문자·부분일치(카드 표기 변형·PG접두·법인명·지점명을 흡수). acct 는 예산단위
bgacctNm 과 catalog._resolve_seed_budget 로 매칭되므로 **세부계정명 정확 표기**여야 한다
(모호하면 매칭 실패 → None → AI 힌트로만 동작).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MerchantRule:
    keywords: tuple[str, ...]  # 소문자 부분일치(카드 표기명 lower 에 포함되면 매칭)
    category: str  # 사람이 읽는 유형(AI 힌트 문구에 사용)
    acct: str | None  # 예산단위 계정명(결정적 해석용) — 모호하면 None
    strong: bool  # True=결정적 폴백 후보, False=AI 힌트만
    source: str  # 출처: '내부'(seed 마이닝)·'웹'(인터넷 브랜드)·'내부+웹'·'큐레이션'


# ── 코드 기본 사전 (DB 시드 원본 + DB 미가용 시 폴백) ─────────────────────────────
# 실제 매칭은 DB(merchant_dict_rules)에서 로드한 규칙으로 한다(load_rules). 이 상수는
# 마이그레이션 0025 가 테이블에 시드하는 원본이자, DB 로드 실패 시의 폴백이다.
# strong=True 는 계정이 명확한 것만(주유소·해외 OTA). 나머지는 AI 힌트.
DEFAULT_RULES: tuple[MerchantRule, ...] = (
    # 주유·유류 — seed 104건 최다 신호. 카드 표기 변형 다수(오일뱅크·칼텍스·석유·에너지).
    MerchantRule(
        ("주유소", "주유", "오일뱅크", "칼텍스", "gs칼텍스", "s-oil", "에스오일", "sk에너지",
         "현대오일", "석유", "에너지", "gas", "oil", "주유충전", "충전소"),
        "주유·유류", "차량유지비-유류", True, "내부+웹",
    ),
    # 통행료·하이패스 — 매입세액 불공(vat 는 별도 vat.py 도 커버). 계정은 여비 계열이라 모호 → 힌트.
    MerchantRule(
        ("통행료", "하이패스", "하이플러스", "도로공사", "톨게이트", "highway"),
        "통행료(불공)", None, False, "내부+큐레이션",
    ),
    # 해외 호텔/항공 예약(OTA) — seed 에 거의 없어 웹 지식 보강. 해외출장 계정이 유력.
    MerchantRule(
        ("아고다", "agoda", "부킹", "booking.com", "booking", "트립닷컴", "trip.com", "trip",
         "익스피디아", "expedia", "호텔스닷컴", "hotels.com", "hotel", "hostel", "airbnb", "에어비앤비"),
        "해외 호텔/항공 예약(OTA)", "여비교통비-해외출장", True, "웹",
    ),
    # 항공 — 대한항공·아시아나·제주·티웨이 등. 해외/국내 혼재라 계정은 힌트로만.
    MerchantRule(
        ("대한항공", "아시아나", "제주항공", "티웨이", "진에어", "에어부산", "에어서울",
         "korean air", "asiana", "airlines", "airline", "항공"),
        "항공", None, False, "내부+웹",
    ),
    # 택시·모빌리티 — DiDi·카카오T·티머니·우버 등 카드 표기 변형 다수. 계정 모호(국내/해외/시내).
    MerchantRule(
        ("택시", "taxi", "didi", "우버", "uber", "카카오 t", "카카오t", "티머니", "tmoney",
         "grab", "그랩", "대리운전", "카카오 대리"),
        "택시/모빌리티", None, False, "내부+웹",
    ),
    # 대중교통 — 지하철·버스·코레일·기차.
    MerchantRule(
        ("지하철", "metro", "코레일", "korail", "srt", "고속버스", "시외버스", "버스", "철도", "기차"),
        "대중교통", None, False, "큐레이션",
    ),
    # 주차·주차료 — 아이파킹·하이파킹·파킹클라우드·주차장. 여비교통비 계열이나 세부(국내/해외
    # 공항/시내) 모호 → 힌트만. ⚠ '파크' 는 노이즈(테크노파크·비발디파크·파크에너지=주유)라 제외.
    MerchantRule(
        ("주차", "파킹", "parking", "아이파킹", "하이파킹", "파킹클라우드"),
        "주차/주차료", None, False, "내부",
    ),
    # 카페/커피 — 스타벅스·투썸·메가·이디야 등. 복리후생비 계열이나 세부 모호 → 힌트.
    MerchantRule(
        ("스타벅스", "starbucks", "커피", "coffee", "카페", "cafe", "투썸", "메가엠지씨", "메가커피",
         "이디야", "컴포즈", "빽다방", "할리스", "폴바셋", "엔제리너스", "탐앤탐스"),
        "카페/커피", None, False, "내부+웹",
    ),
    # 편의점 — GS25·CU·세븐일레븐·이마트24.
    MerchantRule(
        ("편의점", "gs25", "지에스25", "씨유", "cu ", "세븐일레븐", "seven eleven", "이마트24",
         "emart24", "미니스톱", "ministop"),
        "편의점", None, False, "내부+웹",
    ),
    # 온라인쇼핑 — 쿠팡·네이버·G마켓·11번가 등. 소모품/구매 계열 유력이나 품목 따라 다름 → 힌트.
    MerchantRule(
        ("쿠팡", "coupang", "쿠페이", "지마켓", "gmarket", "11번가", "옥션", "auction", "위메프",
         "티몬", "인터파크", "네이버파이낸셜", "smartstore", "스마트스토어"),
        "온라인쇼핑", None, False, "내부+웹",
    ),
    # 대형마트/생활 — 이마트·홈플러스·롯데마트·코스트코.
    MerchantRule(
        ("이마트", "emart", "홈플러스", "homeplus", "롯데마트", "코스트코", "costco", "트레이더스"),
        "대형마트", None, False, "웹",
    ),
    # 배달앱 — 배민(우아한형제들)·요기요·쿠팡이츠.
    MerchantRule(
        ("배달의민족", "우아한형제들", "요기요", "쿠팡이츠", "배민"),
        # ⚠ 배달앱은 **음식이 확실**하므로 식대 계열로 결정적 해석한다(2026-07-27 감사:
        #   쿠팡이츠 11건이 소모품비로 분류됐다 — 힌트만으로는 AI 실패 시 폴백이 없었다).
        #   여기서 주는 '석식'은 **식대 계열 앵커**일 뿐이고, 조식/석식 슬롯은 거래시각으로
        #   meal_time.correct_budget 이 최종 확정한다(11시 이전 배달 → 조식).
        #   앵커를 중식 → 석식으로 교체(사규 변경 2026-08-13, 중식 폐지).
        "배달앱(식대)", "복리후생비-석식", True, "웹",
    ),
    # 통신 — 통신3사·우체국(통신비).
    MerchantRule(
        ("sk텔레콤", "kt ", "lg유플러스", "lgu+", "통신", "우체국", "우정사업본부"),
        "통신/우편", None, False, "내부",
    ),
    # 전자·컴퓨터·사무기기 판매 — 동구전자 등 부품·기기 도매/소매. AI 가 방향(사무용품비)은
    # 맞히나 confidence 가 낮아(0.3~0.4) 임계값 미달로 폐기→blind 기본값으로 떨어지던 문제
    # (2026-07-24 동구전자 실측). 힌트만으로 confidence 0.85 로 올라 채택된다. 계정은 소모품/
    # 사무용품/비품이 품목 따라 갈려 AI 가 정하도록 힌트만(strong 아님). ⚠ 바 '전자'는 오탐
    # (시외버스 '전자승차권' 등)이라 제외 — 안전한 복합어·업종어만.
    MerchantRule(
        # ⚠ '하이마트'는 '이마트'(대형마트 규칙, 앞순위)의 부분문자열이라 가려짐 → 제외.
        ("동구전자", "전자상가", "전자랜드", "용산전자", "세운상가", "테크노마트",
         "베스트샵", "디지털프라자", "컴퓨존", "컴퓨터", "다나와", "아이코다", "노트북",
         "오피스디포", "문구", "복사용지", "토너", "잉크", "사무용품", "모나미"),
        "전자·컴퓨터·사무기기(소모품/사무용품)", None, False, "웹+큐레이션",
    ),
)


# ── DB 로드 + 캐시 ────────────────────────────────────────────────────────────
# 매칭은 핫패스(행별)라 매번 쿼리하지 않고 모듈 캐시에 담는다. TTL 경과 또는 편집 후
# invalidate_cache() 로 갱신한다. DB 미가용/빈 테이블이면 DEFAULT_RULES 로 폴백한다.
import logging  # noqa: E402
import time  # noqa: E402

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 60.0
_cache: tuple[float, tuple[MerchantRule, ...]] | None = None


def invalidate_cache() -> None:
    """CRUD 편집 후 호출 — 다음 load_rules 가 DB 를 다시 읽게 한다."""
    global _cache
    _cache = None


def _row_to_rule(row: object) -> MerchantRule:
    kws = tuple(k.strip().lower() for k in str(row.keywords).split(",") if k.strip())
    return MerchantRule(kws, row.category, row.acct, bool(row.strong), row.source)


async def load_rules() -> tuple[MerchantRule, ...]:
    """활성 사전 규칙을 sort_order 순으로 로드(캐시). DB 실패/빈 테이블이면 DEFAULT_RULES."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_S:
        return _cache[1]
    try:
        from sqlalchemy import select

        from app.db import get_sessionmaker
        from app.models import MerchantDictRule

        async with get_sessionmaker()() as s:
            rows = (
                (
                    await s.execute(
                        select(MerchantDictRule)
                        .where(MerchantDictRule.enabled.is_(True))
                        .order_by(MerchantDictRule.sort_order, MerchantDictRule.category)
                    )
                )
                .scalars()
                .all()
            )
        rules = tuple(_row_to_rule(r) for r in rows) or DEFAULT_RULES
    except Exception:  # noqa: BLE001 — DB 미가용이어도 매칭은 폴백으로 계속.
        logger.warning("가맹점 사전 DB 로드 실패 — 코드 기본 사전으로 폴백", exc_info=True)
        rules = DEFAULT_RULES
    _cache = (now, rules)
    return rules


def match_in(merchant: str | None, rules: tuple[MerchantRule, ...]) -> MerchantRule | None:
    """카드 표기명을 부분일치(소문자)로 매칭 — **가장 구체적인(긴) 키워드**가 이긴다.

    ⚠ 근본원인(2026-07-27 사용자 감사, 쿠팡이츠 11건이 소모품비): 종전에는 규칙 **순서**로
      첫 매칭을 반환해, 온라인쇼핑 규칙의 '쿠팡'이 배달앱 규칙의 '쿠팡이츠'보다 앞에 있다는
      이유만으로 배달 음식이 소모품비로 분류됐다. 규칙 순서는 사람이 관리하는 값이라
      새 규칙을 넣을 때마다 같은 사고가 재발한다 — 매칭 기준 자체를 구체성으로 바꾼다.
      ('쿠팡이츠'(4자)가 '쿠팡'(2자)을 이긴다. 길이가 같으면 기존처럼 앞선 규칙 우선.)
    """
    if not merchant:
        return None
    m = str(merchant).lower()
    best: tuple[int, int, MerchantRule] | None = None  # (키워드 길이, -순번, 규칙)
    for order, rule in enumerate(rules):
        hit = max((len(kw) for kw in rule.keywords if kw in m), default=0)
        if not hit:
            continue
        cand = (hit, -order, rule)
        if best is None or cand[:2] > best[:2]:
            best = cand
    return best[2] if best else None


def match_merchant(merchant: str | None, rules: tuple[MerchantRule, ...] | None = None) -> MerchantRule | None:
    """카드 표기명 매칭. rules 미지정 시 코드 기본 사전(DEFAULT_RULES) 사용(동기 편의·테스트용).

    핫패스(prefill)는 load_rules() 로 DB 규칙을 1회 받아 match_in 으로 행별 매칭한다.
    """
    return match_in(merchant, rules if rules is not None else DEFAULT_RULES)
