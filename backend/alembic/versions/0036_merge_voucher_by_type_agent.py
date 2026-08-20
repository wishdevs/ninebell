"""외상매출금/외상매입금 병합: voucher-trade-receivable + voucher-trade-payable → voucher-by-type.

Revision ID: 0036_merge_voucher_by_type_agent
Revises: 0035_rename_card_chat_agent
Create Date: 2026-08-20

'유형별 전표조회 승인'(voucher-by-type) 하나로 병합한다 — 전표유형(국내매출/해외매출/내수구매)이
에이전트 분기에서 **실행 전 폼의 다중 선택**으로 바뀌었다. workflow_id 도 voucher-by-type 으로
통합되므로 agent_runs(agent_id 에 workflow_id 저장)의 두 이력도 새 id 로 합친다.

⚠ 이 마이그레이션이 없으면 데이터가 조용히 사라진다(0035 와 동일 근거). 기동 시드(seed_all)가
  픽스처에 없는 행을 prune 하므로, 코드만 바꿔 배포하면 구 두 행이 삭제되고 자식 FK 가
  CASCADE 로 함께 지워진다:
    · agent_org_access — **조직구분 접근 제한이 통째로 소실 → 전체 허용으로 개방(보안 회귀)**
    · user_code_favorites(kind='agent') — 고아가 되어 홈 '자주쓰는 에이전트'에서 조용히 소멸
    · agent_runs — 구 workflow_id 로 남아 새 에이전트 상세의 런 이력/통계에서 사라진다

순서는 0035 와 동일하게 **복사 → 자식 이관 → 구 행 삭제** 다(`UPDATE agents SET id=…` 는
자식 FK 에 ON UPDATE CASCADE 가 없어 실패). 새 행은 매출금(voucher-trade-receivable) 행을
원본으로 복사하고 id/이름/설명을 덮는다. workflow_id 는 UNIQUE 라 NULL 로 비우고 기동 시드가
픽스처 값(voucher-by-type)으로 채운다(seed.py 는 NULL 일 때만 채운다 — 0035 선례).
접근 제한·즐겨찾기는 **두 구 에이전트의 합집합**으로 이관한다(중복은 방어적으로 배제).

신규 DB(구 행 없음)에서는 전부 0행 처리라 무해하고, 재실행(대상 행 이미 존재)도 guard 로 멱등이다.
downgrade 는 best-effort 역이관 — 병합된 행을 두 구 id 로 복원하되, 합쳐진 접근/즐겨찾기/런
이력은 전부 매출금(voucher-trade-receivable/voucher-receivable) 쪽으로 돌린다(분리 근거 소실).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036_merge_voucher_by_type_agent"
down_revision: str | Sequence[str] | None = "0035_rename_card_chat_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_ID = "voucher-by-type"
OLD_RECEIVABLE = "voucher-trade-receivable"
OLD_PAYABLE = "voucher-trade-payable"
NEW_WF = "voucher-by-type"
OLD_WF_RECEIVABLE = "voucher-receivable"
OLD_WF_PAYABLE = "voucher-payable"


def _move_children(old: str, new: str) -> None:
    """old 에이전트의 자식 참조(조직 접근·즐겨찾기)를 new 로 이관한다(중복 방어)."""
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


def upgrade() -> None:
    # 1) 새 행 복사 — **컬럼을 나열하지 않는다**(임시 테이블 경유, 0035 선례). 원본은 매출금 행
    #    우선, 없으면 매입금 행(한쪽만 남은 DB 에서도 자식 이관 전에 새 행이 반드시 존재해야
    #    agent_org_access FK 가 깨지지 않는다). workflow_id 는 UNIQUE 라 NULL 로 비우고 기동
    #    시드가 픽스처 값으로 채운다.
    op.execute(
        f"""
        CREATE TEMP TABLE _agent_merge ON COMMIT DROP AS
        SELECT * FROM agents WHERE id IN ('{OLD_RECEIVABLE}', '{OLD_PAYABLE}')
        ORDER BY (id = '{OLD_RECEIVABLE}') DESC LIMIT 1
        """
    )
    op.execute(
        f"""
        UPDATE _agent_merge SET
            id = '{NEW_ID}',
            workflow_id = NULL,
            name = '유형별 전표조회 승인',
            description = '실행 시 선택한 전표유형(국내매출/해외매출/내수구매)의 미결·전자결재저장 전표를 조회해, 메뉴 필터로 대상을 추린 뒤 전표별 하위(계정정보) 건수를 파악해 묶음 단위로 결제창을 열어 전자결재로 상신합니다.'
        """
    )
    op.execute(
        f"""
        INSERT INTO agents SELECT * FROM _agent_merge
        WHERE NOT EXISTS (SELECT 1 FROM agents WHERE id = '{NEW_ID}')
        """
    )
    # 2) 자식 이관 — 두 구 에이전트의 합집합(보존 핵심: 조직 접근 제한).
    _move_children(OLD_RECEIVABLE, NEW_ID)
    _move_children(OLD_PAYABLE, NEW_ID)
    # 3) 런 이력 통합 — agent_runs.agent_id 에는 **workflow_id** 가 저장된다.
    op.execute(
        f"""
        UPDATE agent_runs SET agent_id = '{NEW_WF}'
        WHERE agent_id IN ('{OLD_WF_RECEIVABLE}', '{OLD_WF_PAYABLE}')
        """
    )
    # 4) 구 행 삭제 — steps/logs/interventions 는 CASCADE 로 정리되고 시드가 재생성한다.
    op.execute(f"DELETE FROM agents WHERE id IN ('{OLD_RECEIVABLE}', '{OLD_PAYABLE}')")


def downgrade() -> None:
    # best-effort: 병합 행을 두 구 id 로 복원(내용은 병합 행 복사, 이름만 구 표기).
    for old_id, old_name in ((OLD_RECEIVABLE, "외상매출금"), (OLD_PAYABLE, "외상매입금")):
        op.execute(
            f"CREATE TEMP TABLE _agent_split_{old_id.replace('-', '_')} ON COMMIT DROP AS "
            f"SELECT * FROM agents WHERE id = '{NEW_ID}'"
        )
        op.execute(
            f"""
            UPDATE _agent_split_{old_id.replace('-', '_')}
            SET id = '{old_id}', workflow_id = NULL, name = '{old_name}'
            """
        )
        op.execute(
            f"""
            INSERT INTO agents SELECT * FROM _agent_split_{old_id.replace('-', '_')}
            WHERE NOT EXISTS (SELECT 1 FROM agents WHERE id = '{old_id}')
            """
        )
    # 합쳐진 접근/즐겨찾기/런 이력은 분리 근거가 없어 전부 매출금 쪽으로 돌린다.
    _move_children(NEW_ID, OLD_RECEIVABLE)
    op.execute(
        f"UPDATE agent_runs SET agent_id = '{OLD_WF_RECEIVABLE}' WHERE agent_id = '{NEW_WF}'"
    )
    op.execute(f"DELETE FROM agents WHERE id = '{NEW_ID}'")
