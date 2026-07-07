"""HEADLESS 읽기전용 프로브 — 출장(국내/자차) 결의서입력 필드 토폴로지 실측.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - F7(저장) 절대 금지. 저장/상신/전표 생성·취소 계열 버튼 클릭 금지.
  - 폼 필드 세팅·F3 행추가·피커 열기/읽기/닫기는 허용(저장 전 미영속).
  - 저장류 확인 모달의 '예' 클릭 금지. 종료 시 저장하지 않고 브라우저를 닫는다.
  - 코드피커 '적용' 클릭은 P7 확정에 필요할 때만(문서 draft 반영일 뿐 미영속).

계정: 이트라이브2/1111(회계). ERP 직접 로그인 → GLDDOC00300 → 결의구분 출장(국내 자차).
P1~P9 를 순차 실행하고 결과를 artifacts/trip_probe_*.json + 스크린샷으로 남긴다.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/trip_probe.py [all|1|2|...|9]   # 숫자 = 그 Pn 까지 실행하고 정지
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.card_collect import js as cc_js  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

import os  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

TODAY_COMPACT = _date.today().isoformat().replace("-", "")

# ── 프로브 전용 in-page JS (읽기/발견 전용, document 스코프) ──────────────────────

# select 옵션 전체 덤프. arg = css selector. 반환 {ok, options:[{value,text}]} | {ok:false}.
SELECT_OPTIONS_JS = """(sel) => {
  const s = document.querySelector(sel);
  if (!s) return { ok: false, reason: 'no-select' };
  return { ok: true, options: [...s.options].map(o => ({ value: o.value, text: (o.text||'').trim() })) };
}"""

# 증빙유형 팝업(.k-window.dialog) 그리드 전체행 덤프(코드/이름). 반환 {ok, n, rows:[{code,name}]}.
EVDN_DUMP_ALL_JS = """() => {
  try {
    const dlg = [...document.querySelectorAll('.k-window.dialog')].find(d => d.offsetParent !== null);
    if (!dlg) return { ok: false, reason: 'no-dialog' };
    const pg = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = pg.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    return { ok: true, n, rows: rows.map(x => ({
      code: String(x.EVDN_TP_CD == null ? '' : x.EVDN_TP_CD).trim(),
      name: String(x.EVDN_TP_NM == null ? '' : x.EVDN_TP_NM).trim() })) };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""

# 문서 전역 코드피커 래퍼 발견 — `#<id>-wrapper` 안에 .dews-codepicker-button 이 있는 요소.
# 각 래퍼의 id(=field), 근처 라벨 텍스트, 버튼 좌표를 반환(document 스코프 피커 후보).
DOC_PICKERS_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const out = [];
  for (const wr of document.querySelectorAll('[id$=-wrapper]')) {
    if (wr.offsetParent === null) continue;
    const btn = wr.querySelector('.dews-codepicker-button, .dews-multicodepicker-button');
    if (!btn) continue;
    const id = wr.id.replace(/-wrapper$/, '');
    // 근처 라벨: 같은 행(top 근접) label/th 중 왼쪽 가장 가까운 것.
    const wrr = wr.getBoundingClientRect();
    let label = '';
    let best = 1e9;
    for (const l of document.querySelectorAll('label, th, .dews-form-label, span')) {
      if (l.offsetParent === null) continue;
      const t = c(l.innerText); if (!t || t.length > 20) continue;
      const r = l.getBoundingClientRect();
      if (Math.abs(r.top - wrr.top) < 20 && r.left < wrr.left) {
        const dx = wrr.left - r.left; if (dx < best) { best = dx; label = t; }
      }
    }
    const br = btn.getBoundingClientRect();
    out.push({ field: id, label, multi: btn.className.includes('multi'),
      box: { x: Math.round(br.x+br.width/2), y: Math.round(br.y+br.height/2) } });
  }
  return out;
}"""

# 문서 전역 텍스트/일반 input 발견(id 있는 것) — 상대계정거래처 등 텍스트 입력 후보.
DOC_INPUTS_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const out = [];
  for (const i of document.querySelectorAll('input[id]')) {
    if (i.offsetParent === null) continue;
    const r = i.getBoundingClientRect();
    out.push({ id: i.id, type: i.type || '', value: c(i.value).slice(0,40),
      x: Math.round(r.x), y: Math.round(r.y) });
  }
  return out;
}"""

# 그리드[index] 컬럼 전체 덤프(field/header/visible) + rowCount. detail=1.
GRID_COLUMNS_JS = """(index) => {
  try {
    const ctrl = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl');
    const g = ctrl._grid;
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
      field: cc.fieldName || cc.name || cc.field || null,
      header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || null,
      visible: cc.visible !== false }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const row0 = n > 0 ? ds.getJsonRows(0, 0)[0] : null;
    return { ok: true, n, cols, fieldKeys: row0 ? Object.keys(row0) : null };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 140) }; }
}"""

# detail 그리드(index 1) 특정 컬럼에 값 세팅 + 표시값 검증. arg = {index, row, field, value}.
GRID_SETVALUE_JS = """({ index, row, field, value }) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl')._grid;
    const before = g.getValue(row, field);
    g.setValue(row, field, value);
    const after = g.getValue(row, field);
    let disp = '';
    try { const o = g.getDisplayValuesOfRow(row); disp = o && o[field] != null ? String(o[field]) : ''; } catch(e){}
    return { ok: true, before: String(before == null ? '' : before), after: String(after == null ? '' : after), disp };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 140) }; }
}"""

# 마지막 열린 k-window(피커 팝업) 그리드의 컬럼/행수 덤프. 반환 {ok, title, n, cols, sampleRows}.
LAST_POPUP_GRID_JS = """(limit) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const p = wins[wins.length - 1];
  if (!p) return { ok: false, reason: 'no-popup' };
  const title = c((p.querySelector('.k-window-title')||{}).innerText);
  try {
    const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => cc.fieldName || cc.name).filter(Boolean);
    const take = Math.min(n, limit || 5);
    const sampleRows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    // 검색창 id 탐지.
    const kwEl = p.querySelector('#keyword') || p.querySelector('#s_search_key')
      || p.querySelector('[id$=search_key]') || p.querySelector('[id*=keyword]')
      || [...p.querySelectorAll('input')].filter(i => i.offsetParent!==null && (i.type==='text'||!i.type))[0];
    return { ok: true, title, n, cols, searchId: kwEl ? (kwEl.id || '(no-id)') : null, sampleRows };
  } catch (e) { return { ok: false, title, reason: String(e).slice(0, 140) }; }
}"""

# 마지막 열린 팝업 검색창에 q 세팅(네이티브 setter + input/change).
POPUP_SEARCH_JS = """(q) => {
  const p = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).slice(-1)[0];
  if (!p) return { ok: false, reason: 'no-popup' };
  const kw = p.querySelector('#keyword') || p.querySelector('#s_search_key')
    || p.querySelector('[id$=search_key]') || p.querySelector('[id*=keyword]')
    || [...p.querySelectorAll('input')].filter(i => i.offsetParent!==null && (i.type==='text'||!i.type))[0];
  if (!kw) return { ok: false, reason: 'no-keyword' };
  const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'); d.set.call(kw, q);
  ['input','change'].forEach(t => kw.dispatchEvent(new Event(t, { bubbles: true })));
  return { ok: true, field: kw.id || '(no-id)' };
}"""

# 마지막 열린 팝업 닫기(취소/닫기).
POPUP_CLOSE_JS = js_lib.PICKER_CLOSE_JS  # 동일 로직 재사용


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"trip_probe_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"trip_probe_{name}.png")
        await page.screenshot(path=p)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _find_doc_picker(page: Page, field_candidates: list[str], label_kw: list[str]) -> dict | None:
    """document 스코프 코드피커 후보 중 field id 또는 라벨로 매칭. 반환 후보 dict | None."""
    pickers = await page.evaluate(DOC_PICKERS_JS)
    for p in pickers:
        if p.get("field") in field_candidates:
            return p
    for p in pickers:
        lbl = p.get("label") or ""
        if any(k in lbl for k in label_kw):
            return p
    return None


async def main() -> None:
    stop_at = 9
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg != "all":
        try:
            stop_at = int(arg)
        except ValueError:
            print(f"unknown arg {arg!r} — use all|1..9", flush=True)
            sys.exit(1)

    results: dict = {"userid": USERID, "today_compact": TODAY_COMPACT, "stop_at": stop_at}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
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

        # ── P1: 결의구분 옵션 덤프 + 출장(국내 자차) 전환 ─────────────────────────
        print("\n===== P1: 결의구분 옵션 =====", flush=True)
        opt = await page.evaluate(SELECT_OPTIONS_JS, selectors.GUBUN_SELECT)
        options = opt.get("options") or []
        # '출장' + ('자차' or '국내') 포함 라벨 후보.
        trip_labels = [o for o in options if "출장" in o["text"]]
        chosen = None
        for o in trip_labels:
            if "자차" in o["text"] or ("국내" in o["text"]):
                chosen = o
                break
        results["P1"] = {"all_options": options, "trip_labels": trip_labels, "chosen": chosen}
        print(f"[P1] options={[o['text'] for o in options]}", flush=True)
        print(f"[P1] trip_labels={[o['text'] for o in trip_labels]} chosen={chosen}", flush=True)
        if chosen:
            r = await page.evaluate(
                js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
                {"selector": selectors.GUBUN_SELECT, "text": chosen["text"]},
            )
            await page.wait_for_timeout(1_800)
            results["P1"]["set_result"] = r
            print(f"[P1] set gubun -> {r}", flush=True)
        else:
            results["P1"]["set_result"] = {"ok": False, "reason": "no trip label with 자차/국내"}
        await _shot(page, "p1")
        await _dump("results", results)
        if stop_at < 2:
            return

        # ── add_row (F3) — P2/P3 전제 ────────────────────────────────────────────
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

        # ── P7(선): detail 그리드 컬럼 + 문서 폼 피커/인풋 전량 발견 ──────────────
        # (P4·P8 도 이 덤프를 참조하므로 먼저 수집한다.)
        print("\n===== P7-discovery: detail cols + doc pickers/inputs =====", flush=True)
        detail_cols = await page.evaluate(GRID_COLUMNS_JS, 1)
        master_cols = await page.evaluate(GRID_COLUMNS_JS, 0)
        doc_pickers = await page.evaluate(DOC_PICKERS_JS)
        doc_inputs = await page.evaluate(DOC_INPUTS_JS)
        results["P7"] = {
            "detail_grid": detail_cols,
            "master_grid": master_cols,
            "doc_pickers": doc_pickers,
            "doc_inputs": doc_inputs,
        }
        print(f"[P7] detail cols n={detail_cols.get('n')} cols={[c.get('field') for c in (detail_cols.get('cols') or [])]}", flush=True)
        print(f"[P7] doc_pickers={[(p.get('field'), p.get('label')) for p in doc_pickers]}", flush=True)
        await _dump("results", results)

        # ── P3: ACTG_DT compact 세팅 ─────────────────────────────────────────────
        print("\n===== P3: ACTG_DT compact 세팅 =====", flush=True)
        p3 = await page.evaluate(cc_js.SET_ACCT_DATE_JS, TODAY_COMPACT)
        results["P3"] = {"input_compact": TODAY_COMPACT, "result": p3}
        print(f"[P3] set ACTG_DT({TODAY_COMPACT}) -> {p3}", flush=True)
        await _dump("results", results)
        if stop_at < 2:
            return

        # ── P2: 증빙 에디터 열기 + 증빙 옵션 전량 + 코드 10 ───────────────────────
        print("\n===== P2: 증빙유형 옵션 + 코드 10 =====", flush=True)
        p2: dict = {"opened": False}
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
                    p2["opened"] = True
                    break
            if p2["opened"]:
                break
        if p2["opened"]:
            await page.wait_for_timeout(600)
            dump_all = await page.evaluate(EVDN_DUMP_ALL_JS)
            p2["evdn_dump"] = dump_all
            rows = dump_all.get("rows") or []
            code10 = next((x for x in rows if x["code"] == "10"), None)
            p2["code10"] = code10
            print(f"[P2] evdn rows n={dump_all.get('n')}: {[(x['code'], x['name']) for x in rows]}", flush=True)
            print(f"[P2] code10={code10}", flush=True)
            await _shot(page, "p2_popup")
            # 코드 10 선택 시 팝업/부가필드 출현 여부 관찰(적용은 P7 확정 시에만).
            if code10:
                sel = await page.evaluate(js_lib.EVDN_SELECT_BY_CODE_JS, "10")
                p2["select10"] = sel
                await page.wait_for_timeout(500)
                # 적용 클릭(문서 draft 반영 — 미영속). 이후 부가 팝업/필드 스냅샷.
                box = await page.evaluate(js_lib.EVDN_APPLY_BOX_JS)
                if box:
                    await mouse_click(page, box["x"], box["y"])
                    await page.wait_for_timeout(1_500)
                p2["cell_after_apply"] = await page.evaluate(js_lib.DETAIL_EVDN_CELL_JS)
                p2["modals_after_apply"] = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
                # 차단 모달 있으면 확인/예 해제(저장 아님 — 예산현황 등 draft 확인).
                await page.wait_for_timeout(500)
                await _shot(page, "p2_after10")
        else:
            p2["reason"] = "증빙유형 팝업 열기 실패(3회)"
        results["P2"] = p2
        await _dump("results", results)

        # 증빙 적용 후 doc pickers/detail cols 재덤프(증빙 확정으로 필드가 활성화될 수 있음).
        results["P7"]["detail_grid_after_evdn"] = await page.evaluate(GRID_COLUMNS_JS, 1)
        results["P7"]["doc_pickers_after_evdn"] = await page.evaluate(DOC_PICKERS_JS)
        results["P7"]["doc_inputs_after_evdn"] = await page.evaluate(DOC_INPUTS_JS)
        await _dump("results", results)
        if stop_at < 4:
            return

        # ── P7 값 세팅 검증: 공급가액/적요 컬럼 후보에 setValue ───────────────────
        print("\n===== P7: 공급가액/적요 setValue 검증 =====", flush=True)
        detail_now = await page.evaluate(GRID_COLUMNS_JS, 1)
        field_keys = detail_now.get("fieldKeys") or [c.get("field") for c in (detail_now.get("cols") or [])]
        field_keys = [f for f in field_keys if f]
        # 공급가액 후보(금액 계열), 적요 후보(적요/비고 계열).
        amt_cands = [f for f in field_keys if any(k in f.upper() for k in ("SUPLY", "SPPRC", "SUPPLY", "AMT"))]
        note_cands = [f for f in field_keys if any(k in f.upper() for k in ("NOTE", "RMRK", "REMARK", "SUMRY"))]
        p7set: dict = {"field_keys": field_keys, "amt_candidates": amt_cands, "note_candidates": note_cands, "sets": {}}
        for f in amt_cands[:4]:
            p7set["sets"][f] = await page.evaluate(GRID_SETVALUE_JS, {"index": 1, "row": 0, "field": f, "value": "12345"})
        for f in note_cands[:4]:
            p7set["sets"][f] = await page.evaluate(GRID_SETVALUE_JS, {"index": 1, "row": 0, "field": f, "value": "통행료(현금)"})
        results["P7"]["setvalue_probe"] = p7set
        print(f"[P7] amt_cands={amt_cands} note_cands={note_cands}", flush=True)
        for f, r in p7set["sets"].items():
            print(f"[P7] setValue {f} -> {r}", flush=True)
        await _shot(page, "p7_setvalue")
        await _dump("results", results)

        # ── P4: 거래처 피커(document 스코프) 발견 + 구조 ──────────────────────────
        print("\n===== P4: 거래처 피커 =====", flush=True)
        p4: dict = {}
        partner = await _find_doc_picker(page, ["partner_cd", "PARTNER_CD", "s_partner_cd"], ["거래처"])
        p4["picker_found"] = partner
        if partner:
            await mouse_click(page, partner["box"]["x"], partner["box"]["y"])
            await page.wait_for_timeout(1_500)
            grid = await page.evaluate(LAST_POPUP_GRID_JS, 5)
            p4["popup_empty_search"] = grid
            print(f"[P4] popup title={grid.get('title')} n={grid.get('n')} searchId={grid.get('searchId')} cols={grid.get('cols')}", flush=True)
            await _shot(page, "p4_popup")

            # ── P5: 본인 이름 검색 → 단건 매칭 ───────────────────────────────────
            print("\n===== P5: 본인이름 검색 =====", flush=True)
            await page.evaluate(POPUP_SEARCH_JS, USERID)
            await page.wait_for_timeout(1_500)
            grid5 = await page.evaluate(LAST_POPUP_GRID_JS, 10)
            results["P5"] = {"query": USERID, "popup": grid5}
            print(f"[P5] search '{USERID}' -> n={grid5.get('n')} rows={grid5.get('sampleRows')}", flush=True)
            await _shot(page, "p5")
            await page.evaluate(POPUP_CLOSE_JS)
            await page.wait_for_timeout(600)
        else:
            p4["reason"] = "거래처 코드피커를 document 스코프에서 못 찾음 — detail 셀일 가능성(P7 참조)"
            results["P5"] = {"skipped": "P4 피커 미발견"}
        results["P4"] = p4
        await _dump("results", results)
        if stop_at < 6:
            return

        # ── P6: 예산단위 "여비교통비-국내출장" 조합행 ────────────────────────────
        print("\n===== P6: 예산단위 여비교통비/국내출장 =====", flush=True)
        p6: dict = {}
        budget = await _find_doc_picker(page, ["bg_cd", "BG_CD", "s_bg_cd"], ["예산단위", "예산"])
        p6["picker_found"] = budget
        if budget:
            for kw in ("여비교통비", "국내출장"):
                await mouse_click(page, budget["box"]["x"], budget["box"]["y"])
                await page.wait_for_timeout(1_200)
                await page.evaluate(POPUP_SEARCH_JS, kw)
                await page.wait_for_timeout(1_500)
                g = await page.evaluate(LAST_POPUP_GRID_JS, 30)
                p6[f"search_{kw}"] = g
                print(f"[P6] '{kw}' -> n={g.get('n')} title={g.get('title')}", flush=True)
                await _shot(page, f"p6_{kw}")
                await page.evaluate(POPUP_CLOSE_JS)
                await page.wait_for_timeout(600)
        else:
            p6["reason"] = "예산단위 코드피커 document 스코프 미발견 — detail 셀 가능성"
        results["P6"] = p6
        await _dump("results", results)

        # ── P8: 상대계정거래처 필드(프로젝트 그리드 하단 왼쪽) ────────────────────
        print("\n===== P8: 상대계정거래처 필드 =====", flush=True)
        p8_pickers = await page.evaluate(DOC_PICKERS_JS)
        p8_inputs = await page.evaluate(DOC_INPUTS_JS)
        # 상대/상대계정 라벨 근처 피커 또는 인풋.
        counter = await _find_doc_picker(page, ["counter_partner_cd", "rel_partner_cd"], ["상대", "상대계정", "상대처"])
        results["P8"] = {"counter_picker": counter, "all_pickers": p8_pickers, "all_inputs": p8_inputs}
        print(f"[P8] counter_picker={counter}", flush=True)
        print(f"[P8] pickers={[(p.get('field'), p.get('label')) for p in p8_pickers]}", flush=True)
        await _shot(page, "p8")
        await _dump("results", results)
        if stop_at < 9:
            return

        # ── P9: F3 2번째 행 → 증빙/예산 carry-over ───────────────────────────────
        print("\n===== P9: F3 2행째 carry-over =====", flush=True)
        before_n = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
        await js_click(page, selectors.BTN_ADD)
        after_n = -1
        for _ in range(20):
            await page.wait_for_timeout(300)
            after_n = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
            if isinstance(after_n, int) and after_n > before_n:
                break
        row2_cols = await page.evaluate(GRID_COLUMNS_JS, 1)
        # 새 행(마지막 행)의 증빙/예산 셀 값 읽기.
        row2_dump = await page.evaluate(
            "(idx) => { try { const ds = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1])"
            ".data('dewsControl')._grid.getDataSource(); return ds.getJsonRows(idx, idx)[0]; }"
            " catch(e){ return { err: String(e).slice(0,100) }; } }",
            max(0, (after_n or 1) - 1),
        )
        results["P9"] = {"before_n": before_n, "after_n": after_n, "row2_grid": row2_cols, "row2_data": row2_dump}
        print(f"[P9] rows {before_n}->{after_n}; new row EVDN={row2_dump.get('EVDN_TP_NM') if isinstance(row2_dump, dict) else '?'}", flush=True)
        await _shot(page, "p9")
        await _dump("results", results)

        print("\n===== PROBE COMPLETE (저장 없이 종료) =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(page, "exception")
        await _dump("results", results)
    finally:
        # ⚠ 저장하지 않고 그냥 닫는다(미영속 draft 폐기).
        await browser.close()
        await pw.stop()

    print("\n===== FINAL RESULTS SUMMARY =====", flush=True)
    print(json.dumps({k: (v if not isinstance(v, dict) else "…") for k, v in results.items()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
