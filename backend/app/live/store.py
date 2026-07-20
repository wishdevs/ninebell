"""AgentRun/AgentTemplate 영속 헬퍼 — 라이브 흐름과 독립된 세션으로 기록·조회한다.

on_terminal 콜백은 SSE 요청과 분리된 펌프 태스크에서 돌아 요청 범위 DB 세션을 쓸 수 없다.
그래서 여기 헬퍼는 `get_sessionmaker()` 로 자체 세션을 열고 커밋한다(요청 수명과 무관).
실행 이력(run history) 목록/상세와 템플릿 CRUD 도 같은 자체-세션 패턴으로 제공한다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from app.db import get_sessionmaker
from app.models import AgentRun, AgentTemplate

logger = logging.getLogger(__name__)


async def create_run(*, run_id: str, agent_id: str, user_id: uuid.UUID) -> None:
    """런 행 생성(이미 있으면 무시 — 재연결/중복 요청 안전)."""
    async with get_sessionmaker()() as s:
        existing = await s.get(AgentRun, run_id)
        if existing is not None:
            return
        s.add(AgentRun(id=run_id, agent_id=agent_id, user_id=user_id, status="running", logs=[]))
        await s.commit()


async def get_run(run_id: str) -> AgentRun | None:
    async with get_sessionmaker()() as s:
        return (
            await s.execute(select(AgentRun).where(AgentRun.id == run_id))
        ).scalar_one_or_none()


async def set_terminal(run_id: str, status: str, note: object, logs: list) -> None:
    """흐름 종료 시 최종 상태·결과·로그를 1회 확정한다.

    note 는 문자열(성공/실패 사유) 또는 구조(dict — 대화형 완료 시 selections 포함)일 수
    있다. result 컬럼(JSONVariant)이 둘 다 수용한다.
    """
    async with get_sessionmaker()() as s:
        run = await s.get(AgentRun, run_id)
        if run is None:
            return
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.result = note
        run.logs = logs
        await s.commit()


async def list_runs(
    *,
    user_id: uuid.UUID | None,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[AgentRun]:
    """런 목록(최신순). user_id=None 이면 전체 유저(로깅 뷰 — logs:read 관리자용),
    값이 주어지면 해당 유저로 스코프. agent_id 주어지면 워크플로우로, status 주어지면
    실행 상태로 추가 필터."""
    async with get_sessionmaker()() as s:
        stmt = select(AgentRun)
        if user_id is not None:
            stmt = stmt.where(AgentRun.user_id == user_id)
        if agent_id:
            stmt = stmt.where(AgentRun.agent_id == agent_id)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        stmt = stmt.order_by(AgentRun.started_at.desc()).limit(limit).offset(offset)
        return list((await s.execute(stmt)).scalars().all())


async def count_runs(
    *,
    user_id: uuid.UUID | None,
    agent_id: str | None = None,
    status: str | None = None,
) -> int:
    """list_runs 와 동일 필터의 전체 건수(페이지네이션 total 용). LIMIT/OFFSET 없음."""
    async with get_sessionmaker()() as s:
        stmt = select(func.count()).select_from(AgentRun)
        if user_id is not None:
            stmt = stmt.where(AgentRun.user_id == user_id)
        if agent_id:
            stmt = stmt.where(AgentRun.agent_id == agent_id)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        return (await s.execute(stmt)).scalar_one()


# ── AgentTemplate(대화형 selections 저장·재생) ─────────────────────────────
async def create_template(
    *, template_id: str, agent_id: str, user_id: uuid.UUID, name: str, selections: list
) -> AgentTemplate:
    """템플릿 저장. selections 는 대화형 실행에서 누적한 ChatSelection[]."""
    async with get_sessionmaker()() as s:
        tpl = AgentTemplate(
            id=template_id,
            agent_id=agent_id,
            user_id=user_id,
            name=name,
            selections=selections,
        )
        s.add(tpl)
        await s.commit()
        return tpl


async def list_templates(
    *, user_id: uuid.UUID, agent_id: str | None = None
) -> list[AgentTemplate]:
    """현재 유저의 템플릿 목록(최신순). agent_id 주어지면 해당 워크플로우로 필터."""
    async with get_sessionmaker()() as s:
        stmt = select(AgentTemplate).where(AgentTemplate.user_id == user_id)
        if agent_id:
            stmt = stmt.where(AgentTemplate.agent_id == agent_id)
        stmt = stmt.order_by(AgentTemplate.created_at.desc())
        return list((await s.execute(stmt)).scalars().all())


async def get_template(template_id: str) -> AgentTemplate | None:
    async with get_sessionmaker()() as s:
        return await s.get(AgentTemplate, template_id)


async def delete_template(template_id: str, *, user_id: uuid.UUID) -> bool:
    """소유자 스코프 삭제. 삭제됐으면 True, 대상이 없거나 소유자 불일치면 False."""
    async with get_sessionmaker()() as s:
        result = await s.execute(
            delete(AgentTemplate)
            .where(AgentTemplate.id == template_id)
            .where(AgentTemplate.user_id == user_id)
        )
        await s.commit()
        return (result.rowcount or 0) > 0
