"""(가맹점 × 계정) → 적요 데이터 계층(Phase 1) 검증.

card_seed_notes / card_learned_notes 는 기존 가맹점→예산단위 학습과 **별개**로, 같은 가맹점이라도
계정마다 다른 적요를 담는다. 검증: 유니크 제약(계정별 분리), 집계 함수의 (가맹점×계정) 분리,
record_account_notes 의 계정별 upsert·count++, seed 로드·멱등.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import CardLearnedNote, CardSeedNote
from app.services import card_learning
from app.services.seed import _CARD_SEED_NOTES_PATH, seed_card_seed_notes

# 집계 함수는 스크립트에 있다 — scripts 를 경로에 넣고 top-level 모듈로 임포트.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from import_card_seed_notes import aggregate_rows  # noqa: E402


# ─────────────────────────── 집계 함수(순수) ───────────────────────────


def test_aggregate_separates_same_merchant_by_account():
    """같은 가맹점이 두 계정에 나오면 (가맹점 × 계정) 조합이 2행으로 분리되고, 각 계정의 최빈 적요가 붙는다."""
    records = [
        # (merchant, acct_code, acct_name, note, year)
        ("네이버파이낸셜(주)", "81202", "여비교통비-해외", "해외 숙박비", 2025),
        ("네이버파이낸셜㈜", "81202", "여비교통비-해외", "해외 숙박비", 2025),
        ("네이버파이낸셜(주)", "51103", "복리후생비-석식", "야근식대", 2024),
    ]
    rows = aggregate_rows(records)
    by_code = {r["acct_code"]: r for r in rows}
    assert set(by_code) == {"81202", "51103"}
    # 괄호표기만 다른 두 네이버는 정규화로 같은 가맹점 키.
    assert len({r["norm_merchant"] for r in rows}) == 1
    assert by_code["81202"]["note"] == "해외 숙박비"
    assert by_code["81202"]["count"] == 2
    assert by_code["51103"]["note"] == "야근식대"
    assert by_code["51103"]["count"] == 1


def test_aggregate_recency_weighted_most_common_note():
    """같은 (가맹점 × 계정)에서 적요가 갈리면 최근 연도 가중치가 큰 적요가 선정되고 dominance<1."""
    records = [
        ("스타벅스 강남", "81112", "복리후생비-업무", "옛적요", 2023),
        ("스타벅스 강남", "81112", "복리후생비-업무", "옛적요", 2023),
        ("스타벅스 강남", "81112", "복리후생비-업무", "새적요", 2025),  # 2025 가중 4 > 2023×2
    ]
    rows = aggregate_rows(records)
    assert len(rows) == 1
    assert rows[0]["note"] == "새적요"
    assert 0.0 < rows[0]["dominance"] < 1.0
    assert rows[0]["last_year"] == 2025


def test_aggregate_skips_rows_without_acct_code():
    """계정코드 없는 레코드는 (가맹점 × 계정) 모델에 맞지 않아 집계에서 제외."""
    records = [
        ("무계정상점", "", "복리후생비", "적요", 2025),
        ("무계정상점", "  ", "복리후생비", "적요", 2025),
    ]
    assert aggregate_rows(records) == []


# ─────────────────────────── 모델 유니크 제약 ───────────────────────────


async def test_seed_note_unique_on_merchant_acct(sm):
    """card_seed_notes 는 (norm_merchant, acct_code) 유니크 — 같은 조합 중복은 IntegrityError."""
    async with sm() as s:
        s.add(CardSeedNote(norm_merchant="m1", merchant="상점", acct_code="A1", note="n1"))
        await s.commit()
    with pytest.raises(IntegrityError):
        async with sm() as s:
            s.add(CardSeedNote(norm_merchant="m1", merchant="상점", acct_code="A1", note="n2"))
            await s.commit()
    # 같은 가맹점 + 다른 계정은 허용(계정별 분리 저장).
    async with sm() as s:
        s.add(CardSeedNote(norm_merchant="m1", merchant="상점", acct_code="A2", note="n3"))
        await s.commit()
    async with sm() as s:
        cnt = (
            await s.execute(
                select(func.count())
                .select_from(CardSeedNote)
                .where(CardSeedNote.norm_merchant == "m1")
            )
        ).scalar_one()
    assert cnt == 2


async def test_learned_note_unique_on_user_merchant_acct(sm, make_user):
    """card_learned_notes 는 (user_id, norm_merchant, acct_code) 유니크."""
    uid = await make_user("note-uniq", "user")
    async with sm() as s:
        s.add(CardLearnedNote(user_id=uid, norm_merchant="m1", merchant="상점", acct_code="A1"))
        await s.commit()
    with pytest.raises(IntegrityError):
        async with sm() as s:
            s.add(CardLearnedNote(user_id=uid, norm_merchant="m1", merchant="상점", acct_code="A1"))
            await s.commit()


# ─────────────────────────── record_account_notes ───────────────────────────


async def test_record_account_notes_separates_by_account(sm, make_user):
    """같은 가맹점이라도 계정이 다르면 별도 행으로 저장(계정별 적요 분리)."""
    uid = await make_user("note-sep", "user")
    owner = str(uid)
    n = await card_learning.record_account_notes(
        owner,
        [
            {"merchant": "쿠팡", "acct_code": "81103", "acct_name": "복리후생비-석식", "note": "야근식대"},
            {"merchant": "쿠팡", "acct_code": "81202", "acct_name": "여비교통비-해외", "note": "해외교통"},
        ],
    )
    assert n == 2
    async with sm() as s:
        rows = (
            await s.execute(select(CardLearnedNote).where(CardLearnedNote.user_id == uid))
        ).scalars().all()
    by_code = {r.acct_code: r for r in rows}
    assert by_code["81103"].note == "야근식대"
    assert by_code["81202"].note == "해외교통"


async def test_record_account_notes_increments_count_and_updates_note(sm, make_user):
    """같은 (가맹점 × 계정) 재확정은 count++ + 최신 적요 갱신(다른 계정 행은 불변)."""
    uid = await make_user("note-inc", "user")
    owner = str(uid)
    await card_learning.record_account_notes(
        owner, [{"merchant": "김밥천국", "acct_code": "81103", "acct_name": "복리후생비-석식", "note": "중식"}]
    )
    await card_learning.record_account_notes(
        owner, [{"merchant": "김밥천국", "acct_code": "81103", "acct_name": "복리후생비-석식", "note": "야근식대"}]
    )
    async with sm() as s:
        row = (
            await s.execute(
                select(CardLearnedNote).where(
                    CardLearnedNote.user_id == uid, CardLearnedNote.acct_code == "81103"
                )
            )
        ).scalar_one()
    assert row.count == 2
    assert row.note == "야근식대"  # 최신


async def test_record_account_notes_dedupes_same_combo_in_batch(sm, make_user):
    """한 배치에 같은 (가맹점 × 계정)이 2건이면 유니크 위반 없이 최신 1건으로 접힌다."""
    uid = await make_user("note-batchdup", "user")
    owner = str(uid)
    n = await card_learning.record_account_notes(
        owner,
        [
            {"merchant": "네이버파이낸셜(주)", "acct_code": "81202", "acct_name": "여비교통비", "note": "첫번째"},
            {"merchant": "네이버파이낸셜㈜", "acct_code": "81202", "acct_name": "여비교통비", "note": "최신"},
        ],
    )
    assert n == 1
    async with sm() as s:
        row = (
            await s.execute(select(CardLearnedNote).where(CardLearnedNote.user_id == uid))
        ).scalar_one()
    assert row.note == "최신"
    assert row.count == 1


async def test_record_account_notes_skips_missing_acct_code(sm, make_user):
    """계정코드 없는 항목은 skip(방어) — owner 없으면 0."""
    uid = await make_user("note-noacct", "user")
    n = await card_learning.record_account_notes(
        str(uid), [{"merchant": "무계정", "acct_code": "", "note": "적요"}]
    )
    assert n == 0
    assert await card_learning.record_account_notes(None, [{"merchant": "x", "acct_code": "A1"}]) == 0


# ─────────────────────────── seed 로드 ───────────────────────────


async def test_seed_card_seed_notes_loaded_and_idempotent(sm):
    """전사 계정별 적요가 gz 시드 파일 전량으로 적재되고, 재실행해도 중복이 없어야 한다."""
    expected = len(json.loads(gzip.open(_CARD_SEED_NOTES_PATH, "rb").read().decode("utf-8")))
    assert expected > 0  # 시드 파일 비어있지 않음(회귀 방지).

    # sm 픽스처가 seed_all(→ seed_card_seed_notes)을 1회 실행함 → 전량 적재돼 있어야 한다.
    async with sm() as s:
        n1 = (await s.execute(select(func.count()).select_from(CardSeedNote))).scalar_one()
    assert n1 == expected

    # 비어있을 때만 넣으므로 재실행해도 중복 없음.
    async with sm() as s:
        await seed_card_seed_notes(s)
        await s.commit()
    async with sm() as s:
        n2 = (await s.execute(select(func.count()).select_from(CardSeedNote))).scalar_one()
    assert n2 == expected


async def test_seed_notes_capture_multi_account_merchants(sm):
    """시드 데이터에 같은 가맹점이 복수 계정으로 들어간 사례가 실제로 존재한다(Phase 1 목적 검증)."""
    async with sm() as s:
        rows = (await s.execute(select(CardSeedNote.norm_merchant, CardSeedNote.acct_code))).all()
    by_merchant: dict[str, set[str]] = {}
    for norm, acct in rows:
        by_merchant.setdefault(norm, set()).add(acct)
    multi = {m: codes for m, codes in by_merchant.items() if len(codes) >= 2}
    assert len(multi) >= 10  # 실측 217개 — 회귀 방지로 하한만 확인.
