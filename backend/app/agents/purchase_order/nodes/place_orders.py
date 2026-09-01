"""place_orders — 화면 ③ 구매발주일괄입력(PUOORD02000): 발주단위(=PRQ)마다
진입 → 구매발주유형 원재료 → 구매요청 팝업(PRQ 조회) → 의사 거래처 행 변경거래처 적용 →
전체 적용 → 마스터(거래처 1행)별 납기 [적용] + 비고 → 💾 저장(발주번호).

계획서 대응: 가공품/판금품 행 → unit.vendorGroups 의 실거래처, 납기/비고 → vendorGroups[vendor].dueDate/note.
게이트: 저장 전 confirm HITL 1회(발주단위 목록). ⚠ 저장은 되돌릴 수단 없음(사용자 승인 (a) 2026-08-28).

병렬화(2026-09-01 사용자 승인): PRQ 는 상호 독립(세션별 화면 상태·딥링크 재진입 초기화)이라
브라우저 세션 3개 워커 풀이 PRQ 큐를 분담한다 — 같은 계정 동시 3세션 허용은
`e2e/concurrent_session_probe.py` 실측(강제 로그아웃·세션 간 간섭 없음). 워커 부트스트랩
로그인은 **순차**로 한다(동시 로그인 발사는 미실측 — 실측 범위 안에서만 병렬화).
실패 정책: 실패 PRQ 만 기록하고 나머지는 완주 후 종합 보고 — 독립 작업이라 1건 실패가
나머지를 막을 이유가 없다(직렬 시절의 즉시 중단 대체). 재개 파서(purchase_order_resume)
규격 문구('PRQ…: 발주 저장 완료' 등)는 병렬에서도 그대로 남는다.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from app.agents.purchase_order import steps_screen3 as s3
from app.agents.purchase_order.nodes.save_units import KST
from app.agents.purchase_order.parallel import WORKERS, WorkerTracker
from app.agents.purchase_order.parallel import bootstrap_worker_page as _bootstrap_worker_page
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


async def _process_prq(page, prq: str, unit: dict, prior: bool, events, today: str) -> dict:
    """PRQ 1건 처리 — 유형 지정→팝업 조회→변경거래처→하단 적용→행별 납기·비고→저장.

    반환 {"ok": True, "record": {…}|None(스킵)} 또는 {"ok": False, "reason": str}.
    진입(navigate)은 호출부(워커 루프) 책임 — page 교체가 워커 상태라서다.
    """
    r = await s3.ensure_po_type(page)
    if not r.get("ok"):
        return {"ok": False, "reason": f"{prq}: 구매발주유형(원재료) 지정 실패 — {r.get('reason')}"}
    r = await s3.open_request_popup(page)
    if not r.get("ok"):
        return {"ok": False, "reason": f"{prq}: {r.get('reason')}"}
    # 재개 대상(prior)은 0행 = 이미 발주가 지배적(2026-08-31 ETRI-004~006 실측: 22건 전부
    # PUR 발급 완료) — 재시도 2회 + 0행 대기 1초로 잘라 이미 발주 건은 ~3초 안에 스킵한다(사용자 지시).
    # 행이 뜰 거면 보통 1~2초 안에 뜨므로(무필터 조회 실측) 순간 공백 함정 방어에도 족하다.
    q = await s3.popup_query_prq(
        page, prq, tries=2 if prior else 4, allow_missing=prior,
        zero_cap_ms=1_000 if prior else None,
    )
    if not q.get("ok"):
        return {"ok": False, "reason": f"{prq}: {q.get('reason')}"}
    if q.get("already"):
        # 'PRQ…: 발주 저장 완료' 는 재개 파서(RE_ORDERED) 규격 문구 — ERP 확인(팝업 0행)을
        # 기록에 남겨야 다음 실행/배너가 이 PRQ 를 완료로 인식한다(기록 자가 보정).
        await emit_log(events, f"{prq}: 발주 저장 완료 — 이전 런에서 발주됨(팝업 잔여 0행). 건너뜁니다.", "info")
        return {"ok": True, "record": None}
    rows = q["rows"]
    real_idxs = q.get("idxs") or list(range(len(rows)))
    if q.get("foreign"):
        await emit_log(events, f"{prq}: 팝업에 타 요청 잔존 {q['foreign']}행 — 대상 {len(rows)}행만 선택합니다.", "warn")
    # plan_vendor_changes 는 rows 내 위치를 돌려주므로 팝업 그리드 실 인덱스로 변환한다.
    changes = s3.plan_vendor_changes(unit, rows)
    # 품목주거래처 공란 행(계획서 '미지정' 실거래처 미지정)은 하단 적용에서 제외 —
    # ERP 가 이런 행이 섞이면 확인 [예] 후에도 무반응으로 팝업을 유지해 배치 전체가
    # 20s 타임아웃으로 죽는다(2026-09-01 empty_vendor 프로브 실측).
    skip_pos = set(s3.unorderable_positions(unit, rows))
    if skip_pos:
        items = ", ".join(str(rows[p].get("ITEM_CD") or "?") for p in sorted(skip_pos)[:5])
        await emit_log(
            events,
            f"{prq}: 거래처 미지정 {len(skip_pos)}행({items})은 ERP가 하단 적용을 거부해 "
            "발주에서 제외합니다 — 계획서 '미지정' 그룹에 실거래처를 지정하면 포함됩니다.",
            "warn",
        )
    for vendor, poss in changes.items():
        idxs = [real_idxs[p] for p in poss]
        a = await s3.popup_apply_vendor(page, idxs, vendor)
        if not a.get("ok"):
            return {"ok": False, "reason": f"{prq}: {a.get('reason')}"}
        if a.get("retried"):
            await emit_log(
                events,
                f"{prq}: {vendor} 적용 1차가 무반응이라 [적용] 재클릭으로 반영했습니다"
                "(간헐 ERP 무반응 — 2026-09-01 함정).",
                "warn",
            )
        await emit_log(events, f"{prq}: {vendor} ← {len(idxs)}행 변경거래처 적용(코드 {a.get('codes')}).", "info")
    await emit_shot(events.put, page)
    apply_idxs = [ix for p, ix in enumerate(real_idxs) if p not in skip_pos]
    if not apply_idxs:
        # 팝업은 연 채 두어도 다음 PRQ 의 딥링크 재진입이 화면을 초기화한다(D8 실측).
        await emit_log(events, f"{prq}: 발주 가능한 행이 없어(전부 거래처 미지정) 건너뜁니다.", "warn")
        return {"ok": True, "record": None}
    b = await s3.popup_bottom_apply(page, apply_idxs)
    if not b.get("ok"):
        return {"ok": False, "reason": f"{prq}: {b.get('reason')}"}
    masters = await s3.master_rows(page)
    await emit_log(events, f"{prq}: 하단 적용 — 거래처 {len(masters)}행 생성 ({', '.join(str(m.get('PARTNER_NM')) for m in masters)}).", "ok")

    for i, m in enumerate(masters):
        vendor = str(m.get("PARTNER_NM") or "")
        g = s3.vendor_group_for(unit, vendor) or {}
        due = str(g.get("dueDate") or unit.get("dueDate") or "")
        note = str(g.get("note") or "").strip()
        sel = await s3.select_master_row(page, i, vendor=vendor)
        if not sel.get("ok"):
            return {"ok": False, "reason": f"{prq}: {sel.get('reason')}"}
        # 발주일 이전 납기는 ERP 가 [적용]도 저장도 조용히 거부한다(2026-08-28 실측: 요청 납기
        # 08-21 인 발주단위 #2 저장 무응답) → 발주일(오늘)로 대체하고 경고를 남긴다.
        if (not due) or s3.due_before_today(due, today):
            await emit_log(events, f"{prq}/{vendor}: 계획 납기 {due or '(없음)'} 가 발주일({today}) 이전이라 납기를 발주일로 대체합니다.", "warn")
            due = today
        if due:
            d = await s3.apply_due_to_detail(page, due)
            if not d.get("ok"):
                return {"ok": False, "reason": f"{prq}/{vendor}: {d.get('reason')}"}
        note_via = "유지"
        if note and note != str(m.get("RMK_DC") or "").strip():
            n = await s3.set_master_note(page, i, note)
            if not n.get("ok"):
                return {"ok": False, "reason": f"{prq}/{vendor}: {n.get('reason')}"}
            note_via = f"갱신({n.get('via')})"
        await emit_log(events, f"{prq}/{vendor}: 납기 {due or '(유지)'} · 비고 {note_via}{' (계획서 그룹 미매칭 — 발주단위 납기 사용)' if not g else ''}.", "info")
    await emit_shot(events.put, page)
    s = await s3.click_save_orders(page, len(masters))
    if not s.get("ok"):
        await emit_shot(events.put, page)
        return {"ok": False, "reason": f"{prq}: 발주 저장 실패 — {s.get('reason')}"}
    record = {
        "prq": prq,
        "seq": unit.get("seq"),
        "orders": s.get("numbers"),
        "vendors": [str(m.get("PARTNER_NM")) for m in masters],
    }
    await emit_log(events, f"{prq}: 발주 저장 완료 — 발주번호 {s.get('numbers')}.", "ok")
    await emit_shot(events.put, page)
    return {"ok": True, "record": record}


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
        order_pos = {prq: i for i, (prq, _, _) in enumerate(targets)}
        done: list[dict] = []
        errors: list[dict] = []
        main = {"page": page}  # navigate_schema 가 page 를 교체하면 반영(닫힌 page 재사용 방지)

        # ── 워커 부트스트랩 — 메인 페이지 1 + 추가 세션 최대 WORKERS-1(순차 로그인).
        #    상신 단계 세션은 정리 패스에서 이미 종료됐다(2026-09-01 사용자 지시 — 단계 사이
        #    '한 개의 창' 정돈 후 새 세션으로 시작, 꼬임·화면 오염 방지).
        worker_pages: list = [page]
        contexts: list = []
        browser = state.get("browser")
        userid, password = state.get("userid"), state.get("password")
        want_extra = min(WORKERS, len(targets)) - 1
        if want_extra > 0 and browser is not None and userid:
            scale = getattr(page, "_scale", None)
            for _ in range(want_extra):
                try:
                    ctx, wpage = await _bootstrap_worker_page(
                        browser, userid=userid, password=password, base=base, scale=scale
                    )
                except Exception as exc:  # noqa: BLE001 — 워커 하나 실패는 해당 워커만 제외.
                    await emit_log(events, f"병렬 워커 기동 실패 — 해당 세션 없이 진행합니다({str(exc)[:120]}).", "warn")
                    continue
                contexts.append(ctx)
                worker_pages.append(wpage)
            if len(worker_pages) > 1:
                await emit_log(
                    events,
                    f"병렬 발주 — 브라우저 세션 {len(worker_pages)}개가 {len(targets)}건을 분담합니다"
                    "(같은 계정 동시 세션 실측 허용 — concurrent_session_probe).",
                    "info",
                )

        queue: asyncio.Queue = asyncio.Queue()
        for t in targets:
            queue.put_nowait(t)

        # 워커 상태 프레임 — FE 라이브 스테이지가 "세션별 현재 처리 항목" 칩을 그린다(2026-09-01
        # 사용자 요청). 병렬일 때만 방출(단독 직렬 런은 기존 로그로 충분 — 재생 노이즈 방지).
        tracker = WorkerTracker(events, len(worker_pages))
        await tracker.emit()

        async def _worker(wid: int, wpage) -> None:
            page_w = wpage
            while True:
                try:
                    prq, unit, prior = queue.get_nowait()
                except asyncio.QueueEmpty:
                    await tracker.done(wid)
                    return
                await tracker.working(wid, prq, unit.get("seq"))
                try:
                    active = await navigate_schema(page_w, PURCHASE_PO_BATCH, base, emit=events.put, step_id=None)
                    if active is not None:
                        page_w = active
                        if wid == 0:
                            main["page"] = page_w
                except Exception as exc:  # noqa: BLE001
                    errors.append({"prq": prq, "reason": f"{prq}: 구매발주일괄입력 진입 실패 — {str(exc)[:160]}"})
                    await emit_log(events, f"{prq}: 구매발주일괄입력 진입 실패 — 나머지 구매요청은 계속 진행합니다.", "error")
                    continue
                try:
                    r = await _process_prq(page_w, prq, unit, prior, events, today)
                except Exception as exc:  # noqa: BLE001
                    r = {"ok": False, "reason": f"{prq}: 처리 예외 — {str(exc)[:160]}"}
                if r.get("ok"):
                    if r.get("record"):
                        done.append(r["record"])
                else:
                    errors.append({"prq": prq, "reason": str(r.get("reason"))})
                    await emit_log(events, f"{r.get('reason')} — 나머지 구매요청은 계속 진행합니다.", "error")

        try:
            await asyncio.gather(*[_worker(i, wp) for i, wp in enumerate(worker_pages)])
        finally:
            for ctx in contexts:
                try:
                    await ctx.close()
                except Exception:  # noqa: BLE001 — 정리 실패는 결과에 영향 없음.
                    pass

        done.sort(key=lambda rec: order_pos.get(str(rec.get("prq")), len(order_pos)))
        if errors:
            await emit_step(events, STEP, "failed")
            summary = "; ".join(e["reason"] for e in errors[:3])
            if len(errors) > 3:
                summary += f" 외 {len(errors) - 3}건"
            return {
                "error": f"발주 {len(errors)}건 실패({len(done)}건 저장 완료) — {summary}",
                "purchase_orders": done,
                "page": main["page"],
            }
        await emit_step(events, STEP, "done", _ms(t0))
        return {"purchase_orders": done, "page": main["page"]}

    return place_orders
