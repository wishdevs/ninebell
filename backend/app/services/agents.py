"""Agent ORM → 프론트 Agent JSON(camelCase) 직렬화.

프론트 `src/lib/data/agents.ts` 타입과 1:1. steps[].id 는 저장 컬럼 `key`,
logs[].at 는 logged_at(ISO), 옵셔널 필드(skill/detail/substeps/intervention/flowGraph)는
값이 있을 때만 포함한다.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentIntervention, AgentLog, AgentRun, AgentStep
from app.services.agent_settings import effective_settings, settings_schema_dicts
from app.services.skills import skill_label

# 실행 통계 기본값(실 이력 없음) — 픽스처 컬럼(옛 목업 23회 등) 대신 이걸 폴백으로 쓴다.
_EMPTY_STATS: dict[str, Any] = {
    "run_count": 0,
    "success_rate": 0.0,
    "avg_seconds": 0,
    "last_run_at": None,
}

# 인프로세스 TTL 캐시(step_timings 패턴) — GET /agents 마다 agent_runs 를 재집계하지
# 않는다. 키는 요청 agent_ids(정렬 tuple), 값은 (기록 시각 monotonic, 결과 dict).
_STATS_CACHE_TTL_SEC = 300.0
_stats_cache: dict[tuple[str, ...], tuple[float, dict[str, dict]]] = {}


def invalidate_stats_cache() -> None:
    """런 종료 시 호출 — 방금 끝난 실행이 TTL(5분)을 기다리지 않고 통계에 반영되게 한다."""
    _stats_cache.clear()


def _finalize(total: int, ok: int, fail: int, last, avg_s: float | None) -> dict:
    """집계 원시값 → 반환 계약(run_count/success_rate/avg_seconds/last_run_at) 공통 변환."""
    terminal = ok + fail
    return {
        "run_count": total,
        "success_rate": round(ok / terminal * 100, 1) if terminal else 0.0,
        "avg_seconds": round(avg_s) if avg_s is not None else 0,
        "last_run_at": last,
    }


async def _stats_sql(db: AsyncSession, agent_ids: list[str]) -> dict[str, dict]:
    """단일 SQL(GROUP BY agent_id + count FILTER + avg(소요초)) 집계 — 운영 PG 주 경로.

    완료 런 평균은 avg 가 NULL(미종료 finished_at) 행을 자동 제외하는 SQL 시맨틱을 쓴다.
    소요초 표현식만 방언 분기: PG 는 extract(epoch, finished-started), SQLite 는
    julianday 차 ×86400 — SQLite 분기는 운영 디스패치(아래 compute_run_stats)에선 타지
    않지만, 테스트가 SQL 경로와 파이썬 폴백의 동일 결과를 실제로 비교할 수 있게 둔다.
    """
    bind = db.bind
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "sqlite":
        dur_s = (func.julianday(AgentRun.finished_at) - func.julianday(AgentRun.started_at)) * 86400.0
    else:
        dur_s = func.extract("epoch", AgentRun.finished_at - AgentRun.started_at)
    rows = (
        await db.execute(
            select(
                AgentRun.agent_id,
                func.count(),
                func.count().filter(AgentRun.status == "succeeded"),
                func.count().filter(AgentRun.status == "failed"),
                func.max(AgentRun.started_at),
                func.avg(dur_s),
            )
            .where(AgentRun.agent_id.in_(agent_ids))
            .group_by(AgentRun.agent_id)
        )
    ).all()
    return {
        agent_id: _finalize(total, ok, fail, last, float(avg_s) if avg_s is not None else None)
        for agent_id, total, ok, fail, last, avg_s in rows
    }


async def _stats_python(db: AsyncSession, agent_ids: list[str]) -> dict[str, dict]:
    """파이썬 집계 폴백 — SQLite(테스트) 등 비 PG 방언용(기존 경로 그대로)."""
    rows = (
        await db.execute(
            select(
                AgentRun.agent_id,
                AgentRun.status,
                AgentRun.started_at,
                AgentRun.finished_at,
            ).where(AgentRun.agent_id.in_(agent_ids))
        )
    ).all()

    agg: dict[str, dict] = {}
    for agent_id, run_status, started_at, finished_at in rows:
        a = agg.setdefault(
            agent_id,
            {"total": 0, "ok": 0, "fail": 0, "last": None, "dur_sum": 0.0, "dur_n": 0},
        )
        a["total"] += 1
        if run_status == "succeeded":
            a["ok"] += 1
        elif run_status == "failed":
            a["fail"] += 1
        if started_at is not None and (a["last"] is None or started_at > a["last"]):
            a["last"] = started_at
        if started_at is not None and finished_at is not None:
            a["dur_sum"] += (finished_at - started_at).total_seconds()
            a["dur_n"] += 1

    return {
        agent_id: _finalize(
            a["total"], a["ok"], a["fail"], a["last"],
            (a["dur_sum"] / a["dur_n"]) if a["dur_n"] else None,
        )
        for agent_id, a in agg.items()
    }


async def compute_run_stats(db: AsyncSession, agent_ids: list[str]) -> dict[str, dict]:
    """agent_runs 실 이력에서 에이전트별 표시 통계를 집계한다(실행수·성공률·평균시간·최근실행).

    - run_count = 전체 실행 수(진행 중 포함), last_run_at = 가장 최근 시작 시각.
    - success_rate = 성공/(성공+실패)×100 — 종료(취소·진행중 제외) 런만. 없으면 0.
    - avg_seconds = 완료(finished_at 있음) 런의 평균 소요(초). 없으면 0.
    PG 는 단일 SQL(GROUP BY) 로 DB 안에서 집계하고(전 행 로드 없음), SQLite(테스트)는
    파이썬 집계 폴백을 쓴다. 결과는 TTL 캐시(300s)로 재사용 — 통계는 표시용이라 5분
    지연을 허용한다(step_timings 와 동일 규율).
    """
    if not agent_ids:
        return {}
    key = tuple(sorted(agent_ids))
    now = time.monotonic()
    hit = _stats_cache.get(key)
    if hit is not None and now - hit[0] < _STATS_CACHE_TTL_SEC:
        return hit[1]

    bind = db.bind
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        result = await _stats_sql(db, agent_ids)
    else:
        result = await _stats_python(db, agent_ids)
    _stats_cache[key] = (now, result)
    return result


def _serialize_step(step: AgentStep, expected_ms: dict[str, int] | None = None) -> dict:
    out: dict = {
        "id": step.key,
        "label": step.label,
        "status": step.status,
        "intervention": step.intervention,
    }
    if step.skill:
        # skill 컬럼은 카탈로그 KEY — 응답에서는 기존 shape 대로 라벨을 유지하고,
        # 키가 필요한 소비자(역인덱스 등)를 위해 skillKey 를 함께 내려준다.
        out["skill"] = skill_label(step.skill)
        out["skillKey"] = step.skill
    if step.detail:
        out["detail"] = step.detail
    if step.phase:
        # 큰 단계(카테고리) 라벨 — 프론트 Phase 아코디언 그룹핑 소스.
        out["phase"] = step.phase
    if step.substeps:
        out["substeps"] = step.substeps
    if expected_ms and step.key in expected_ms:
        # 최근 성공 런 실측 평균(ms) — ETA 타임라인용. 표본 있는 단계만 포함(옵셔널 컨벤션).
        out["expectedMs"] = expected_ms[step.key]
    return out


def _serialize_log(log: AgentLog) -> dict:
    out: dict = {
        "id": log.key,
        "at": log.logged_at.isoformat() if log.logged_at else None,
        "level": log.level,
        "message": log.message,
    }
    if log.step_label:
        out["step"] = log.step_label
    return out


def _serialize_intervention(iv: AgentIntervention) -> dict:
    out: dict = {"kind": iv.kind, "title": iv.title, "prompt": iv.prompt}
    if iv.options:
        out["options"] = iv.options
    if iv.messages:
        out["messages"] = iv.messages
    if iv.placeholder:
        out["placeholder"] = iv.placeholder
    return out


def serialize_agent(
    agent: Agent,
    *,
    stats: dict | None = None,
    include_flow: bool = False,
    step_expected_ms: dict[str, int] | None = None,
) -> dict:
    # 실행 통계는 agent_runs 실 이력 집계(compute_run_stats). 미제공이면 0/None(옛 픽스처 컬럼
    # run_count=23 등은 목업 잔재라 더 이상 표시하지 않는다). last_run_at 은 datetime.
    st = stats or _EMPTY_STATS
    last_run_at = st.get("last_run_at")
    out: dict = {
        "id": agent.id,
        "workflowId": agent.workflow_id,  # 실행 워크플로우 id(없으면 실행 불가) — 프론트 게이트.
        # 소속 그룹(2뎁스 분류) — 목록 섹션·브레드크럼 전용. 단독 에이전트는 null.
        # description 은 목록 섹션 헤더의 설명 한 줄에 쓰인다(없으면 null).
        "group": (
            {"id": agent.group.id, "name": agent.group.name, "description": agent.group.description}
            if agent.group
            else None
        ),
        "name": agent.name,
        "description": agent.description,
        "drive": agent.drive,
        "interaction": agent.interaction,
        "targetSystem": agent.target_system,
        "targetUrl": agent.target_url,
        "status": agent.status,
        "progress": agent.progress,
        "timeoutSeconds": agent.timeout_seconds,
        "elapsedSeconds": agent.elapsed_seconds,
        "currentAction": agent.current_action,
        "runCount": st["run_count"],
        "successRate": st["success_rate"],
        "avgSeconds": st["avg_seconds"],
        "lastRunAt": last_run_at.isoformat() if isinstance(last_run_at, datetime) else None,
        "steps": [_serialize_step(s, step_expected_ms) for s in agent.steps],
        "logs": [_serialize_log(log) for log in agent.logs],
        "intervention": _serialize_intervention(agent.intervention) if agent.intervention else None,
    }
    if agent.handoff_note:
        # 완료 후 사람이 이어서 할 일 — 완료 화면에서 성공 결과와 구분해 안내한다(값 있을 때만).
        out["handoffNote"] = agent.handoff_note
    schema = settings_schema_dicts(agent.id)
    if schema is not None:
        # 세부설정: 실효값(기본값+저장값 오버레이) + 선언 스키마 — 스키마 있는 에이전트만
        # 포함(옵셔널 컨벤션). 스키마는 소량이라 목록·상세 모두 내려도 부담 없다.
        out["settings"] = effective_settings(agent.id, agent.settings)
        out["settingsSchema"] = schema
    if include_flow and agent.flow_graph:
        out["flowGraph"] = agent.flow_graph
    return out
