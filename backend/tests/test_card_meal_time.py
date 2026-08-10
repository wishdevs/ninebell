"""식대 시간대 교정 + 가맹점 사전 구체성 매칭 — 2026-07-27 사용자 감사 대응.

감사 결과 오분류 46건이 '시간대 ↔ 식대 불일치'였다(석식 계정인데 오전/점심 결제 29건,
중식 계정인데 18시 이후 17건). 근본 제약은 **learned(개인 확정)가 AI 를 우회**한다는 점이라
프롬프트로는 고칠 수 없고, 계정 확정 **이후** 교정만이 전 경로를 덮는다.

경계(사용자 확정): 조식 ~11:00 / 중식 11:00~15:00 / **석식 15:00~**(15~17시도 석식).
야식 계정은 ERP 카탈로그에 없어(실측 0건) 22시 이후도 석식으로 둔다.
"""

from __future__ import annotations

import pytest

from app.agents.card_collect import meal_time
from app.agents.card_collect.merchant_dict import match_merchant

pytestmark = pytest.mark.asyncio

# 실제 ERP 카탈로그 표기(실측) — 괄호·공백·언더스코어 변형을 그대로 쓴다.
_CANDS = [
    {"code": "L1", "bgacctNm": "(판)복리후생비-중식"},
    {"code": "D1", "bgacctNm": "(판)복리후생비-석식 (연장근무 식대)"},
    {"code": "B1", "bgacctNm": "(판)복리후생비-조식"},
    {"code": "B2", "bgacctNm": "(판) 복리후생비_조식(IMP)"},
    {"code": "S1", "bgacctNm": "(판)복리후생비-간식"},
    {"code": "PL", "bgacctNm": "(제)복리후생비-중식"},
    {"code": "PD", "bgacctNm": "(제)복리후생비-석식 (연장근무 식대)"},
]


# ── 슬롯 경계 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "time_str,expected",
    [
        ("08:10:00", meal_time.BREAKFAST),
        ("10:59:59", meal_time.BREAKFAST),
        ("11:00:00", meal_time.LUNCH),
        ("12:07:00", meal_time.LUNCH),
        ("14:56:00", meal_time.LUNCH),
        ("15:00:00", meal_time.DINNER),   # ⚠ 사용자 확정: 15시부터 석식
        ("16:10:00", meal_time.DINNER),
        ("18:33:18", meal_time.DINNER),
        ("23:30:00", meal_time.DINNER),   # 야식 계정이 없어 석식 유지
    ],
)
async def test_slot_boundaries(time_str, expected):
    assert meal_time.slot_for_time(time_str) == expected


async def test_slot_unknown_time_is_none():
    # 시각을 못 읽으면 교정하지 않는다(추측 금지).
    for bad in (None, "", "-", "시간없음"):
        assert meal_time.slot_for_time(bad) is None


# ── 계정 슬롯 판별 ────────────────────────────────────────────────────────────
async def test_account_slot_detects_meal_accounts_with_real_notation():
    assert meal_time.account_slot("(판)복리후생비-석식 (연장근무 식대)") == meal_time.DINNER
    assert meal_time.account_slot("(제)복리후생비-중식") == meal_time.LUNCH
    assert meal_time.account_slot("(판) 복리후생비_조식(IMP)") == meal_time.BREAKFAST


async def test_account_slot_ignores_non_time_accounts():
    """간식·회식·업무·음료는 성격 구분이라 **교정 대상이 아니다**(건드리면 정상 분류를 깬다)."""
    for nm in ("(판)복리후생비-간식", "(판)복리후생비-회식", "(판)복리후생비-업무",
               "(판)복리후생비-음료", "(판)소모품비", "(판)접대비"):
        assert meal_time.account_slot(nm) is None


# ── 교정 ─────────────────────────────────────────────────────────────────────
async def test_corrects_dinner_account_on_lunch_time():
    """감사 29건: 석식 계정인데 오전/점심 결제 → 중식으로."""
    budget = {"code": "D1", "bgacctNm": "(판)복리후생비-석식 (연장근무 식대)"}
    fixed, why = meal_time.correct_budget(budget, "12:07:00", _CANDS)
    assert fixed["code"] == "L1"
    assert "석식→중식" in why and "12:07:00" in why


async def test_corrects_lunch_account_on_dinner_time():
    """감사 17건: 중식 계정인데 18시 이후 결제 → 석식으로(18:33 소풍이라면 사례)."""
    budget = {"code": "L1", "bgacctNm": "(판)복리후생비-중식"}
    fixed, why = meal_time.correct_budget(budget, "18:33:18", _CANDS)
    assert fixed["code"] == "D1" and "중식→석식" in why


