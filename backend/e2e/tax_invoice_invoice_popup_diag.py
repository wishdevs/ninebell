"""전자세금계산서 팝업 "0건" 진단 — team-lead 재프레임(2026-08-19): 사용자 확정으로 이 환경에
데이터가 **있다**. "0건은 정상(데이터 부재)" 결론은 틀렸고, 자동화의 팝업 조회 경로에 버그가
있다는 전제로 재진단한다.

⚠⚠ 절대 안전 규칙 ⚠⚠ — F7(저장) 절대 금지, 전자세금계산서 팝업 '적용' 클릭 금지(구조/데이터
덤프만). 증빙유형 팝업 적용까지는 진행(미저장 draft — trip_probe.py 선례와 동일 안전 프로파일).
종료 시 저장하지 않고 브라우저를 닫는다.

진단 항목(팀 지시):
  1. 팝업 열린 직후 + 조회 직후 각각 스크린샷.
  2. 조회조건 **전 입력필드**(8종 추정) 실제 값 재독 — period 뿐 아니라 팝업 내 모든 input.
  3. 조회 버튼 클릭 → 로딩 대기 → rowcount 시간차 재독(지연 로드 여부) + **그리드 전량**(1개
     가정 금지) 스캔 — 엉뚱한 빈 그리드를 읽고 있을 가능성.
  4. 수동 대조 — 기간만 이번 달로 두고 나머지 필드를 비운 뒤 재조회, 행 출현 여부.

Usage: cd backend && E2E_HEADLESS=0 .venv/bin/python e2e/tax_invoice_invoice_popup_diag.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from e2e.trip_probe import SELECT_OPTIONS_JS  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

GUBUN_LABEL = "세금계산서"
EVDN_CODE = "03"  # POST03(일반 세금계산서·발행 후·무분할) — team-lead 가 지목한 케이스.

TODAY = date.today().isoformat()
THIS_MONTH_FROM = f"{TODAY[:7]}-01"

# ── 진단 전용 JS — **그리드 전량**(복수 가능성) + **입력필드 전량**(조건 상속 확인) ─────────
POPUP_FULL_DIAG_JS = """(limit) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const titles = wins.map(w => c((w.querySelector('.k-window-title')||{}).innerText));
  // 제목에 '전자세금계산서'/'전자계산서' 포함하는 창을 우선(마지막 창 가정 금지 — steps.py 교훈).
  let idx = -1;
  for (let i = wins.length - 1; i >= 0; i--) {
    if (/전자세금계산서|전자계산서/.test(titles[i])) { idx = i; break; }
  }
  if (idx < 0) idx = wins.length - 1;
  const dlg = wins[idx];
  if (!dlg) return { ok: false, reason: 'no-popup', titles };
  const title = titles[idx];
  const inputs = [...dlg.querySelectorAll('input')].filter(i => i.offsetParent !== null).map(i => ({
    id: i.id || null, name: i.name || null, type: i.type || '', value: c(i.value).slice(0, 60),
    placeholder: i.placeholder || null }));
  const gridEls = [...dlg.querySelectorAll('.dews-ui-grid')];
  const grids = gridEls.map((el, gi) => {
    try {
      const g = window.jQuery(el).data('dewsControl')._grid;
      const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
        field: cc.fieldName || cc.name || cc.field || null,
        header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || null,
        visible: cc.visible !== false }));
      const ds = g.getDataSource();
      const n = ds.getRowCount();
      const take = Math.min(n, limit || 20);
      const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
      const r = el.getBoundingClientRect();
      return { gridIndex: gi, n, cols, rows, elId: el.id || null,
        rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } };
    } catch (e) { return { gridIndex: gi, err: String(e).slice(0, 140) }; }
  });
  return { ok: true, title, titles, windowIndex: idx, windowCount: wins.length, inputs, gridCount: gridEls.length, grids };
}"""

# 조회 버튼 — 팝업 스코프 안에서(제목 지정), 부분일치("조회"/"검색") 전량 나열.
POPUP_QUERY_BUTTONS_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const titles = wins.map(w => c((w.querySelector('.k-window-title')||{}).innerText));
  let idx = -1;
  for (let i = wins.length - 1; i >= 0; i--) {
    if (/전자세금계산서|전자계산서/.test(titles[i])) { idx = i; break; }
  }
  if (idx < 0) idx = wins.length - 1;
  const dlg = wins[idx];
  if (!dlg) return [];
  return [...dlg.querySelectorAll('button')].filter(b => b.offsetParent !== null)
    .map(b => { const r = b.getBoundingClientRect();
      return { text: c(b.innerText), x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) }; })
    .filter(b => /조회|검색/.test(b.text));
}"""

