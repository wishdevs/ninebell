"""AgentRun/AgentTemplate 영속 헬퍼 — 라이브 흐름과 독립된 세션으로 기록·조회한다.

on_terminal 콜백은 SSE 요청과 분리된 펌프 태스크에서 돌아 요청 범위 DB 세션을 쓸 수 없다.
그래서 여기 헬퍼는 `get_sessionmaker()` 로 자체 세션을 열고 커밋한다(요청 수명과 무관).
실행 이력(run history) 목록/상세와 템플릿 CRUD 도 같은 자체-세션 패턴으로 제공한다.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from sqlalchemy.orm.attributes import set_committed_value

from app.db import get_sessionmaker
from app.models import AgentRun, AgentTemplate

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _session_scope(session: AsyncSession | None):
    """조회 헬퍼 공용 세션 스코프 — 주입 세션이 있으면 그대로 쓰고(수명은 호출자 소유),
    없으면 기존처럼 자체 세션을 연다."""
    if session is not None:
        yield session
    else:
        async with get_sessionmaker()() as s:
            yield s


async def create_run(*, run_id: str, agent_id: str, user_id: uuid.UUID) -> None:
    """런 행 생성(이미 있으면 무시 — 재연결/중복 요청 안전)."""
    async with get_sessionmaker()() as s:
        existing = await s.get(AgentRun, run_id)
        if existing is not None:
            return
        s.add(AgentRun(id=run_id, agent_id=agent_id, user_id=user_id, status="running", logs=[]))
        await s.commit()


async def get_run(run_id: str, *, session: AsyncSession | None = None) -> AgentRun | None:
    async with _session_scope(session) as s:
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
    # 방금 끝난 런이 목록 통계(실행수·평균시간)에 즉시 반영되게 캐시를 비운다(지연 import —
    # services.agents 가 무거운 직렬화 의존을 갖고 있어 모듈 로드 시점 결합을 피한다).
    from app.services.agents import invalidate_stats_cache

    invalidate_stats_cache()


async def list_runs(
    *,
    user_id: uuid.UUID | None,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession | None = None,
) -> list[AgentRun]:
    """런 목록(최신순). user_id=None 이면 전체 유저(로깅 뷰 — logs:read 관리자용),
    값이 주어지면 해당 유저로 스코프. agent_id 주어지면 워크플로우로, status 주어지면
    실행 상태로 추가 필터.

    대형 컬럼(logs — 런당 최대 2000프레임 JSON)은 목록 요약에 불필요하므로 로드하지
    않는다(load_only). 요약의 failedStep 이 필요한 **실패 런만** logs 를 별도 쿼리로
    가져와 인스턴스에 채워 둔다(반환 shape 불변 — 실패 런의 .logs 접근은 기존과 동일).
    """
    async with _session_scope(session) as s:
        stmt = select(AgentRun).options(
            load_only(
                AgentRun.id,
                AgentRun.agent_id,
                AgentRun.user_id,
                AgentRun.status,
                AgentRun.started_at,
                AgentRun.finished_at,
                AgentRun.result,  # 요약(resultSummary)에 필요 — logs 만 제외한다.
            )
        )
        if user_id is not None:
            stmt = stmt.where(AgentRun.user_id == user_id)
        if agent_id:
            stmt = stmt.where(AgentRun.agent_id == agent_id)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        stmt = stmt.order_by(AgentRun.started_at.desc()).limit(limit).offset(offset)
        runs = list((await s.execute(stmt)).scalars().all())

        failed_ids = [r.id for r in runs if r.status == "failed"]
        if failed_ids:
            log_rows = (
                await s.execute(
                    select(AgentRun.id, AgentRun.logs).where(AgentRun.id.in_(failed_ids))
                )
            ).all()
            logs_by_id = {rid: lg for rid, lg in log_rows}
            for r in runs:
                if r.status == "failed":
                    # deferred 컬럼을 로드된 값으로 확정 — 세션 종료 후 lazy load 방지.
                    set_committed_value(r, "logs", logs_by_id.get(r.id))
        return runs


async def count_runs(
    *,
    user_id: uuid.UUID | None,
    agent_id: str | None = None,
    status: str | None = None,
    session: AsyncSession | None = None,
) -> int:
    """list_runs 와 동일 필터의 전체 건수(페이지네이션 total 용). LIMIT/OFFSET 없음."""
    async with _session_scope(session) as s:
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
    *, user_id: uuid.UUID, agent_id: str | None = None, session: AsyncSession | None = None
) -> list[AgentTemplate]:
    """현재 유저의 템플릿 목록(최신순). agent_id 주어지면 해당 워크플로우로 필터."""
    async with _session_scope(session) as s:
        stmt = select(AgentTemplate).where(AgentTemplate.user_id == user_id)
        if agent_id:
            stmt = stmt.where(AgentTemplate.agent_id == agent_id)
        stmt = stmt.order_by(AgentTemplate.created_at.desc())
        return list((await s.execute(stmt)).scalars().all())


async def get_template(
    template_id: str, *, session: AsyncSession | None = None
) -> AgentTemplate | None:
    async with _session_scope(session) as s:
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
