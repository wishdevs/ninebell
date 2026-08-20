"""HEADLESS 읽기전용(부작용 0) 프로브 — 세금계산서 결의서입력 필드 토폴로지 실측.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - F7(저장) 절대 금지.
  - 증빙유형/전자세금계산서 팝업의 확정 '적용' 클릭 금지(단계 지시서 명시). 예산단위/프로젝트/
    자금과목 팝업은 검색·읽기만(적용 금지, hakjagum/gyeongjo 프로브 관례 준용).
  - 금액 입력→예산현황 다이얼로그 커밋 금지(에디터 구조만 덤프).
  - 행 삭제·상신 금지. 종료 시 저장하지 않고 브라우저를 닫는다.

tax_invoice(app/agents/tax_invoice/PROCESS.md) ❓ 항목을 실측한다. hakjagum_probe.py/
gyeongjo_probe.py 를 참조 구현으로 재사용한다(발견용 덤프 JS 는 e2e.trip_probe 에서 직접
import, 셀 피커 오픈은 app.agents.trip_domestic.steps._open_detail_cell_picker 재사용).
신규 작성분은 이 문서 고유 항목(전자세금계산서 팝업 구조·조회 버튼 탐색·날짜 위젯 정체)뿐이다.
프로덕션 조건 재현: LIVE_VIEWPORT + _ScaledPage(delay_scale=0.4)(형제 프로브와 동일).

확인 대상(tax_invoice PROCESS.md ❓):
  1. D3 결의구분 "세금계산서" 정확 라벨·value(옵션 전량 덤프)
  2. D4 증빙유형 팝업 코드 전량 덤프 — 03/04/05/06/07/11/13/22/23/24 실재·명칭 확인
  3. D5 전자세금계산서/전자계산서 팝업 — 트리거 조건('조회' 버튼)·컬럼·조회조건필드·복수선택
     여부(적용은 누르지 않음, 구조만)
  4. detail 그리드 컬럼 필드명 전량(START_DT·SPPRC_AMT2·NOTE_DC·BG_CD·PJT_CD·자금과목·결제조건·
     자금예정일·사유구분 대응 필드 확인)
  5. 날짜 위젯 정체 — 녹화 get_by_title('/07')/('/08') 가 회계일(ACTG_DT, 마스터)인지 다른
     필드인지

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/tax_invoice_read_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) — 형제 구현체 그대로 import ──────────────────────────
from app.agents.trip_domestic.steps import _open_detail_cell_picker  # noqa: E402  (재사용: 셀 피커 오픈 3회 재시도 로직)
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402  (재사용: 프로덕션조건 재현 프록시)
from e2e.trip_probe import (  # noqa: E402  (재사용: trip_probe.py 발견용 in-page JS 그대로)
    DOC_INPUTS_JS,
    DOC_PICKERS_JS,
    EVDN_DUMP_ALL_JS,
    SELECT_OPTIONS_JS,
)
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.codepicker import _picker_search  # noqa: E402
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
# D4 매핑(PROCESS.md 사용자 확정, 실재 검증 대상) — 팝업 25종(형제 목록) 중 이 10코드가 있는지.
EVDN_CODES = ["03", "04", "05", "06", "07", "11", "13", "22", "23", "24"]

# ── 신규 작성분(이 문서 고유) — 증빙유형/전자세금계산서 팝업 조사, 날짜 위젯 정체 ──────
# GRID_COLUMNS_JS 는 hakjagum/gyeongjo 와 동일하게 trip_probe.py 원본에 editor 필드를 추가한
# 확장판(과업 지시 "getColumns() 전량 덤프"가 editor 를 명시 요구) — 재정의가 아니라 관례 반복.
GRID_COLUMNS_JS = """(index) => {
  try {
    const ctrl = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl');
    const g = ctrl._grid;
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
      field: cc.fieldName || cc.name || cc.field || null,
      header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || null,
      visible: cc.visible !== false,
      editor: (cc.editor && (cc.editor.type || cc.editor.editorType)) || null }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const row0 = n > 0 ? ds.getJsonRows(0, 0)[0] : null;
    return { ok: true, n, cols, fieldKeys: row0 ? Object.keys(row0) : null };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 140) }; }
}"""

# 화면 전체에서 정확 텍스트가 일치하는 버튼 전량(document 스코프) — D5 '조회' 버튼 존재/정체
# 판별용. 툴바 버튼("조회 (F2)")과 인패널 버튼("조회")이 텍스트로 구분되는지 확인한다.
BUTTON_BY_TEXT_JS = """(text) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  return [...document.querySelectorAll('button')]
    .filter(b => b.offsetParent !== null && c(b.innerText) === text)
    .map(b => { const r = b.getBoundingClientRect();
      return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2),
        id: b.id || null, cls: (b.className||'').toString().slice(0,90), text: c(b.innerText) }; });
}"""

# 최근 열린 k-window(비-법인카드) 팝업 전량 구조 덤프 — 컬럼(field/header/visible)·조회조건
# input·표본 행(최대 limit, 취소분/음수 감지용)·선택가능성(checkAll 류 메서드 존재) 힌트.
INVOICE_POPUP_DUMP_JS = """(limit) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-popup' };
  const title = c((dlg.querySelector('.k-window-title')||{}).innerText);
  const inputs = [...dlg.querySelectorAll('input')].filter(i => i.offsetParent !== null).map(i => ({
    id: i.id || null, type: i.type || '', value: c(i.value).slice(0, 30) }));
  const radios = [...dlg.querySelectorAll('input[type=radio],input[type=checkbox]')]
    .filter(i => i.offsetParent !== null)
    .map(i => ({ id: i.id || null, checked: !!i.checked, name: i.name || null }));
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
    grid = { n, cols, rows,
      checkable_hint: !!(g.getCheckedRows || g.getCheckedItems || typeof g.checkAll === 'function') };
  } catch (e) { grid = { err: String(e).slice(0, 140) }; }
  return { ok: true, title, inputs, radios, grid };
}"""

# input 조상 3단계까지의 모든 자손 요소(태그/클래스/rect) 덤프 — 추측 좌표 대신 실제 아이콘
# element 를 찾는다(SKILL.md 진단 원칙 "DOM 을 덤프, 좌표를 추측하지 말 것").
NEAR_INPUT_DOM_JS = """(inputId) => {
  const i = document.getElementById(inputId);
  if (!i) return null;
  let anc = i;
  for (let k = 0; k < 3 && anc.parentElement; k++) anc = anc.parentElement;
  const out = [];
  for (const el of anc.querySelectorAll('*')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || r.width > 200) continue;
    out.push({ tag: el.tagName, cls: (el.className||'').toString().slice(0,70), id: el.id||null,
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) });
  }
  return out;
}"""

# 열린 kendo calendar 팝업(body 에 붙는 .k-animation-container 내부)의 day-cell title 전량.
KENDO_CALENDAR_DAYS_JS = """() => {
  const cal = [...document.querySelectorAll('.k-calendar')].find(c => c.offsetParent !== null);
  if (!cal) return null;
  const links = [...cal.querySelectorAll('a[title], td[title]')].filter(e => e.offsetParent !== null);
  return { n: links.length, sample: links.slice(0, 10).map(e => ({
    title: e.title, text: (e.innerText||'').trim() })) };
}"""


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"tax_invoice_probe_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"tax_invoice_probe_{name}.png")
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
        # ── 진입: login → 회계 → GLDDOC00300 ────────────────────────────────────
        print("[entry] login + user_type(회계) + menu_nav(GLDDOC00300)…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)
        await _shot(page, "entry")

        # ── 1) D3: 결의구분 옵션 덤프 + "세금계산서" 전환 ───────────────────────────
        print("\n===== D3: 결의구분 옵션 =====", flush=True)
        opt = await page.evaluate(SELECT_OPTIONS_JS, selectors.GUBUN_SELECT)
        options = opt.get("options") or []
        chosen = next((o for o in options if o["text"] == GUBUN_LABEL), None)
        results["D3"] = {"all_options": options, "chosen": chosen}
        print(f"[D3] options={[o['text'] for o in options]}", flush=True)
        print(f"[D3] chosen({GUBUN_LABEL})={chosen}", flush=True)
        if not chosen:
            results["D3"]["set_result"] = {"ok": False, "reason": f"'{GUBUN_LABEL}' 라벨 없음"}
            await _dump("results", results)
            print("[FATAL] 결의구분 옵션에 '세금계산서' 없음 — 즉시 중단(원인분류: 필드부재)", flush=True)
            return
        r = await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
            {"selector": selectors.GUBUN_SELECT, "text": GUBUN_LABEL},
        )
        await page.wait_for_timeout(1_800)
        results["D3"]["set_result"] = r
        print(f"[D3] set gubun -> {r}", flush=True)
        await _shot(page, "d3_gubun")
        await _dump("results", results)

        # ── add_row (F3) ─────────────────────────────────────────────────────────
        print("\n===== add_row (F3) =====", flush=True)
        await js_click(page, selectors.BTN_ADD)
        drc = -1
        for _ in range(33):
            await page.wait_for_timeout(300)
            drc = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
            if isinstance(drc, int) and drc > 0:
                break
        results["add_row"] = {"detail_rowcount": drc}
        print(f"[add_row] detail_rowcount={drc}", flush=True)
        await _shot(page, "addrow")
        await _dump("results", results)
        if not (isinstance(drc, int) and drc > 0):
            print("[FATAL] F3 후 행 생성 실패 — 중단(원인분류: 타이밍/셀렉터드리프트)", flush=True)
            return

        # ── 2) detail/master 컬럼 전량 + 문서 폼 피커/인풋 발견(과업 항목 4) ────────
        print("\n===== detail/master 컬럼 + 문서 폼 피커 =====", flush=True)
        detail_cols = await page.evaluate(GRID_COLUMNS_JS, 1)
        master_cols = await page.evaluate(GRID_COLUMNS_JS, 0)
        doc_pickers = await page.evaluate(DOC_PICKERS_JS)
        doc_inputs = await page.evaluate(DOC_INPUTS_JS)
        results["detail_grid"] = detail_cols
        results["master_grid"] = master_cols
        results["doc_pickers"] = doc_pickers
        results["doc_inputs"] = doc_inputs
        detail_headers = {c.get("field"): c.get("header") for c in (detail_cols.get("cols") or [])}
        target_fields = ["START_DT", "SPPRC_AMT2", "NOTE_DC", "BG_CD", "PJT_CD"]
        target_kw = ["자금과목", "결제조건", "자금예정일", "사유구분"]
        results["field_check"] = {
            "explicit_fields": {f: (f in detail_headers) for f in target_fields},
            "keyword_headers": {
                kw: [f for f, h in detail_headers.items() if h and kw in h] for kw in target_kw
            },
        }
        print(f"[detail] n={detail_cols.get('n')} cols={[c.get('field') for c in (detail_cols.get('cols') or [])]}", flush=True)
        print(f"[detail] field_check={results['field_check']}", flush=True)
        await _shot(page, "detail_cols")
        await _dump("results", results)

        # ── 3) D4: 증빙유형 팝업 전량 덤프 — 10코드 실재 확인(적용 없이 닫기) ───────
        print("\n===== D4: 증빙유형 팝업 코드 10종 =====", flush=True)
        d4: dict = {"opened": False}
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
                    d4["opened"] = True
                    break
            if d4["opened"]:
                break
        if d4["opened"]:
            dump_all = {"ok": False, "n": 0, "rows": []}
            for _ in range(20):
                await page.wait_for_timeout(300)
                dump_all = await page.evaluate(EVDN_DUMP_ALL_JS)
                if dump_all.get("ok") and (dump_all.get("n") or 0) > 0:
                    break
            d4["evdn_dump"] = dump_all
            rows = dump_all.get("rows") or []
            by_code = {r["code"]: r["name"] for r in rows}
            d4["target_codes"] = {code: by_code.get(code) for code in EVDN_CODES}
            print(f"[D4] evdn rows n={dump_all.get('n')}: {[(x['code'], x['name']) for x in rows]}", flush=True)
            print(f"[D4] target_codes={d4['target_codes']}", flush=True)
            await _shot(page, "d4_evdn_popup")
            # ⚠ 적용 클릭 없이 팝업만 닫는다(지시서 명시 — 증빙유형 팝업 적용 금지).
            closed = await page.evaluate(js_lib.PICKER_CLOSE_JS)
            d4["closed_without_apply"] = closed
            await page.wait_for_timeout(500)
        else:
            d4["reason"] = "증빙유형 팝업 열기 실패(3회)"
        results["D4"] = d4
        await _dump("results", results)

        # ── 4) D5: '조회' 버튼(전자세금계산서/전자계산서 팝업 트리거) 탐색 ──────────
        # ⚠ 증빙유형 팝업 적용을 하지 않았으므로(위 D4 close_without_apply), detail 셀은
        #   여전히 증빙 미확정 상태다 — 이 상태에서 '조회' 버튼이 존재/활성인지가 곧 트리거
        #   조건(증빙유형 확정 필요 여부)의 1차 증거다. 지시서가 두 팝업(증빙유형/전자세금계산서)
        #   모두 '적용' 클릭을 명시 금지했으므로, 증빙유형을 커밋(적용)하지 않고 도달 가능한
        #   범위까지만 조사한다 — 커밋이 필요하면 그 자체가 결론(D5 트리거 조건)이다.
        print("\n===== D5: '조회' 버튼 탐색(증빙유형 미확정 상태) =====", flush=True)
        d5: dict = {}
        lookup_buttons_before = await page.evaluate(BUTTON_BY_TEXT_JS, "조회")
        d5["lookup_buttons_pre_evdn_commit"] = lookup_buttons_before
        print(f"[D5] 증빙 미확정 상태의 '조회' 버튼 후보: {lookup_buttons_before}", flush=True)
        await _shot(page, "d5_pre_evdn")
        if lookup_buttons_before:
            # 커밋 없이도 버튼이 있다 — 클릭해 전자세금계산서 팝업이 뜨는지 확인(적용은 안 함).
            box = lookup_buttons_before[-1]
            await mouse_click(page, box["x"], box["y"])
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
            d5["popup_opened_without_evdn_commit"] = popup_opened
            if popup_opened:
                dump = await page.evaluate(INVOICE_POPUP_DUMP_JS, 50)
                d5["invoice_popup"] = dump
                print(f"[D5] 전자세금계산서 팝업 title={dump.get('title')} grid={dump.get('grid', {}).get('n')}", flush=True)
                await _shot(page, "d5_invoice_popup")
                # ⚠ 적용 클릭 금지 — Escape 로 닫는다(닫기/취소 버튼도 커밋 아님이나 Escape 가 최안전).
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)
            else:
                d5["reason"] = "'조회' 클릭했으나 전자세금계산서/전자계산서 팝업 미출현(다른 동작이었을 수 있음)"
        else:
            d5["reason"] = (
                "증빙유형 미확정 상태에서 '조회' 버튼 후보 0건 — D5 팝업은 증빙유형 확정(적용) 후에만"
                " 나타나는 것으로 추정됨(구조적 근거: PROCESS.md 녹화 순서상 증빙 적용 직후 조회 클릭)."
                " 지시서가 증빙유형 팝업 적용도 금지했으므로 이 프로브에서는 실제 팝업 오픈까지"
                " 도달하지 못함 — ❓ 잔존, 사용자 확인 필요(증빙유형 적용을 프로브에 허용할지)."
            )
            print(f"[D5] {d5['reason']}", flush=True)
        results["D5"] = d5
        await _dump("results", results)

        # ── 5) 날짜 위젯 정체 — 마스터 ACTG_DT/WRT_DT 오버레이 날짜입력 직접 타겟 ─────
        # attempt 1(document 전역 querySelector 로 .k-datepicker 존재만 확인하던 첫 시도)은
        # 조회조건 #s_month(월피커, 상시 렌더)를 오탐했을 위험이 있다(원인분류: 셀렉터드리프트/
        # 오탐) — doc_inputs 덤프로 실측된 전용 오버레이 입력(`_grid_date`, 값이 오늘 날짜와
        # 일치 = ACTG_DT 추정)을 id 로 직접 타겟해 재검증한다.
        print("\n===== 날짜 위젯 정체: 마스터 _grid_date 오버레이 =====", flush=True)
        dw: dict = {}
        grid_date_id = "GLDDOC00300_1000_1900_grid_date"
        near_dom = await page.evaluate(NEAR_INPUT_DOM_JS, grid_date_id)
        dw["near_dom_dump"] = near_dom
        print(f"[dw] {grid_date_id} 주변 DOM: {near_dom}", flush=True)
        # 아이콘 후보: input 자신이 아닌, k-icon/k-select/작은 정사각형에 가까운 요소 우선.
        icon_el = None
        if near_dom:
            square = [e for e in near_dom if e.get("id") != grid_date_id and abs(e["w"] - e["h"]) <= 6 and e["w"] <= 24]
            icon_el = (square or [e for e in near_dom if e.get("id") != grid_date_id])[-1] if (square or near_dom) else None
        if icon_el:
            cx, cy = icon_el["x"] + icon_el["w"] // 2, icon_el["y"] + icon_el["h"] // 2
            dw["icon_clicked"] = {"cls": icon_el.get("cls"), "x": cx, "y": cy}
            await mouse_click(page, cx, cy)
            await page.wait_for_timeout(700)
            cal = await page.evaluate(KENDO_CALENDAR_DAYS_JS)
            dw["calendar_after_grid_date_click"] = cal
            print(f"[dw] 아이콘({icon_el.get('cls')}) 클릭 후 캘린더 day-cell: {cal}", flush=True)
            await _shot(page, "dw_grid_date_calendar")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
        else:
            dw["reason"] = f"{grid_date_id} 주변에서 아이콘 후보 element 를 특정하지 못함"
            print(f"[dw] {dw['reason']}", flush=True)

        # 대조군: 마스터 WRT_DT(결의일, 마찬가지로 visible 컬럼)도 같은 방식으로 확인 —
        # 두 필드 모두 전용 오버레이 입력 id 가 있는지 문서 전체를 재스캔해 대조한다.
        doc_inputs_now = await page.evaluate(DOC_INPUTS_JS)
        dw["doc_inputs_snapshot"] = doc_inputs_now
        dw["input_id_candidates"] = [i.get("id") for i in doc_inputs_now]
        print(f"[dw] 문서 전체 input id 후보: {dw['input_id_candidates']}", flush=True)
        results["date_widget"] = dw
        await _dump("results", results)

        print("\n===== PROBE COMPLETE (저장 없이 종료, 부작용 0) =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        await _dump("results", results)
    finally:
        # ⚠ 저장하지 않고 그냥 닫는다(미영속 draft 폐기) — F7 미클릭.
        await browser.close()
        await pw.stop()

    print("\n===== FINAL RESULTS SUMMARY =====", flush=True)
    print(json.dumps({k: (v if not isinstance(v, dict) else "…") for k, v in results.items()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
