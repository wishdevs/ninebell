"""출장(국내/자차) 실저장 사이클 스모크 — 그래프 완주(F7 실저장)→검증→삭제 N회 반복.

정책 변경(사용자 지시 2026-07-07): 저장 없는 반복은 무의미 → card e2e 처럼 **실저장(F7)→검증→
삭제** 사이클로 테스트한다. F7 실저장이 테스트에서 명시 승인됨(단 반드시 F6 삭제로 정리, 상신 금지).

⚠ 안전 수칙
  - **삭제까지가 한 사이클** — 삭제 검증(잔존 0) 없이는 다음 사이클 진행 금지.
  - **상신(결재) 절대 금지** — 삭제 불가 상태를 만들지 않는다. F7(저장)·F6(삭제)만.
  - 삭제 가드레일: 결의자(WRT_EMP_NM)=로그인계정 + 결의구분(ABDOCU_FG_CD)=53(출장 국내·자차) +
    미결(DOCU_NO 공백). 하나라도 안 맞으면 **삭제 중단·보고**(테스트 계정 외 전표 보호).
  - 삭제가 한 번이라도 실패하면 사이클 중단하고 전표번호와 함께 즉시 보고.

Usage: cd backend && .venv/bin/python e2e/trip_smoke_cycle.py   (TRIP_SMOKE_CYCLES=1 로 1회 검증 먼저)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.agents import build_trip_domestic_graph  # noqa: E402
from app.agents.card_collect import js as cc_js  # noqa: E402 — MODAL_* JS
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.omnisol import selectors  # noqa: E402
# card e2e 검증 JS 재사용(마스터 조회·덤프·전체선택).
from e2e.e2e_smoke import BTN_BOX_JS, MASTER_DUMP_JS, MASTER_ROWCOUNT_JS, SELECT_MASTER_JS  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
CYCLES = int(os.environ.get("TRIP_SMOKE_CYCLES", "10"))
ART = Path(__file__).resolve().parent / "artifacts"
ART.mkdir(exist_ok=True)
TODAY = _date.today().isoformat()

TRIP_FG = "53"  # 결의구분 출장(국내·자차) 코드(P1 실측).

_TOLL_PARTNER = {"partnerCode": "10512", "partnerName": "한국도로공사"}
_PROJECT = {"code": "1310|1310", "name": "포장개선"}
_DEPARTMENT = "인사/기획팀"
_COST_TYPE = "판관비"
_CAR_CLASSES = ["under1000", "under1600", "under2000", "over2000"]


def _cycle_params(cycle: int) -> dict:
    toll_n = 1 + (cycle % 2)
    rows: list[dict] = []
    for j in range(toll_n):
        rows.append({"type": "toll", **_TOLL_PARTNER, "amount": 12000 + cycle * 500 + j * 3300,
                     "project": dict(_PROJECT), "note": "통행료(현금)"})
    car_class = _CAR_CLASSES[cycle % len(_CAR_CLASSES)]
    km = 50 + (cycle * 25) % 251
    rows.append({"type": "fuel", "km": km, "carClass": car_class, "project": dict(_PROJECT),
                 "note": "국내출장 자차 유류비 지원"})
    return {
        "trip": {"acctDate": TODAY, "rows": rows},
        "department": _DEPARTMENT, "cost_type": _COST_TYPE,
        "fuel_eff_under_1000": 14, "fuel_eff_under_1600": 9,
        "fuel_eff_under_2000": 7, "fuel_eff_over_2000": 6, "fuel_unit_price": 2000,
        "_summary": {"toll_rows": toll_n, "fuel_km": km, "fuel_car_class": car_class},
    }


def _row_is_ours(row: dict) -> bool:
    """삭제 안전 가드 — 결의자=USERID + 결의구분=53(출장 국내·자차) + 미결(DOCU_NO 공백)."""
    writer_ok = str(row.get("WRT_EMP_NM") or "").strip() == USERID
    fg_ok = str(row.get("ABDOCU_FG_CD") or "") == TRIP_FG
    not_posted = not str(row.get("DOCU_NO") or "").strip()
    return writer_ok and fg_ok and not_posted


async def _drive_graph(page, params: dict) -> dict:
    """runner state 주입 미러 + 그래프 ainvoke(실저장 F7 — 몽키패치 없음). 이벤트 수집."""
    events: asyncio.Queue = asyncio.Queue()
    state = {"page": page, "browser": None, "events": events, "userid": USERID,
             "password": PASSWORD, "params": params, "owner": None, "run_id": None}
    graph = build_trip_domestic_graph()
    steps_ms: dict[str, int] = {}
    steps_failed: list[str] = []
    errors: list[str] = []
    task = asyncio.create_task(graph.ainvoke(state))
    while not task.done() or not events.empty():
        try:
            ev = await asyncio.wait_for(events.get(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        if "step" in ev:
            if ev.get("status") in ("done", "failed") and isinstance(ev.get("ms"), int):
                steps_ms[ev["step"]] = ev["ms"]
            if ev.get("status") == "failed":
                steps_failed.append(ev["step"])
        elif ev.get("level") == "error":
            errors.append(ev.get("log") or "")
    final = await task
    return {"steps_ms": steps_ms, "steps_failed": steps_failed, "errors": errors,
            "result": (final or {}).get("result"), "error": (final or {}).get("error")}


async def _query_master(page) -> int:
    """조회(F2) 클릭 후 마스터 rowcount 안정화까지 폴링. 반환 행수(-1=실패)."""
    box = await page.evaluate(BTN_BOX_JS, selectors.BTN_LOOKUP)
    if box:
        await page.mouse.click(box["x"], box["y"])
    else:
        await page.keyboard.press("F2")
    prev, stable, rc = -2, 0, -1
    for _ in range(25):
        await page.wait_for_timeout(800)
        rc = await page.evaluate(MASTER_ROWCOUNT_JS)
        if isinstance(rc, int) and rc >= 0 and rc == prev:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        prev = rc
    return rc if isinstance(rc, int) else -1


async def _verify_and_delete(page, cycle: int) -> dict:
    """저장된 출장 결의를 조회→가드레일 검증→F6 삭제→잔존 0 확인. 반환 진단 dict."""
    out: dict = {"before": None, "all_ours": None, "deleted": False, "after": None,
                 "abdocu_nos": [], "error": None}
    await _query_master(page)
    dump = await page.evaluate(MASTER_DUMP_JS, 0)
    before = dump.get("n", -1)
    out["before"] = before
    rows = dump.get("rows") or []
    out["abdocu_nos"] = [str(r.get("ABDOCU_NO") or "") for r in rows]
    if before <= 0:
        out["error"] = "삭제 대상 0건 — 저장이 안 됐을 수 있음(팬텀 저장?)"
        return out
    all_ours = all(_row_is_ours(r) for r in rows)
    out["all_ours"] = all_ours
    if not all_ours:
        out["error"] = "가드레일 불일치 — 우리 전표가 아닌 행 존재. 삭제 중단."
        out["dump"] = dump
        await page.screenshot(path=str(ART / f"trip_save_c{cycle}_guardrail.png"))
        return out
    await page.evaluate(SELECT_MASTER_JS, 0)
    dbox = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
    if dbox:
        await page.mouse.click(dbox["x"], dbox["y"])
    else:
        await page.keyboard.press("F6")
    for _ in range(8):
        await page.wait_for_timeout(1_200)
        modals = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
        if not modals:
            break
        clicked = False
        for label in ("예", "확인", "삭제"):
            btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, label)
            if btn:
                await page.mouse.click(btn["x"], btn["y"])
                clicked = True
                break
        if not clicked:
            break
    await page.wait_for_timeout(1_000)
    after = await _query_master(page)
    out["after"] = after
    out["deleted"] = after == 0
    if after != 0:
        out["error"] = f"삭제 후 잔존 {after}건 — 수동 정리 필요(전표번호 {out['abdocu_nos']})"
        await page.screenshot(path=str(ART / f"trip_save_c{cycle}_leftover.png"))
    return out


async def _run_one_cycle(browser, cycle: int, warm_state: dict | None) -> dict:
    params = _cycle_params(cycle)
    summary = params.pop("_summary")
    ctx_kwargs = {"viewport": LIVE_VIEWPORT}
    if warm_state is not None:
        ctx_kwargs["storage_state"] = warm_state
    ctx = await browser.new_context(**ctx_kwargs)
    page = await ctx.new_page()
    t0 = time.monotonic()
    saved_state = None
    try:
        r = await _drive_graph(page, params)
        run_ms = int((time.monotonic() - t0) * 1000)
        save_ok = r["error"] is None and "save_doc" in r["steps_ms"] and "save_doc" not in r["steps_failed"]
        post_save = None
        if save_ok:
            await page.wait_for_timeout(800)
            md = await page.evaluate(MASTER_DUMP_JS, 0)
            r0 = (md.get("rows") or [{}])[-1] if md.get("rows") else {}
            # detail 각 행의 금액 필드 덤프(합계 정합 실측 — 거래금액/공급가액/합계).
            detail = await page.evaluate("""() => {
              try { const ds = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
                const n = ds.getRowCount(); const rows = n>0 ? ds.getJsonRows(0,n-1) : [];
                return { n, rows: rows.map(r => ({ SPPRC_AMT2: String(r.SPPRC_AMT2==null?'':r.SPPRC_AMT2),
                  SPPRC_AMT: String(r.SPPRC_AMT==null?'':r.SPPRC_AMT), TOTAL_AMT: String(r.TOTAL_AMT==null?'':r.TOTAL_AMT),
                  PARTNER_NM: String(r.PARTNER_NM==null?'':r.PARTNER_NM),
                  BFC_PARTNER_CD: String(r.BFC_PARTNER_CD==null?'':r.BFC_PARTNER_CD) })) };
              } catch(e){ return { err: String(e).slice(0,80) }; }
            }""")
            post_save = {"n": md.get("n"), "ABDOCU_NO": str(r0.get("ABDOCU_NO") or ""),
                         "DETAIL_SUM_AMT": str(r0.get("DETAIL_SUM_AMT") or ""),
                         "DETAIL_SUM_AMT3": str(r0.get("DETAIL_SUM_AMT3") or ""),
                         "detail_amounts": detail}
        vd = await _verify_and_delete(page, cycle)
        try:
            saved_state = await ctx.storage_state()
        except Exception:  # noqa: BLE001
            saved_state = None
        ok = save_ok and vd.get("deleted") is True
        return {"cycle": cycle, "ok": ok, "run_ms": run_ms, "params_summary": summary,
                "save_ok": save_ok, "post_save": post_save, "result": r["result"], "error": r["error"],
                "steps_ms": r["steps_ms"], "errors": r["errors"], "delete": vd, "_warm_state": saved_state}
    finally:
        await ctx.close()


async def main() -> None:
    print(f"[SMOKE] 실저장 사이클(F7→검증→삭제) 시작. cycles={CYCLES}. ⚠ 상신 금지·삭제 필수.", flush=True)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    cycles: list[dict] = []
    warm_state = None
    aborted = False
    try:
        for i in range(1, CYCLES + 1):
            print(f"\n===== CYCLE {i}/{CYCLES} =====", flush=True)
            try:
                c = await _run_one_cycle(browser, i, warm_state)
            except Exception as exc:  # noqa: BLE001
                c = {"cycle": i, "ok": False, "run_ms": 0, "params_summary": {}, "save_ok": False,
                     "post_save": None, "result": None, "error": f"cycle exception: {exc!r}",
                     "steps_ms": {}, "errors": [], "delete": {}, "_warm_state": None}
            if c.get("_warm_state"):
                warm_state = c["_warm_state"]
            c.pop("_warm_state", None)
            cycles.append(c)
            vd = c.get("delete") or {}
            mark = "PASS" if c["ok"] else "FAIL"
            ps = c["params_summary"]
            print(f"[CYCLE {i}] {mark} run={c['run_ms']/1000:.1f}s | 통행료{ps.get('toll_rows')}행+유류비({ps.get('fuel_car_class')}/{ps.get('fuel_km')}km)", flush=True)
            print(f"[CYCLE {i}] save_ok={c['save_ok']} result={c.get('result')}", flush=True)
            print(f"[CYCLE {i}] post_save={c.get('post_save')}", flush=True)
            print(f"[CYCLE {i}] delete: before={vd.get('before')} all_ours={vd.get('all_ours')} deleted={vd.get('deleted')} after={vd.get('after')} 전표={vd.get('abdocu_nos')}", flush=True)
            if c.get("error"):
                print(f"[CYCLE {i}] run error: {c['error']}", flush=True)
            if vd.get("error") or (c["save_ok"] and not vd.get("deleted")):
                print(f"[CYCLE {i}][ABORT] 삭제 문제 → 사이클 중단. {vd.get('error')}", flush=True)
                aborted = True
                break
    finally:
        await browser.close()
        await pw.stop()

    passed = sum(1 for c in cycles if c["ok"])
    times = [c["run_ms"]/1000 for c in cycles if c["run_ms"] > 0]
    avg = sum(times)/len(times) if times else 0
    print("\n" + "=" * 60, flush=True)
    print(f"TRIP SAVE-CYCLE SUMMARY — {passed}/{len(cycles)} PASS · avg run {avg:.1f}s · aborted={aborted}", flush=True)
    print("=" * 60, flush=True)
    leftover = [c for c in cycles if (c.get('delete') or {}).get('after') not in (0, None)]
    if leftover:
        print("⚠ 잔존 전표 있음:", flush=True)
        for c in leftover:
            print(f"  cycle {c['cycle']}: after={(c['delete'] or {}).get('after')} 전표={(c['delete'] or {}).get('abdocu_nos')}", flush=True)
    else:
        print("잔존 전표 0 확인(모든 사이클 삭제 완료).", flush=True)
    (ART / "trip_smoke_cycle.json").write_text(json.dumps({"cycles": cycles, "aborted": aborted}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n리포트: {ART / 'trip_smoke_cycle.json'}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
