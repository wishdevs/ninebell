"""개입 학습 서비스(card_learning) — 저장·조회·배치 중복 처리.

핵심 회귀: 한 런에 같은 가맹점이 2건 이상이면 (user, norm_merchant) 유니크 위반으로 커밋
전체가 롤백돼 아무것도 저장 안 되던 버그(2026-07-05). 배치 내 중복은 최신 우선 1건으로 접는다.
"""

from __future__ import annotations

from app.services import card_learning


async def test_record_dedupes_duplicate_merchant_in_same_batch(sm, make_user):
    """같은 런에 중복 가맹점(정규화 동일)이 있어도 유니크 위반 없이 최신 선택 1건으로 저장."""
    uid = await make_user("learn-dup", "user")
    owner = str(uid)
    n = await card_learning.record_selections(
        owner,
        [
            # 네이버 2건 — 괄호표기만 다르고 정규화하면 동일 키. 최신(두 번째)이 우선돼야 한다.
            {"merchant": "네이버파이낸셜(주)", "budget": {"code": "B1", "name": "팀"}, "project": None, "note": "첫번째"},
            {"merchant": "네이버파이낸셜㈜", "budget": {"code": "B1", "name": "팀"}, "project": None, "note": "최신적요"},
            {"merchant": "카카오", "budget": {"code": "B2", "name": "팀2"}, "project": None, "note": "카카오적요"},
        ],
    )
    assert n == 2  # 네이버(중복 접힘 1) + 카카오 = 2건

    hits = await card_learning.retrieve_for_merchants(owner, ["네이버파이낸셜(주)", "카카오"])
    naver = hits[card_learning.norm_merchant("네이버파이낸셜(주)")]
    assert naver["note"] == "최신적요"  # 최신 선택 우선
    assert naver["count"] == 1
    assert card_learning.norm_merchant("카카오") in hits


async def test_record_second_run_increments_count(sm, make_user):
    """같은 가맹점을 다음 런에서 다시 확정하면 count++ + 스냅샷 갱신."""
    uid = await make_user("learn-inc", "user")
    owner = str(uid)
    await card_learning.record_selections(
        owner, [{"merchant": "스타벅스 강남", "budget": {"code": "B1", "name": "팀"}, "project": None, "note": "커피"}]
    )
    await card_learning.record_selections(
        owner, [{"merchant": "스타벅스 강남", "budget": {"code": "B9", "name": "새팀"}, "project": None, "note": "간식"}]
    )
    hits = await card_learning.retrieve_for_merchants(owner, ["스타벅스 강남"])
    row = hits[card_learning.norm_merchant("스타벅스 강남")]
    assert row["count"] == 2
    assert row["budget"]["code"] == "B9" and row["note"] == "간식"  # 최신 스냅샷