# period 두 input 을 네이티브 setter 로 세팅(steps.SET_INVOICE_PERIOD_JS 와 동일 로직, 진단용 복제).
SET_PERIOD_JS = """({ from, to }) => {
  const set = (id, val) => { const i = document.getElementById(id); if (!i) return { ok:false };
    const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    d.set.call(i, val); i.dispatchEvent(new Event('input', {bubbles:true}));
    i.dispatchEvent(new Event('change', {bubbles:true}));
    return { ok:true, valueAfter: i.value }; };
  return { start: set('period_startinput', from), end: set('period_endinput', to) };
}"""

# 임의 input id 를 네이티브 setter 로 비운다(수동 대조 — 조건 상속 가설 검증).
CLEAR_INPUT_JS = """(id) => {
  const i = document.getElementById(id); if (!i) return { ok:false };
  const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  d.set.call(i, ''); i.dispatchEvent(new Event('input', {bubbles:true}));
  i.dispatchEvent(new Event('change', {bubbles:true}));
  return { ok:true, valueAfter: i.value };
}"""


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"tax_invoice_invoice_popup_diag_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"tax_invoice_invoice_popup_diag_{name}.png")
        await page.screenshot(path=p)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def main() -> None:
    results: dict = {"userid": USERID, "gubun_label": GUBUN_LABEL, "evdn_code": EVDN_CODE}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    try:
        print("[entry] login + user_type(회계) + menu_nav(GLDDOC00300)…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)

        # 결의구분 = 세금계산서.
        opt = await page.evaluate(SELECT_OPTIONS_JS, selectors.GUBUN_SELECT)
        chosen = next((o for o in (opt.get("options") or []) if o["text"] == GUBUN_LABEL), None)
        if not chosen:
            print("[FATAL] 결의구분에 세금계산서 없음", flush=True)
            return
        await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": selectors.GUBUN_SELECT, "text": GUBUN_LABEL},
        )
        await page.wait_for_timeout(1_800)

        # add_row (F3).
        await js_click(page, selectors.BTN_ADD)
        drc = -1
        for _ in range(33):
            await page.wait_for_timeout(300)
            drc = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
            if isinstance(drc, int) and drc > 0:
                break
        if not (isinstance(drc, int) and drc > 0):
            print("[FATAL] F3 후 행 생성 실패", flush=True)
            return

        # ── 증빙유형 03(세금계산서·발행 후) 선택 + 적용 ──────────────────────────
        print(f"\n===== 증빙유형 {EVDN_CODE} 선택+적용 =====", flush=True)
        ev: dict = {"opened": False}
        for attempt in range(1, 4):
            shown = await page.evaluate(js_lib.OPEN_EVDN_EDITOR_JS)
            if not shown:
                continue
            rect = None
            waited = 0
            while waited < 1_500:
                await page.wait_for_timeout(150)
                waited += 150
                rect = await page.evaluate(js_lib.EVDN_EDITOR_MAGNIFIER_RECT_JS)
                if rect:
                    break
            if not rect:
                continue
            await mouse_click(page, rect["x"], rect["y"])
            for _ in range(20):
                await page.wait_for_timeout(300)
                if await page.evaluate(js_lib.EVDN_POPUP_OPEN_JS):
                    ev["opened"] = True
                    break
            if ev["opened"]:
                break
        if not ev["opened"]:
            print("[FATAL] 증빙유형 팝업 열기 실패", flush=True)
            results["evdn"] = ev
            await _dump("results", results)
            return
        sel = {"ok": False}
        for _ in range(20):
            sel = await page.evaluate(js_lib.EVDN_SELECT_BY_CODE_JS, EVDN_CODE)
            if sel.get("ok"):
                break
            await page.wait_for_timeout(300)
        ev["select"] = sel
        box = await page.evaluate(js_lib.EVDN_APPLY_BOX_JS)
        if box:
            await mouse_click(page, box["x"], box["y"])
        await page.wait_for_timeout(1_200)
        results["evdn"] = ev
        print(f"[EVDN] select={sel}", flush=True)

        # ── 조회(F2) 클릭 → 게이트 다이얼로그 "예" → 전자세금계산서 팝업 ──────────
        print("\n===== 조회(F2) → 게이트 다이얼로그 → 전자세금계산서 팝업 =====", flush=True)
        lookup_box = await page.evaluate(
            "(sel) => { const b = document.querySelector(sel); if(!b) return null;"
            " const r = b.getBoundingClientRect(); if(!r.width) return null;"
            " return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; }",
            selectors.BTN_LOOKUP,
        )
        if not lookup_box:
            print("[FATAL] 조회(F2) 버튼 좌표 없음", flush=True)
            await _dump("results", results)
            return
        await mouse_click(page, lookup_box["x"], lookup_box["y"])
        gate_clicked = False
        for _ in range(15):
            await page.wait_for_timeout(300)
            modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
            gate = next((m for m in modals if "전자발행된 증빙" in m.get("text", "")), None)
            if gate:
                ybtn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "예")
                if ybtn:
                    await mouse_click(page, ybtn["x"], ybtn["y"])
                    gate_clicked = True
                break
        results["gate_dialog_clicked"] = gate_clicked
        print(f"[gate] 처리={gate_clicked}", flush=True)

        popup_opened = False
        for _ in range(20):
            await page.wait_for_timeout(300)
            wins = await page.evaluate(
                "() => [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)"
                ".map(w => (w.querySelector('.k-window-title')||{}).innerText || '')"
            )
            if any("전자세금계산서" in w or "전자계산서" in w for w in wins):
                popup_opened = True
                break
        results["popup_opened"] = popup_opened
        if not popup_opened:
            print("[FATAL] 팝업 미출현", flush=True)
            results["modals_after"] = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
            await _shot(page, "no_popup")
            await _dump("results", results)
            return

        # ⚠ 진단 1 — 팝업 열린 "직후"(기간 세팅 전) 즉시 스크린샷 + 그리드 전량/입력 전량 덤프.
        for _ in range(20):  # 로딩 스피너("도움창 확인 중") 대응 폴링.
            diag0 = await page.evaluate(POPUP_FULL_DIAG_JS, 20)
            if diag0.get("ok") and diag0.get("gridCount", 0) >= 1:
                break
            await page.wait_for_timeout(300)
        results["diag_on_open"] = diag0
        await _shot(page, "1_popup_opened")
        print(
            f"[diag1] title={diag0.get('title')} windowCount={diag0.get('windowCount')} "
            f"gridCount={diag0.get('gridCount')} grid_n_values={[g.get('n') for g in diag0.get('grids', [])]}",
            flush=True,
        )
        print(f"[diag1] inputs={json.dumps(diag0.get('inputs'), ensure_ascii=False)}", flush=True)
        await _dump("results", results)

        # ⚠ 진단 2 — 조회조건 세팅(이번 달) + 실제 커밋값 재독.
        print("\n===== 진단2: 조회기간 세팅(이번 달) + 커밋값 재독 =====", flush=True)
        set_period = await page.evaluate(SET_PERIOD_JS, {"from": THIS_MONTH_FROM, "to": TODAY})
        results["set_period"] = set_period
        print(f"[diag2] 기간 세팅 결과(설정 직후 재독값 포함)={set_period}", flush=True)
        await page.wait_for_timeout(300)
        diag_after_period = await page.evaluate(POPUP_FULL_DIAG_JS, 20)
        results["diag_after_period_set"] = diag_after_period
        # period 이외 값이 있는 입력 전량 — 조건 상속/잔존 가설 확인.
        other_nonempty = [
            i for i in (diag_after_period.get("inputs") or [])
            if i.get("id") not in ("period_startinput", "period_endinput") and (i.get("value") or "").strip()
        ]
        results["other_nonempty_inputs_before_query"] = other_nonempty
        print(f"[diag2] period 외 비어있지 않은 입력필드={json.dumps(other_nonempty, ensure_ascii=False)}", flush=True)

        # ── 조회 버튼 클릭 → 즉시 스크린샷 → 시간차 rowcount 재독(그리드 전량) ──────
        print("\n===== 진단3: 조회 클릭 → 로딩 대기 → rowcount 시간차 재독(그리드 전량) =====", flush=True)
        qbtns = await page.evaluate(POPUP_QUERY_BUTTONS_JS)
        results["query_buttons"] = qbtns
        print(f"[diag3] 팝업 내 조회 버튼 후보={qbtns}", flush=True)
        if not qbtns:
            print("[FATAL] 팝업 내 조회 버튼을 찾지 못함", flush=True)
            await _shot(page, "no_query_button")
            await _dump("results", results)
            await page.keyboard.press("Escape")
            await browser.close()
            await pw.stop()
            return
        await mouse_click(page, qbtns[0]["x"], qbtns[0]["y"])
        await _shot(page, "2_query_clicked_immediate")
        timeseries = []
        for t in range(10):  # 0, 400, 800, … 3600ms — 지연 로드 여부 확인.
            await page.wait_for_timeout(400)
            d = await page.evaluate(POPUP_FULL_DIAG_JS, 5)
            ns = [g.get("n") for g in (d.get("grids") or [])]
            timeseries.append({"t_ms": (t + 1) * 400, "gridCount": d.get("gridCount"), "grid_n": ns})
            print(f"[diag3] t={(t+1)*400}ms gridCount={d.get('gridCount')} grid_n={ns}", flush=True)
        results["rowcount_timeseries"] = timeseries
        diag_final = await page.evaluate(POPUP_FULL_DIAG_JS, 30)
        results["diag_after_query"] = diag_final
        await _shot(page, "3_after_query_settled")
        await _dump("results", results)

        # ── 진단4: 수동 대조 — period 외 비어있지 않은 입력을 전부 비우고 재조회 ─────
        if other_nonempty:
            print("\n===== 진단4: period 외 필드 전부 비우고 재조회(조건 상속 가설 대조) =====", flush=True)
            cleared = []
            for inp in other_nonempty:
                if not inp.get("id"):
                    continue
                r = await page.evaluate(CLEAR_INPUT_JS, inp["id"])
                cleared.append({"id": inp["id"], "before": inp.get("value"), "clear_result": r})
            results["cleared_inputs"] = cleared
            print(f"[diag4] 비운 필드={cleared}", flush=True)
            qbtns2 = await page.evaluate(POPUP_QUERY_BUTTONS_JS)
            if qbtns2:
                await mouse_click(page, qbtns2[0]["x"], qbtns2[0]["y"])
                await page.wait_for_timeout(1_500)
                diag_control = await page.evaluate(POPUP_FULL_DIAG_JS, 20)
                results["diag_control_test"] = diag_control
                await _shot(page, "4_control_test_cleared_fields")
                print(
                    f"[diag4] 대조 조회 결과 gridCount={diag_control.get('gridCount')} "
                    f"grid_n={[g.get('n') for g in diag_control.get('grids', [])]}",
                    flush=True,
                )
            else:
                print("[diag4] 대조 조회 버튼 못 찾음", flush=True)
        else:
            print("\n[diag4] period 외 비어있지 않은 입력 없음 — 조건 상속 가설 기각(대조 생략)", flush=True)

        await _dump("results", results)
        print("\n[DONE] 적용 클릭 없이 Escape 로 종료(F7 없음, 미저장 draft 폐기).", flush=True)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        results["error"] = repr(exc)
        try:
            await _shot(page, "exception")
        except Exception:  # noqa: BLE001
            pass
        await _dump("results", results)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
