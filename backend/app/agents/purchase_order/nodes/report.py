"""report — 확정된 계획을 결과로 반환하고 끝낸다(Phase A 는 여기까지 — 쓰기 없음).

result = {"plan","project","bomSummary"} — 러너가 result 프레임으로 흘리고 영속한다.
저장(F7)·결재 자동화는 쓰기 실측(Phase B) 후 개방 — handoff 성격의 메시지로 명시한다.
"""

from __future__ import annotations

import time

from app.live.events import emit_log, emit_step

STEP = "report"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_report_node():
    async def report(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()

        plan = state.get("confirmed_plan") or {}
        project = state.get("project") or {}
        summary = state.get("bom_summary") or {}
        units = plan.get("units") or []
        await emit_log(
            events,
            (
                f"발주 계획 확정 — 프로젝트 {project.get('name') or project.get('code')} · "
                f"발주단위 {len(units)}개. 저장 자동화는 쓰기 실측 후 개방됩니다 — "
                "이 실행은 계획 확정까지이며 ERP 에는 아무것도 저장하지 않았습니다."
            ),
            "ok",
        )
        await emit_step(events, STEP, "done", _ms(t0))
        return {
            "result": {
                "plan": plan,
                "project": project,
                "bomSummary": summary,
            }
        }

    return report
