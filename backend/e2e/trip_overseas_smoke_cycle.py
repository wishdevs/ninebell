"""출장(해외/정산서) 실저장 사이클 스모크 — 그래프 완주(F7 실저장)→검증→삭제 N회 반복.

trip_smoke_cycle.py(국내출장) 포팅 — gyeongjo_smoke_cycle.py 가 같은 포팅을 먼저 했고 구조·안전
가드·리포트 형식을 그대로 따른다. 정책 동일: 저장 없는 반복은 무의미 → **실저장(F7)→검증→삭제**
사이클로 테스트한다(단 반드시 F6 삭제로 정리, 상신 금지).

해외 델타(국내 대비, PROCESS.md/FLOW.md · 2026-07-09 라이브 실측):
  - 결의구분 **'출장(해외·정산서)' value 54**(국내 53, 경조 55) — 삭제 가드레일도 54 로 격리한다.
  - 행 유형(통행료/유류비) 구분 없음 — **전 행 동일 형태**(계산서일·공급가액·프로젝트·적요).
  - 거래처 = **전 행 작성자 본인**(국내는 통행료만 카탈로그) → detail PARTNER_NM 을 사이클마다 검증.
  - 공급가액 **직접 입력**(국내 유류비의 km·연비·단가 계산 없음) → 입력 금액이 그대로
    SPPRC_AMT2 로 저장되는지 행별로 검증(계산 로직이 없으니 불일치는 곧 채움 회귀다).
  - 적요 **자유 입력**(국내는 유형별 기본 문구) → NOTE_DC 행별 검증.
  - 예산계정 '여비교통비-**해외**출장'(국내 '국내출장').
  - 회계일자 = 계산서일(START_DT) **최댓값** 파생 → 한 사이클의 행은 같은 달로 유지한다
    (월이 걸치는 건은 결의서를 나눠 상신해야 한다 — PROCESS.md 상신 주의).
  - **부가선택에 상대계정거래처 항목이 없다**(gubun 54 실측) → `register_counter_partner` 가
    우아하게 스킵(ok, skipped=True)되고, 그 스텝의 부작용인 **스트레이 빈 행이 생기지 않는다**.
    경조금 사이클과 같은 방식으로 **detail 행수 = 입력 행수**(빈 행 없음)를 사이클마다 검증한다.

⚠ 안전 수칙
  - **삭제까지가 한 사이클** — 삭제 검증(잔존 0) 없이는 다음 사이클 진행 금지.
  - **상신(결재) 절대 금지** — 삭제 불가 상태를 만들지 않는다. F7(저장)·F6(삭제)만.
  - 삭제 가드레일: 결의자(WRT_EMP_NM)=로그인계정 + 결의구분(ABDOCU_FG_CD)=54(출장 해외·정산서) +
    미결(DOCU_NO 공백). 하나라도 안 맞으면 **삭제 중단·보고**(테스트 계정 외 전표 보호).
    ⚠ 같은 ERP 계정으로 국내출장(53)·경조금(55)·학자금(56) 스모크가 **동시에** 돌 수 있다.
    조회(F2)는 결의구분 드롭다운(#s_abdocu_fg_cd = 54)으로 필터되고 가드가 54 를 재확인하므로
    다른 구분의 전표는 조회 대상에도, 삭제 대상에도 들어오지 않는다.
  - 삭제가 한 번이라도 실패하면 사이클 중단하고 전표번호와 함께 즉시 보고.
  - **cycle 1 안전 게이트**: 첫 사이클에서 저장 금액 불일치 또는 스트레이 빈 행이 보이면(fill 노드
    회귀) 나머지 사이클을 진행하지 않고 즉시 중단·보고한다.

Usage: cd backend && TRIP_OVERSEAS_SMOKE_CYCLES=10 .venv/bin/python e2e/trip_overseas_smoke_cycle.py
  (TRIP_OVERSEAS_SMOKE_CYCLES 미지정 시 기본 1 — 단발 검증용)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import date as _date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.agents import build_trip_overseas_graph  # noqa: E402
from app.agents.card_collect import js as cc_js  # noqa: E402 — MODAL_* JS
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.omnisol import selectors  # noqa: E402
# card e2e 검증 JS 재사용(마스터 조회·덤프·전체선택).
from e2e.e2e_smoke import BTN_BOX_JS, MASTER_DUMP_JS, MASTER_ROWCOUNT_JS, SELECT_MASTER_JS  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
CYCLES = int(os.environ.get("TRIP_OVERSEAS_SMOKE_CYCLES", "1"))
ART = Path(__file__).resolve().parent / "artifacts"
ART.mkdir(exist_ok=True)

TRIP_OVERSEAS_FG = "54"  # 결의구분 출장(해외·정산서) 코드(2026-07-09 라이브 실측).

_PROJECT = {"code": "1310|1310", "name": "포장개선"}
_DEPARTMENT = "인사/기획팀"
_COST_TYPE = "판관비"

# detail 그리드(index 1) 덤프 — trip/gyeongjo 사이클에서 재사용(신규 발명 아님). `n`(행수)이 곧
# "스트레이 빈 행 없음" 검증 대상이고, PARTNER_NM/NOTE_DC 는 해외 델타(전 행 본인·적요 자유입력)
# 검증 대상이다. BFC_PARTNER_CD 는 상대계정 스텝이 스킵되는 유형이라 의미 있는 신호가 아니라 뺐다.
_DETAIL_DUMP_JS = """() => {
  try { const ds = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
    const n = ds.getRowCount(); const rows = n>0 ? ds.getJsonRows(0,n-1) : [];
    return { n, rows: rows.map(r => ({ SPPRC_AMT2: String(r.SPPRC_AMT2==null?'':r.SPPRC_AMT2),
      SPPRC_AMT: String(r.SPPRC_AMT==null?'':r.SPPRC_AMT), TOTAL_AMT: String(r.TOTAL_AMT==null?'':r.TOTAL_AMT),
      PARTNER_NM: String(r.PARTNER_NM==null?'':r.PARTNER_NM), NOTE_DC: String(r.NOTE_DC==null?'':r.NOTE_DC) })) };
  } catch(e){ return { err: String(e).slice(0,80) }; }
}"""

# 사이클별 행 금액 표 — 해외는 금액 계산 규칙이 없어 **입력값이 그대로** 공급가액이어야 한다.
# 행수를 1~3으로 흔들어 F3 반복·행별 채움 회귀를 함께 본다(국내 사이클이 통행료 행수를 흔드는 것과
# 같은 축). 행마다 금액을 다르게 둬 **행 순서까지** 대조되게 한다. 표보다 사이클이 많으면 순환.
_CYCLE_PLAN: list[list[int]] = [
    [51000],
    [23000, 47500],
    [12345, 67890, 100000],
    [88800, 15200],
    [99999],
    [31000, 42000, 53000],
    [7000, 8000],
    [123456],
    [64001, 71001],
    [10500, 20500, 30500],
]


def _row_dates(n: int) -> list[str]:
    """행별 계산서일(증빙일) — 오늘부터 역순 n개, 단 **월을 넘지 않게** 클램프.

    회계일자는 계산서일 최댓값(=오늘)으로 파생된다(D4). 월이 걸치는 건은 결의서를 나눠 상신해야
    하므로(PROCESS.md 상신 주의) 한 사이클의 행은 같은 달로 유지한다 — 월초에는 전부 오늘이 된다.
    """
    today = _date.today()
    span = max(1, min(n, today.day))
    return [(today - timedelta(days=i % span)).isoformat() for i in range(n)]


def _cycle_params(cycle: int) -> dict:
    """`_CYCLE_PLAN` 표에서 행 금액 목록 결정 — 표보다 사이클이 많으면 순환.

    project 는 코드베이스 전역에서 라이브(피커 검색) 검증된 유일한 코드로 고정한다(1310|1310·
    포장개선 — trip/gyeongjo 사이클 공유). 흔드는 축은 금액과 행수뿐이다(신규 발명 금지).
    """
    amounts = _CYCLE_PLAN[(cycle - 1) % len(_CYCLE_PLAN)]
    dates = _row_dates(len(amounts))
    notes = [f"해외출장 일비 {cycle}-{i + 1}" for i in range(len(amounts))]
    rows = [
        {"invoiceDate": dates[i], "amount": amounts[i], "project": dict(_PROJECT), "note": notes[i]}
        for i in range(len(amounts))
    ]
    return {
        "trip": {"rows": rows},
        "department": _DEPARTMENT,
        "cost_type": _COST_TYPE,
        "_summary": {"row_count": len(amounts), "amounts": list(amounts), "notes": notes,
                     "dates": dates, "grand_total": sum(amounts)},
    }


def _row_is_ours(row: dict) -> bool:
    """삭제 안전 가드 — 결의자=USERID + 결의구분=54(출장 해외·정산서) + 미결(DOCU_NO 공백)."""
    writer_ok = str(row.get("WRT_EMP_NM") or "").strip() == USERID
    fg_ok = str(row.get("ABDOCU_FG_CD") or "") == TRIP_OVERSEAS_FG
    not_posted = not str(row.get("DOCU_NO") or "").strip()
    return writer_ok and fg_ok and not_posted


def _as_int(v: object) -> int | None:
    """그리드 금액 문자열 → int(콤마·소수점 0 허용). 파싱 불가면 None(불일치로 단정하지 않는다)."""
    s = str(v if v is not None else "").replace(",", "").strip()
    if not s:
        return None
    if s.endswith(".0") or s.endswith(".00"):
        s = s.split(".")[0]
    try:
        return int(s)
    except ValueError:
        return None


async def _drive_graph(page, params: dict) -> dict:
    """runner state 주입 미러 + 그래프 ainvoke(실저장 F7 — 몽키패치 없음). 이벤트 수집."""
    events: asyncio.Queue = asyncio.Queue()
    state = {"page": page, "browser": None, "events": events, "userid": USERID,
             "password": PASSWORD, "params": params, "owner": None, "run_id": None}
    graph = build_trip_overseas_graph()
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
    """저장된 해외출장 결의를 조회→가드레일 검증→F6 삭제→잔존 0 확인. 반환 진단 dict."""
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
        await page.screenshot(path=str(ART / f"trip_overseas_save_c{cycle}_guardrail.png"))
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
        await page.screenshot(path=str(ART / f"trip_overseas_save_c{cycle}_leftover.png"))
    return out


async def _run_one_cycle(browser, cycle: int, warm_state: dict | None) -> dict:
    params = _cycle_params(cycle)
    summary = params.pop("_summary")
    expected_amounts: list[int] = summary["amounts"]
    expected_notes: list[str] = summary["notes"]
    grand_total: int = summary["grand_total"]
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
        partner_match = None
        note_match = None
        total_match = None
        if save_ok:
            await page.wait_for_timeout(800)
            md = await page.evaluate(MASTER_DUMP_JS, 0)
            r0 = (md.get("rows") or [{}])[-1] if md.get("rows") else {}
            detail = await page.evaluate(_DETAIL_DUMP_JS)
            detail_rows = detail.get("rows") or []
            actual_amounts = [_as_int(x.get("SPPRC_AMT2")) for x in detail_rows]
            # 상대계정 스텝 스킵(해외 유형) → 회귀 신호 = detail 행수가 정확히 입력 행수(빈 행 없음).
            rows_clean = detail.get("n") == len(expected_amounts)
            # 금액은 계산 없이 입력값 그대로여야 한다 — 행 순서까지 대조.
            amount_match = rows_clean and actual_amounts == expected_amounts
            # 해외 델타: 거래처는 전 행 작성자 본인.
            partner_match = rows_clean and all(
                str(x.get("PARTNER_NM") or "").strip() == USERID for x in detail_rows
            )
            # 해외 델타: 적요 자유입력이 행별로 그대로 저장.
            note_match = rows_clean and [
                str(x.get("NOTE_DC") or "").strip() for x in detail_rows
            ] == expected_notes
            actual_total = _as_int(r0.get("DETAIL_SUM_AMT"))
            total_match = actual_total == grand_total
            post_save = {"n": md.get("n"), "ABDOCU_NO": str(r0.get("ABDOCU_NO") or ""),
                         "ACTG_DT": str(r0.get("ACTG_DT") or ""),  # 계산서일 최댓값 파생 근거(대조 없음).
                         "DETAIL_SUM_AMT": str(r0.get("DETAIL_SUM_AMT") or ""),
                         "DETAIL_SUM_AMT3": str(r0.get("DETAIL_SUM_AMT3") or ""),
                         "detail_amounts": detail,
                         "expected_amounts": expected_amounts, "actual_amounts": actual_amounts,
                         "expected_total": grand_total, "actual_total": actual_total,
                         "amount_match": amount_match, "detail_rowcount": detail.get("n"),
                         "rows_clean": rows_clean, "partner_match": partner_match,
                         "note_match": note_match, "total_match": total_match}
        vd = await _verify_and_delete(page, cycle)
        try:
            saved_state = await ctx.storage_state()
        except Exception:  # noqa: BLE001
            saved_state = None
        ok = (save_ok and vd.get("deleted") is True and bool(amount_match) and bool(rows_clean)
              and bool(partner_match) and bool(note_match) and bool(total_match))
        return {"cycle": cycle, "ok": ok, "run_ms": run_ms, "params_summary": summary,
                "save_ok": save_ok, "post_save": post_save, "result": r["result"], "error": r["error"],
                "steps_ms": r["steps_ms"], "errors": r["errors"], "delete": vd, "_warm_state": saved_state}
    finally:
        await ctx.close()


async def main() -> None:
    print(f"[SMOKE] 해외출장(정산서) 실저장 사이클(F7→검증→삭제) 시작. cycles={CYCLES}. ⚠ 상신 금지·삭제 필수.", flush=True)
    print(f"[SMOKE] 삭제 격리: 결의구분 {TRIP_OVERSEAS_FG}(해외 정산서) 전표만 대상 — 국내53·경조55·학자56 은 건드리지 않는다.", flush=True)
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
            print(f"[CYCLE {i}] {mark} run={c['run_ms']/1000:.1f}s | {summ.get('row_count')}행 amounts={summ.get('amounts')} 합계={summ.get('grand_total')} 계산서일={summ.get('dates')}", flush=True)
            print(f"[CYCLE {i}] save_ok={c['save_ok']} result={c.get('result')}", flush=True)
            print(f"[CYCLE {i}] 단계별 ms={c.get('steps_ms')}", flush=True)
            print(f"[CYCLE {i}] post_save: expected={ps.get('expected_amounts')} actual={ps.get('actual_amounts')} amount_match={ps.get('amount_match')} detail_rowcount={ps.get('detail_rowcount')} rows_clean={ps.get('rows_clean')} partner_match={ps.get('partner_match')} note_match={ps.get('note_match')} total_match={ps.get('total_match')}(기대 {ps.get('expected_total')}·실제 {ps.get('actual_total')})", flush=True)
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
    print(f"TRIP-OVERSEAS SAVE-CYCLE SUMMARY — {passed}/{len(cycles)} PASS · avg run {avg:.1f}s · aborted={aborted}", flush=True)
    print("=" * 60, flush=True)
    leftover = [c for c in cycles if (c.get('delete') or {}).get('after') not in (0, None)]
    if leftover:
        print("⚠ 잔존 전표 있음:", flush=True)
        for c in leftover:
            print(f"  cycle {c['cycle']}: after={(c['delete'] or {}).get('after')} 전표={(c['delete'] or {}).get('abdocu_nos')}", flush=True)
    else:
        print("잔존 전표 0 확인(모든 사이클 삭제 완료).", flush=True)
    (ART / "trip_overseas_smoke_cycle.json").write_text(json.dumps({"cycles": cycles, "aborted": aborted}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n리포트: {ART / 'trip_overseas_smoke_cycle.json'}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
