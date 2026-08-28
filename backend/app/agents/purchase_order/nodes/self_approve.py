"""self_approve — D7 셀프결재(화면 ② 구매요청처리 PUOPRQ00300): 저장된 PRQ 번호마다 조회 →
가드레일(결재상태 '저장' ∧ 결재상신코드 빈칸) → 행 선택 → 결재 아이콘 → EAP 결재창 → 상신.

게이트 3겹: (1) 빌더 allow_submit, (2) params.debug(디버그 모드면 결재창을 열고 닫기만),
(3) 상신 직전 사용자 confirm HITL(헤디드로 직접 보고 승인). ⛔ 보관 버튼은 절대 클릭하지 않는다.
결재라인은 본인만(셀프) — 교차 지정 없음. 상신 성공 판정 = 결재창 닫힘 + 재조회에서 결재상태 변화.
"""

from __future__ import annotations

import time

from app.agents.purchase_order import steps_write
from app.agents.voucher_receivable import steps as voucher_steps
from app.config import get_settings
from app.live.events import emit_log, emit_step
from nbkit.omnisol.menu_schemas import PURCHASE_REQ_PROCESS
from nbkit.patterns import emit_shot
from nbkit.patterns.menu_navigate_flow import navigate_schema

from .confirm import ask_confirm

STEP = "self_approve"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_self_approve_node(*, allow_submit: bool = False):
    async def self_approve(state: dict) -> dict:
        if state.get("error") or state.get("write_aborted"):
            return {}
        events = state["events"]
        page = state["page"]
        # read_bom 이 no_modules 로 남긴 '발주할 모듈 없음' result 는 재실행(submit_prqs) 경로에선
        # 무의미하다 — report 가 최종 result 로 덮어쓴다.
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()
        prqs = [p for p in (state.get("purchase_request_nos") or []) if p.get("number")]
        # 재실행 경로 — 이미 저장된 PRQ 만 상신(graph._after_read_bom 이 여기로 직행시킨다).
        po = (state.get("params") or {}).get("purchase_order") or {}
        if po.get("submit_prqs"):
            prqs = [{"number": str(x).strip(), "seq": "-"} for x in po["submit_prqs"] if str(x).strip()]
        if not prqs:
            await emit_log(events, "상신할 구매요청번호가 없습니다(저장된 PRQ 0건) — 셀프결재를 건너뜁니다.", "warn")
            await emit_step(events, STEP, "done", _ms(t0))
            return {"submitted": []}

        debug = bool((state.get("params") or {}).get("debug")) or bool(state.get("debug_mode"))
        submit_on = allow_submit and not debug
        if allow_submit and not submit_on:
            await emit_log(events, "디버그 모드 — 결재창을 열고 확인만 하며 상신하지 않습니다.", "info")

        try:
            active = await navigate_schema(page, PURCHASE_REQ_PROCESS, get_settings().erp_base, emit=events.put)
            if active is not None:
                page = active
        except Exception as exc:  # noqa: BLE001
            await emit_step(events, STEP, "failed")
            return {"error": f"구매요청처리 화면 진입 실패 — {str(exc)[:160]}"}
        p = await steps_write.ensure_req_plant(page)
        if not p.get("ok"):
            await emit_step(events, STEP, "failed")
            return {"error": f"공장(나인벨) 지정 실패 — {p.get('reason')}"}

        if submit_on:
            value = await ask_confirm(
                state,
                title="셀프결재 상신 확인",
                prompt=(
                    "다음 구매요청을 결재라인 본인만으로 전자결재 상신합니다(보관 미클릭):\n"
                    + "\n".join(f"· {x['number']} (발주단위 #{x['seq']})" for x in prqs)
                    + "\n\n브라우저에서 저장 결과를 확인한 뒤 선택하세요."
                ),
                options=[
                    {"value": "yes", "label": "상신 진행", "recommended": True},
                    {"value": "no", "label": "상신하지 않고 종료"},
                ],
            )
            if value != "yes":
                await emit_log(events, "사용자가 상신을 진행하지 않았습니다 — 구매요청 저장까지 완료.", "warn")
                await emit_step(events, STEP, "done", _ms(t0))
                return {"submitted": []}

        submitted: list[dict] = []
        for x in prqs:
            no = x["number"]
            q = await steps_write.query_request(page, no)
            if not q.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": q.get("reason"), "submitted": submitted}
            row = q["row"]
            guard = steps_write.submit_guard(row)
            if guard:
                await emit_log(events, f"{no}: {guard} — 건너뜁니다.", "warn")
                continue
            if not await steps_write.select_request_row(page, int(row["i"])):
                await emit_step(events, STEP, "failed")
                return {"error": f"{no}: 마스터 행 선택 실패.", "submitted": submitted}
            await emit_shot(events.put, page)
            o = await steps_write.open_request_approval(page)
            if not o.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"{no}: {o.get('reason')}", "submitted": submitted}
            child = o["child"]
            await emit_log(events, f"{no}: 결재창 열림({o.get('selector')}).", "info")
            try:
                top = await voucher_steps.poll_child_ready(child)
                if not top:
                    await emit_step(events, STEP, "failed")
                    return {"error": f"{no}: 결재창 상단 버튼(상신)이 렌더되지 않았습니다.", "submitted": submitted}
                await emit_shot(events.put, child, window="child")
                if not submit_on:
                    await emit_log(events, f"{no}: (가상 상신) 결재창 확인 후 닫습니다.", "info")
                    submitted.append({"number": no, "submitted": False})
                    continue
                s = await voucher_steps.click_child_submit(child)
                if not s.get("ok"):
                    await emit_shot(events.put, child, window="child")
                    await emit_step(events, STEP, "failed")
                    return {"error": f"{no}: 상신 실패 — {s.get('reason')}", "submitted": submitted}
            finally:
                await voucher_steps.close_child(child)
                await voucher_steps.settle_parent_after_child_close(page, child)

            q2 = await steps_write.query_request(page, no)
            row2 = (q2.get("row") or {}) if q2.get("ok") else {}
            st, gw = row2.get("ATHZ_ST_NM"), row2.get("GWDOCU_NO")
            if q2.get("ok") and not steps_write.submit_guard(row2):
                await emit_step(events, STEP, "failed")
                return {"error": f"{no}: 상신 후 재조회에서 결재상태가 여전히 '저장'/상신코드 빈칸입니다.", "submitted": submitted}
            submitted.append({"number": no, "submitted": True, "status": st, "gwdocuNo": gw})
            await emit_log(events, f"{no}: 상신 완료 — 결재상태 {st} · 결재상신코드 {gw or '(미조회)'}.", "ok")
            await emit_shot(events.put, page)

        await emit_step(events, STEP, "done", _ms(t0))
        return {"submitted": submitted, "page": page}

    return self_approve
