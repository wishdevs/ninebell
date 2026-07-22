"""에이전트 가시성/실행 게이트 공용 서비스 — agents.py(목록·상세)와 runs.py(실행)가 공유.

이전에는 agents.py 의 _visible 과 runs.py 의 인라인 게이트가 같은 규칙을 이중 구현했고
runs.py 가 agents.py 프라이빗 심볼(_HIDDEN_AGENT_IDS, _is_org_admin)을 직접 import 했다
— 여기로 승격해 단일 소스화(docs/LIST-COMMONALIZATION-BE.md §4).

조직구분 접근 규칙(두 문맥 공통):
- access_configured=false(최초 미설정) = 전체 허용.
- 소속(org_unit) 미지정 사용자는 allow_unassigned 로 허용 여부 결정.
- 그 외에는 AgentOrgAccess 에 (agent, 소속 조직구분) 행이 있어야 허용. admin+ 는 우회.

숨김(hidden=True 픽스처) 취급은 문맥별로 다르다(의도된 비대칭 — 통합하지 않고 보존):
- 목록/상세(visible_agents): 관리자 포함 전원에게 숨긴다(UI 도달 차단, 직접 URL 도 404).
- 실행(ensure_can_run): 비관리자만 차단 — 관리자는 게이트 스모크 실행 허용(도메인 검증 전).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ROLE_ADMIN, ROLE_RANK, role_rank
from app.models import Agent, AgentOrgAccess, User
from app.services.agent_fixtures import AGENT_FIXTURES

# 숨김 에이전트(hidden=True) — 목록/상세/실행에서 제외한다(현재 숨김 대상 0 — 전 에이전트 노출.
# 메커니즘은 유지: 향후 hidden=True 픽스처가 생기면 자동 적용). DB 행·워크플로우 등록은 유지하되
# UI 도달을 막는다(직접 URL 도 404). 픽스처 플래그가 단일 소스.
HIDDEN_AGENT_IDS: frozenset[str] = frozenset(f["id"] for f in AGENT_FIXTURES if f.get("hidden"))


def is_org_admin(user: User) -> bool:
    role_code = user.role.code if user.role is not None else None
    return role_rank(role_code) >= ROLE_RANK[ROLE_ADMIN]


async def accessible_agent_ids(db: AsyncSession, user: User) -> set[str]:
    """user 소속 조직구분이 명시 허용된 agent id 집합(미지정 사용자는 빈 집합)."""
    if not user.org_unit_id:
        return set()
    rows = await db.execute(
        select(AgentOrgAccess.agent_id).where(AgentOrgAccess.org_unit_id == user.org_unit_id)
    )
    return set(rows.scalars())


def is_visible(agent: Agent, user: User, allowed_ids: set[str]) -> bool:
    if not agent.access_configured:
        return True  # 최초(미설정) = 전체 허용.
    if not user.org_unit_id:
        return agent.allow_unassigned
    return agent.id in allowed_ids


async def visible_agents(
    db: AsyncSession, user: User, *, hidden_ids: frozenset[str] = HIDDEN_AGENT_IDS
) -> list[Agent]:
    """user 에게 노출 가능한 에이전트 목록(created_at 순) — 숨김 제외 + user 롤 조직접근 필터.

    hidden_ids 는 라우터 모듈 전역(_HIDDEN_AGENT_IDS)을 호출 시점에 받는다 — 테스트가 합성
    숨김 id 를 라우터 모듈에 monkeypatch 로 주입하는 앵커라서다(test_agent_run_stats.py).
    """
    rows = list((await db.execute(select(Agent).order_by(Agent.created_at.asc()))).scalars().all())
    rows = [a for a in rows if a.id not in hidden_ids]
    if not is_org_admin(user):
        allowed_ids = await accessible_agent_ids(db, user)
        rows = [a for a in rows if is_visible(a, user, allowed_ids)]
    return rows


async def ensure_can_run(
    db: AsyncSession, user: User, agent: Agent, *, hidden_ids: frozenset[str] = HIDDEN_AGENT_IDS
) -> str | None:
    """실행 게이트 — 차단 사유(한국어, 라우터가 그대로 403 body 로 감싼다)를 반환, 통과면 None.

    - 숨김(검증 전) 에이전트는 비관리자 차단(관리자는 게이트 스모크 실행 허용).
    - 조직구분 접근제어: 명시 설정된 에이전트는 user 롤에 한해 소속 조직구분을 검사(admin+ 우회).
      미지정 사용자는 에이전트 접근 설정의 '미지정' 체크(allow_unassigned)로 허용 가능.
    """
    if agent.id in hidden_ids and not is_org_admin(user):
        return "아직 공개되지 않은(검증 전) 에이전트입니다. 관리자만 실행할 수 있습니다."
    if agent.access_configured and not is_org_admin(user):
        if not user.org_unit_id:
            if not agent.allow_unassigned:
                return "조직구분이 지정되지 않아 이 에이전트를 실행할 수 없습니다. 관리자에게 문의하세요."
        else:
            allowed = (
                await db.execute(
                    select(AgentOrgAccess.agent_id).where(
                        AgentOrgAccess.agent_id == agent.id,
                        AgentOrgAccess.org_unit_id == user.org_unit_id,
                    )
                )
            ).first()
            if allowed is None:
                return "이 에이전트를 실행할 권한이 없습니다(조직구분 접근 제한)."
    return None
