"""계정 인지 적요 리졸버(suggest_note) + 엔드포인트(GET /me/note-suggest) 검증.

리졸버 사다리: learned(개인) > seed(전사 가맹점×계정) > AI(미학습 조합 계정 맞춤 생성, allow_ai+
acct_name 있을 때) > category(계정 최빈, cold-start) > heuristic(가맹점 키워드) > None. 계정 없으면
계정 tier 스킵하고 heuristic 만. AI tier 는 실 LLM 대신 _ai_note_generate 를 monkeypatch 로 대체해
결정적으로 검증한다. isolated acct 코드를 써 seed_all 실데이터와 충돌하지 않는다.
"""

from __future__ import annotations

from sqlalchemy import select

import app.agents.card_collect.nodes._shared as cc_shared
from app.models import CardAiNote, CardLearnedNote, CardSeedNote
from app.services import card_learning


# ─────────────────────────── 리졸버 사다리 ───────────────────────────
async def test_suggest_note_learned_beats_seed(sm, make_user):
    """개인 학습(CardLearnedNote)이 있으면 seed 보다 우선(가장 구체적)."""
    uid = await make_user("sug-learned", "user")
    norm = card_learning.norm_merchant("사다리상점")
    async with sm() as s:
        s.add(CardLearnedNote(
            user_id=uid, norm_merchant=norm, merchant="사다리상점", acct_code="LAD1", note="개인적요"
        ))
        s.add(CardSeedNote(
            norm_merchant=norm, merchant="사다리상점", acct_code="LAD1", note="전사적요", count=9
        ))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=uid, merchant="사다리상점", acct_code="LAD1"
        )
    assert res == {"note": "개인적요", "source": "learned"}


async def test_suggest_note_seed_when_no_learned(sm, make_user):
    """개인 학습이 없으면 전사 seed(norm×acct) 적요를 반환."""
    uid = await make_user("sug-seed", "user")
    norm = card_learning.norm_merchant("씨드상점")
    async with sm() as s:
        s.add(CardSeedNote(
            norm_merchant=norm, merchant="씨드상점", acct_code="SEED1", note="전사관례적요", count=5
        ))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=uid, merchant="씨드상점", acct_code="SEED1"
        )
    assert res == {"note": "전사관례적요", "source": "seed"}


async def test_suggest_note_category_uses_account_name(sm):
    """계정만으로 채우는 적요는 **계정명 그대로**(일반 적요) — 특정 과거 적요("세차비") 금지.

    사용자 확정 2026-07-24: 계정 최빈 적요가 특정 서비스/품목이면 무관한 거래에 붙으므로,
    계정명(어떤 거래에도 일반적)을 쓴다. (판)/(제) 접두는 벗긴다.
    """
    async with sm() as s:
        # 계정에 특정 과거 적요('세차비')가 최빈이어도 무시하고 계정명을 쓴다.
        s.add(CardSeedNote(norm_merchant="세차집", merchant="세차집", acct_code="CAT1", note="세차비", count=99))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="첫방문가맹점XYZ", acct_code="CAT1", acct_name="(판)차량유지비-관리"
        )
    assert res == {"note": "차량유지비-관리", "source": "category"}  # 접두 제거된 계정명.


async def test_suggest_note_category_uses_company_convention_across_merchants(sm):
    """⚠ 회귀(사용자 지적 2026-08-14): 같은 석식인데 학습 적요는 '직원 야근식대(법인카드)',
    기본 적요는 계정명 '복리후생비-석식'으로 갈렸다. 여러 가맹점에 걸친 **전사 관례**가
    있으면 계정명 대신 그 관례를 기본값으로 쓴다(학습/시드/기본이 한 표현으로 수렴)."""
    async with sm() as s:
        # 같은 적요가 서로 다른 가맹점 8곳에 걸쳐 쓰인다 = 그 계정의 비용 성격.
        for i in range(8):
            s.add(CardSeedNote(
                norm_merchant=f"식당{i}", merchant=f"식당{i}", acct_code="CONV1",
                note="직원 야근식대(법인카드)", count=40,
            ))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="처음보는식당", acct_code="CONV1",
            acct_name="(판)복리후생비-석식 (연장근무 식대)",
        )
    assert res == {"note": "직원 야근식대(법인카드)", "source": "category"}


