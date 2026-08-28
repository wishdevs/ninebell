"""report — 실행 결과 반환(계획 + 저장된 이동요청/구매요청번호 + 상신 결과).

result = {"plan","project","bomSummary","moveRequestNo","purchaseRequests","submitted"} — 러너가
result 프레임으로 흘리고 영속한다. 화면 ③(구매발주일괄입력)은 아직 자동화 대상이 아니라 handoff 로 명시.
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
        prqs = state.get("purchase_request_nos") or []
        submitted = [s for s in (state.get("submitted") or []) if s.get("submitted")]
        prq_txt = ", ".join(str(p.get("number")) for p in prqs if p.get("number")) or "없음"
        await emit_log(
            events,
            (
                f"완료 — 프로젝트 {project.get('name') or project.get('code')} · 발주단위 {len(units)}개 · "
                f"이동요청 {state.get('move_request_no') or '없음'} · 구매요청 {prq_txt} · "
                f"상신 {len(submitted)}건. 구매발주일괄입력(화면 ③)은 수동으로 진행하세요."
            ),
            "ok",
        )
        await emit_step(events, STEP, "done", _ms(t0))
        return {
            "result": {
                "plan": plan,
                "project": project,
                "bomSummary": summary,
                "moveRequestNo": state.get("move_request_no"),
                "purchaseRequests": prqs,
                "submitted": state.get("submitted") or [],
            }
        }

    return report
