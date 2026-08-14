"""적요 PII 정리(sanitize_note) — 차량번호·사람이름 괄호·개인 물품 상세 제거(card_learning 순수 헬퍼).

사용자 확정(2026-07-22, DB 전수 실측 기반): R1 차량번호(괄호 덩어리+맨몸, 적용 행 한정 오탈자
정정), R2 사람이름 괄호(관용 괄호는 보존), R3 '소모품 구입 (…)' 절단. 멱등 필수.
적대 리뷰 보정(같은 날): R2 다중 이름 나열·'외 N명', R3 관용 괄호 게이트, R1 번호판 한글 명시 목록.
패리티 감시 대상은 **alembic 0023**(최신 복제본) — 0022 는 구규칙 동결(멱등성만 검증).
suggest_note 사다리의 tier 폴스루(순수 PII learned → 다음 tier)도 여기서 검증한다.
"""

import importlib.util
from pathlib import Path

import pytest

from app.services import card_learning
from app.services.card_learning import sanitize_note

# ── 변환 케이스: (원본, 기대 결과) — 사용자 예시 전부 포함 ─────────────────────────────
TRANSFORM_CASES = [
    # R1 차량번호 — 괄호 덩어리 통째 제거.
    ("차량유류비(IMP 157하5208 G80)", "차량유류비"),
    ("차량 유류비(임원실180호5137 GV90)", "차량 유류비"),
    # R1 — 괄호 밖 맨몸 차량번호 제거.
    ("254머8872 차량 검사수수료", "차량 검사수수료"),
    # R1 — 중첩/미닫힘 괄호까지 한 번에 제거.
    ("차량유류비(임원실 159호4288 (팰리세이드)", "차량유류비"),
    # R1 — 오탈자 정정(차랑→차량, R1 적용된 행에 한해).
    ("차랑유류비(175호3757 GV80)", "차량유류비"),
    # R3 — 개인 물품 상세 절단.
    ("소모품 구입 (라센트라 크리넥스)", "소모품 구입"),
    ("소모품 구입 (라센트라 비치용 눈삽)", "소모품 구입"),
    # R2 — (이대훈) 만 제거, (…6명) 인원수 괄호는 보존.
    (
        '"본부 회식(본부 직원 전체 6명)"2022년 신용카드전표 미발행분(이대훈)',
        '"본부 회식(본부 직원 전체 6명)"2022년 신용카드전표 미발행분',
    ),
    # R2 — (천래경) 제거, 나머지 유지.
    ("중국출장 호텔 04.23~04.24(천래경) 500위안", "중국출장 호텔 04.23~04.24 500위안"),
    # R2 — 그 밖의 실측 이름 괄호.
    ("중국출장 숙박(장일환)", "중국출장 숙박"),
    ("출장경비(순천웅)", "출장경비"),
    # R2 — 다중 이름 나열·'외 N명' 꼬리(적대 리뷰 확정 — seed 잔존 6행 원문).
    ("중국출장 숙박(장일환,손용선) 458.19달러", "중국출장 숙박 458.19달러"),
    ("중국출장 숙박(천래경,박건희) 3,676위안", "중국출장 숙박 3,676위안"),
    ("중국출장 숙박(김영일,황성국) 2,688위안", "중국출장 숙박 2,688위안"),
    ("중국출장 숙박(최동수,김정식)", "중국출장 숙박"),
    ("해외출장 부식비(장일환 외 2명)", "해외출장 부식비"),
]

