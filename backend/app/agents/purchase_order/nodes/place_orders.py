"""place_orders — 화면 ③ 구매발주일괄입력(PUOORD02000): 발주단위(=PRQ)마다
진입 → 구매발주유형 원재료 → 구매요청 팝업(PRQ 조회) → 의사 거래처 행 변경거래처 적용 →
전체 적용 → 마스터(거래처 1행)별 납기 [적용] + 비고 → 💾 저장(발주번호).

계획서 대응: 가공품/판금품 행 → unit.vendorGroups 의 실거래처, 납기/비고 → vendorGroups[vendor].dueDate/note.
게이트: 저장 전 confirm HITL 1회(발주단위 목록). ⚠ 저장은 되돌릴 수단 없음(사용자 승인 (a) 2026-08-28).
"""

from __future__ import annotations

import time
from datetime import datetime

from app.agents.purchase_order import steps_screen3 as s3
from app.agents.purchase_order.nodes.save_units import KST
from app.config import get_settings
from app.live.events import emit_log, emit_step
from nbkit.omnisol.menu_schemas import PURCHASE_PO_BATCH
from nbkit.patterns import emit_shot
from nbkit.patterns.menu_navigate_flow import navigate_schema

from .confirm import ask_confirm

STEP = "place_orders"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def targets_from_state(state: dict) -> list[tuple[str, dict]]:
    """(PRQ, unit) 목록 — 저장 루프 결과(purchase_request_nos) 또는 재실행 파라미터(order_prqs 'PRQ=seq')."""
    plan = state.get("confirmed_plan") or ((state.get("params") or {}).get("purchase_order") or {}).get("plan") or {}
    units = {int(u.get("seq") or i + 1): u for i, u in enumerate(plan.get("units") or [])}
    po = (state.get("params") or {}).get("purchase_order") or {}
    out: list[tuple[str, dict]] = []
    if po.get("order_prqs"):
        for item in po["order_prqs"]:
            prq, _, seq = str(item).partition("=")
            unit = units.get(int(seq)) if seq.strip().isdigit() else None
            out.append((prq.strip(), unit or {}))
        return out
    for p in state.get("purchase_request_nos") or []:
        if p.get("number"):
            out.append((str(p["number"]), units.get(int(p.get("seq") or 0)) or {}))
    return out


