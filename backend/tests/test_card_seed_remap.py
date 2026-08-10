"""전사 시드 재키잉(remap_seed_notes_to_catalog) 검증.

옛 자료의 5자리 계정과목 코드를 현 ERP 카탈로그(budget_unit)의 9자리 bgacctCd 로, (계정이름 +
제/판)으로 재키잉한다. seed_all 이 실 gz(card_seed_notes)를 채우므로 각 테스트는 대상 표
(card_seed_notes / erp_code_catalog)를 비우고 격리된 시나리오만 넣는다.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from app.models import CardSeedNote, ErpCodeCatalog
from app.services.card_seed_remap import (
    _acct_jp,
    _norm_acct_name,
    remap_seed_notes_to_catalog,
)


# ─────────────────────────── 정규화/제·판 ───────────────────────────
def test_norm_acct_name_strips_jp_and_parentheticals():
    assert _norm_acct_name("(제)복리후생비-석식 (연장근무 식대)") == "복리후생비-석식"
    assert _norm_acct_name("복리후생비-석식") == "복리후생비-석식"
    assert _norm_acct_name("건물 (예산)") == "건물"
    assert _norm_acct_name("(판)여비교통비-해외출장") == "여비교통비-해외출장"


def test_acct_jp_by_leading_digit():
    assert _acct_jp("51103") == "제"  # 제조원가 5xxxx
    assert _acct_jp("811012600") == "판"  # 판관비 8xxxx (9자리에도 유지)
    assert _acct_jp("131000950") is None  # 자산 등 대상 아님
    assert _acct_jp(None) is None


# ─────────────────────────── 재키잉 ───────────────────────────
async def _reset(s):
    await s.execute(delete(CardSeedNote))
    await s.execute(delete(ErpCodeCatalog))


def _cat(code, bgacct_cd, bgacct_nm):
    return ErpCodeCatalog(
        kind="budget_unit", dept="", code=code, name=bgacct_nm,
        extra={"bgacctCd": bgacct_cd, "bgacctNm": bgacct_nm},
    )


async def test_remap_5digit_to_catalog_9digit(sm):
    """5자리 시드가 이름 매칭으로 현 ERP 9자리 코드로 갱신되고 적요는 보존된다."""
    async with sm() as s:
        await _reset(s)
        s.add(_cat("C1", "511002600", "(제)복리후생비-중식"))
        s.add(CardSeedNote(
            norm_merchant="가게", merchant="가게", acct_code="51102",
            acct_name="복리후생비-중식", note="중식대", count=3,
        ))
        await s.commit()
    async with sm() as s:
        stats = await remap_seed_notes_to_catalog(s)
    assert stats["remapped"] == 1
    async with sm() as s:
        row = (await s.execute(select(CardSeedNote))).scalars().one()
    assert row.acct_code == "511002600"
    assert row.note == "중식대"  # 적요는 그대로.


async def test_remap_unmatched_left_unchanged(sm):
    """카탈로그에 이름이 없는 계정(폐지된 총괄계정 등)은 원 코드를 유지한다."""
    async with sm() as s:
        await _reset(s)
        s.add(_cat("C1", "511002600", "(제)복리후생비-중식"))
        s.add(CardSeedNote(
            norm_merchant="가게", merchant="가게", acct_code="51100",
            acct_name="복리후생비", note="복리", count=1,
        ))
        await s.commit()
    async with sm() as s:
        stats = await remap_seed_notes_to_catalog(s)
    assert stats["unmatched"] == 1 and stats["remapped"] == 0
    async with sm() as s:
        row = (await s.execute(select(CardSeedNote))).scalars().one()
    assert row.acct_code == "51100"


async def test_remap_idempotent(sm):
    """이미 정렬된 뒤 재실행하면 아무것도 바꾸지 않는다(skipped)."""
    async with sm() as s:
        await _reset(s)
        s.add(_cat("C1", "511002600", "(제)복리후생비-중식"))
        s.add(CardSeedNote(
            norm_merchant="가게", merchant="가게", acct_code="51102",
            acct_name="복리후생비-중식", note="중식", count=1,
        ))
        await s.commit()
    async with sm() as s:
        await remap_seed_notes_to_catalog(s)
    async with sm() as s:
        stats2 = await remap_seed_notes_to_catalog(s)
    assert stats2["remapped"] == 0 and stats2["skipped"] == 1


async def test_remap_jp_disambiguates_same_name(sm):
    """이름이 같아도 제조(5)/판관(8)은 각자 코드로 — 선두 숫자로 갈린다."""
    async with sm() as s:
        await _reset(s)
        s.add(_cat("C1", "511002600", "(제)복리후생비-중식"))
        s.add(_cat("C2", "811002600", "(판)복리후생비-중식"))
        s.add(CardSeedNote(
            norm_merchant="제조가게", merchant="제조가게", acct_code="51102",
            acct_name="복리후생비-중식", note="제중식", count=1,
        ))
        s.add(CardSeedNote(
            norm_merchant="판관가게", merchant="판관가게", acct_code="81102",
            acct_name="복리후생비-중식", note="판중식", count=1,
        ))
        await s.commit()
    async with sm() as s:
        stats = await remap_seed_notes_to_catalog(s)
    assert stats["remapped"] == 2
    async with sm() as s:
        by_merchant = {
            r.merchant: r.acct_code
            for r in (await s.execute(select(CardSeedNote))).scalars().all()
        }
    assert by_merchant["제조가게"] == "511002600"
    assert by_merchant["판관가게"] == "811002600"


async def test_remap_ambiguous_not_touched(sm):
    """같은 (제/판 + 이름)에 서로 다른 코드가 2개면 다중 → 안전하게 미변경."""
    async with sm() as s:
        await _reset(s)
        s.add(_cat("C1", "511002600", "(제)복리후생비-중식"))
        s.add(_cat("C2", "511009999", "(제)복리후생비-중식"))
        s.add(CardSeedNote(
            norm_merchant="가게", merchant="가게", acct_code="51102",
            acct_name="복리후생비-중식", note="중식", count=1,
        ))
        await s.commit()
    async with sm() as s:
        stats = await remap_seed_notes_to_catalog(s)
    assert stats["ambiguous_skipped"] == 1 and stats["remapped"] == 0
    async with sm() as s:
        row = (await s.execute(select(CardSeedNote))).scalars().one()
    assert row.acct_code == "51102"


async def test_remap_collision_skipped(sm):
    """같은 가맹점이 이미 목표 9자리를 보유하면 유니크 충돌을 피해 미변경한다."""
    async with sm() as s:
        await _reset(s)
        s.add(_cat("C1", "511002600", "(제)복리후생비-중식"))
        s.add(CardSeedNote(
            norm_merchant="가게", merchant="가게", acct_code="511002600",
            acct_name="기존", note="기존적요", count=5,
        ))
        s.add(CardSeedNote(
            norm_merchant="가게", merchant="가게", acct_code="51102",
            acct_name="복리후생비-중식", note="새적요", count=1,
        ))
        await s.commit()
    async with sm() as s:
        stats = await remap_seed_notes_to_catalog(s)
    assert stats["collided"] == 1
    async with sm() as s:
        codes = {r.acct_code for r in (await s.execute(select(CardSeedNote))).scalars().all()}
    assert codes == {"51102", "511002600"}  # 51102 는 충돌로 미변경(기존 511002600 그대로).
