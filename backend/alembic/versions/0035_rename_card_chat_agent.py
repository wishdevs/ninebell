"""에이전트 id 변경: card-chat → corporate-card (표시명 '법인카드'와 일치).

Revision ID: 0035_rename_card_chat_agent
Revises: 0034_favorite_default_unique
Create Date: 2026-08-11

`card-chat` 은 구 `expense-card-chat` 그래프 시절의 잔재라 URL(/agents/card-chat)이 업무명과
어긋났다(사용자 지적 2026-08-11). agent id 는 업무명, workflow_id 는 그래프 구현 id 라는
형제 컨벤션(family-event/gyeongjo-grant 등)에 맞춰 id 만 바꾼다 — workflow_id(card-collect)는
그대로라 **런 이력·템플릿·통계는 영향이 없다**(agent_runs.agent_id 에는 workflow_id 가 저장된다).

⚠ 이 마이그레이션이 없으면 데이터가 조용히 사라진다. 기동 시드(seed_all)가 픽스처에 없는
  행을 prune 하므로, 코드만 바꿔 배포하면 구 `card-chat` 행이 삭제되고 자식 FK 가 CASCADE 로
  함께 지워진다:
    · agent_org_access — **조직구분 접근 제한이 통째로 소실 → 전체 허용으로 개방(보안 회귀)**
    · agents.settings — 관리자가 저장한 회계시점 결정일(acct_cutoff_day)이 기본값으로 리셋
    · user_code_favorites(kind='agent', code) — FK 가 없어 삭제되진 않지만 고아가 되어
      홈 '자주쓰는 에이전트'에서 조용히 사라진다

`UPDATE agents SET id=…` 는 자식 FK 에 ON UPDATE CASCADE 가 없어 실패하므로, 순서는
**복사 → 자식 이관 → 구 행 삭제** 다. 엔트리포인트가 alembic 을 먼저 돌리고 그 뒤 앱이
시드를 돌리므로(backend/docker-entrypoint.sh), 이 시점엔 아직 prune 이 일어나지 않았다.

신규 DB(card-chat 행 없음)에서는 전부 0행 처리라 무해하다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035_rename_card_chat_agent"
down_revision: str | Sequence[str] | None = "0034_favorite_default_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ID = "card-chat"
NEW_ID = "corporate-card"


def _move(old: str, new: str) -> None:
    """old → new 로 에이전트 행과 그 참조를 이관한다(양방향 공용)."""
    # 1) 새 행 복사 — **컬럼을 나열하지 않는다**(임시 테이블 경유). agents 스키마가 바뀌어도
    #    깨지지 않고, 실제 테이블에 없는 컬럼(hidden 등 코드 레벨 필드)을 잘못 적을 위험도 없다.
    #    workflow_id 는 UNIQUE 라 NULL 로 비우고, 기동 시드가 픽스처 값으로 채운다
    #    (seed.py 는 row.workflow_id 가 None 일 때만 픽스처 값을 넣는다).
    op.execute(f"CREATE TEMP TABLE _agent_move ON COMMIT DROP AS SELECT * FROM agents WHERE id = '{old}'")
    op.execute(f"UPDATE _agent_move SET id = '{new}', workflow_id = NULL")
    op.execute(
        f"""
        INSERT INTO agents SELECT * FROM _agent_move
        WHERE NOT EXISTS (SELECT 1 FROM agents WHERE id = '{new}')
        """
    )
    # 2) 자식 이관 — 조직 접근 설정(보존 핵심). 복합 PK 충돌은 방어적으로 배제.
    op.execute(
        f"""
        UPDATE agent_org_access SET agent_id = '{new}'
        WHERE agent_id = '{old}'
          AND NOT EXISTS (
              SELECT 1 FROM agent_org_access b
              WHERE b.agent_id = '{new}' AND b.org_unit_id = agent_org_access.org_unit_id
          )
        """
    )
    # 3) 즐겨찾기(FK 없음 — code 문자열 매칭). 같은 사용자에 새 id 행이 이미 있으면 건너뛴다.
    op.execute(
        f"""
        UPDATE user_code_favorites SET code = '{new}'
        WHERE kind = 'agent' AND code = '{old}'
          AND NOT EXISTS (
              SELECT 1 FROM user_code_favorites b
              WHERE b.user_id = user_code_favorites.user_id AND b.kind = 'agent' AND b.code = '{new}'
          )
        """
    )
    # 4) 구 행 삭제 — steps/logs/interventions 는 CASCADE 로 정리되고 시드가 재생성한다.
    op.execute(f"DELETE FROM agents WHERE id = '{old}'")


def upgrade() -> None:
    _move(OLD_ID, NEW_ID)


def downgrade() -> None:
    _move(NEW_ID, OLD_ID)