async def test_suggest_note_category_ignores_convention_from_few_merchants(sm):
    """가맹점이 적으면 '관례'가 아니라 그 가맹점의 서비스다 — 계정명을 쓴다(2026-07-24 규율).
    지배율 100% 라도 가맹점 다양성 하한을 못 넘으면 채택하지 않는다."""
    async with sm() as s:
        for i in range(2):  # 2곳뿐 — ACCT_NOTE_MIN_MERCHANTS 미만.
            s.add(CardSeedNote(
                norm_merchant=f"세차장{i}", merchant=f"세차장{i}", acct_code="CONV2",
                note="세차비(법인카드)", count=99,
            ))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="처음보는가맹점", acct_code="CONV2",
            acct_name="(판)차량유지비-관리",
        )
    assert res == {"note": "차량유지비-관리", "source": "category"}


async def test_suggest_note_category_ignores_split_account(sm):
    """계정이 서로 다른 성격으로 갈리면(지배율 미달) 관례로 확정하지 않는다."""
    async with sm() as s:
        for i in range(6):
            s.add(CardSeedNote(norm_merchant=f"가맹{i}", merchant=f"가맹{i}",
                               acct_code="CONV3", note="해외출장 교통비", count=10))
            s.add(CardSeedNote(norm_merchant=f"숙소{i}", merchant=f"숙소{i}",
                               acct_code="CONV3", note="해외출장 숙박비", count=9))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="처음보는곳", acct_code="CONV3",
            acct_name="여비교통비-해외출장",
        )
    assert res == {"note": "여비교통비-해외출장", "source": "category"}


async def test_suggest_note_convention_strips_cost_division_before_tally(sm):
    """판/제 접미로 쪼개진 같은 관례는 합산해 한 표현으로 수렴시킨다(-제품/-판매 → base)."""
    async with sm() as s:
        for i in range(6):
            suffix = "-제품" if i % 2 else "-판매"
            s.add(CardSeedNote(
                norm_merchant=f"점포{i}", merchant=f"점포{i}", acct_code="CONV4",
                note=f"직원 야근식대(법인카드){suffix}", count=30,
            ))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="새가맹점", acct_code="CONV4", acct_name="복리후생비-석식"
        )
    assert res == {"note": "직원 야근식대(법인카드)", "source": "category"}


async def test_suggest_note_category_needs_acct_name_else_heuristic(sm):
    """acct_name 이 없으면 계정명 적요를 만들 수 없어 heuristic(가맹점 키워드)로 폴백."""
    async with sm() as s:
        s.add(CardSeedNote(norm_merchant="세차집", merchant="세차집", acct_code="CATH", note="세차비", count=9))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="김밥천국", acct_code="CATH"  # acct_name 미전달.
        )
    assert res["source"] == "heuristic"



async def test_suggest_note_heuristic_when_account_has_no_data(sm):
    """계정 코드는 있으나 그 계정에 seed 가 없으면(category 빈값) 가맹점 키워드 휴리스틱."""
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="김밥천국", acct_code="NOSEED_ZZZ"
        )
    assert res == {"note": "식대(법인카드)", "source": "heuristic"}


