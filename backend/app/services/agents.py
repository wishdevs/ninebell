"""Agent ORM → 프론트 Agent JSON(camelCase) 직렬화.

프론트 `src/lib/data/agents.ts` 타입과 1:1. steps[].id 는 저장 컬럼 `key`,
logs[].at 는 logged_at(ISO), 옵셔널 필드(skill/detail/substeps/intervention/flowGraph)는
값이 있을 때만 포함한다.
"""

from __future__ import annotations

from app.models import Agent, AgentIntervention, AgentLog, AgentStep
from app.services.skills import skill_label


def _serialize_step(step: AgentStep) -> dict:
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
    if step.substeps:
        out["substeps"] = step.substeps
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


def serialize_agent(agent: Agent, *, include_flow: bool = False) -> dict:
    out: dict = {
        "id": agent.id,
        "workflowId": agent.workflow_id,  # 실행 워크플로우 id(없으면 실행 불가) — 프론트 게이트.
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
        "runCount": agent.run_count,
        "successRate": agent.success_rate,
        "avgSeconds": agent.avg_seconds,
        "lastRunAt": agent.last_run_at.isoformat() if agent.last_run_at else None,
        "steps": [_serialize_step(s) for s in agent.steps],
        "logs": [_serialize_log(log) for log in agent.logs],
        "intervention": _serialize_intervention(agent.intervention) if agent.intervention else None,
    }
    if include_flow and agent.flow_graph:
        out["flowGraph"] = agent.flow_graph
    return out
