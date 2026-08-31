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
        orders = state.get("purchase_orders") or []
        po_nos = [n for o in orders for n in (o.get("orders") or [])]
        await emit_log(
            events,
            (
                f"완료 — 프로젝트 {project.get('name') or project.get('code')} · 발주단위 {len(units)}개 · "
                f"이동요청 {state.get('move_request_no') or '없음'} · 구매요청 {prq_txt} · "
                f"상신 {len(submitted)}건 · 발주 {len(po_nos)}건{(' (' + ', '.join(po_nos) + ')') if po_nos else ''}."
            ),
            "ok",
        )
        await emit_step(events, STEP, "done", _ms(t0))
        # ⚠ 와이어 계약(프론트 types.ts): result 는 **문자열**이다 — dict 를 넣으면 결과 카드가
        #   React child 오류로 터진다(2026-08-31 실측). 구조 데이터는 계획서 보관(purchase_order_plans)
        #   과 런 로그에 이미 있으므로 여기선 사람이 읽는 요약만 반환한다.
        lines = [
            f"프로젝트 {project.get('name') or project.get('code')} — 발주단위 {len(units)}개 처리.",
        ]
        if state.get("move_request_no"):
            lines.append(f"이동요청: {state.get('move_request_no')}")
        if prq_txt != "없음":
            lines.append(f"구매요청: {prq_txt}")
        if submitted:
            lines.append(
                "상신: " + ", ".join(f"{s.get('number')}({s.get('gwdocuNo') or '종결'})" for s in submitted)
            )
        if po_nos:
            lines.append(f"구매발주 {len(po_nos)}건: " + ", ".join(po_nos))
        return {"result": "\n".join(lines)}

    return report