async def test_suggest_note_no_acct_skips_db_tiers(sm, make_user):
    """계정 없으면 learned/seed/category(1·2·3) 스킵 — 학습이 있어도 휴리스틱만 반환."""
    uid = await make_user("sug-noacct", "user")
    norm = card_learning.norm_merchant("주유상점")
    async with sm() as s:
        s.add(CardLearnedNote(
            user_id=uid, norm_merchant=norm, merchant="주유상점", acct_code="ANY1", note="개인적요"
        ))
        s.add(CardSeedNote(
            norm_merchant=norm, merchant="주유상점", acct_code="ANY1", note="전사적요", count=3
        ))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=uid, merchant="주유상점", acct_code=None
        )
    # 학습('개인적요')이 있어도 acct 없으니 무시 → 키워드('주유') 휴리스틱.
    assert res == {"note": "차량 주유비(법인카드)", "source": "heuristic"}


async def test_suggest_note_returns_none_when_nothing_matches(sm, monkeypatch):
    """모든 tier 실패(휴리스틱까지 빈값)면 {note:None, source:None}."""
    monkeypatch.setattr(cc_shared, "recommend_note", lambda *a, **k: "")
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="무매칭ABC", acct_code="NOSEED_ZZZ"
        )
    assert res == {"note": None, "source": None}


# ─────────────────────────── 엔드포인트 ───────────────────────────
async def test_note_suggest_endpoint_with_account(client, make_user, auth_as, sm):
    """GET /me/note-suggest?merchant&acct → 계정 매칭 seed 적요 + source."""
    uid = await make_user("ep-seed", "user")
    auth_as(uid)
    norm = card_learning.norm_merchant("엔드포인트상점")
    async with sm() as s:
        s.add(CardSeedNote(
            norm_merchant=norm, merchant="엔드포인트상점", acct_code="EP1", note="전사적요", count=4
        ))
        await s.commit()
    r = await client.get("/me/note-suggest", params={"merchant": "엔드포인트상점", "acct": "EP1"})
    assert r.status_code == 200
    assert r.json() == {"note": "전사적요", "source": "seed"}


async def test_note_suggest_endpoint_without_account_is_heuristic(client, make_user, auth_as):
    """acct 미지정 → 계정 무관 키워드 휴리스틱만."""
    uid = await make_user("ep-heur", "user")
    auth_as(uid)
    r = await client.get("/me/note-suggest", params={"merchant": "김밥천국"})
    assert r.status_code == 200
    assert r.json() == {"note": "식대(법인카드)", "source": "heuristic"}


async def test_note_suggest_requires_merchant(client, make_user, auth_as):
    """merchant 는 필수 쿼리 파라미터 — 없으면 422."""
    uid = await make_user("ep-req", "user")
    auth_as(uid)
    r = await client.get("/me/note-suggest")
    assert r.status_code == 422


async def test_note_suggest_requires_auth(client):
    """인증 없으면 401(세션 쿠키 없음)."""
    r = await client.get("/me/note-suggest", params={"merchant": "김밥천국"})
    assert r.status_code == 401


# ─────────────────────────── AI tier (미학습 조합) ───────────────────────────
async def test_suggest_note_ai_generates_when_learned_seed_miss(sm, monkeypatch):
    """learned/seed 미스 + allow_ai + acct_name → AI 계정 맞춤 생성(source 'ai') + 캐시 적재."""
    calls: list[tuple[str, str]] = []

    async def fake_gen(merchant: str, acct_name: str):
        calls.append((merchant, acct_name))
        return "회의비(법인카드)", "test-model"

    monkeypatch.setattr(card_learning, "_ai_note_generate", fake_gen)
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="에이아이상점", acct_code="AI_MEET",
            acct_name="회의비", allow_ai=True,
        )
    assert res == {"note": "회의비(법인카드)", "source": "ai"}
    assert calls == [("에이아이상점", "회의비")]  # 생성 1회.
    norm = card_learning.norm_merchant("에이아이상점")
    async with sm() as s:
        rows = (
            await s.execute(select(CardAiNote).where(CardAiNote.norm_merchant == norm))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].note == "회의비(법인카드)"
    assert rows[0].acct_code == "AI_MEET"
    assert rows[0].acct_name == "회의비"