# ── 보존 케이스 — 관용 괄호·판/제 접미사는 절대 건드리지 않는다(회귀 금지) ────────────────
PRESERVE_CASES = [
    "시내출장 주차료 (법인카드)-제품",
    "직원 야근식대(법인카드)-판매",
    "거래처 접대비 (법인카드)-판매",
    "차량유류비-판매",  # 끝의 -판매/-제품 접미사 보존
    "복리후생비-제품",
    "업무추진비(판매)",  # strip_division 이 의존하는 관용 괄호
    # R3 게이트(적대 리뷰 확정) — '소모품 구입' 뒤 관용 괄호는 절단하지 않는다.
    "소모품 구입 (법인카드)-판매",
    # R1 명시 목록(적대 리뷰 확정) — '만'·'년'은 번호판 글자가 아니다(금액/연도 보존).
    "경조사비 10만5000원",
    "2022년1234 결산",
    # R2 — 콤마 없는 공백 나열은 이름 나열이 아니다(인원수 괄호 보존).
    "본부 회식(본부 직원 전체 6명)",
]


@pytest.mark.parametrize("raw,expected", TRANSFORM_CASES)
def test_sanitize_transforms(raw, expected):
    assert sanitize_note(raw) == expected


@pytest.mark.parametrize("note", PRESERVE_CASES)
def test_sanitize_preserves(note):
    assert sanitize_note(note) == note


@pytest.mark.parametrize(
    "raw", [c[0] for c in TRANSFORM_CASES] + PRESERVE_CASES
)
def test_sanitize_idempotent(raw):
    once = sanitize_note(raw)
    assert sanitize_note(once) == once


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_sanitize_empty_inputs(raw):
    assert sanitize_note(raw) is None


def test_sanitize_all_removed_returns_none():
    # 차량번호만 있는 적요 — 전량 제거되면 None(NULL) 이어야 추천 사다리에서 자연 제외된다.
    assert sanitize_note("254머8872") is None


# ── 패리티: alembic 0023(최신 복제본)의 정리 함수가 sanitize_note 와 동일 결과여야 한다 ──────
# 0022 는 구규칙으로 동결된 역사(이미 적용됨) — 앱 규칙과 의도적으로 갈라졌으므로 동등성 단언은
# 제거하고, 리비전 자체의 멱등성(재실행 무해)만 검증한다.
_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_ALL_INPUTS = [c[0] for c in TRANSFORM_CASES] + PRESERVE_CASES + [None, "", "   ", "254머8872"]


def _load_migration_module(filename: str):
    spec = importlib.util.spec_from_file_location(f"mig_{filename[:4]}_sanitize", _VERSIONS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("raw", _ALL_INPUTS)
def test_migration_0023_parity(raw):
    mig = _load_migration_module("0023_resanitize_card_note_pii.py")
    assert mig._sanitize_note(raw) == sanitize_note(raw)


@pytest.mark.parametrize("raw", _ALL_INPUTS)
def test_migration_0022_idempotent(raw):
    # 0022 동등성 단언은 제거 — 구규칙 동결본이라 최신 앱 규칙과 다른 게 정상. 멱등성만 유지 검증.
    mig = _load_migration_module("0022_sanitize_card_note_pii.py")
    once = mig._sanitize_note(raw)
    assert mig._sanitize_note(once) == once


# ── suggest_note tier 폴스루 — learned 가 순수 PII 면 다음 tier(깨끗한 값)로 폴백 ──────────
async def test_suggest_note_falls_through_pure_pii_learned(sm, make_user):
    """learned 적요가 순수 PII('254머8872' → 정리 후 빈값)면 사다리를 끊지 않고 seed 로 폴백."""
    from app.models import CardLearnedNote, CardSeedNote

    uid = await make_user("sug-pii-fall", "user")
    norm = card_learning.norm_merchant("피아이상점")
    async with sm() as s:
        s.add(CardLearnedNote(
            user_id=uid, norm_merchant=norm, merchant="피아이상점", acct_code="PII1", note="254머8872"
        ))
        s.add(CardSeedNote(
            norm_merchant=norm, merchant="피아이상점", acct_code="PII1", note="차량 검사수수료", count=5
        ))
        await s.commit()
    async with sm() as s:
        res = await card_learning.suggest_note(
            s, user_id=uid, merchant="피아이상점", acct_code="PII1"
        )
    assert res == {"note": "차량 검사수수료", "source": "seed"}
