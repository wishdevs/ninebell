"""agent_runs 조회 인덱스 + 상태/비용구분 CHECK + 기본 즐겨찾기 부분 유니크.

- ix_agent_runs_started(started_at): 관리자 전체 뷰(user_id 필터 없음) 최신순 정렬 스캔 회피.
- ix_agent_runs_agent_status_started(agent_id, status, started_at): 에이전트×상태 필터
  목록/통계(step_timings 성공 런 최신순 등) 커버.
- CHECK: agent_runs.status / users.status / org_units.cost_type — 코드 전수 조사로 확정한
  실기록 값 집합만 허용(store·session 이 쓰는 running/succeeded/failed/cancelled +
  모델·cancel 경로에 문서화된 waiting; users 는 UserPatch Literal 과 동일한 active/suspended;
  cost_type 은 COST_TYPES 판관비/제조원가 또는 NULL). 위반 기존 데이터는 생성 전 정규화.
⚠ 계획됐던 user_code_favorites (user_id, kind) WHERE is_default 부분 유니크 인덱스는
  이 리비전에서 보류됐다가 **0034 에서 flush 선행 후 도입** — 철회 사유였던
  me_codes.set_default_favorite 의 한 플러시 커밋(UOW 가 UPDATE 를 uuid PK 정렬로 방출해
  대상 지정이 먼저 나가면 즉시 위반)은 형제 해제 루프 직후 flush 선행으로 해소됐고,
  dedupe + 인덱스 생성은 0034_favorite_default_unique 가 수행한다.

모델 __table_args__(agent_run/user/org_unit)에 동일 정의가 반영돼 있어
테스트의 sqlite create_all 경로에도 같은 제약이 걸린다. 운영 마이그레이션 대상은 PG 뿐이라
ALTER ... ADD CONSTRAINT 를 직접 쓴다(SQLite 는 create_all 이 담당, alembic 미적용).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033_run_integrity_checks"
down_revision: str | None = "0031_users_job_title"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_STATUSES = ("running", "waiting", "succeeded", "failed", "cancelled")
_USER_STATUSES = ("active", "suspended")
_COST_TYPES = ("판관비", "제조원가")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # ── ① / ② agent_runs 조회 인덱스 ─────────────────────────────────────────
    op.create_index("ix_agent_runs_started", "agent_runs", ["started_at"])
    op.create_index(
        "ix_agent_runs_agent_status_started", "agent_runs", ["agent_id", "status", "started_at"]
    )

    # ── ③ CHECK — 생성 전에 위반 기존 데이터를 정규화한다 ─────────────────────
    # 알 수 없는 런 상태(크래시 잔존 등)는 실패로 확정한다(진행 중으로 남기면 cancel 경로가 재시도).
    op.execute(
        f"UPDATE agent_runs SET status = 'failed' WHERE status NOT IN ({_in_list(_RUN_STATUSES)})"
    )
    op.create_check_constraint(
        op.f("ck_agent_runs_status"),
        "agent_runs",
        f"status IN ({_in_list(_RUN_STATUSES)})",
    )

    # 알 수 없는 사용자 상태는 active 로 정규화(suspended 오기록보다 잠금 오탐이 더 위험).
    op.execute(
        f"UPDATE users SET status = 'active' WHERE status NOT IN ({_in_list(_USER_STATUSES)})"
    )
    op.create_check_constraint(
        op.f("ck_users_status"),
        "users",
        f"status IN ({_in_list(_USER_STATUSES)})",
    )

    # 알 수 없는 비용구분은 NULL(미지정) 로 정규화 — 카드 자동화의 (판)/(제) 선택은 폴백을 쓴다.
    op.execute(
        "UPDATE org_units SET cost_type = NULL "
        f"WHERE cost_type IS NOT NULL AND cost_type NOT IN ({_in_list(_COST_TYPES)})"
    )
    op.create_check_constraint(
        op.f("ck_org_units_cost_type"),
        "org_units",
        f"cost_type IS NULL OR cost_type IN ({_in_list(_COST_TYPES)})",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_org_units_cost_type"), "org_units", type_="check")
    op.drop_constraint(op.f("ck_users_status"), "users", type_="check")
    op.drop_constraint(op.f("ck_agent_runs_status"), "agent_runs", type_="check")
    op.drop_index("ix_agent_runs_agent_status_started", table_name="agent_runs")
    op.drop_index("ix_agent_runs_started", table_name="agent_runs")