async def test_suggest_note_ai_cache_hit_skips_regenerate(sm, monkeypatch):
    """같은 (가맹점×계정) 재호출은 캐시에서 반환 — LLM 생성 재호출 없음."""
    calls: list[int] = []

    async def fake_gen(merchant: str, acct_name: str):
        calls.append(1)
        return "회의비(법인카드)", "test-model"

    monkeypatch.setattr(card_learning, "_ai_note_generate", fake_gen)
    async with sm() as s:
        await card_learning.suggest_note(
            s, user_id=None, merchant="캐시상점", acct_code="AI_C",
            acct_name="회의비", allow_ai=True,
        )
    async with sm() as s:
        res2 = await card_learning.suggest_note(
            s, user_id=None, merchant="캐시상점", acct_code="AI_C",
            acct_name="회의비", allow_ai=True,
        )
    assert res2 == {"note": "회의비(법인카드)", "source": "ai"}
    assert len(calls) == 1  # 두 번째는 캐시 히트 — 생성은 1회뿐.


async def test_suggest_note_ai_gated_by_allow_ai(sm, monkeypatch):
    """allow_ai=False(배치 기본)면 acct_name 이 있어도 AI 미호출 → 결정적 폴백."""
    async def boom(*a, **k):
        raise AssertionError("allow_ai=False 인데 AI 가 호출됨")

    monkeypatch.setattr(card_learning, "_ai_note_generate", boom)
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="김밥천국", acct_code="NOSEED_ZZZ",
            acct_name="회의비", allow_ai=False,
        )
    # AI 미호출(게이트) 후 category tier 가 계정명("회의비")을 일반 적요로 반환(2026-07-24).
    assert res == {"note": "회의비", "source": "category"}


async def test_suggest_note_ai_needs_acct_name(sm, monkeypatch):
    """allow_ai=True 라도 acct_name 없으면 AI 스킵(생성 근거 없음) → 결정적 폴백."""
    async def boom(*a, **k):
        raise AssertionError("acct_name 없는데 AI 가 호출됨")

    monkeypatch.setattr(card_learning, "_ai_note_generate", boom)
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="김밥천국", acct_code="NOSEED_ZZZ",
            acct_name=None, allow_ai=True,
        )
    assert res == {"note": "식대(법인카드)", "source": "heuristic"}


async def test_suggest_note_ai_failure_falls_through(sm, monkeypatch):
    """AI 생성 실패(None: 키없음/오류)면 category·heuristic 로 폴백 — 응답 안 죽음."""
    async def none_gen(*a, **k):
        return None

    monkeypatch.setattr(card_learning, "_ai_note_generate", none_gen)
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="김밥천국", acct_code="NOSEED_ZZZ",
            acct_name="회의비", allow_ai=True,
        )
    # AI 실패 후 category tier 가 계정명("회의비")을 반환(heuristic 아님 — acct_name 있으므로).
    assert res == {"note": "회의비", "source": "category"}


async def test_suggest_note_seed_beats_ai(sm, monkeypatch):
    """(가맹점×계정) seed 실이력이 있으면 AI 미호출하고 seed 반환."""
    async def boom(*a, **k):
        raise AssertionError("seed 있는데 AI 가 호출됨")

    monkeypatch.setattr(card_learning, "_ai_note_generate", boom)
    norm = card_learning.norm_merchant("씨드우선상점")
    async with sm() as s:
        s.add(CardSeedNote(
            norm_merchant=norm, merchant="씨드우선상점", acct_code="SB1", note="전사관례", count=7
        ))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="씨드우선상점", acct_code="SB1",
            acct_name="회의비", allow_ai=True,
        )
    assert res == {"note": "전사관례", "source": "seed"}


