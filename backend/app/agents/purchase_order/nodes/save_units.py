"""save_units — D5 발주단위 반복 저장(화면 ①): 구매요청만 조회 → 발주단위마다 SET 체크(자손 자동 전파,
정확 일치 검증) → 납기예정일 [적용] → 구매사유 입력 → 저장(구매요청번호 PRQ… 1건) → 재조회.

⚠ 체크는 ds 행 공간(checkRow) 만 — 체크 집합이 기대와 다르면 저장 전에 하드 실패(다음 발주단위
오염 방지). 저장 성공 신호 = PRQ 번호 발급 또는 성공 스낵바.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from app.agents.purchase_order import steps, steps_write
from app.agents.purchase_order.params import parse_purchase_order_params
from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

STEP = "save_units"
READ_FIELDS = ["ITEM_CD", "ITEM_NM"]


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


KST = timezone(timedelta(hours=9))


def _digits(s: object) -> str:
    """날짜 비교용 정규화 — 그리드 BFDEDT_DT 는 JS Date(UTC, 예 2026-08-27T15:00Z = KST 08-28)로
    돌아오므로(2026-08-28 실측) datetime 이면 KST 날짜 YYYYMMDD 로, 문자열이면 숫자만 남긴다."""
    if isinstance(s, datetime):
        if s.tzinfo is None:
            s = s.replace(tzinfo=timezone.utc)
        return s.astimezone(KST).strftime("%Y%m%d")
    return re.sub(r"\D", "", str(s or ""))[:8]


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
        # 재실행 보호(e2e/재시도용): 이미 저장된 발주단위 seq 목록은 건너뛴다.
        po = (state.get("params") or {}).get("purchase_order") or {}
        skip_seqs = {int(x) for x in (po.get("skip_units") or []) if str(x).isdigit()}
        po_params = parse_purchase_order_params(state.get("params"))

        for n, unit in enumerate(units, 1):
            seq = unit.get("seq") or n
            if int(seq) in skip_seqs:
                await emit_log(events, f"발주단위 #{seq} — skip_units 로 건너뜁니다(이미 저장됨).", "warn")
                continue
            codes = [str(m.get("itemCode") or "").strip() for m in (unit.get("modules") or [])]
            codes = [c for c in codes if c]
            if not codes:
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 에 모듈 품목코드가 없습니다."}

            # 직전 저장으로 헤더에 PRQ 가 남아 있으면 신규(F3)로 초기화 — 없으면 무동작.
            rh = await steps_write.reset_header_for_new_request(
                page, keyword=po_params.keyword or "", pjt_no=po_params.project_no or ""
            )
            if not rh.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 헤더 초기화 실패 — {rh.get('reason')}", "purchase_request_nos": saved}
            if rh.get("via") == "add":
                await emit_log(events, f"발주단위 #{seq} — 신규(F3)로 구매요청번호 초기화{' + 프로젝트 재적용' if rh.get('project_reapplied') else ''}.", "info")

            q = await steps_write.query_view(page, move_only=False)
            if not q.get("ok"):
                await emit_step(events, STEP, "failed")
                return {"error": f"발주단위 #{seq} 구매요청만 조회 실패 — {q.get('reason')}", "purchase_request_nos": saved}
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
