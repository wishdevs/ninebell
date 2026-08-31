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

STEP = "place_orders"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def targets_from_state(state: dict) -> list[tuple[str, dict, bool]]:
    """(PRQ, unit, prior) 목록 — 이 런의 저장 결과 + 자동 재개(resume) 합류 + 재실행 파라미터.

    prior=True(이전 런 잔여물)는 발주 팝업이 0행이면 '이미 발주됨'으로 보고 스킵한다 — 이 런에서
    막 상신한 PRQ 의 0행(반영 지연)은 여전히 하드 실패다.
    """
    plan = state.get("confirmed_plan") or ((state.get("params") or {}).get("purchase_order") or {}).get("plan") or {}
    units = {int(u.get("seq") or i + 1): u for i, u in enumerate(plan.get("units") or [])}
    po = (state.get("params") or {}).get("purchase_order") or {}
    out: list[tuple[str, dict, bool]] = []
    if po.get("order_prqs"):
        for item in po["order_prqs"]:
            prq, _, seq = str(item).partition("=")
            unit = units.get(int(seq)) if seq.strip().isdigit() else None
            out.append((prq.strip(), unit or {}, True))
        return out
    for p in state.get("purchase_request_nos") or []:
        if p.get("number"):
            out.append((str(p["number"]), units.get(int(p.get("seq") or 0)) or {}, False))
    # 자동 재개 — 이전 런 PRQ 는 그 런의 보관 계획서에서 unit(seq)을 찾는다.
    resume = state.get("resume") or {}
    plan_by_run = resume.get("planByRun") or {}
    have = {prq for prq, _, _ in out}
    for p in resume.get("prqs") or []:
        no = str(p.get("number") or "")
        if not no or no in have:
            continue
        r_plan = plan_by_run.get(str(p.get("runId"))) or {}
        r_units = {int(u.get("seq") or i + 1): u for i, u in enumerate(r_plan.get("units") or [])}
        unit = r_units.get(int(p.get("seq") or 0)) or units.get(int(p.get("seq") or 0)) or {}
        out.append((no, unit, True))
    return out


def make_place_orders_node():
    async def place_orders(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()
        # 디버그 모드 — 상신이 가상(실상신 0)이라 발주 팝업에 요청이 안 뜬다. 저장 자체도 비가역이라
        # 디버그에서는 발주 단계를 통째로 건너뛴다(self_approve 의 debug 게이트와 일관, 2026-08-31).
        debug = bool((state.get("params") or {}).get("debug")) or bool(state.get("debug_mode"))
        if debug:
            await emit_log(events, "디버그 모드 — 구매발주 저장을 건너뜁니다(상신도 가상이므로 발주 불가).", "info")
            await emit_step(events, STEP, "done", _ms(t0))
            return {"purchase_orders": []}
        targets = targets_from_state(state)
        if not targets:
            await emit_log(events, "발주할 구매요청번호가 없어 구매발주일괄입력을 건너뜁니다.", "warn")
            await emit_step(events, STEP, "done", _ms(t0))
            return {"purchase_orders": []}
        missing = [prq for prq, u, _ in targets if not u]
        if missing:
            await emit_step(events, STEP, "failed")
            return {"error": f"계획서 발주단위를 찾지 못한 구매요청 — {missing[:5]} (order_prqs 는 'PRQ=seq' 형식)."}

        # 개입 없음(사용자 확정 2026-08-31) — 계획서 확인 이후는 전부 자동 진행.
        await emit_log(
            events,
            "구매발주 저장 시작 — "
            + ", ".join(f"{prq}(#{u.get('seq')}{', 재개' if prior else ''})" for prq, u, prior in targets)
            + ".",
            "info",
        )

        base = get_settings().erp_base
        today = datetime.now(KST).strftime("%Y-%m-%d")
        done: list[dict] = []
        cur = {"page": page}  # navigate_schema 가 page 를 교체하면 여기에 반영(닫힌 page 재사용 방지)
        for prq, unit, prior in targets:
            seq = unit.get("seq")
            try:
                active = await navigate_schema(page, PURCHASE_PO_BATCH, base, emit=events.put)
                if active is not None:
                    page = active
                    cur["page"] = page
            except Exception as exc:  # noqa: BLE001
                return await _fail(events, t0, done, f"{prq}: 구매발주일괄입력 진입 실패 — {str(exc)[:160]}")
            r = await s3.ensure_po_type(page)
            if not r.get("ok"):
                return await _fail(events, t0, done, f"{prq}: 구매발주유형(원재료) 지정 실패 — {r.get('reason')}")
            r = await s3.open_request_popup(page)
            if not r.get("ok"):
                return await _fail(events, t0, done, f"{prq}: {r.get('reason')}")
            q = await s3.popup_query_prq(page, prq, allow_missing=prior)
            if not q.get("ok"):
                return await _fail(events, t0, done, f"{prq}: {q.get('reason')}")
            if q.get("already"):
                # 'PRQ…: 발주 저장 완료' 는 재개 파서(RE_ORDERED) 규격 문구 — ERP 확인(팝업 0행)을
                # 기록에 남겨야 다음 실행/배너가 이 PRQ 를 완료로 인식한다(기록 자가 보정).
                await emit_log(events, f"{prq}: 발주 저장 완료 — 이전 런에서 발주됨(팝업 잔여 0행). 건너뜁니다.", "info")
                continue
            rows = q["rows"]
            real_idxs = q.get("idxs") or list(range(len(rows)))
            if q.get("foreign"):
                await emit_log(events, f"{prq}: 팝업에 타 요청 잔존 {q['foreign']}행 — 대상 {len(rows)}행만 선택합니다.", "warn")
            # plan_vendor_changes 는 rows 내 위치를 돌려주므로 팝업 그리드 실 인덱스로 변환한다.
            changes = s3.plan_vendor_changes(unit, rows)
            for vendor, poss in changes.items():
                idxs = [real_idxs[p] for p in poss]
                a = await s3.popup_apply_vendor(page, idxs, vendor)
                if not a.get("ok"):
                    return await _fail(events, t0, done, f"{prq}: {a.get('reason')}")
                await emit_log(events, f"{prq}: {vendor} ← {len(idxs)}행 변경거래처 적용(코드 {a.get('codes')}).", "info")
            await emit_shot(events.put, page)
            b = await s3.popup_bottom_apply(page, real_idxs)
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
                # 발주일 이전 납기는 ERP 가 [적용]도 저장도 조용히 거부한다(2026-08-28 실측: 요청 납기
                # 08-21 인 발주단위 #2 저장 무응답) → 발주일(오늘)로 대체하고 경고를 남긴다.
                if (not due) or s3.due_before_today(due, today):
                    await emit_log(events, f"{prq}/{vendor}: 계획 납기 {due or '(없음)'} 가 발주일({today}) 이전이라 납기를 발주일로 대체합니다.", "warn")
                    due = today
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
        return {"purchase_orders": done, "page": cur["page"]}

    async def _fail(events, t0, done, msg):
        await emit_step(events, STEP, "failed")
        return {"error": msg, "purchase_orders": done}

    return place_orders