# ── 저신뢰(dominance 미달) seed → AI 폴스루 ──────────────────────────────────
async def _add_seed(sm, merchant: str, acct: str, note: str, dominance: float) -> None:
    async with sm() as s:
        s.add(CardSeedNote(
            norm_merchant=card_learning.norm_merchant(merchant), merchant=merchant,
            acct_code=acct, note=note, count=20, dominance=dominance,
        ))
        await s.commit()


async def test_ambiguous_seed_falls_through_to_ai(sm, monkeypatch):
    """아고다 회귀 — 한 계정에 항공·숙박이 섞여 dominance 가 낮으면 최빈 seed 를 확정하지 않는다."""
    async def fake_gen(merchant: str, acct_name: str):
        return "해외출장 경비(법인카드)", "test-model"

    monkeypatch.setattr(card_learning, "_ai_note_generate", fake_gen)
    await _add_seed(sm, "아고다상점", "AMB1", "해외출장 교통비(법인카드)", 0.31)
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="아고다상점", acct_code="AMB1",
            acct_name="여비교통비-해외출장", ai_on_ambiguous_seed=True,
        )
    assert res == {"note": "해외출장 경비(법인카드)", "source": "ai"}


async def test_dominant_seed_still_wins_without_ai(sm, monkeypatch):
    """dominance 가 임계 이상이면 종전대로 seed 확정 — AI 는 호출되지 않는다."""
    async def boom(*a, **k):
        raise AssertionError("지배적 seed 인데 AI 가 호출됨")

    monkeypatch.setattr(card_learning, "_ai_note_generate", boom)
    await _add_seed(sm, "단일용도상점", "DOM1", "주차료(법인카드)", card_learning.SEED_NOTE_MIN_DOMINANCE)
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="단일용도상점", acct_code="DOM1",
            acct_name="여비교통비-국내출장", ai_on_ambiguous_seed=True,
        )
    assert res == {"note": "주차료(법인카드)", "source": "seed"}


async def test_ambiguous_seed_without_optin_skips_ai(sm, monkeypatch):
    """opt-in 없으면(기본 배치 아님) 저신뢰 seed 도 AI 를 안 태우고 category·heuristic 로 폴백."""
    async def boom(*a, **k):
        raise AssertionError("opt-in 없는데 AI 가 호출됨")

    monkeypatch.setattr(card_learning, "_ai_note_generate", boom)
    await _add_seed(sm, "옵트인없음상점", "AMB2", "해외출장 교통비(법인카드)", 0.2)
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="옵트인없음상점", acct_code="AMB2",
            acct_name="여비교통비-해외출장",
        )
    assert res["source"] != "ai"


async def test_ambiguous_seed_ai_failure_falls_back(sm, monkeypatch):
    """AI 생성이 실패해도 런을 죽이지 않고 category·heuristic 로 내려간다."""
    async def none_gen(*a, **k):
        return None

    monkeypatch.setattr(card_learning, "_ai_note_generate", none_gen)
    await _add_seed(sm, "에이아이실패상점", "AMB3", "해외출장 교통비(법인카드)", 0.2)
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="에이아이실패상점", acct_code="AMB3",
            acct_name="여비교통비-해외출장", ai_on_ambiguous_seed=True,
        )
    assert res["source"] in {"category", "heuristic"} and res["note"]


async def test_note_suggest_endpoint_ai_with_acct_name(client, make_user, auth_as, monkeypatch):
    """GET /me/note-suggest?...&acctName → 미학습 조합은 AI 생성(source 'ai')."""
    async def fake_gen(merchant: str, acct_name: str):
        return f"{acct_name}(법인카드)", "test-model"

    monkeypatch.setattr(card_learning, "_ai_note_generate", fake_gen)
    uid = await make_user("ep-ai", "user")
    auth_as(uid)
    r = await client.get(
        "/me/note-suggest",
        params={"merchant": "에이아이엔드", "acct": "EPAI1", "acctName": "회의비"},
    )
    assert r.status_code == 200
    assert r.json() == {"note": "회의비(법인카드)", "source": "ai"}
