"""학자금신청서 실저장 사이클 스모크 — 그래프 완주(F7 실저장)→검증→삭제 N회 반복.

gyeongjo_smoke_cycle.py(경조금) 포팅. 정책은 동일: 저장 없는 반복은 무의미 → **실저장(F7)→검증→
삭제** 사이클로 테스트한다. F7 실저장이 테스트에서 명시 승인됨(단 반드시 F6 삭제로 정리, 상신 금지).

학자금 델타(경조금 대비): 결의구분 HAKJAGUM_FG(라벨 "학자금신청서" — 코드는 hakjagum_probe.py
실측 후 확정) · 단건 params(hakjagum 네임스페이스) · **근속<1년 50% 규칙 없음** — baseAmount 정액이
그대로 공급가액(SPPRC_AMT2)으로 저장되는지 사이클마다 검증(expected=base). **상대계정거래처는
불필요(경조금 동형 가정)** — fill 노드가 register_counter_partner·delete_blank_row 를 호출하지
않으므로 BFC_PARTNER_CD 는 검사하지 않는다. 대신 그 스텝이 만들던 **스트레이 빈 행이 없어야
한다** — 사이클마다 detail 행수(=1)로 검증한다.

⚠ 안전 수칙
  - **삭제까지가 한 사이클** — 삭제 검증(잔존 0) 없이는 다음 사이클 진행 금지.
  - **상신(결재) 절대 금지** — 삭제 불가 상태를 만들지 않는다. F7(저장)·F6(삭제)만.
  - 삭제 가드레일: 결의자(WRT_EMP_NM)=로그인계정 + 결의구분(ABDOCU_FG_CD)=HAKJAGUM_FG(학자금신청서) +
    미결(DOCU_NO 공백). 하나라도 안 맞으면 **삭제 중단·보고**(테스트 계정 외 전표 보호).
  - 삭제가 한 번이라도 실패하면 사이클 중단하고 전표번호와 함께 즉시 보고.
  - **cycle 1 안전 게이트**: 첫 사이클에서 저장 금액 불일치 또는 스트레이 빈 행이 보이면(fill 노드
    회귀) 나머지 사이클을 진행하지 않고 즉시 중단·보고한다.
  - **프로브 선행 게이트**: HAKJAGUM_FG 가 실측 전 placeholder("TODO_PROBE")면 즉시 실패 종료
    (삭제 가드레일이 결의구분 코드 대조를 요구 — 실측 없이 실행하면 가드가 무력화된다).

Usage: cd backend && HAKJAGUM_SMOKE_CYCLES=10 .venv/bin/python e2e/hakjagum_smoke_cycle.py
  (HAKJAGUM_SMOKE_CYCLES 미지정 시 기본 1 — 단발 검증용)
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

from app.agents import build_hakjagum_grant_graph  # noqa: E402
from app.agents.card_collect import js as cc_js  # noqa: E402 — MODAL_* JS
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.omnisol import selectors  # noqa: E402
# card e2e 검증 JS 재사용(마스터 조회·덤프·전체선택).
from e2e.e2e_smoke import BTN_BOX_JS, MASTER_DUMP_JS, MASTER_ROWCOUNT_JS, SELECT_MASTER_JS  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
CYCLES = int(os.environ.get("HAKJAGUM_SMOKE_CYCLES", "1"))
ART = Path(__file__).resolve().parent / "artifacts"
ART.mkdir(exist_ok=True)
TODAY = _date.today().isoformat()

# 결의구분 학자금신청서 코드 — hakjagum_probe.py 실측(2026-07-15): 라벨 "학자금신청서"=value "56"
# (경조금신청서 55 바로 다음). 삭제 가드레일 _row_is_ours 가 이 코드로 우리 전표를 식별한다.
HAKJAGUM_FG = "56"

_PROJECT = {"code": "1310|1310", "name": "포장개선"}
_DEPARTMENT = "인사/기획팀"
_COST_TYPE = "판관비"

# detail 그리드(index 1) 금액 필드 덤프 — trip_smoke_cycle 재사용(신규 발명 아님). 상대계정거래처
# 스텝 없음(경조금 동형)으로 BFC_PARTNER_CD 는 의미 있는 신호가 아니라 덤프에서 뺐다. `n`
# (행수)이 곧 "스트레이 빈 행 없음" 검증 대상 — 단건이라 정확히 1이어야 한다.
_DETAIL_DUMP_JS = """() => {
  try { const ds = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
    const n = ds.getRowCount(); const rows = n>0 ? ds.getJsonRows(0,n-1) : [];
    return { n, rows: rows.map(r => ({ SPPRC_AMT2: String(r.SPPRC_AMT2==null?'':r.SPPRC_AMT2),
      SPPRC_AMT: String(r.SPPRC_AMT==null?'':r.SPPRC_AMT), TOTAL_AMT: String(r.TOTAL_AMT==null?'':r.TOTAL_AMT) })) };
  } catch(e){ return { err: String(e).slice(0,80) }; }
}"""

# 사이클별 baseAmount 정액 표 — 학자금은 근속 감액 규칙이 없어 정액이 그대로 저장돼야 한다
# (expected=base). 경조금 _CYCLE_PLAN 의 금액 축을 유지하되 under1Year 축은 삭제. cycle 이 표보다
# 많으면 순환 재사용.
_CYCLE_PLAN: list[int] = [
    100001,
    84000,
    300001,
    125000,
    250001,
    99999,
    71001,
    200002,
    133333,
    64001,
]


def _cycle_params(cycle: int) -> dict:
    """`_CYCLE_PLAN` 표에서 baseAmount 결정 — 표보다 사이클이 많으면 순환.

    project 는 코드베이스 전역에서 라이브(피커 검색) 검증된 유일한 코드로 고정한다(1310|1310·
    포장개선 — trip_smoke_cycle 등 수십 개 e2e 스크립트가 공유). 비용구분 기본 프로젝트(800 계열,
    `app/services/cost_project.py`)는 DB 카탈로그 조회일 뿐 ERP 코드피커 검색 실측이 없어, 이번
    회귀 테스트에 임의 도입하면 검증 목적과 무관한 실패(데이터 없음/검색 실패)를 만들 위험이 있다
    (신규 발명 금지 원칙) — trip_smoke_cycle 자신도 프로젝트는 고정, 금액만 사이클별로 흔든다.
    """
    base_amount = _CYCLE_PLAN[(cycle - 1) % len(_CYCLE_PLAN)]
    expected = base_amount  # 학자금은 감액 규칙 없음 — 정액 그대로 공급가액.
    return {
        "hakjagum": {
            "evidenceDate": TODAY,
            "baseAmount": base_amount,
            "project": dict(_PROJECT),
        },
        "department": _DEPARTMENT,
        "cost_type": _COST_TYPE,
        "_summary": {"baseAmount": base_amount, "expected_supply": expected},
    }


def _row_is_ours(row: dict) -> bool:
    """삭제 안전 가드 — 결의자=USERID + 결의구분=HAKJAGUM_FG(학자금신청서) + 미결(DOCU_NO 공백)."""
    writer_ok = str(row.get("WRT_EMP_NM") or "").strip() == USERID
    fg_ok = str(row.get("ABDOCU_FG_CD") or "") == HAKJAGUM_FG
    not_posted = not str(row.get("DOCU_NO") or "").strip()
    return writer_ok and fg_ok and not_posted


async def _drive_graph(page, params: dict) -> dict:
    """runner state 주입 미러 + 그래프 ainvoke(실저장 F7 — 몽키패치 없음). 이벤트 수집."""
    events: asyncio.Queue = asyncio.Queue()
    state = {"page": page, "browser": None, "events": events, "userid": USERID,
             "password": PASSWORD, "params": params, "owner": None, "run_id": None}
    graph = build_hakjagum_grant_graph()
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
    """저장된 학자금 결의를 조회→가드레일 검증→F6 삭제→잔존 0 확인. 반환 진단 dict."""
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
        await page.screenshot(path=str(ART / f"hakjagum_save_c{cycle}_guardrail.png"))
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
        await page.screenshot(path=str(ART / f"hakjagum_save_c{cycle}_leftover.png"))
    return out


async def _run_one_cycle(browser, cycle: int, warm_state: dict | None) -> dict:
    params = _cycle_params(cycle)
    summary = params.pop("_summary")
    expected_supply = summary["expected_supply"]
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
        amount_match = None
        rows_clean = None
        if save_ok:
            await page.wait_for_timeout(800)
            md = await page.evaluate(MASTER_DUMP_JS, 0)
            r0 = (md.get("rows") or [{}])[-1] if md.get("rows") else {}
            detail = await page.evaluate(_DETAIL_DUMP_JS)
            detail_rows = detail.get("rows") or []
            actual_amt = detail_rows[0].get("SPPRC_AMT2") if detail_rows else None
            amount_match = actual_amt is not None and actual_amt == str(expected_supply)
            # 상대계정 스텝 없음(경조금 동형) → 회귀 신호 = detail 행수가 정확히 1(단건, 스트레이 빈 행 없음).
            rows_clean = detail.get("n") == 1
            post_save = {"n": md.get("n"), "ABDOCU_NO": str(r0.get("ABDOCU_NO") or ""),
                         "DETAIL_SUM_AMT": str(r0.get("DETAIL_SUM_AMT") or ""),
                         "DETAIL_SUM_AMT3": str(r0.get("DETAIL_SUM_AMT3") or ""),
                         "detail_amounts": detail,
                         "expected_supply": expected_supply, "actual_supply": actual_amt,
                         "amount_match": amount_match, "detail_rowcount": detail.get("n"),
                         "rows_clean": rows_clean}
        vd = await _verify_and_delete(page, cycle)
        try:
            saved_state = await ctx.storage_state()
        except Exception:  # noqa: BLE001
            saved_state = None
        ok = save_ok and vd.get("deleted") is True and bool(amount_match) and bool(rows_clean)
        return {"cycle": cycle, "ok": ok, "run_ms": run_ms, "params_summary": summary,
                "save_ok": save_ok, "post_save": post_save, "result": r["result"], "error": r["error"],
                "steps_ms": r["steps_ms"], "errors": r["errors"], "delete": vd, "_warm_state": saved_state}
    finally:
        await ctx.close()


async def main() -> None:
    # 프로브 선행 게이트 — HAKJAGUM_FG 실측 전(placeholder) 실행은 삭제 가드레일을 무력화하므로 즉시 실패.
    if not HAKJAGUM_FG.isdigit():
        print(f"[FATAL] HAKJAGUM_FG={HAKJAGUM_FG!r} — hakjagum_probe.py 실측 코드로 교체 전에는 실행 금지"
              "(삭제 가드레일 _row_is_ours 가 결의구분 코드 대조를 요구).", flush=True)
        raise SystemExit(2)
    print(f"[SMOKE] 학자금신청서 실저장 사이클(F7→검증→삭제) 시작. cycles={CYCLES}. ⚠ 상신 금지·삭제 필수.", flush=True)
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
            ps = c.get("post_save") or {}
            mark = "PASS" if c["ok"] else "FAIL"
            summ = c["params_summary"]
            print(f"[CYCLE {i}] {mark} run={c['run_ms']/1000:.1f}s | baseAmount={summ.get('baseAmount')} expected_supply={summ.get('expected_supply')}", flush=True)
            print(f"[CYCLE {i}] save_ok={c['save_ok']} result={c.get('result')}", flush=True)
            print(f"[CYCLE {i}] post_save: expected={ps.get('expected_supply')} actual={ps.get('actual_supply')} amount_match={ps.get('amount_match')} detail_rowcount={ps.get('detail_rowcount')} rows_clean={ps.get('rows_clean')}", flush=True)
            print(f"[CYCLE {i}] post_save raw={ps}", flush=True)
            print(f"[CYCLE {i}] delete: before={vd.get('before')} all_ours={vd.get('all_ours')} deleted={vd.get('deleted')} after={vd.get('after')} 전표={vd.get('abdocu_nos')}", flush=True)
            if c.get("error"):
                print(f"[CYCLE {i}] run error: {c['error']}", flush=True)
            # cycle 1 안전 게이트 — fill 노드 회귀(금액 불일치·스트레이 빈 행) 조기 감지, 나머지 중단.
            if i == 1 and c["save_ok"] and (not ps.get("amount_match") or not ps.get("rows_clean")):
                print(f"[CYCLE 1][GATE] 회귀 감지(amount_match={ps.get('amount_match')}·rows_clean={ps.get('rows_clean')}) → 나머지 사이클 중단.", flush=True)
                aborted = True
                break
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
    print(f"HAKJAGUM SAVE-CYCLE SUMMARY — {passed}/{len(cycles)} PASS · avg run {avg:.1f}s · aborted={aborted}", flush=True)
    print("=" * 60, flush=True)
    leftover = [c for c in cycles if (c.get('delete') or {}).get('after') not in (0, None)]
    if leftover:
        print("⚠ 잔존 전표 있음:", flush=True)
        for c in leftover:
            print(f"  cycle {c['cycle']}: after={(c['delete'] or {}).get('after')} 전표={(c['delete'] or {}).get('abdocu_nos')}", flush=True)
    else:
        print("잔존 전표 0 확인(모든 사이클 삭제 완료).", flush=True)
    (ART / "hakjagum_smoke_cycle.json").write_text(json.dumps({"cycles": cycles, "aborted": aborted}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n리포트: {ART / 'hakjagum_smoke_cycle.json'}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