def make_place_orders_node():
    async def place_orders(state: dict) -> dict:
        if state.get("error") or state.get("write_aborted"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()
        targets = targets_from_state(state)
        if not targets:
            await emit_log(events, "발주할 구매요청번호가 없어 구매발주일괄입력을 건너뜁니다.", "warn")
            await emit_step(events, STEP, "done", _ms(t0))
            return {"purchase_orders": []}
        missing = [prq for prq, u in targets if not u]
        if missing:
            await emit_step(events, STEP, "failed")
            return {"error": f"계획서 발주단위를 찾지 못한 구매요청 — {missing[:5]} (order_prqs 는 'PRQ=seq' 형식)."}

        value = await ask_confirm(
            state,
            title="구매발주 저장 확인",
            prompt=(
                "구매발주일괄입력에서 발주단위별로 거래처 적용·납기·비고를 넣고 저장합니다"
                "(발주번호 발급, 되돌릴 수 없음):\n"
                + "\n".join(f"· {prq} (발주단위 #{u.get('seq')}, 거래처 그룹 {len(u.get('vendorGroups') or [])})" for prq, u in targets)
                + "\n\n브라우저에서 확인한 뒤 선택하세요."
            ),
            options=[
                {"value": "yes", "label": "발주 저장 진행", "recommended": True},
                {"value": "no", "label": "발주하지 않고 종료"},
            ],
        )
        if value != "yes":
            await emit_log(events, "사용자가 발주 저장을 진행하지 않았습니다.", "warn")
            await emit_step(events, STEP, "done", _ms(t0))
            return {"purchase_orders": []}

        base = get_settings().erp_base
        today = datetime.now(KST).strftime("%Y-%m-%d")
        done: list[dict] = []
        for prq, unit in targets:
            seq = unit.get("seq")
            try:
                active = await navigate_schema(page, PURCHASE_PO_BATCH, base, emit=events.put)
                if active is not None:
                    page = active
            except Exception as exc:  # noqa: BLE001
                return await _fail(events, t0, done, f"{prq}: 구매발주일괄입력 진입 실패 — {str(exc)[:160]}")
            r = await s3.ensure_po_type(page)
            if not r.get("ok"):
                return await _fail(events, t0, done, f"{prq}: 구매발주유형(원재료) 지정 실패 — {r.get('reason')}")
            r = await s3.open_request_popup(page)
            if not r.get("ok"):
                return await _fail(events, t0, done, f"{prq}: {r.get('reason')}")
            q = await s3.popup_query_prq(page, prq)
            if not q.get("ok"):
                return await _fail(events, t0, done, f"{prq}: {q.get('reason')}")
            rows = q["rows"]
            changes = s3.plan_vendor_changes(unit, rows)
            for vendor, idxs in changes.items():
                a = await s3.popup_apply_vendor(page, idxs, vendor)
                if not a.get("ok"):
                    return await _fail(events, t0, done, f"{prq}: {a.get('reason')}")
                await emit_log(events, f"{prq}: {vendor} ← {len(idxs)}행 변경거래처 적용(코드 {a.get('codes')}).", "info")
            await emit_shot(events.put, page)
            b = await s3.popup_bottom_apply(page, list(range(len(rows))))
            if not b.get("ok"):
                return await _fail(events, t0, done, f"{prq}: {b.get('reason')}")
            masters = await s3.master_rows(page)
            await emit_log(events, f"{prq}: 하단 적용 — 거래처 {len(masters)}행 생성 ({', '.join(str(m.get('PARTNER_NM')) for m in masters)}).", "ok")

            for i, m in enumerate(masters):
                vendor = str(m.get("PARTNER_NM") or "")
                g = s3.vendor_group_for(unit, vendor) or {}
                due = str(g.get("dueDate") or unit.get("dueDate") or "")
                note = str(g.get("note") or "").strip()
                sel = await s3.select_master_row(page, i, vendor=vendor)
                if not sel.get("ok"):
                    return await _fail(events, t0, done, f"{prq}: {sel.get('reason')}")
                if due and s3.due_before_today(due, today):
                    await emit_log(events, f"{prq}/{vendor}: 계획 납기 {due} 가 발주일({today}) 이전이라 적용하지 않습니다(구매요청 납기 유지).", "warn")
                    due = ""
                if due:
                    d = await s3.apply_due_to_detail(page, due)
                    if not d.get("ok"):
                        return await _fail(events, t0, done, f"{prq}/{vendor}: {d.get('reason')}")
                note_via = "유지"
                if note and note != str(m.get("RMK_DC") or "").strip():
                    n = await s3.set_master_note(page, i, note)
                    if not n.get("ok"):
                        return await _fail(events, t0, done, f"{prq}/{vendor}: {n.get('reason')}")
                    note_via = f"갱신({n.get('via')})"
                await emit_log(events, f"{prq}/{vendor}: 납기 {due or '(유지)'} · 비고 {note_via}{' (계획서 그룹 미매칭 — 발주단위 납기 사용)' if not g else ''}.", "info")
            await emit_shot(events.put, page)
            s = await s3.click_save_orders(page, len(masters))
            if not s.get("ok"):
                await emit_shot(events.put, page)
                return await _fail(events, t0, done, f"{prq}: 발주 저장 실패 — {s.get('reason')}")
            done.append({"prq": prq, "seq": seq, "orders": s.get("numbers"), "vendors": [str(m.get("PARTNER_NM")) for m in masters]})
            await emit_log(events, f"{prq}: 발주 저장 완료 — 발주번호 {s.get('numbers')}.", "ok")
            await emit_shot(events.put, page)

        await emit_step(events, STEP, "done", _ms(t0))
        return {"purchase_orders": done}

    async def _fail(events, t0, done, msg):
        await emit_step(events, STEP, "failed")
        return {"error": msg, "purchase_orders": done}

    return place_orders
