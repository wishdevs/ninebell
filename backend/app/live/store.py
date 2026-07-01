"""AgentRun 영속 헬퍼 — 라이브 흐름과 독립된 세션으로 런 요약을 기록한다.

on_terminal 콜백은 SSE 요청과 분리된 펌프 태스크에서 돌아 요청 범위 DB 세션을 쓸 수 없다.
그래서 여기 헬퍼는 `get_sessionmaker()` 로 자체 세션을 열고 커밋한다(요청 수명과 무관).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import AgentRun

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


async def set_terminal(run_id: str, status: str, note: str | None, logs: list) -> None:
    """흐름 종료 시 최종 상태·결과·로그를 1회 확정한다."""
    async with get_sessionmaker()() as s:
        run = await s.get(AgentRun, run_id)
        if run is None:
            return
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.result = note
        run.logs = logs
        await s.commit()