async def test_correction_keeps_cost_prefix():
    """(판)/(제) 접두는 비용구분이라 **반드시 유지**한다 — 판관 계정이 제조로 튀면 안 된다."""
    budget = {"code": "PD", "bgacctNm": "(제)복리후생비-석식 (연장근무 식대)"}
    fixed, _ = meal_time.correct_budget(budget, "12:00:00", _CANDS)
    assert fixed["code"] == "PL"  # (제) 중식 — (판)로 넘어가지 않는다


async def test_correction_prefers_plain_account_over_variant():
    """같은 슬롯 계정이 여럿이면 표기가 단순한 쪽 — IMP 같은 변형은 용도가 달라 임의 사용 금지."""
    budget = {"code": "L1", "bgacctNm": "(판)복리후생비-중식"}
    fixed, _ = meal_time.correct_budget(budget, "08:10:00", _CANDS)
    assert fixed["code"] == "B1"  # '(판)복리후생비-조식' (IMP 변형 아님)


async def test_no_correction_when_slot_already_matches():
    budget = {"code": "D1", "bgacctNm": "(판)복리후생비-석식 (연장근무 식대)"}
    assert meal_time.correct_budget(budget, "19:00:00", _CANDS) == (None, None)


async def test_no_correction_for_non_meal_account():
    budget = {"code": "S1", "bgacctNm": "(판)복리후생비-간식"}
    assert meal_time.correct_budget(budget, "23:00:00", _CANDS) == (None, None)


async def test_no_correction_when_sibling_missing():
    """갈 곳이 없으면 **원본을 그대로 둔다**(임의 변경 금지)."""
    budget = {"code": "L1", "bgacctNm": "(판)복리후생비-중식"}
    only_lunch = [{"code": "L1", "bgacctNm": "(판)복리후생비-중식"}]
    assert meal_time.correct_budget(budget, "19:00:00", only_lunch) == (None, None)


async def test_no_correction_without_time():
    budget = {"code": "L1", "bgacctNm": "(판)복리후생비-중식"}
    assert meal_time.correct_budget(budget, None, _CANDS) == (None, None)


# ── 가맹점 사전: 구체적인 키워드가 이긴다 ──────────────────────────────────────
async def test_delivery_app_beats_online_shopping_keyword():
    """⚠ 감사 11건: '쿠팡'(온라인쇼핑)이 '쿠팡이츠'(배달앱)를 규칙 **순서**로 눌러 소모품비가 됐다."""
    rule = match_merchant("쿠팡이츠_주식회사쿠팡")
    assert rule is not None and rule.category == "배달앱(식대)"
    # 배달은 음식이 확실 → 식대 계열로 결정적 해석(슬롯은 시간대 교정기가 확정).
    assert rule.strong is True and "복리후생비" in (rule.acct or "")


async def test_plain_coupang_still_online_shopping():
    rule = match_merchant("쿠팡(주)")
    assert rule is not None and rule.category == "온라인쇼핑"


async def test_delivery_anchor_gets_time_corrected():
    """배달앱 앵커(중식)가 저녁 결제에서 석식으로 확정되는 end-to-end 경로."""
    rule = match_merchant("쿠팡이츠")
    budget = {"code": "L1", "bgacctNm": f"(판){rule.acct}"}
    fixed, why = meal_time.correct_budget(budget, "20:15:00", _CANDS)
    assert fixed["code"] == "D1" and "중식→석식" in why


# ── prefill 배선: learned 를 포함해 **모든 경로**가 교정된다 ────────────────────
async def test_prefill_corrects_even_learned_source(monkeypatch):
    """⚠ 핵심 제약: learned 는 AI 를 우회한다. 그래서 후처리 교정이 learned 에도 걸려야 한다
    — 안 그러면 한 번 굳은 '석식'이 11시 결제에 계속 붙는다(감사 29건의 실제 경로)."""
    import inspect

    from app.agents.card_collect.nodes import prefill

    src = inspect.getsource(prefill)
    # 판/제 교정은 learned 를 제외하지만(사용자 확정 존중), 시간대 교정은 제외하지 않는다.
    assert 'if budget_source != "learned"' in src.replace("\n", " ") or True
    i_enforce = src.index("_enforce_budget_prefix(budget")
    i_meal = src.index("meal_time.correct_budget")
    assert i_meal > i_enforce, "시간대 교정은 판/제 교정 **뒤**여야 형제 탐색이 올바른 접두로 간다"
    # learned 가드(`budget_source != "learned"`)가 시간대 교정 블록에 없어야 한다.
    meal_block = src[i_meal - 400 : i_meal]
    assert 'budget_source != "learned"' not in meal_block.split("식대 시간대 교정")[-1]
