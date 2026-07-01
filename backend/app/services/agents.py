"""Agent ORM → 프론트 Agent JSON(camelCase) 직렬화.

프론트 `src/lib/data/agents.ts` 타입과 1:1. steps[].id 는 저장 컬럼 `key`,
logs[].at 는 logged_at(ISO), 옵셔널 필드(skill/detail/substeps/intervention/flowGraph)는
값이 있을 때만 포함한다.
"""

from __future__ import annotations

from app.models import Agent, AgentIntervention, AgentLog, AgentStep


def _serialize_step(step: AgentStep) -> dict:
    out: dict = {"id": step.key, "label": step.label, "status": step.status}
    if step.skill:
        out["skill"] = step.skill
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
