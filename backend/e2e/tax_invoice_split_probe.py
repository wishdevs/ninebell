"""HEADLESS 프로브 — 세금계산서 원증빙(11)+비용분할 경로 실측. F7 저장 없음(부작용 0).

⚠⚠ 절대 안전 규칙 ⚠⚠
  - F7(저장) 절대 금지. 종료 시 저장하지 않고 브라우저를 닫는다(미영속 draft 폐기).
  - **이번 프로브는 증빙유형 팝업 '적용'까지는 진행한다**(1차 read probe 의 "적용 금지" 지시와
    다름 — team-lead 의 후속 요청(분할처리 팝업 컬럼 덤프)이 구조적으로 증빙유형 확정 없이는
    "비용분할" 버튼 자체가 비활성이라 도달 불가함을 1차 프로브에서 확인했다. 증빙유형 적용은
    미저장 draft 상태 변경일 뿐 서버 영속이 없다(F7 전까지) — trip_probe.py P2 선례와 동일 안전
    프로파일). **전자세금계산서 팝업의 '적용'은 여전히 클릭하지 않는다**(구조 덤프만).
  - 분할처리 팝업의 '적용'도 클릭하지 않는다(구조 덤프까지만, 보수적 유지).

확인 대상(team-lead 후속 요청):
  1. D5 재시도 — 증빙유형 11 확정 후 '조회' 버튼이 나타나는지, 전자세금계산서 팝업 구조
  2. 분할처리 팝업(`#GLDDOC00300_DISTRIBUTION_grid`) 그리드 컬럼 필드명 전량

Usage: cd backend && .venv/bin/python e2e/tax_invoice_split_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.trip_domestic.steps import _open_detail_cell_picker, type_amount  # noqa: E402  (재사용)
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from e2e.trip_probe import SELECT_OPTIONS_JS  # noqa: E402
from nbkit.omnisol.codepicker import _picker_search  # noqa: E402
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
EVDN_CODE = "11"  # 세금계산서(원증빙) — D2/D4: 비용분할 가능 코드

BUTTON_BY_TEXT_JS = """(text) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  return [...document.querySelectorAll('button')]
    .filter(b => b.offsetParent !== null && c(b.innerText) === text)
    .map(b => { const r = b.getBoundingClientRect();
      return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2),
        id: b.id || null, cls: (b.className||'').toString().slice(0,90),
        disabled: !!b.disabled, text: c(b.innerText) }; });
}"""

INVOICE_POPUP_DUMP_JS = """(limit) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-popup' };
  const title = c((dlg.querySelector('.k-window-title')||{}).innerText);
  const inputs = [...dlg.querySelectorAll('input')].filter(i => i.offsetParent !== null).map(i => ({
    id: i.id || null, type: i.type || '', value: c(i.value).slice(0, 30) }));
  let grid = null;
  try {
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
      field: cc.fieldName || cc.name || cc.field || null,
      header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || null,
      visible: cc.visible !== false }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(n, limit || 50);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    grid = { n, cols, rows };
  } catch (e) { grid = { err: String(e).slice(0, 140) }; }
  return { ok: true, title, inputs, grid };
}"""

# 분할처리 팝업 grid — id 로 특정(dews-ui-grid 여러 개 중 어느 것인지 순서 의존 없이 확정).
DISTRIBUTION_GRID_DUMP_JS = """() => {
  const el = document.getElementById('GLDDOC00300_DISTRIBUTION_grid');
  if (!el) return { ok: false, reason: 'no-element' };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
      field: cc.fieldName || cc.name || cc.field || null,
      header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || null,
      visible: cc.visible !== false,
      editor: (cc.editor && (cc.editor.type || cc.editor.editorType)) || null }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    return { ok: true, n, cols, fieldKeys: rows[0] ? Object.keys(rows[0]) : null, rows };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 140) }; }
}"""


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"tax_invoice_split_probe_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"tax_invoice_split_probe_{name}.png")
        await page.screenshot(path=p)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def main() -> None:
    results: dict = {"userid": USERID, "gubun_label": GUBUN_LABEL, "delay_scale": DELAY_SCALE}
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
        results["add_row"] = {"detail_rowcount": drc}
        if not (isinstance(drc, int) and drc > 0):
            print("[FATAL] F3 후 행 생성 실패", flush=True)
            return
        await _shot(page, "addrow")

        # ── 증빙유형 11(세금계산서 원증빙) 선택 + 적용(이번 프로브만 허용, 상단 주석 참조) ──
        print("\n===== 증빙유형 11(원증빙) 선택+적용 =====", flush=True)
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
        # ⚠ 팝업 오픈 직후는 '데이터 로딩 중' 상태라 즉시 select 하면 code-not-found 로 실패한다
        # (SKILL.md §4 타이밍 함정, hakjagum_probe.py 동일 대응) — 성공할 때까지 조건 폴링.
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
        # split 녹화 선례: 11 선택 시 추가 확인 "예" 다이얼로그가 뜬다.
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        ev["modals_after_apply"] = modals
        if modals:
            ybtn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "예")
            if ybtn:
                await mouse_click(page, ybtn["x"], ybtn["y"])
                await page.wait_for_timeout(800)
        ev["cell_after"] = await page.evaluate(js_lib.DETAIL_EVDN_CELL_JS)
        print(f"[EVDN] select={sel} modals={modals} cell_after={ev['cell_after']}", flush=True)
        results["evdn"] = ev
        await _shot(page, "evdn11_applied")
        await _dump("results", results)

        # ── D5 재시도: '조회' 버튼 정체 확정 ─────────────────────────────────────
        # attempt 1(BUTTON_BY_TEXT_JS 정확일치)은 0건이었다 — 원인: 녹화의
        # page.get_by_role("button", name="조회")는 exact=True 가 아니라 **부분일치**라
        # 실제로는 툴바의 "조회 (F2)"(selectors.BTN_LOOKUP)에 매칭된 것으로 재해석.
        # 새 버튼이 아니라 기존 조회(F2) 클릭이 증빙유형 확정 후에는 전자세금계산서 팝업을
        # 띄우는 컨텍스트 동작으로 추정 — 그대로 검증한다.
        print("\n===== D5 재시도: 조회(F2) 클릭(증빙유형 확정 후 컨텍스트 동작 가설) =====", flush=True)
        lookup_box = await page.evaluate(
            "(sel) => { const b = document.querySelector(sel); if(!b) return null;"
            " const r = b.getBoundingClientRect(); if(!r.width) return null;"
            " return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; }",
            selectors.BTN_LOOKUP,
        )
        results["D5_lookup_box"] = lookup_box
        print(f"[D5] 조회(F2) 버튼 좌표: {lookup_box}", flush=True)
        if lookup_box:
            await mouse_click(page, lookup_box["x"], lookup_box["y"])
            # ⚠ attempt 1(위 기록) 실측: 조회(F2) 클릭 직후 "선택 — 전자발행된 증빙으로
            # 입력하시겠습니까? 예/아니요" 게이트 다이얼로그가 먼저 뜬다 — 이걸 놓치면 팝업
            # 자체가 안 열린 것으로 오판한다. "예"를 눌러야 전자세금계산서 팝업으로 이어진다.
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
            results["D5_gate_dialog_clicked"] = gate_clicked
            print(f"[D5] 게이트 다이얼로그('전자발행된 증빙') 처리={gate_clicked}", flush=True)
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
            results["D5_popup_opened"] = popup_opened
            if popup_opened:
                # ⚠ attempt 1 실측: 팝업 도착 직후 "도움창 확인 중입니다" 로딩 스피너 상태라
                # 그리드가 아직 없다(SKILL.md §4 타이밍 함정) — grid 접근 가능해질 때까지 폴링.
                dump = {"ok": False}
                for _ in range(20):
                    dump = await page.evaluate(INVOICE_POPUP_DUMP_JS, 50)
                    if dump.get("grid") and not dump["grid"].get("err"):
                        break
                    await page.wait_for_timeout(400)
                results["D5_invoice_popup"] = dump
                print(f"[D5] 전자세금계산서 팝업: title={dump.get('title')} grid_n={dump.get('grid',{}).get('n')} cols={[c.get('field') for c in dump.get('grid',{}).get('cols',[])]}", flush=True)
                await _shot(page, "d5_invoice_popup")

                # ── 데이터 존재 범위 확인(신규, team-lead 요청) — 기간을 2026-01-01~오늘로
                #    넓혀 전자발행 데이터가 이 계정/회사에 한 건이라도 있는지 확인(읽기 전용,
                #    행 적용 금지). period_startinput/period_endinput 을 네이티브 setter 로
                #    세팅 후 팝업 내 '조회' 버튼을 눌러 재조회한다.
                print("\n===== 데이터 존재 범위 확인(2026-01-01~오늘) =====", flush=True)
                wide: dict = {}
                set_period = await page.evaluate(
                    """() => {
                      const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
                      const set = (id, val) => { const i = document.getElementById(id); if (!i) return false;
                        const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
                        d.set.call(i, val); i.dispatchEvent(new Event('input', {bubbles:true}));
                        i.dispatchEvent(new Event('change', {bubbles:true})); return true; };
                      return { start: set('period_startinput', '2026-01-01'),
                               end: set('period_endinput', '2026-08-19') };
                    }"""
                )
                wide["set_period"] = set_period
                print(f"[wide] 기간 세팅: {set_period}", flush=True)
                # 팝업 내 조회 버튼(최근 열린 k-window 스코프).
                wide_query_box = await page.evaluate(
                    """() => {
                      const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
                      const wins = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null);
                      const dlg = wins[wins.length-1]; if (!dlg) return null;
                      const b = [...dlg.querySelectorAll('button')].filter(x=>x.offsetParent!==null)
                        .find(x => /조회|검색/.test(c(x.innerText)));
                      if (!b) return null; const r = b.getBoundingClientRect();
                      return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), text: c(b.innerText) };
                    }"""
                )
                wide["query_button"] = wide_query_box
                print(f"[wide] 팝업 내 조회버튼: {wide_query_box}", flush=True)
                if wide_query_box:
                    await mouse_click(page, wide_query_box["x"], wide_query_box["y"])
                    wide_dump = {"ok": False}
                    for _ in range(20):
                        await page.wait_for_timeout(400)
                        wide_dump = await page.evaluate(INVOICE_POPUP_DUMP_JS, 100)
                        if wide_dump.get("grid") and not wide_dump["grid"].get("err"):
                            break
                    wide["dump"] = wide_dump
                    g = wide_dump.get("grid") or {}
                    rows = g.get("rows") or []
                    neg_rows = [r for r in rows if isinstance(r.get("SPPRC_AMT"), (int, float, str))
                                and str(r.get("SPPRC_AMT") or "").lstrip("-").replace(".", "").isdigit()
                                and float(r.get("SPPRC_AMT") or 0) < 0]
                    data_fg_values = sorted({str(r.get("DATA_FG_NM") or "") for r in rows})
                    wide["summary"] = {"n": g.get("n"), "neg_amount_rows": len(neg_rows),
                                       "data_fg_values_seen": data_fg_values}
                    print(f"[wide] 2026-01-01~08-19 조회 결과 n={g.get('n')} neg_rows={len(neg_rows)} DATA_FG_NM종류={data_fg_values}", flush=True)
                    await _shot(page, "d5_wide_range")
                results["data_existence_range"] = wide
                await _dump("results", results)

                # ⚠ 적용 클릭 금지 — Escape 로 닫기.
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(600)
            else:
                print("[D5] '조회' 클릭했으나 전자세금계산서 팝업 미출현", flush=True)
                await _shot(page, "d5_after_lookup_click_no_popup")
                results["D5_detail_rowcount_after"] = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
                results["D5_modals_after"] = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
                print(f"[D5] detail_rowcount_after={results['D5_detail_rowcount_after']} modals={results['D5_modals_after']}", flush=True)
        await _dump("results", results)

        # ── 공급가액 실타이핑(비용분할 게이트 — attempt 1 실측: SPPRC_AMT2=0 이면 "공급가액
        #    (거래금액)이 입력되지 않았습니다" 토스트로 반려됨). F7 과 무관한 draft 조작이라
        #    안전(erp-headless-grid-automation §1 함정 대응: setValue 금지, 실타이핑+Tab+예산현황
        #    확인 — app.agents.trip_domestic.steps.type_amount 그대로 재사용).
        print("\n===== 공급가액 실타이핑(비용분할 게이트 해제) =====", flush=True)
        amt = await type_amount(page, 100000)
        results["amount_typed"] = amt
        print(f"[amount] type_amount(100000) -> {amt}", flush=True)
        await _shot(page, "amount_typed")
        await _dump("results", results)

        # ── 예산단위 채움(2번째 게이트 — attempt 1 실측: "예산단위가 입력되지 않았습니다") ──
        # attempt 1~2 는 돋보기 팝업 자체가 안 열렸다(각 3회 실패). 원인 확정(attempt 3):
        # BG_CD 는 detail 컬럼 덤프상 visible:false(숨김 백킹필드) — showEditor 로 열 수 있는
        # 화면 필드는 표시 컬럼 **BG_NM**(hakjagum_probe.py 선례와 동일 패턴). fieldName 을
        # BG_CD→BG_NM 으로 교체.
        print("\n===== 예산단위 채움(비용분할 2번째 게이트 해제) =====", flush=True)
        bg: dict = {}
        op = await _open_detail_cell_picker(page, "BG_NM", "예산단위")
        bg["open"] = op
        if op.get("ok"):
            for kw in ("일반", "공통", "관리"):
                await _picker_search(page, kw)
                read = await page.evaluate(js_lib.PICKER_READ_JS, ["BG_CD", "BG_NM", 5])
                opts = read.get("options") or []
                if opts:
                    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, opts[0]["i"])
                    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
                    if apply_box:
                        await mouse_click(page, apply_box["x"], apply_box["y"])
                        await page.wait_for_timeout(1_000)
                        confirm_box = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
                        if confirm_box:
                            await mouse_click(page, confirm_box["x"], confirm_box["y"])
                            await page.wait_for_timeout(500)
                    bg["picked"] = {"kw": kw, "chosen": opts[0], "select": sel}
                    break
            else:
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
        results["budget_unit"] = bg
        print(f"[budget] {bg}", flush=True)
        await _shot(page, "budget_filled")
        await _dump("results", results)

        # attempt 4(최종, 원인 확정): 이전 시도의 "중립 클릭(960,400)"이 실제로는 **마스터
        # 그리드 회계일 셀에 포커스를 옮기고 있었다**(스크린샷 확인 — 매번 동일 재현). 그 결과
        # '비용분할'이 보는 현재 행 컨텍스트가 detail 이 아니라 master 로 바뀌어 조용히 no-op
        # 됐을 가능성 — 중립 클릭을 제거하고 Escape 만으로 정착시킨다.
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(1_000)

        # ── 비용분할 버튼 → 분할처리 팝업 → 컬럼 덤프 ───────────────────────────
        print("\n===== 비용분할 → 분할처리 팝업 컬럼 덤프 =====", flush=True)
        split_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "비용분할")
        results["split_button"] = split_btn
        print(f"[split] 비용분할 버튼: {split_btn}", flush=True)
        if split_btn and not split_btn[0].get("disabled"):
            # 좌표가 stale 할 수 있어(팝업 상호작용 후 DOM 변동) 재조회한 좌표로 클릭한다.
            b = (await page.evaluate(BUTTON_BY_TEXT_JS, "비용분할")) or split_btn
            b = b[0]
            await mouse_click(page, b["x"], b["y"])
            await page.wait_for_timeout(200)
            await _shot(page, "split_click_immediate")  # 최종 진단 — 폴링 전 즉시 상태
            # 토스트(VALIDATION_TOAST_JS)는 수명 ~3.6s 라 6초짜리 팝업탐지 루프 끝에 확인하면
            # 이미 사라진다 — 클릭 직후 즉시 1회 스냅샷.
            await page.wait_for_timeout(200)
            early_toasts = await page.evaluate(js_lib.VALIDATION_TOAST_JS)
            if early_toasts:
                await _shot(page, "split_click_toast")
            popup_opened = False
            wins_seen: list = []
            for _ in range(20):
                await page.wait_for_timeout(300)
                wins_seen = await page.evaluate(
                    "() => [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)"
                    ".map(w => (w.querySelector('.k-window-title')||{}).innerText || '')"
                )
                if any("분할처리" in w for w in wins_seen):
                    popup_opened = True
                    break
            results["split_popup_opened"] = popup_opened
            results["split_windows_seen"] = wins_seen
            results["split_early_toasts"] = early_toasts
            print(f"[split] early_toasts={early_toasts}", flush=True)
            if not popup_opened:
                results["split_modals"] = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
                results["split_toasts"] = await page.evaluate(js_lib.VALIDATION_TOAST_JS)
                await _shot(page, "split_click_no_popup")
                print(f"[split] windows_seen={wins_seen} modals={results['split_modals']} toasts={results['split_toasts']}", flush=True)
            if popup_opened:
                await _shot(page, "split_popup_open")
                # 컬럼 덤프는 빈 그리드에서도 가능 — 먼저 시도, 필요하면 "추가"로 행 1개 생성 후 재덤프.
                dump0 = await page.evaluate(DISTRIBUTION_GRID_DUMP_JS)
                results["distribution_grid_empty"] = dump0
                print(f"[split] (행추가 전) grid dump ok={dump0.get('ok')} n={dump0.get('n')} cols={[c.get('field') for c in (dump0.get('cols') or [])]}", flush=True)

                add_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "추가")
                if add_btn:
                    await mouse_click(page, add_btn[-1]["x"], add_btn[-1]["y"])
                    await page.wait_for_timeout(800)
                    # "확인" 안내 다이얼로그가 뜰 수 있음(split 녹화 선례).
                    confirm_btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, "확인")
                    if confirm_btn:
                        await mouse_click(page, confirm_btn["x"], confirm_btn["y"])
                        await page.wait_for_timeout(600)
                    dump1 = await page.evaluate(DISTRIBUTION_GRID_DUMP_JS)
                    results["distribution_grid_after_add"] = dump1
                    print(f"[split] (행추가 후) grid dump ok={dump1.get('ok')} n={dump1.get('n')} cols={[c.get('field') for c in (dump1.get('cols') or [])]}", flush=True)
                    await _shot(page, "split_after_add")
                await _dump("results", results)
                # ⚠ 분할처리 팝업의 '적용' 클릭 금지 — Escape/닫기로 정리.
                close_btn = await page.evaluate(BUTTON_BY_TEXT_JS, "Close")
                if close_btn:
                    await mouse_click(page, close_btn[-1]["x"], close_btn[-1]["y"])
                else:
                    await page.keyboard.press("Escape")
                await page.wait_for_timeout(600)
            else:
                print("[split] 분할처리 팝업 미출현", flush=True)
        else:
            print("[split] 비용분할 버튼 없음/비활성 — 스킵", flush=True)
        await _dump("results", results)

        print("\n===== PROBE COMPLETE (저장 없이 종료) =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        await _dump("results", results)
    finally:
        await browser.close()
        await pw.stop()

    print("\n===== FINAL RESULTS SUMMARY =====", flush=True)
    print(json.dumps({k: (v if not isinstance(v, dict) else "…") for k, v in results.items()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
