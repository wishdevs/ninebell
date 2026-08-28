"""HEADED 프로브 — 구매발주일괄입력[나인벨](화면③, `/PU/PUOORD02000_X20616`) D8·D9 조작 경로 실측.

omnisol-flow-prober 위임(2026-08-28). 대상: 프로젝트 `ETRIBE ERP TEST 001`(코드 ETRI-001),
PRQ2026080694~PRQ2026080702(9건, 원재료, 셀프결재 종결). 미션 항목 1~8 은 PROCESS.md D8/D9
+ '화면 ②③ 랜딩 실측' 절 참조.

⛔ 절대 규칙: 툴바 💾 저장(`button.main-button.save`) 클릭 금지 · 상신 금지.
✅ 허용: 팝업 내 [적용] · 하단 [적용] · 납기 [적용](미저장 초안 변경) — 끝나면 화면 이탈/재진입으로
   폐기하고 마스터 0행을 확인한다.

재사용: nbkit.omnisol.{js_lib,codepicker,verify,latency}, nbkit.patterns.{login_flow,user_type_flow},
nbkit.omnisol.navigator.navigate_menu, app.agents.purchase_order.js(po_js)·steps_write(po_steps_write)
  - pick_code_document / click_by_id / scan_dialog / click_dialog_button / BOX_BY_ID_JS / DIALOGS_JS /
    INPUT_VALUE_JS / SET_INPUT_JS.
신규(이 화면 고유, 이 파일에 로컬): 구매요청 팝업(k-window) 스코프 덤프/조작 JS — PROCESS.md 에
아직 없는 화면③ 전용 구조라 로컬로 두고, 확정되면 po/js.py 로 승격한다.

Usage:
    cd backend && .venv/bin/python e2e/purchase_order_screen3_ops_probe.py
env:
    E2E_HEADLESS=0(기본, 헤디드) / 1(헤드리스)
    E2E_USERID/E2E_PASSWORD (기본 이트라이브2/1111)
    E2E_DELAY_SCALE (기본 1.0 — 헤디드 관찰이라 실시간)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.purchase_order import js as po_js  # noqa: E402
from app.agents.purchase_order import steps_write as po_write  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import _ScaledPage  # noqa: E402
from nbkit.omnisol import codepicker, js_lib, verify  # noqa: E402
from nbkit.omnisol.errors import MenuError  # noqa: E402
from nbkit.omnisol.navigator import navigate_menu  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "0") == "1"  # 기본 헤디드(사용자 지시 2026-08-28)
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "1.0"))
SLOW_MO_MS = int(os.environ.get("E2E_SLOW_MO", "200"))
VIEWPORT = {"width": 1920, "height": 1200}
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

DEEPLINK_SCREEN3 = "/PU/PUOORD02000_X20616"
LABEL_SCREEN3 = "구매발주일괄입력[나인벨]"
PROJECT_NAME = "ETRIBE ERP TEST 001"
PRQ_FIRST = "PRQ2026080694"
PRQ_LAST = "PRQ2026080702"
VENDOR_HAERYONG = ("해룡", "30209")
VENDOR_ALPHA = ("알파테크", "10061")
DUE_DATE = "2026-09-30"

# ── 팝업(k-window) 스코프 프리앰블 — js_lib._PICKER_POP_PREAMBLE 과 동일 규칙("최근 열린
#    non-법인카드 k-window")을 이 파일 로컬로 복제(비공개 심볼 임포트 대신 명시 재작성). ──
_POP = (
    "  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();\n"
    "  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)\n"
    "    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];"
)


def _pop_js(params: str, body: str) -> str:
    return f"({params}) => {{\n{_POP}\n{body}\n}}"


# 팝업 존재+제목 — present/title.
POPUP_PRESENT_JS = _pop_js("", "  return p ? { present: true, title: c((p.querySelector('.k-window-title')||{}).innerText) } : { present: false };")

# 팝업 스코프 라벨 필드 전량 — screen23_dump_probe DUMP_LABELED_FIELDS_JS 를 p 스코프로 이식.
POPUP_LABELED_FIELDS_JS = _pop_js(
    "",
    """  if (!p) return [];
  const out = [];
  const labels = [...p.querySelectorAll('label')].filter(l => l.offsetParent !== null);
  for (const lbl of labels) {
    const text = c(lbl.innerText);
    if (!text) continue;
    const li = lbl.closest('li') || lbl.closest('div') || lbl.closest('td') || lbl.parentElement;
    if (!li) continue;
    const wrapper = li.querySelector('[id$="-wrapper"]');
    const checkbox = li.querySelector('input[type=checkbox]');
    const select = li.querySelector('select');
    const anyInput = li.querySelector('input');
    out.push({
      label: text,
      wrapperId: wrapper ? wrapper.id : null,
      hasCheckbox: !!checkbox,
      hasSelect: !!select,
      selectId: select ? select.id : null,
      anyInputId: anyInput ? anyInput.id : null,
      anyInputValue: anyInput ? anyInput.value : null,
      liHtmlSnippet: li.outerHTML.replace(/\\s+/g, ' ').slice(0, 400),
    });
  }
  return out;""",
)

# 팝업 스코프 버튼/아이콘 전량(텍스트·id·class·rect) — 조회/적용/닫기 위치 특정용.
POPUP_BUTTONS_JS = _pop_js(
    "",
    """  if (!p) return [];
  const out = [];
  for (const b of [...p.querySelectorAll('button, a.k-button, .k-button, [role=button]')]) {
    if (b.offsetParent === null) continue;
    const r = b.getBoundingClientRect();
    out.push({
      tag: b.tagName, id: b.id || '', cls: (b.className||'').toString().slice(0,150),
      text: c(b.innerText).slice(0, 30), disabled: !!b.disabled,
      x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2),
    });
  }
  return out;""",
)

# 팝업 스코프 그리드 전량 컬럼+행수(마스터/디테일 여러 개일 수 있음).
POPUP_GRIDS_JS = _pop_js(
    "",
    """  if (!p) return [];
  const grids = [...p.querySelectorAll('.dews-ui-grid')];
  return grids.map((g, i) => {
    try {
      const ctrl = window.jQuery(g).data('dewsControl')._grid;
      const cols = ctrl.getColumns().map(col => ({ fieldName: col.fieldName, header: col.header, visible: col.visible }));
      return { i, rowCount: ctrl.getDataSource().getRowCount(), columns: cols };
    } catch (e) { return { i, error: String(e).slice(0, 100) }; }
  });""",
)

# 팝업 스코프 그리드[idx] 전량 원시 행(getJsonRows) — limit 캡.
POPUP_GRID_ROWS_JS = _pop_js(
    "[gridIdx, limit]",
    """  if (!p) return { ok: false, reason: 'no-popup' };
  const grids = [...p.querySelectorAll('.dews-ui-grid')];
  const el = grids[gridIdx];
  if (!el) return { ok: false, reason: 'no-grid-' + gridIdx };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(limit, n);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    return { ok: true, rowCount: n, rows };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }""",
)

# 팝업(구매요청) 스코프 하단 '적용' 버튼(class confirm.ok) 중앙 좌표 — 전역 검색이면 다른
# k-window(변경거래처 코드피커 잔존 등)의 동명 버튼을 오클릭할 위험이 있어 팝업 스코프로 좁힌다.
POPUP_BOTTOM_APPLY_BOX_JS = _pop_js(
    "",
    """  if (!p) return null;
  const b = [...p.querySelectorAll('button.confirm.ok, button.dews-ui-button.confirm.ok')].find(x => x.offsetParent !== null);
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };""",
)

# 메인 화면(팝업 밖) 그리드 전량 컬럼+행수 — 인덱스 확정용(마스터/디테일).
MAIN_GRIDS_JS = r"""() => {
  const grids = [...document.querySelectorAll('.dews-ui-grid')];
  return grids.map((g, i) => {
    try {
      const ctrl = window.jQuery(g).data('dewsControl')._grid;
      const cols = ctrl.getColumns().map(col => ({ fieldName: col.fieldName, header: col.header, visible: col.visible }));
      return { i, rowCount: ctrl.getDataSource().getRowCount(), columns: cols };
    } catch (e) { return { i, error: String(e).slice(0, 100) }; }
  });
}"""

# 메인 화면 그리드[idx] 전량 원시 행(getJsonRows).
MAIN_GRID_ROWS_JS = r"""([gridIdx, limit]) => {
  const grids = [...document.querySelectorAll('.dews-ui-grid')];
  const el = grids[gridIdx];
  if (!el) return { ok: false, reason: 'no-grid-' + gridIdx };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(limit, n);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    return { ok: true, rowCount: n, rows };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""

# 팝업 스코프 — 라벨 완전일치 li 의 outerHTML 전체(길이 제한 없음). arg = label.
POPUP_FULL_LI_HTML_JS = _pop_js(
    "label",
    """  if (!p) return null;
  const lbl = [...p.querySelectorAll('label')].find(l => l.offsetParent !== null && c(l.innerText) === label);
  if (!lbl) return null;
  const li = lbl.closest('li') || lbl.closest('div') || lbl.parentElement;
  return li ? li.outerHTML : null;""",
)

# 팝업 스코프 flat 그리드(gridIdx) 체크 전체 on/off. arg = [gridIdx, on].
POPUP_FLAT_CHECK_ALL_JS = _pop_js(
    "[gridIdx, on]",
    """  if (!p) return { ok: false, reason: 'no-popup' };
  const el = [...p.querySelectorAll('.dews-ui-grid')][gridIdx];
  if (!el) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    const before = (g.getCheckedRows() || []).length;
    g.checkAll(!!on);
    const after = (g.getCheckedRows() || []).length;
    return { ok: true, before, after };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }""",
)

# 팝업 스코프 flat 그리드(gridIdx) 지정 행들 checkRow(true). arg = [gridIdx, rows].
POPUP_FLAT_CHECK_ROWS_JS = _pop_js(
    "[gridIdx, rows]",
    """  if (!p) return { ok: false, reason: 'no-popup' };
  const el = [...p.querySelectorAll('.dews-ui-grid')][gridIdx];
  if (!el) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    for (const r of rows) g.checkRow(r, true);
    const checked = (g.getCheckedRows() || []).slice();
    return { ok: true, checked };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }""",
)

# 팝업 스코프 flat 그리드(gridIdx) 지정 행들의 여러 필드 값. arg = [gridIdx, idxs, fields].
POPUP_FLAT_FIELDS_JS = _pop_js(
    "[gridIdx, idxs, fields]",
    """  if (!p) return {};
  const el = [...p.querySelectorAll('.dews-ui-grid')][gridIdx];
  if (!el) return {};
  try {
    const ds = window.jQuery(el).data('dewsControl')._grid.getDataSource();
    const out = {};
    for (const i of idxs) {
      const row = {};
      for (const f of fields) { try { row[f] = ds.getValue(i, f); } catch (e) { row[f] = null; } }
      out[i] = row;
    }
    return out;
  } catch (e) { return {}; }""",
)

# 메인화면(팝업 밖) grid[idx] 체크 전체 on/off.
MAIN_FLAT_CHECK_ALL_JS = r"""([gridIdx, on]) => {
  const el = document.querySelectorAll('.dews-ui-grid')[gridIdx];
  if (!el) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    const before = (g.getCheckedRows() || []).length;
    g.checkAll(!!on);
    const after = (g.getCheckedRows() || []).length;
    return { ok: true, before, after };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""

# 메인화면 grid[idx] 지정 행들의 여러 필드 값.
MAIN_FLAT_FIELDS_JS = r"""([gridIdx, idxs, fields]) => {
  const el = document.querySelectorAll('.dews-ui-grid')[gridIdx];
  if (!el) return {};
  try {
    const ds = window.jQuery(el).data('dewsControl')._grid.getDataSource();
    const out = {};
    for (const i of idxs) {
      const row = {};
      for (const f of fields) { try { row[f] = ds.getValue(i, f); } catch (e) { row[f] = null; } }
      out[i] = row;
    }
    return out;
  } catch (e) { return {}; }
}"""

# 메인화면 grid[idx] 의 캔버스 rect(헤더 높이 추정 포함) — 행 실클릭 좌표 계산용.
MAIN_GRID_RECT_JS = r"""(gridIdx) => {
  const el = document.querySelectorAll('.dews-ui-grid')[gridIdx];
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
}"""

# 메인화면 grid[0](마스터) 셀 에디터 오픈(setCurrent+showEditor) — RMK_DC 인라인 편집 시도.
MAIN_OPEN_EDITOR_JS = r"""([itemIndex, fieldName]) => {
  const el = document.querySelectorAll('.dews-ui-grid')[0];
  if (!el) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    g.setCurrent({ itemIndex, fieldName });
    g.showEditor();
    return { ok: true };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""

# 현재 화면에 보이는 모든 input 요소(id/value/bbox) — 에디터 오버레이 판별용(스킬 진단 플레이북).
ALL_VISIBLE_INPUTS_JS = r"""() => {
  const out = [];
  for (const i of document.querySelectorAll('input')) {
    if (i.offsetParent === null) continue;
    const r = i.getBoundingClientRect();
    if (r.width <= 0) continue;
    out.push({ id: i.id || '', type: i.type, value: i.value, x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) });
  }
  return out;
}"""

# 랜딩 상단 필드 상태(공장/발주일/발주유형/구매그룹/구매조직/세무구분 + select 들).
LANDING_STATE_JS = r"""() => {
  const val = id => { const e = document.getElementById(id); return e ? e.value : null; };
  const selects = [...document.querySelectorAll('select')].filter(s => s.offsetParent !== null).map(s => ({
    id: s.id, cls: (s.className||'').toString().slice(0,80),
    selected: (s.options[s.selectedIndex]||{}).text || null,
  }));
  return {
    plant: val('s_plant_cd'), plant_text: val('s_plant_cd_text'),
    po_dt: val('s_pur_po_dt'),
    po_tp: val('s_po_tp_cd'), po_tp_text: val('s_po_tp_cd_text'),
    purgrp: val('s_purgrp_cd'), purgrp_text: val('s_purgrp_cd_text'),
    purorg: val('s_purorg_cd'), purorg_text: val('s_purorg_cd_text'),
    taxafs: val('s_taxafs_cd'), taxafs_text: val('s_taxafs_cd_text'),
    selects,
  };
}"""


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"po_screen3_ops_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"po_screen3_ops_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def stage(name: str) -> None:
    print(f"\n===== STAGE: {name} =====", flush=True)


async def main() -> None:
    results: dict = {"userid": USERID}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
    raw_page = await browser.new_page(viewport=VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    try:
        await stage("1. 로그인 + SCM-구매 전환")
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "SCM")

        await stage("2. 화면③ 진입")
        try:
            await navigate_menu(page, DEEPLINK_SCREEN3, base, label=LABEL_SCREEN3, grids_required=2)
        except MenuError as exc:
            results["entry_error"] = str(exc)
            print(f"[entry] grids_required=2 실패({exc}) → 1로 재시도", flush=True)
            await navigate_menu(page, DEEPLINK_SCREEN3, base, label=LABEL_SCREEN3, grids_required=1)
        await page.wait_for_timeout(1_500)
        await _shot(page, "01_landing")

        await stage("3. 랜딩 상태 덤프 (항목1)")
        landing = await page.evaluate(LANDING_STATE_JS)
        results["landing"] = landing
        print(f"[landing] {landing}", flush=True)
        main_grids = await page.evaluate(MAIN_GRIDS_JS)
        results["main_grids_landing"] = main_grids
        for g in main_grids:
            print(f"[grid {g['i']}] rowCount={g.get('rowCount')} cols={[c['fieldName'] for c in g.get('columns', [])][:8]}...", flush=True)
        await _dump("01_landing", {"landing": landing, "main_grids": main_grids})

        await stage("4. 구매발주유형 = 원재료 (항목2)")
        po_tp_result = await po_write.pick_code_document(page, "s_po_tp_cd", "원재료")
        results["po_tp_result"] = po_tp_result
        print(f"[po_tp] {po_tp_result}", flush=True)
        await _shot(page, "02_after_po_tp")
        landing2 = await page.evaluate(LANDING_STATE_JS)
        results["landing_after_po_tp"] = landing2
        print(f"[landing_after_po_tp] po_tp={landing2.get('po_tp')} text={landing2.get('po_tp_text')}", flush=True)

        if not po_tp_result.get("ok"):
            print("[FATAL] 구매발주유형 세팅 실패 — 이후 단계 중단, 결과만 덤프", flush=True)
            await _dump("results", results)
            return

        await stage("5. #btn_req 클릭 → 구매요청 팝업 (항목3)")
        click_res = await po_write.click_by_id(page, "btn_req")
        results["btn_req_click"] = click_res
        print(f"[btn_req] {click_res}", flush=True)
        await page.wait_for_timeout(1_500)
        present = await page.evaluate(POPUP_PRESENT_JS)
        results["popup_present"] = present
        print(f"[popup] present={present}", flush=True)
        await _shot(page, "03_popup_open")

        if not present.get("present"):
            print("[FATAL] 구매요청 팝업이 뜨지 않음 — 결과만 덤프하고 종료", flush=True)
            await _dump("results", results)
            return

        await stage("6. 팝업 구조 전량 덤프 (항목3)")
        popup_fields = await page.evaluate(POPUP_LABELED_FIELDS_JS)
        popup_buttons = await page.evaluate(POPUP_BUTTONS_JS)
        popup_grids = await page.evaluate(POPUP_GRIDS_JS)
        results["popup_fields"] = popup_fields
        results["popup_buttons"] = popup_buttons
        results["popup_grids"] = popup_grids
        print(f"[popup] 라벨 필드 {len(popup_fields)}개:", flush=True)
        for f in popup_fields:
            print(f"   - {f['label']!r} wrapper={f.get('wrapperId')} select={f.get('selectId')} input={f.get('anyInputId')}", flush=True)
        print(f"[popup] 버튼 {len(popup_buttons)}개:", flush=True)
        for b in popup_buttons:
            print(f"   - text={b['text']!r} id={b['id']!r} disabled={b['disabled']} rect=({b['x']},{b['y']})", flush=True)
        print(f"[popup] 그리드 {len(popup_grids)}개:", flush=True)
        for g in popup_grids:
            print(f"   - grid[{g['i']}] rowCount={g.get('rowCount')} cols={[c['fieldName'] for c in g.get('columns', [])]}", flush=True)
        print("\n===== STAGE A(항목1~3) 완료 =====", flush=True)

        await stage("7. 팝업 마스터 grid[0] 전량 읽기 → 대상 PRQ 9건 필터 (항목4b)")
        popup_rows_raw = await page.evaluate(POPUP_GRID_ROWS_JS, [0, 900])
        results["popup_grid0_rowcount_before_query"] = popup_rows_raw.get("rowCount")
        all_rows = popup_rows_raw.get("rows") or []
        print(f"[popup grid0] 전체 {len(all_rows)}행(rowCount={popup_rows_raw.get('rowCount')})", flush=True)
        target_prqs = {f"PRQ2026080{n}" for n in range(694, 703)}
        target_idx = [i for i, r in enumerate(all_rows) if str(r.get("PURREQ_NO") or "") in target_prqs]
        print(f"[target] PRQ694~702 매칭 행 {len(target_idx)}/9 — idx={target_idx}", flush=True)
        for i in target_idx:
            r = all_rows[i]
            print(f"   idx={i} PURREQ_NO={r.get('PURREQ_NO')} ITEM_NM={r.get('ITEM_NM')} "
                  f"PRINCIPALPARTN_NM={r.get('PRINCIPALPARTN_NM')} REQN_PARTNER_NM={r.get('REQN_PARTNER_NM')} "
                  f"CHG_PARTNER_NM={r.get('CHG_PARTNER_NM')} WBS_NO={r.get('WBS_NO')}", flush=True)
        results["target_rows_before"] = [all_rows[i] for i in target_idx]
        await _dump("07_target_rows_before", results["target_rows_before"])

        await stage("7b. 요청유형 실측 표시값 + WBS 요소 필드 원본 HTML (항목3 보강)")
        purreq_tp_html = await page.evaluate(POPUP_FULL_LI_HTML_JS, "요청유형")
        wbs_html = await page.evaluate(POPUP_FULL_LI_HTML_JS, "WBS 요소")
        results["purreq_tp_html"] = purreq_tp_html
        results["wbs_html"] = wbs_html
        print(f"[요청유형 html] {purreq_tp_html}", flush=True)
        print(f"[WBS 요소 html] {wbs_html}", flush=True)

        # ⚠ 자가수정(attempt2): 직전 시도에서 여기(구매요청번호+Enter 조회 시험)가 그리드를
        # 647→84행으로 **실제로 재조회**시켰는데(메커니즘 자체는 확인 완료 — 아래 8b), 그 직후
        # groups/target_idx 를 **다시 읽지 않고** 재조회 전 인덱스(최대 641)로 checkRow 를 호출해
        # 대부분이 새 84행 범위를 벗어나 무시됐다(원인=스테일 인덱스, RealGrid 문제 아님).
        # 이번 시도는 groups 산출을 **조회 직후 즉시**(개입 없이) 하고, 조회 메커니즘 시험은
        # 전 구간(항목5~8) 종료 뒤 별도 팝업 세션에서 한다.

        if len(target_idx) == 0:
            print("[FATAL] 대상 PRQ 9건이 팝업 그리드에서 전혀 매칭되지 않음 — 이후 항목5~8 중단", flush=True)
            await _dump("results", results)
            return

        await stage("9. 품목거래처명 그룹 산출 → 해룡/알파테크 2그룹 변경거래처 적용 (항목5)")
        groups: dict[str, list[int]] = {}
        for i in target_idx:
            key = str(all_rows[i].get("PRINCIPALPARTN_NM") or "").strip()
            groups.setdefault(key, []).append(i)
        results["principal_partner_groups"] = {k: v for k, v in groups.items()}
        print(f"[groups] 품목거래처명 분포: { {k: len(v) for k, v in groups.items()} }", flush=True)

        group_keys = list(groups.keys())
        vendor_apply_log: list[dict] = []
        vendor_targets = [VENDOR_HAERYONG, VENDOR_ALPHA]
        MAX_ROWS_PER_GROUP = 5  # 대량 산개 인덱스 checkRow 는 이미 화면①에서 검증됐으므로,
        # 여기서는 그룹당 앞쪽 5행만 표본으로 써 실행시간·재현성을 확보한다(전량 필요시 확장).
        for gi, key in enumerate(group_keys[: len(vendor_targets)]):
            rows_for_group = groups[key][:MAX_ROWS_PER_GROUP]
            vendor_kw, vendor_code = vendor_targets[gi]
            entry: dict = {"group_key": key, "rows": rows_for_group, "vendor_kw": vendor_kw, "vendor_code": vendor_code}
            print(f"[vendor-apply] 그룹 {gi+1} 품목거래처명={key!r} rows={rows_for_group} → 변경거래처={vendor_kw}", flush=True)
            try:
                r0 = await page.evaluate(POPUP_FLAT_CHECK_ALL_JS, [0, False])
                entry["uncheck_all"] = r0
                r1 = await page.evaluate(POPUP_FLAT_CHECK_ROWS_JS, [0, rows_for_group])
                entry["check_rows"] = r1
                print(f"   checkRow 결과: {r1}", flush=True)
                await _shot(page, f"08_group{gi+1}_checked")
                pick = await po_write.pick_code_document(page, "s_chg_partner_cd", vendor_kw)
                entry["pick_vendor"] = pick
                print(f"   변경거래처 코드피커: {pick}", flush=True)
                if pick.get("ok"):
                    apply_click = await po_write.click_by_id(page, "btn_apply")
                    entry["apply_click"] = apply_click
                    await page.wait_for_timeout(1_200)
                    await _shot(page, f"08_group{gi+1}_applied")
                    verify_fields = await page.evaluate(
                        POPUP_FLAT_FIELDS_JS, [0, rows_for_group, ["PURREQ_NO", "CHG_PARTNER_NM", "CHG_PARTNER_CD"]]
                    )
                    entry["verify_after_apply"] = verify_fields
                    print(f"   적용 후 확인: {verify_fields}", flush=True)
            except Exception as exc:  # noqa: BLE001
                entry["exception"] = repr(exc)
                print(f"   예외: {exc!r}", flush=True)
            vendor_apply_log.append(entry)
        results["vendor_apply_log"] = vendor_apply_log
        await _dump("results", results)

        await stage("10. 대상 행 선택 → 하단 적용 → 본화면 반영 (항목6)")
        union_rows = sorted({i for e in vendor_apply_log for i in e.get("rows", [])})
        bottom_apply: dict = {"union_rows": union_rows}
        try:
            await page.evaluate(POPUP_FLAT_CHECK_ALL_JS, [0, False])
            chk = await page.evaluate(POPUP_FLAT_CHECK_ROWS_JS, [0, union_rows])
            bottom_apply["final_check"] = chk
            print(f"[bottom-apply] 최종 체크: {chk}", flush=True)
            await _shot(page, "09_before_bottom_apply")
            main_grids_before = await page.evaluate(MAIN_GRIDS_JS)
            bottom_apply["main_master_rowcount_before"] = (main_grids_before[0] or {}).get("rowCount") if main_grids_before else None
            box = await page.evaluate(POPUP_BOTTOM_APPLY_BOX_JS)
            bottom_apply["apply_btn_box"] = box
            if box:
                await page.mouse.click(box["x"], box["y"])
            else:
                print("[bottom-apply] 팝업 스코프 하단 적용 버튼 미발견 — 좌표(925,930) 폴백", flush=True)
                await page.mouse.click(925, 930)
            closed = None
            dialogs_seen: list[dict] = []
            for _ in range(20):
                await page.wait_for_timeout(500)
                dlg = await po_write.scan_dialog(page, cap_ms=300)
                if dlg:
                    dialogs_seen.append(dlg)
                    print(f"[bottom-apply] 다이얼로그 감지: {dlg}", flush=True)
                    btns = dlg.get("buttons") or []
                    await po_write.click_dialog_button(page, "예" if "예" in btns else (btns[0] if btns else "확인"))
                    continue
                st = await page.evaluate(POPUP_PRESENT_JS)
                if not st.get("present"):
                    closed = True
                    break
            bottom_apply["dialogs_seen"] = dialogs_seen
            bottom_apply["popup_closed"] = closed
            print(f"[bottom-apply] 팝업 닫힘: {closed} (다이얼로그 {len(dialogs_seen)}건)", flush=True)
            await _shot(page, "10_after_bottom_apply")
        except Exception as exc:  # noqa: BLE001
            bottom_apply["exception"] = repr(exc)
            print(f"[bottom-apply] 예외: {exc!r}", flush=True)
        results["bottom_apply"] = bottom_apply
        await _dump("results", results)

        await stage("11. 본화면 마스터/디테일 덤프 (항목6)")
        main_dump: dict = {}
        try:
            main_grids_after = await page.evaluate(MAIN_GRIDS_JS)
            main_dump["grids"] = main_grids_after
            master_rowcount = (main_grids_after[0] or {}).get("rowCount") if main_grids_after else 0
            print(f"[main] 적용 후 grid[0](마스터) rowCount={master_rowcount}", flush=True)
            if isinstance(master_rowcount, int) and master_rowcount > 0:
                master_rows = await page.evaluate(MAIN_GRID_ROWS_JS, [0, master_rowcount])
                main_dump["master_rows"] = master_rows
                for r in (master_rows.get("rows") or []):
                    print(f"   PURDOC_NO={r.get('PURDOC_NO')} PARTNER_NM={r.get('PARTNER_NM')} "
                          f"TERPAY_NM={r.get('TERPAY_NM')} WBS_NM={r.get('WBS_NM')} PJT_NM={r.get('PJT_NM')} "
                          f"RMK_DC={r.get('RMK_DC')}", flush=True)
        except Exception as exc:  # noqa: BLE001
            main_dump["exception"] = repr(exc)
            print(f"[main] 예외: {exc!r}", flush=True)
        results["main_after_apply"] = main_dump
        await _dump("results", results)

        await stage("12. D9 — 마스터 1행 선택 → 디테일 확인 → 납기 적용 (항목7)")
        d9: dict = {}
        try:
            master_rc = (main_dump.get("grids") or [{}])[0].get("rowCount") or 0
            if master_rc > 0:
                rect = await page.evaluate(MAIN_GRID_RECT_JS, 0)
                d9["master_rect"] = rect
                if rect:
                    click_x = rect["x"] + rect["w"] // 3
                    click_y = rect["y"] + 30 + 16  # 헤더 ~30px + 첫 행 중앙 ~16px
                    await page.mouse.click(click_x, click_y)
                    await page.wait_for_timeout(1_200)
                    await _shot(page, "11_after_master_row_click")
                    grids_after_select = await page.evaluate(MAIN_GRIDS_JS)
                    d9["grids_after_master_select"] = grids_after_select
                    detail_rc = (grids_after_select[1] or {}).get("rowCount") if len(grids_after_select) > 1 else None
                    print(f"[D9] 마스터 행 클릭 후 detail rowCount={detail_rc}", flush=True)
                    if isinstance(detail_rc, int) and detail_rc > 0:
                        chk = await page.evaluate(MAIN_FLAT_CHECK_ALL_JS, [1, True])
                        d9["detail_check_all"] = chk
                        print(f"[D9] 디테일 전체 체크: {chk}", flush=True)
                        await page.evaluate(po_js.SET_INPUT_JS, ["BFDEDT_DT", DUE_DATE])
                        due_box = await page.evaluate(po_js.BOX_BY_ID_JS, "btnApplyDT")
                        d9["due_apply_box"] = due_box
                        if due_box:
                            await page.mouse.click(due_box["x"], due_box["y"])
                            await page.wait_for_timeout(1_200)
                            verify_due = await page.evaluate(MAIN_FLAT_FIELDS_JS, [1, list(range(min(detail_rc, 5))), ["BFDEDT_DT", "ITEM_NM"]])
                            d9["verify_due"] = verify_due
                            print(f"[D9] 납기 적용 후 확인: {verify_due}", flush=True)
                        await _shot(page, "12_after_due_apply")

                    # 비고(RMK_DC) 인라인 편집 시도 — setCurrent+showEditor → 오버레이 input 탐색.
                    open_ed = await page.evaluate(MAIN_OPEN_EDITOR_JS, [0, "RMK_DC"])
                    d9["rmk_open_editor"] = open_ed
                    await page.wait_for_timeout(600)
                    inputs = await page.evaluate(ALL_VISIBLE_INPUTS_JS)
                    d9["rmk_visible_inputs"] = inputs
                    print(f"[D9] RMK_DC 에디터 오픈 후 보이는 input {len(inputs)}개", flush=True)
                    await _shot(page, "13_rmk_editor_open")
            else:
                d9["skipped"] = "master rowcount 0"
        except Exception as exc:  # noqa: BLE001
            d9["exception"] = repr(exc)
            print(f"[D9] 예외: {exc!r}", flush=True)
        results["d9"] = d9
        await _dump("results", results)

        await stage("13. 폐기 — 딥링크 재진입 후 마스터 0행 확인 (항목8)")
        discard: dict = {}
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
            dlg_before_nav = await page.evaluate(po_js.DIALOGS_JS)
            discard["dialogs_before_nav"] = dlg_before_nav
            await navigate_menu(page, DEEPLINK_SCREEN3, base, label=LABEL_SCREEN3, grids_required=2)
            await page.wait_for_timeout(1_500)
            # 재진입 과정에서 뜬 다이얼로그(초기화/이탈 확인 등)가 있었다면 위에서 자동 처리되지
            # 않으므로, 재진입 직후에도 남은 다이얼로그가 있는지 별도로 확인한다.
            dlg_after_nav = await page.evaluate(po_js.DIALOGS_JS)
            discard["dialogs_after_nav"] = dlg_after_nav
            grids_final = await page.evaluate(MAIN_GRIDS_JS)
            discard["grids_after_reentry"] = grids_final
            master_rc_final = (grids_final[0] or {}).get("rowCount") if grids_final else None
            discard["master_rowcount_after_reentry"] = master_rc_final
            print(f"[discard] 재진입 후 마스터 rowCount={master_rc_final} (기대 0)", flush=True)
            await _shot(page, "14_after_discard_reentry")
        except Exception as exc:  # noqa: BLE001
            discard["exception"] = repr(exc)
            print(f"[discard] 예외: {exc!r}", flush=True)
        results["discard"] = discard
        await _dump("results", results)

        await stage("14. 구매요청번호 필드 조회 메커니즘 — 격리 재현 (항목4b 대안, discard 후라 안전)")
        query_probe: dict = {}
        try:
            po_tp2 = await po_write.pick_code_document(page, "s_po_tp_cd", "원재료")
            query_probe["po_tp"] = po_tp2
            if po_tp2.get("ok"):
                click_res2 = await po_write.click_by_id(page, "btn_req")
                query_probe["btn_req_click"] = click_res2
                await page.wait_for_timeout(1_500)
                before = await page.evaluate(POPUP_GRIDS_JS)
                query_probe["before_rowcount"] = (before[0] or {}).get("rowCount") if before else None
                await page.evaluate(po_js.SET_INPUT_JS, ["s_purreq_no", PRQ_FIRST])
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1_500)
                after = await page.evaluate(POPUP_GRIDS_JS)
                query_probe["after_rowcount"] = (after[0] or {}).get("rowCount") if after else None
                still = await page.evaluate(POPUP_PRESENT_JS)
                query_probe["popup_present_after"] = still
                print(
                    f"[query-probe] before={query_probe['before_rowcount']} "
                    f"after={query_probe['after_rowcount']} present={still}",
                    flush=True,
                )
                await _shot(page, "15_query_probe_after_enter")
        except Exception as exc:  # noqa: BLE001
            query_probe["exception"] = repr(exc)
            print(f"[query-probe] 예외: {exc!r}", flush=True)
        results["purreq_no_query_probe_isolated"] = query_probe
        await _dump("results", results)

        await stage("15. 최종 폐기 확인 — 재진입 마스터 0행 (잔존 0)")
        final_discard: dict = {}
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
            await navigate_menu(page, DEEPLINK_SCREEN3, base, label=LABEL_SCREEN3, grids_required=2)
            await page.wait_for_timeout(1_500)
            grids_final2 = await page.evaluate(MAIN_GRIDS_JS)
            master_rc2 = (grids_final2[0] or {}).get("rowCount") if grids_final2 else None
            final_discard["master_rowcount"] = master_rc2
            print(f"[final-discard] 최종 마스터 rowCount={master_rc2} (기대 0)", flush=True)
        except Exception as exc:  # noqa: BLE001
            final_discard["exception"] = repr(exc)
            print(f"[final-discard] 예외: {exc!r}", flush=True)
        results["final_discard"] = final_discard
        await _dump("results", results)

        print("\n===== STAGE B(항목4~8) 완료 =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        await _dump("results", results)
        raise
    finally:
        if HEADLESS:
            await browser.close()
        else:
            print("\n[headed] 5초 대기 후 브라우저 종료…", flush=True)
            await page.wait_for_timeout(5_000)
            await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
