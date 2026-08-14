"""card 적요 3테이블 PII 재정리 — 0022 규칙의 적대 리뷰 결함 3건 보정(순수 데이터)

Revision ID: 0023_resanitize_card_note_pii
Revises: 0022_sanitize_card_note_pii
Create Date: 2026-07-22

배경: 0022 적용 후 적대 리뷰(2026-07-22)가 규칙 결함을 확정 — 이 리비전이 **수정된 전체 규칙**으로
3테이블을 재정리한다. 0022 는 이미 적용된 역사라 수정하지 않는다(리비전 불변성).
  1) R2 이름 괄호가 단일 이름만 잡아 다중 나열('(장일환,손용선)')·'외 N명' 꼬리가 잔존(seed 6행)
     → 콤마/·// 나열 + '외 N명' 꼬리까지 확장. '(본부 직원 전체 6명)' 콤마 없는 나열은 비매치(보존).
  2) R3 절단이 관용 괄호까지 파괴('소모품 구입 (법인카드)-판매' → '소모품 구입')
     → 관용어 negative lookahead 로 게이트.
  3) R1 차량번호 [가-힣] 이 '만'(10만5000)·'년'(2022년1234)을 포함해 금액/연도 오검출
     → 실제 번호판 한글 명시 목록으로 교체(유니코드 범위 금지).

원본 동기화: app/services/card_learning.sanitize_note 가 원본이며, **이 파일(0023)이 최신 복제본**
이다(0022 주석의 '원본 동기화' 규칙 승계 — 규칙 변경 시 원본과 최신 리비전 양쪽 동기화, 0022 는
구규칙 동결). tests/test_card_note_sanitize.py 의 패리티 테스트가 0023↔원본 동기화를 감시한다.
마이그레이션은 앱 코드 import 없이 자기완결이어야 하므로 규칙 정규식을 파일 안에 복제한다.

동작: op.get_bind() 로 3테이블의 note 를 행 단위 select → 파이썬 정리 → 변경된 행만 UPDATE.
멱등(정리본에 재적용해도 불변 — 재실행 무해). 스키마 변경 없음(순수 데이터).
card_ai_notes.note 는 NOT NULL 이라 전량 정리되면 행 자체를 삭제한다(재생성 가능한 캐시).

downgrade 는 no-op — 제거된 값이 사람이름 등 PII 라 복원 자체가 목적에 반하고,
원문을 어디에도 보관하지 않으므로 복원이 불가능하다(의도된 비가역).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_resanitize_card_note_pii"
down_revision: str | None = "0022_sanitize_card_note_pii"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── 규칙 정규식 복제 — 원본: card_learning.sanitize_note(이 파일이 최신 복제본, 변경 시 양쪽 동기화) ──
# R1 차량번호: '157하5208' 류. 괄호 덩어리는 [^)]* 가 여는 괄호도 삼켜 중첩/미닫힘까지 제거.
# 가운데 글자는 실제 번호판 한글 명시 목록 — [가-힣] 범위는 '만'·'년'을 포함해 금액/연도 오검출.
_PLATE_KO = "[가나다라마거너더러머고노도로모구누두루무버서어저보소오조부수우주바사아자하허호배]"
_PLATE_RE = re.compile(rf"\d{{2,3}}{_PLATE_KO}\d{{4}}")
_PLATE_PAREN_RE = re.compile(rf"\([^)]*\d{{2,3}}{_PLATE_KO}\d{{4}}[^)]*\)?")
# R2 사람이름 괄호: (이대훈)·(장일환,손용선)·(장일환 외 2명) 류 — 관용 괄호는 lookahead 로 보존.
# '(본부 직원 전체 6명)' 콤마 없는 공백 나열은 비매치(보존).
_NAME_PAREN_RE = re.compile(
    r"\((?!법인|신용|불공|판매|제품|제조|판관|기타|공통|해외)"
    r"[가-힣]{2,4}(?:\s*[,·/]\s*[가-힣]{2,4})*(?:\s*외\s*\d+\s*명)?\)"
)
# R3 개인 물품 상세: '소모품 구입 (라센트라 크리넥스)' → '소모품 구입' 절단.
# 관용 괄호는 lookahead 로 게이트 — '소모품 구입 (법인카드)-판매' 는 원문 보존.
_SUPPLY_PREFIX_RE = re.compile(r"^(소모품 ?구입)\s*\((?!법인|신용|불공|판매|제품|제조|판관|기타|공통|해외)")


def _sanitize_note(note: str | None) -> str | None:
    """card_learning.sanitize_note 의 자기완결 복제(최신) — R1·R2·R3 + 후처리, 멱등."""
    if note is None:
        return None
    s = str(note)
    # R1 — 차량번호: 괄호 덩어리 → 괄호 밖 맨몸 순으로 제거.
    r1 = _PLATE_PAREN_RE.sub(" ", s)
    r1 = _PLATE_RE.sub(" ", r1)
    if r1 != s:
        r1 = r1.replace("차랑유류비", "차량유류비")  # 오탈자 정정 — R1 적용된 행에 한해.
    s = r1
    # R2 — 사람이름 괄호 제거(관용 괄호는 lookahead 로 보존).
    s = _NAME_PAREN_RE.sub(" ", s)
    # R3 — '소모품 구입 (…)' 개인 물품 상세 절단(관용 괄호는 게이트로 보존).
    m = _SUPPLY_PREFIX_RE.match(s.strip())
    if m:
        s = m.group(1)
    # 후처리 — 빈 괄호쌍·고아 괄호·연속 공백·양끝 고아 따옴표 정리.
    s = re.sub(r"\(\s*\)", " ", s)
    s = re.sub(r"\s*\(+\s*$", "", s)  # 끝에 남은 여는 괄호 고아
    s = re.sub(r"^\s*\)+\s*", "", s)  # 앞에 남은 닫는 괄호 고아
    s = re.sub(r"\s+", " ", s).strip()
    for q in ('"', "'"):
        if s.count(q) == 1 and (s.startswith(q) or s.endswith(q)):
            s = s.strip(q).strip()
    return s or None


# (테이블명, note NULL 허용 여부) — card_ai_notes.note 만 NOT NULL.
_TABLES: tuple[tuple[str, bool], ...] = (
    ("card_seed_notes", True),
    ("card_learned_notes", True),
    ("card_ai_notes", False),
)


def upgrade() -> None:
    bind = op.get_bind()
    for table, note_nullable in _TABLES:
        rows = bind.execute(
            sa.text(f"SELECT id, note FROM {table} WHERE note IS NOT NULL")  # noqa: S608
        ).fetchall()
        updated = 0
        deleted = 0
        for row_id, note in rows:
            clean = _sanitize_note(note)
            if clean == note:
                continue  # 변경된 행만 UPDATE(멱등 재실행 시 0건).
            if clean is None and not note_nullable:
                # NOT NULL(card_ai_notes) 인데 전량 정리 — 재생성 가능한 캐시라 행을 지운다.
                bind.execute(
                    sa.text(f"DELETE FROM {table} WHERE id = :id"),  # noqa: S608
                    {"id": row_id},
                )
                deleted += 1
                continue
            bind.execute(
                sa.text(f"UPDATE {table} SET note = :note WHERE id = :id"),  # noqa: S608
                {"note": clean, "id": row_id},
            )
            updated += 1
        print(f"[0023] {table}: {updated} updated, {deleted} deleted (scanned {len(rows)})")


def downgrade() -> None:
    """no-op — 제거 대상이 PII(사람이름 등)라 원문을 보관하지 않으며 복원 불가(의도된 비가역)."""
