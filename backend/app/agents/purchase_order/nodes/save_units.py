"""save_units — D5 발주단위 반복 저장(화면 ①): 구매요청만 조회 → 발주단위마다 SET 체크(자손 자동 전파,
정확 일치 검증) → 납기예정일 [적용] → 구매사유 입력 → 저장(구매요청번호 PRQ… 1건) → 재조회.

⚠ 체크는 ds 행 공간(checkRow) 만 — 체크 집합이 기대와 다르면 저장 전에 하드 실패(다음 발주단위
오염 방지). 저장 성공 신호 = PRQ 번호 발급 또는 성공 스낵바.
"""

from __future__ import annotations

import re
import time

from app.agents.purchase_order import steps, steps_write
from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

STEP = "save_units"
READ_FIELDS = ["ITEM_CD", "ITEM_NM"]


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _digits(s: object) -> str:
    return re.sub(r"\D", "", str(s or ""))


def make_save_units_node():
    async def save_units(state: dict) -> dict:
        if state.get("error") or state.get("write_aborted"):
            return {}
        events = state["events"]
        page = state["page"]
        plan = state.get("confirmed_plan") or {}
        units = plan.get("units") or []
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()
        saved: list[dict] = []

        for n, unit in enumerate(units, 1):
            seq = unit.get("seq") or n
            codes = [str(m.get("itemCode") or "").strip() for m in (unit.get("modules") or [])]
            codes = [c for c in codes if c]
            if not codes:
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 에 모듈 품목코드가 없습니다."}

            q = await steps_write.query_view(page, move_only=False)
            if not q.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 구매요청만 조회 실패 — {q.get('reason')}"}
            read = await steps.read_bom_rows(page, READ_FIELDS)
            rows = read.get("rows") or []
            f = steps_write.find_set_rows(rows, codes)
            if not f.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} — {f.get('reason')}"}
            set_rows = f["rows"]
            expected = sorted({*set_rows, *[d for r in set_rows for d in steps_write.descendant_rows(rows, r)]})
            c = await steps_write.check_rows_exact(page, set_rows, expected)
            if not c.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 모듈 선택 실패 — {c.get('reason')}"}
            leaves = [i for i in expected if i not in set_rows]

            due = str(unit.get("dueDate") or "")
            r = await steps_write.set_text_verified(page, steps_write.DUE_DATE_FIELD, due)
            if not r.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 납기예정일 입력 실패 — {r.get('reason')}"}
            a = await steps_write.click_by_id(page, steps_write.DUE_DATE_APPLY_BTN)
            if not a.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 납기예정일 [적용] 실패 — {a.get('reason')}"}
            vals = await steps_write.read_grid_field(page, leaves or expected, "BFDEDT_DT")
            hit = sum(1 for v in vals.values() if _digits(v) == _digits(due))
            if hit == 0:
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 납기예정일 {due} 이 선택 행(BFDEDT_DT)에 반영되지 않았습니다 — {list(vals.values())[:3]}"}

            reason = str(unit.get("purchaseReason") or "")
            r = await steps_write.set_text_verified(page, steps_write.PURCHASE_REASON_FIELD, reason)
            if not r.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 구매사유 입력 실패 — {r.get('reason')}"}

            await emit_log(
                events,
                f"발주단위 #{seq} 준비 — 모듈 {len(set_rows)}개(행 {len(expected)}) · 납기 {due} 반영 {hit}행 · 사유 '{reason}'. 저장합니다.",
                "info",
            )
            await emit_shot(events.put, page)
            s = await steps_write.click_save_and_wait(page, steps_write.PUR_REQ_PREFIX)
            if not s.get("ok"):
                await emit_shot(events.put, page)
                await emit_step(events, STEP, "failed")
                return {
                    "error": f"발주단위 #{seq} 구매요청 저장 실패 — {s.get('reason')}",
                    "purchase_request_nos": saved,
                }
            no = s.get("number")
            saved.append({"seq": seq, "number": no, "modules": codes, "dueDate": due, "purchaseReason": reason})
            await emit_log(events, f"발주단위 #{seq} 저장 완료 — 구매요청번호 {no or '(미확인)'}.", "ok")
            await emit_shot(events.put, page)

        await emit_step(events, STEP, "done", _ms(t0))
        return {"purchase_request_nos": saved}

    return save_units
