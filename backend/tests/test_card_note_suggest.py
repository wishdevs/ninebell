"""계정 인지 적요 리졸버(suggest_note) + 엔드포인트(GET /me/note-suggest) 검증(Phase 2).

리졸버 사다리: learned(개인) > seed(전사 가맹점×계정) > category(계정 최빈, cold-start) >
heuristic(가맹점 키워드) > None. 계정 없으면 1·2·3 스킵하고 heuristic 만. 엔드포인트는 인증 +
merchant 필수·acct 선택 계약을 고정한다. isolated acct 코드를 써 seed_all 실데이터와 충돌하지 않는다.
"""

from __future__ import annotations

import app.agents.card_collect.nodes._shared as cc_shared
from app.models import CardLearnedNote, CardSeedNote
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


async def test_suggest_note_category_cold_start_most_common(sm):
    """처음 보는 가맹점이라도 그 계정의 최빈 적요(count 합 최대)를 category 로 추천."""
    async with sm() as s:
        # 계정 CAT1: '식대'(5+3=8) vs '회식비'(6) → '식대' 최빈.
        s.add(CardSeedNote(norm_merchant="가게A", merchant="가게A", acct_code="CAT1", note="식대", count=5))
        s.add(CardSeedNote(norm_merchant="가게B", merchant="가게B", acct_code="CAT1", note="식대", count=3))
        s.add(CardSeedNote(norm_merchant="가게C", merchant="가게C", acct_code="CAT1", note="회식비", count=6))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=None, merchant="첫방문가맹점XYZ", acct_code="CAT1"
        )
    assert res == {"note": "식대", "source": "category"}


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
