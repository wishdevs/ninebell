"""save_move — D4 이동요청 저장(화면 ①, 1회): 이동요청만 조회 → 전체 선택 → 저장위치 2종 적용 → 저장.

저장위치는 항상 이동출고=공용자재(1100) / 이동입고=프로젝트(1000) 고정(사용자 확정 2026-08-25).
성공 신호 = 이동요청번호(IRQ…) 자동 발급 또는 성공 스낵바. 이동요청 대상 행이 0이면 저장을
건너뛴다(로그로 남김 — 조용히 넘기지 않는다).
"""

from __future__ import annotations

import time

from app.agents.purchase_order import js, steps_write
from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

STEP = "save_move"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_save_move_node():
    async def save_move(state: dict) -> dict:
        if state.get("error") or state.get("write_aborted"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()

        # 재실행 보호(e2e/재시도용): 이동요청이 이미 저장된 프로젝트에서 중복 생성하지 않도록
        # params.purchase_order.skip_move_request 로 이 단계를 건너뛴다.
        po = (state.get("params") or {}).get("purchase_order") or {}
        if po.get("skip_move_request"):
            await emit_log(events, "skip_move_request — 이동요청 저장을 건너뜁니다(이미 저장됨).", "warn")
            await emit_step(events, STEP, "done", _ms(t0))
            return {"move_request_no": None}

        q = await steps_write.query_view(page, move_only=True)
        if not q.get("ok"):
            last = ((q.get("attempts") or [{}])[-1]).get("signature") or {}
            if last.get("count") == 0:
                await emit_log(events, "이동요청 대상 행이 없어 이동요청 저장을 건너뜁니다.", "warn")
                await emit_step(events, STEP, "done", _ms(t0))
                return {"move_request_no": None}
            await emit_step(events, STEP, "failed")
            return {"error": f"이동요청만 조회 실패 — {q.get('reason')}"}
        count = (q.get("signature") or {}).get("count")

        r = await steps_write.check_all(page, True)
        if not r.get("ok") or not (r.get("after") or 0):
            await emit_step(events, STEP, "failed")
            return {"error": f"이동요청 전체 선택 실패 — {r}"}
        checked = (await page.evaluate(js.TREEGRID_CHECKED_ROWS_JS) or {}).get("checked") or []

        for field_id, btn_id, keyword, column, code in steps_write.STORAGE_LOCATIONS:
            p = await steps_write.pick_code_document(page, field_id, keyword)
            if not p.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"저장위치 '{keyword}' 선택 실패 — {p.get('reason')}"}
            a = await steps_write.click_by_id(page, btn_id)
            if not a.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"저장위치 '{keyword}' [적용] 실패 — {a.get('reason')}"}
            vals = await steps_write.read_grid_field(page, [int(i) for i in checked], column)
            hit = sum(1 for v in vals.values() if str(v or "") == code)
            if hit == 0:
                await emit_step(events, STEP, "failed")
                return {"error": f"저장위치 '{keyword}' 적용이 그리드({column}={code})에 반영되지 않았습니다."}
            await emit_log(events, f"{keyword} 적용 — {column}={code} 반영 {hit}행.", "info")

        await emit_shot(events.put, page)
        s = await steps_write.click_save_and_wait(page, steps_write.MOVE_REQ_PREFIX)
        if not s.get("ok"):
            await emit_shot(events.put, page)
            await emit_step(events, STEP, "failed")
            return {"error": f"이동요청 저장 실패 — {s.get('reason')}"}
        no = s.get("number")
        await emit_log(events, f"이동요청 저장 완료 — {count}행, 이동요청번호 {no or '(화면에서 미확인)'}.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, STEP, "done", _ms(t0))
        return {"move_request_no": no}

    return save_move
