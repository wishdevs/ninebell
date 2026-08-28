"""confirm_write — 계획 확정 뒤, ERP 비가역 저장(이동요청 1회 + 발주단위별 구매요청) 직전 확인 게이트.

'저장 진행' 이면 다음 노드(save_move)로, '중단' 이면 write_aborted 로 그래프가 END 로 간다
(실패가 아니라 사용자 결정 — result 로 종료). 무응답(타임아웃)은 중단과 같다.
"""

from __future__ import annotations

import time

from app.live.events import emit_log, emit_step

from .confirm import ask_confirm

STEP = "confirm_write"
TITLE = "ERP 저장 진행 확인"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def summarize_units(plan: dict) -> str:
    lines = []
    for u in plan.get("units") or []:
        mods = ", ".join(str(m.get("name") or m.get("itemCode") or "") for m in (u.get("modules") or []))
        lines.append(f"#{u.get('seq')} 납기 {u.get('dueDate')} · {u.get('purchaseReason')} — [{mods}]")
    return "\n".join(lines)


def make_confirm_write_node():
    async def confirm_write(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        plan = state.get("confirmed_plan") or {}
        units = plan.get("units") or []
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()
        prompt = (
            f"지금부터 ERP 에 실제로 저장합니다(되돌릴 수 없습니다).\n"
            f"① 이동요청 저장 1회(전체 선택, 이동출고=공용자재 → 이동입고=프로젝트)\n"
            f"② 구매요청 저장 {len(units)}회(발주단위별)\n\n{summarize_units(plan)}\n\n"
            "브라우저 화면을 확인한 뒤 진행 여부를 선택하세요."
        )
        value = await ask_confirm(
            state,
            title=TITLE,
            prompt=prompt,
            options=[
                {"value": "yes", "label": "저장 진행", "recommended": True},
                {"value": "no", "label": "저장하지 않고 종료"},
            ],
        )
        if value != "yes":
            msg = "사용자가 ERP 저장을 진행하지 않았습니다 — 계획 확정까지만 완료(저장 0건)."
            await emit_log(events, msg, "warn")
            await emit_step(events, STEP, "done", _ms(t0))
            return {"write_aborted": True, "result": {"plan": plan, "project": state.get("project"), "message": msg}}
        await emit_log(events, f"사용자 확인 — ERP 저장 진행(발주단위 {len(units)}개).", "ok")
        await emit_step(events, STEP, "done", _ms(t0))
        return {}

    return confirm_write
